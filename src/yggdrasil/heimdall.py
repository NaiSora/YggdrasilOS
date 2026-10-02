"""heimdall — le gardien du Bifröst : pare-feu nftables d'Yggdrasil.

Heimdall gère sa propre table « inet heimdall » et ne touche jamais au reste du
jeu de règles (Docker, libvirt… gardent les leurs). Tout le trafic entrant est
refusé, sauf les réponses aux connexions sortantes et ce que tu autorises :

    heimdall enable                    active le pare-feu (profil desktop)
    heimdall allow minecraft --from lan
    heimdall allow 8080/tcp
    heimdall deny minecraft
    heimdall ports                     qui écoute, et est-ce exposé ?
    heimdall status
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import common, voix
from .common import Runner, YggError

CONFIG_PATH = Path("/etc/heimdall/heimdall.json")
RULESET_PATH = Path("/etc/heimdall/heimdall.nft")
TABLE = "heimdall"

# Services connus : nom → liste de (ports, protocole)
SERVICES: dict[str, list[tuple[str, str]]] = {
    "ssh": [("22", "tcp")],
    "http": [("80", "tcp")],
    "https": [("443", "tcp"), ("443", "udp")],
    "minecraft": [("25565", "tcp")],
    "minecraft-bedrock": [("19132", "udp")],
    "velocity": [("25577", "tcp")],
    "jellyfin": [("8096", "tcp"), ("7359", "udp"), ("1900", "udp")],
    "homeassistant": [("8123", "tcp")],
    "ollama": [("11434", "tcp")],
    "open-webui": [("3000", "tcp")],
    "syncthing": [("8384", "tcp"), ("22000", "tcp"), ("22000", "udp"), ("21027", "udp")],
    # Samba, et wsdd2 (port 3702/udp, 5357/tcp) pour que Windows voie la machine dans « Réseau »
    "samba": [("139", "tcp"), ("445", "tcp"), ("137-138", "udp"), ("3702", "udp"), ("5357", "tcp")],
    "kdeconnect": [("1714-1764", "tcp"), ("1714-1764", "udp")],
    "dns": [("53", "tcp"), ("53", "udp")],
    "adguard": [("53", "tcp"), ("53", "udp"), ("3080", "tcp")],
    "portainer": [("9443", "tcp")],
    "uptime-kuma": [("3001", "tcp")],
    "forgejo": [("3002", "tcp"), ("2222", "tcp")],
    "wireguard": [("51820", "udp")],
    "steam-remote-play": [("27036-27037", "tcp"), ("27031-27036", "udp")],
    "valheim": [("2456-2458", "udp")],
    "terraria": [("7777", "tcp")],
    "factorio": [("34197", "udp")],
    "satisfactory": [("7777", "both"), ("8888", "tcp")],
    "palworld": [("8211", "udp")],
    "enshrouded": [("15636-15637", "udp")],
    "zomboid": [("16261-16262", "udp")],
    "openttd": [("3979", "both")],
}

LAN4 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10"]
LAN6 = ["fc00::/7", "fe80::/10"]

PROFILES = {
    "desktop": "poste de travail : tout l'entrant est bloqué, ping et découverte réseau (mDNS) permis",
    "server": "serveur : comme desktop, avec SSH ouvert par défaut",
    "strict": "strict : aucun ping, aucune découverte réseau, seulement tes règles",
}

ZONES = {
    "maison": "réseau de confiance : tes ouvertures (heimdall allow) s'appliquent",
    "public": "réseau public (café, gare, hôtel) : rien n'entre, ni ping, ni découverte réseau",
}

PORT_RE = re.compile(r"^(\d{1,5})(?:-(\d{1,5}))?(?:/(tcp|udp|both))?$")


@dataclass
class Rule:
    ports: str
    proto: str  # tcp | udp | both
    source: str = "any"  # any | lan | CIDR
    comment: str = ""
    expire: float = 0.0  # date (epoch) où la règle se referme d'elle-même ; 0 = jamais

    def key(self) -> tuple[str, str, str]:
        return (self.ports, self.proto, self.source)

    def expiree(self, now: float | None = None) -> bool:
        return bool(self.expire) and self.expire <= (time.time() if now is None else now)


@dataclass
class Config:
    enabled: bool = False
    profile: str = "desktop"
    log_drops: bool = False
    rules: list[Rule] = field(default_factory=list)
    # Le réseau du moment : « maison » (tes règles s'appliquent) ou « public » (rien n'entre)
    zone: str = "maison"
    # Réseaux connus (identifiant NetworkManager) → {"zone": maison|public, "nom": …}
    reseaux: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        rules = [Rule(**r) for r in data.get("rules", [])]
        cfg = cls(
            enabled=bool(data.get("enabled", False)),
            profile=data.get("profile", "desktop"),
            log_drops=bool(data.get("log_drops", False)),
            rules=rules,
            zone=data.get("zone", "maison"),
            reseaux={str(k): dict(v) for k, v in (data.get("reseaux") or {}).items()},
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.profile not in PROFILES:
            raise YggError(f"profil inconnu « {self.profile} » (disponibles : {', '.join(PROFILES)})")
        if self.zone not in ZONES:
            raise YggError(f"zone inconnue « {self.zone} » (maison ou public)")
        for rule in self.rules:
            parse_port_spec(rule.ports + "/" + rule.proto)
            normalize_source(rule.source)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"


def parse_port_spec(spec: str) -> tuple[str, str]:
    """« 25565 », « 25565/tcp », « 1714-1764/udp », « 53/both » → (ports, proto)."""
    m = PORT_RE.match(spec.strip())
    if not m:
        raise YggError(f"port invalide « {spec} » (exemples : 8080, 8080/tcp, 1714-1764/udp)")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else None
    for p in (start, end):
        if p is not None and not 1 <= p <= 65535:
            raise YggError(f"port hors limites : {p}")
    if end is not None and end <= start:
        raise YggError(f"plage de ports invalide : {start}-{end}")
    ports = f"{start}-{end}" if end else str(start)
    return ports, m.group(3) or "tcp"


def normalize_source(source: str) -> str:
    source = source.strip().lower()
    if source in ("any", "lan"):
        return source
    try:
        return str(ipaddress.ip_network(source, strict=False))
    except ValueError as exc:
        raise YggError(f"source invalide « {source} » (any, lan ou un réseau CIDR comme 192.168.1.0/24)") from exc


def resolve_target(target: str) -> list[tuple[str, str]]:
    name = target.lower()
    if name in SERVICES:
        return SERVICES[name]
    return [parse_port_spec(target)]


# --------------------------------------------------------------------------
# Génération du jeu de règles
# --------------------------------------------------------------------------

def _escape(comment: str) -> str:
    """Commentaire nftables : ASCII simple, sans guillemets."""
    return re.sub(r"[^A-Za-z0-9_ .:/()+-]", "", comment)[:60]


def _nft_ports(ports: str) -> str:
    return ports  # nft accepte « 25565 » comme « 1714-1764 »


def rule_lines(rule: Rule) -> list[str]:
    ports = _nft_ports(rule.ports)
    comment = _escape(rule.comment or f"{rule.ports}/{rule.proto}")
    if rule.proto == "both":
        match = f"meta l4proto {{ tcp, udp }} th dport {ports}"
    else:
        match = f"{rule.proto} dport {ports}"
    if rule.source == "any":
        return [f'{match} accept comment "{comment}"']
    if rule.source == "lan":
        return [
            f'ip saddr @lan4 {match} accept comment "{comment} (lan)"',
            f'ip6 saddr @lan6 {match} accept comment "{comment} (lan)"',
        ]
    net = ipaddress.ip_network(rule.source, strict=False)
    family = "ip" if net.version == 4 else "ip6"
    return [f'{family} saddr {net} {match} accept comment "{comment} ({net})"']


def render_ruleset(cfg: Config, now: float | None = None) -> str:
    cfg.validate()
    public = cfg.zone == "public"
    # En zone publique, aucune ouverture ; ailleurs, les règles non expirées
    rules = [] if public else [r for r in cfg.rules if not r.expiree(now)]
    if not public and cfg.profile == "server" and not any(r.ports == "22" and r.proto in ("tcp", "both")
                                                          for r in rules):
        rules.insert(0, Rule("22", "tcp", "any", "ssh (profil server)"))

    body = [
        "    chain input {",
        "        type filter hook input priority filter; policy drop;",
        "        ct state established,related accept",
        "        ct state invalid drop",
        '        iifname "lo" accept',
        # ICMP indispensable au bon fonctionnement d'IPv4/IPv6
        "        icmp type { destination-unreachable, time-exceeded, parameter-problem } accept",
        "        icmpv6 type { destination-unreachable, packet-too-big, time-exceeded, parameter-problem,"
        " nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert, mld-listener-query } accept",
        '        udp sport 67 udp dport 68 accept comment "client DHCP"',
        '        ip6 saddr fe80::/10 udp dport 546 accept comment "client DHCPv6"',
    ]
    if cfg.profile != "strict" and not public:
        body += [
            '        icmp type echo-request limit rate 10/second accept comment "ping"',
            '        icmpv6 type echo-request limit rate 10/second accept comment "ping"',
            '        ip daddr 224.0.0.251 udp dport 5353 accept comment "mDNS"',
            '        ip6 daddr ff02::fb udp dport 5353 accept comment "mDNS"',
        ]
    if rules:
        body.append("        # règles ajoutées avec « heimdall allow »")
        for rule in rules:
            body += [f"        {line}" for line in rule_lines(rule)]
    if cfg.log_drops:
        body.append('        limit rate 5/minute log prefix "heimdall-refus: " level info')
    body.append('        counter comment "refuses"')
    body.append("    }")

    head = [
        "#!/usr/sbin/nft -f",
        "# Généré par heimdall — ne pas modifier à la main.",
        "# Utilise « heimdall allow / deny / profile » puis « heimdall apply ».",
        f"table inet {TABLE}",
        f"delete table inet {TABLE}",
        "",
        f"table inet {TABLE} {{",
        "    set lan4 {",
        "        type ipv4_addr",
        "        flags interval",
        f"        elements = {{ {', '.join(LAN4)} }}",
        "    }",
        "",
        "    set lan6 {",
        "        type ipv6_addr",
        "        flags interval",
        f"        elements = {{ {', '.join(LAN6)} }}",
        "    }",
        "",
    ]
    return "\n".join(head + body + ["}", ""])


# --------------------------------------------------------------------------
# Écoute réseau : qui est exposé ?
# --------------------------------------------------------------------------

@dataclass
class Listener:
    proto: str
    address: str
    port: int
    process: str = ""


def parse_ss(output: str) -> list[Listener]:
    """Analyse « ss -H -tuln[p] »."""
    listeners = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        proto = parts[0]
        if proto not in ("tcp", "udp"):
            continue
        local = parts[4]
        addr, _, port = local.rpartition(":")
        if not port.isdigit():
            continue
        addr = addr.strip("[]")
        if "%" in addr:
            addr = addr.split("%", 1)[0]
        process = ""
        m = re.search(r'users:\(\("([^"]+)"', line)
        if m:
            process = m.group(1)
        listeners.append(Listener(proto, addr, int(port), process))
    return listeners


def is_loopback(address: str) -> bool:
    if address in ("*", "0.0.0.0", "::"):
        return False
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def port_in(ports: str, port: int) -> bool:
    if "-" in ports:
        lo, hi = ports.split("-")
        return int(lo) <= port <= int(hi)
    return int(ports) == port


def exposure(listener: Listener, cfg: Config) -> str:
    if is_loopback(listener.address):
        return "local uniquement"
    if not cfg.enabled:
        return "EXPOSÉ (pare-feu inactif)"
    rules = list(cfg.rules)
    if cfg.profile == "server":
        rules.append(Rule("22", "tcp"))
    for rule in rules:
        if rule.proto in (listener.proto, "both") and port_in(rule.ports, listener.port):
            return "ouvert à tous" if rule.source == "any" else f"ouvert ({rule.source})"
    if listener.proto == "udp" and listener.port == 5353 and cfg.profile != "strict":
        return "ouvert (mDNS)"
    return "bloqué par heimdall"


# --------------------------------------------------------------------------
# Persistance et application
# --------------------------------------------------------------------------

def load_config(path: Path = CONFIG_PATH) -> Config:
    try:
        return Config.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return Config()
    except (ValueError, TypeError) as exc:
        raise YggError(f"configuration Heimdall illisible ({path}) : {exc}") from exc


def save_config(cfg: Config, runner: Runner, path: Path = CONFIG_PATH) -> None:
    runner.write_file(path, cfg.to_json(), root=True, mode="644")


def apply(cfg: Config, runner: Runner, *, keep_copy: bool = True) -> None:
    """Charge le jeu de règles via l'entrée standard de nft.

    Une copie lisible est gardée dans /etc/heimdall/heimdall.nft, sauf au
    démarrage (le service tourne avec /etc en lecture seule).
    """
    ruleset = render_ruleset(cfg)
    runner.run(["nft", "-f", "/dev/stdin"], root=True, input=ruleset)
    if keep_copy:
        runner.write_file(RULESET_PATH, ruleset, root=True, mode="644")


def unload(runner: Runner) -> None:
    # Échoue silencieusement si la table n'est pas chargée.
    runner.run(["nft", "delete", "table", "inet", TABLE], root=True, check=False, capture=True)


def ouvrir(runner: Runner, cible: str, source: str = "lan", commentaire: str = "") -> int:
    """Ouvre un service ou des ports, pour les autres outils (partage, accès à distance).

    Renvoie le nombre de règles ajoutées (0 si elles existaient déjà).
    """
    cfg = load_config()
    source = normalize_source(source)
    existantes = {r.key() for r in cfg.rules}
    nouvelles = [Rule(ports, proto, source, commentaire or cible) for ports, proto in resolve_target(cible)]
    nouvelles = [r for r in nouvelles if r.key() not in existantes]
    if nouvelles:
        cfg.rules += nouvelles
        save_config(cfg, runner)
        if cfg.enabled:
            apply(cfg, runner)
    return len(nouvelles)


def fermer(runner: Runner, cible: str, source: str | None = None) -> int:
    """Retire les règles d'un service ou de ports (de cette source seulement, si précisée)."""
    cfg = load_config()
    visees = set(resolve_target(cible))
    src = normalize_source(source) if source else None
    avant = len(cfg.rules)
    cfg.rules = [r for r in cfg.rules if not ((r.ports, r.proto) in visees and (src is None or r.source == src))]
    retirees = avant - len(cfg.rules)
    if retirees:
        save_config(cfg, runner)
        if cfg.enabled:
            apply(cfg, runner)
    return retirees


def table_loaded(runner: Runner) -> bool | None:
    if not common.is_root():
        return None
    code, _ = runner.query(["nft", "list", "table", "inet", TABLE])
    return code == 0


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def cmd_status(args, runner: Runner) -> int:
    cfg = load_config()
    common.title("Heimdall — pare-feu")
    voix.annoncer("heimdall", "actif" if cfg.enabled else "inactif")
    state = common.style("actif", "green") if cfg.enabled else common.style("inactif", "red")
    _, svc = runner.query(["systemctl", "is-active", "heimdall.service"])
    print(f"  État        : {state} (service : {svc.strip() or 'inconnu'})")
    print(f"  Profil      : {cfg.profile} — {PROFILES[cfg.profile]}")
    print(f"  Réseau      : zone {cfg.zone} — {ZONES[cfg.zone]}")
    fete = [r for r in cfg.rules if r.expire and not r.expiree()]
    if fete:
        fin = time.strftime("%H:%M", time.localtime(max(r.expire for r in fete)))
        print(f"  LAN party   : {len(fete)} ouverture(s) jusqu'à {fin}")
    print(f"  Journal     : {'refus journalisés' if cfg.log_drops else 'refus non journalisés'}")
    loaded = table_loaded(runner)
    if loaded is not None:
        print(f"  Règles      : {'chargées dans le noyau' if loaded else 'NON chargées'}")
    print()
    regles = list(cfg.rules)
    # Le profil serveur ouvre SSH de lui-même (sauf en zone publique) : on le montre
    if cfg.zone != "public" and cfg.profile == "server" and not any(
            r.ports == "22" and r.proto in ("tcp", "both") for r in regles):
        regles.insert(0, Rule("22", "tcp", "any", "ssh (profil serveur)"))
    if regles:
        print(common.table([(r.ports, r.proto, r.source, r.comment) for r in regles],
                           headers=("ports", "proto", "source", "commentaire")))
    else:
        common.info("Aucune ouverture : tout l'entrant est bloqué (hors réponses et ping).")
    if not cfg.enabled:
        print()
        common.warn("active-le avec « heimdall enable ».")
    return 0


def cmd_enable(args, runner: Runner) -> int:
    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile
    cfg.enabled = True
    cfg.validate()
    save_config(cfg, runner)
    apply(cfg, runner)
    runner.run(["systemctl", "enable", "heimdall.service"], root=True, check=False)
    common.ok(f"Heimdall veille (profil {cfg.profile}).")
    return 0


def cmd_disable(args, runner: Runner) -> int:
    if not common.confirm("Désactiver le pare-feu ? Toutes les connexions entrantes seront acceptées.",
                          assume_yes=args.yes):
        return 1
    cfg = load_config()
    cfg.enabled = False
    save_config(cfg, runner)
    unload(runner)
    runner.run(["systemctl", "disable", "heimdall.service"], root=True, check=False)
    common.warn("Heimdall est désactivé.")
    return 0


def cmd_allow(args, runner: Runner) -> int:
    cfg = load_config()
    source = normalize_source(args.source)
    targets = resolve_target(args.target)
    added = 0
    existing = {r.key() for r in cfg.rules}
    for ports, proto in targets:
        if args.proto:
            proto = args.proto
        rule = Rule(ports, proto, source, args.comment or args.target)
        if rule.key() in existing:
            continue
        cfg.rules.append(rule)
        added += 1
    if not added:
        common.ok("règle déjà présente.")
        return 0
    if source == "any" and not args.yes:
        common.warn("cette ouverture vaut pour Internet entier si ta box redirige ce port. "
                    "« --from lan » limite au réseau local.")
    save_config(cfg, runner)
    if cfg.enabled:
        apply(cfg, runner)
    common.ok(f"{args.target} autorisé depuis « {source} ».")
    voix.annoncer("heimdall", "ouvert", qui="le réseau local" if source == "lan" else source, quoi=args.target)
    if not cfg.enabled:
        common.warn("le pare-feu est inactif : la règle s'appliquera avec « heimdall enable ».")
    return 0


def cmd_deny(args, runner: Runner) -> int:
    cfg = load_config()
    targets = {(p, args.proto or proto) for p, proto in resolve_target(args.target)}
    before = len(cfg.rules)
    cfg.rules = [r for r in cfg.rules if (r.ports, r.proto) not in targets]
    removed = before - len(cfg.rules)
    if not removed:
        common.info("aucune règle correspondante.")
        return 0
    save_config(cfg, runner)
    if cfg.enabled:
        apply(cfg, runner)
    common.ok(f"{removed} règle(s) retirée(s).")
    voix.annoncer("heimdall", "ferme", quoi=args.target)
    return 0


def cmd_profile(args, runner: Runner) -> int:
    cfg = load_config()
    if not args.name:
        for name, desc in PROFILES.items():
            mark = common.style("●", "green") if name == cfg.profile else " "
            print(f"  {mark} {name:8} {desc}")
        return 0
    cfg.profile = args.name
    cfg.validate()
    save_config(cfg, runner)
    if cfg.enabled:
        apply(cfg, runner)
    common.ok(f"profil {args.name} appliqué.")
    return 0


def cmd_apply(args, runner: Runner) -> int:
    cfg = load_config()
    if not cfg.enabled:
        if args.boot:
            return 0
        common.warn("Heimdall est désactivé : rien à appliquer (heimdall enable).")
        return 0
    apply(cfg, runner, keep_copy=not args.boot)
    if not args.boot:
        common.ok("règles appliquées.")
    return 0


def cmd_stop(args, runner: Runner) -> int:
    unload(runner)
    return 0


def cmd_render(args, runner: Runner) -> int:
    sys.stdout.write(render_ruleset(load_config()))
    return 0


def cmd_ports(args, runner: Runner) -> int:
    cfg = load_config()
    code, out = runner.query(["ss", "-H", "-tulnp"], root=False)
    if code != 0:
        raise YggError("impossible d'interroger les sockets (ss).")
    listeners = parse_ss(out)
    rows = []
    seen = set()
    for item in sorted(listeners, key=lambda x: (x.port, x.proto)):
        key = (item.proto, item.address, item.port)
        if key in seen:
            continue
        seen.add(key)
        rows.append((f"{item.port}/{item.proto}", item.address, item.process or "?", exposure(item, cfg)))
    common.title("Ports en écoute sur cette machine")
    print(common.table(rows, headers=("port", "adresse", "programme", "exposition")))
    print()
    common.info(common.dim("Lance « sudo heimdall ports » pour voir le nom de tous les programmes."))
    common.info(common.dim("Les ports publiés par Docker (bifrost) contournent la chaîne d'entrée : "
                           "bifrost les lie à 127.0.0.1 sauf si tu choisis de les exposer."))
    return 0


FAIL2BAN_JAIL = """# Géré par « heimdall guard ssh »
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
"""


def cmd_guard(args, runner: Runner) -> int:
    if args.service != "ssh":
        raise YggError("seul « ssh » est pris en charge pour l'instant.")
    common.title("Protection anti-force-brute de SSH (fail2ban)")
    common.step("installe fail2ban et python3-systemd")
    common.step("bannit 1 h toute adresse qui rate 5 connexions en 10 min")
    if not common.confirm("Continuer ?", default=True, assume_yes=args.yes):
        return 1
    runner.run(["apt-get", "install", "-y", "fail2ban", "python3-systemd"], root=True)
    runner.write_file("/etc/fail2ban/jail.d/yggdrasil-sshd.conf", FAIL2BAN_JAIL, root=True)
    runner.run(["systemctl", "enable", "--now", "fail2ban"], root=True)
    runner.run(["systemctl", "restart", "fail2ban"], root=True)
    common.ok("SSH est sous la garde de fail2ban (sudo fail2ban-client status sshd).")
    return 0


def cmd_log(args, runner: Runner) -> int:
    cfg = load_config()
    if not cfg.log_drops:
        if not common.confirm("La journalisation des refus est désactivée. L'activer ?", default=True,
                              assume_yes=args.yes):
            return 1
        cfg.log_drops = True
        save_config(cfg, runner)
        if cfg.enabled:
            apply(cfg, runner)
    cmd = ["journalctl", "-k", "--no-pager", "-g", "heimdall-refus", "-n", str(args.lines)]
    if args.follow:
        cmd.append("-f")
    return runner.run(cmd, root=True, check=False).returncode


# --------------------------------------------------------------------------
# Le réseau du moment : maison ou public (H1)
# --------------------------------------------------------------------------

def reseau_actif(runner: Runner) -> tuple[str, str, str]:
    """(identifiant, nom, interface) de la connexion NetworkManager principale."""
    _, sortie = runner.query(["nmcli", "-t", "-f", "UUID,NAME,DEVICE,TYPE", "connection", "show", "--active"])
    for line in sortie.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[3] not in ("loopback", "bridge", "tun", "wireguard") and parts[2] != "lo":
            return parts[0], parts[1], parts[2]
    return "", "", ""


def zone_par_defaut(interface: str, sys_net: Path = Path("/sys/class/net")) -> str:
    """Un Wi-Fi inconnu est public jusqu'à preuve du contraire ; un câble, la maison."""
    return "public" if (sys_net / interface / "wireless").exists() else "maison"


def cmd_zone(args, runner: Runner) -> int:
    cfg = load_config()
    if args.auto:
        # Appelé par NetworkManager (dispatcher) quand une connexion monte
        connu = cfg.reseaux.get(args.auto)
        zone = connu["zone"] if connu else zone_par_defaut(args.interface or "")
        if not connu:
            cfg.reseaux[args.auto] = {"zone": zone, "nom": args.nom or args.auto}
            if zone == "public":
                common.alerter("heimdall", "normal",
                               f"nouveau réseau « {args.nom or args.auto} » : traité comme public (rien n'entre). "
                               "S'il est de confiance : heimdall zone maison", systeme=True, cle=f"zone:{args.auto}")
        if cfg.zone != zone or not connu:
            cfg.zone = zone
            save_config(cfg, runner)
            if cfg.enabled:
                apply(cfg, runner)
        return 0
    uuid, nom, interface = reseau_actif(runner)
    if args.zone:
        if args.zone not in ZONES:
            raise YggError("zone : maison ou public")
        if uuid:
            cfg.reseaux[uuid] = {"zone": args.zone, "nom": nom}
        cfg.zone = args.zone
        save_config(cfg, runner)
        if cfg.enabled:
            apply(cfg, runner)
        common.ok(f"« {nom or 'ce réseau'} » : zone {args.zone} — {ZONES[args.zone]}.")
        return 0
    common.title("Heimdall — le réseau du moment")
    print(f"  {common.style(cfg.zone, 'gold')} : {ZONES[cfg.zone]}")
    if nom:
        print(f"  Connexion : {nom}")
    if cfg.reseaux:
        print()
        rows = [(v.get("nom", k), v.get("zone", "?")) for k, v in sorted(cfg.reseaux.items(),
                                                                         key=lambda kv: kv[1].get("nom", ""))]
        print(common.table(rows, headers=("réseau connu", "zone")))
    print()
    common.info(common.dim("heimdall zone maison | public : classer le réseau actuel. "
                           "Un Wi-Fi inconnu est public d'office."))
    return 0


# --------------------------------------------------------------------------
# LAN party : des ports de jeu ouverts quelques heures (H2)
# --------------------------------------------------------------------------

JEUX_FETE = ("minecraft", "minecraft-bedrock", "steam-remote-play", "terraria", "valheim", "factorio")


def ouvrir_fete(cfg: Config, jeux: list[str], heures: float, now: float) -> int:
    expire = now + heures * 3600
    existantes = {r.key(): r for r in cfg.rules}
    ajoutees = 0
    for jeu in jeux:
        for ports, proto in resolve_target(jeu):
            regle = existantes.get((ports, proto, "lan"))
            if regle is None:
                cfg.rules.append(Rule(ports, proto, "lan", f"fete {jeu}", expire))
                ajoutees += 1
            elif regle.expire:  # déjà ouverte pour une fête : on prolonge
                regle.expire = max(regle.expire, expire)
    return ajoutees


def fermer_fete(cfg: Config) -> int:
    avant = len(cfg.rules)
    cfg.rules = [r for r in cfg.rules if not r.expire]
    return avant - len(cfg.rules)


def cmd_fete(args, runner: Runner) -> int:
    cfg = load_config()
    if args.fin:
        fermees = fermer_fete(cfg)
        save_config(cfg, runner)
        if cfg.enabled:
            apply(cfg, runner)
        common.ok(f"fin de la fête : {fermees} ouverture(s) refermée(s).")
        return 0
    if cfg.zone == "public":
        raise YggError("tu es sur un réseau public : pas de LAN party ici (heimdall zone maison si c'est chez toi).")
    jeux = args.jeux or list(JEUX_FETE)
    for jeu in jeux:
        resolve_target(jeu)
    if not 0 < args.heures <= 24:
        raise YggError("durée entre quelques minutes et 24 heures (--heures 3).")
    ouvertes = ouvrir_fete(cfg, jeux, args.heures, time.time())
    save_config(cfg, runner)
    if cfg.enabled:
        apply(cfg, runner)
    # Le cor sonne la fin : une minuterie systemd referme tout, même si personne n'y pense
    runner.run(["systemd-run", "--unit=heimdall-fin-de-fete", "--on-active", f"{int(args.heures * 3600)}s",
                "/usr/bin/heimdall", "fete", "--fin"], root=True, check=False, capture=True)
    common.ok(f"LAN party : {', '.join(jeux)} ouverts au réseau local pour {args.heures:g} h ({ouvertes} règles).")
    common.info(common.dim("« heimdall fete --fin » referme tout avant l'heure."))
    return 0


def cmd_sortant(args, runner: Runner) -> int:
    """Le contrôle des connexions sortantes par application (H4) : OpenSnitch, du royaume d'Ásgard."""
    common.title("Les connexions sortantes")
    common.info("Heimdall garde l'entrée. Pour décider quelle application peut sortir sur Internet, "
                "Yggdrasil s'appuie sur OpenSnitch : à chaque nouvelle connexion, une fenêtre te demande "
                "« autoriser ou refuser ? », et tu peux t'en souvenir.")
    if common.which("opensnitchd"):
        common.ok("OpenSnitch est installé : ses règles sont dans « OpenSnitch » (menu des applications).")
        return 0
    from . import ygg

    return ygg.main(["realm", "add", "asgard", "--seulement", "opensnitch"] + (["-y"] if args.yes else []))


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-y", "--yes", action="store_true", help="valider automatiquement")
    opts.add_argument("-n", "--dry-run", action="store_true", help="simuler")
    opts.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="heimdall", description="Pare-feu d'Yggdrasil (nftables).")
    sub = parser.add_subparsers(dest="command", metavar="commande")

    sub.add_parser("status", help="état du pare-feu", parents=[opts]).set_defaults(func=cmd_status)
    p = sub.add_parser("enable", help="activer le pare-feu", parents=[opts])
    p.add_argument("--profile", choices=list(PROFILES))
    p.set_defaults(func=cmd_enable)
    sub.add_parser("disable", help="désactiver le pare-feu", parents=[opts]).set_defaults(func=cmd_disable)

    p = sub.add_parser("allow", help="ouvrir un port ou un service (ex. minecraft, 8080/tcp)", parents=[opts])
    p.add_argument("target")
    p.add_argument("--from", dest="source", default="any", help="any (défaut), lan, ou réseau CIDR")
    p.add_argument("--proto", choices=["tcp", "udp", "both"])
    p.add_argument("--comment", default="")
    p.set_defaults(func=cmd_allow)

    p = sub.add_parser("deny", help="refermer un port ou un service", parents=[opts])
    p.add_argument("target")
    p.add_argument("--proto", choices=["tcp", "udp", "both"])
    p.set_defaults(func=cmd_deny)

    p = sub.add_parser("profile", help="voir ou changer de profil", parents=[opts])
    p.add_argument("name", nargs="?", choices=list(PROFILES))
    p.set_defaults(func=cmd_profile)

    sub.add_parser("ports", help="ports en écoute et exposition", parents=[opts]).set_defaults(func=cmd_ports)
    sub.add_parser("services", help="services connus", parents=[opts]).set_defaults(func=cmd_services)

    p = sub.add_parser("guard", help="protection anti-force-brute (fail2ban)", parents=[opts])
    p.add_argument("service", choices=["ssh"])
    p.set_defaults(func=cmd_guard)

    p = sub.add_parser("log", help="voir les connexions refusées", parents=[opts])
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("--lines", type=int, default=50)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("apply", help="(re)charger les règles", parents=[opts])
    p.add_argument("--boot", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_apply)
    sub.add_parser("stop", help="décharger les règles (service)", parents=[opts]).set_defaults(func=cmd_stop)

    from . import gjallarhorn

    p = sub.add_parser("zone", help="le réseau du moment : maison (tes règles) ou public (rien n'entre)",
                       parents=[opts])
    p.add_argument("zone", nargs="?", choices=list(ZONES))
    p.add_argument("--auto", metavar="UUID", help=argparse.SUPPRESS)
    p.add_argument("--nom", help=argparse.SUPPRESS)
    p.add_argument("--interface", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_zone)
    p = sub.add_parser("fete", help="LAN party : ports de jeu ouverts au réseau local quelques heures",
                       parents=[opts])
    p.add_argument("jeux", nargs="*", help=f"services de jeu (défaut : {', '.join(JEUX_FETE)})")
    p.add_argument("--heures", type=float, default=4, help="durée (4 h)")
    p.add_argument("--fin", action="store_true", help="tout refermer maintenant")
    p.set_defaults(func=cmd_fete)
    p = sub.add_parser("voisins", help="qui est sur ton réseau local", parents=[opts])
    p.add_argument("--scan", action="store_true", help="interroger toutes les adresses du réseau")
    p.set_defaults(func=gjallarhorn.cmd_voisins)
    sub.add_parser("gjallarhorn", help="une ronde de surveillance (lancée par gjallarhorn.timer)",
                   parents=[opts]).set_defaults(func=gjallarhorn.cmd_gjallarhorn)
    sub.add_parser("sortant", help="contrôler les connexions sortantes par application (OpenSnitch)",
                   parents=[opts]).set_defaults(func=cmd_sortant)
    sub.add_parser("render", help="afficher le jeu de règles nftables généré", parents=[opts]).set_defaults(func=cmd_render)
    return parser


def cmd_services(args, runner: Runner) -> int:
    rows = [(name, ", ".join(f"{p}/{proto}" for p, proto in specs)) for name, specs in sorted(SERVICES.items())]
    print(common.table(rows, headers=("service", "ports")))
    return 0


def _main(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["status"])
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner)


def main(argv=None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
