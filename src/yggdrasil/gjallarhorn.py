"""Gjallarhorn, le cor de Heimdall : il sonne quand quelque chose change à la porte.

    heimdall voisins [--scan]   qui est sur ton réseau local (appareils, noms, fabricants)
    heimdall gjallarhorn        une ronde (gjallarhorn.timer la lance toutes les 10 minutes, en root)

La ronde compare l'état présent à celui de la ronde précédente et dépose des alertes
(common.alerter) que Ratatoskr relaie sur le bureau et, si tu veux, sur ton téléphone :

  * un nouveau service à l'écoute, joignable depuis le réseau ;
  * quelqu'un qui s'acharne sur SSH (au moins 20 échecs en 15 minutes depuis une adresse) ;
  * un appareil inconnu sur le réseau local ;
  * un disque dont la santé SMART lâche.

Gjallarhorn ne bloque rien lui-même : il prévient, et dit quoi faire.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import common
from .common import STATE_DIR, Runner

OUI = Path("/usr/share/ieee-data/oui.txt")
SEUIL_SSH = 20


def etat_path() -> Path:
    return STATE_DIR / "gjallarhorn.json"


def charger_etat() -> dict:
    try:
        return json.loads(etat_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------
# Les voisins
# --------------------------------------------------------------------------

@dataclass
class Voisin:
    ip: str
    mac: str
    etat: str
    nom: str = ""
    fabricant: str = ""


def parse_neigh(texte: str) -> list[Voisin]:
    """Sortie de « ip -j neigh show » → appareils IPv4 joignables ou vus récemment."""
    try:
        donnees = json.loads(texte or "[]")
    except ValueError:
        return []
    voisins = []
    for n in donnees:
        etats = n.get("state") or []
        if not n.get("lladdr") or any(e in ("FAILED", "INCOMPLETE") for e in etats):
            continue
        try:
            if ipaddress.ip_address(n.get("dst", "")).version != 4:
                continue
        except ValueError:
            continue
        voisins.append(Voisin(n["dst"], n["lladdr"].lower(), (etats or ["?"])[0].lower()))
    return sorted(voisins, key=lambda v: ipaddress.ip_address(v.ip))


def parse_oui(texte: str) -> dict[str, str]:
    """Le registre IEEE (paquet ieee-data) : préfixe AA:BB:CC → fabricant."""
    table = {}
    for line in texte.splitlines():
        m = re.match(r"^([0-9A-F]{2})-([0-9A-F]{2})-([0-9A-F]{2})\s+\(hex\)\s+(.+)$", line.strip())
        if m:
            table[":".join(m.groups()[:3]).lower()] = m.group(4).strip()
    return table


def fabricant(mac: str, table: dict[str, str]) -> str:
    if int(mac[:2], 16) & 0x02:
        return "adresse privée (téléphone récent ?)"
    return table.get(mac[:8].lower(), "")


def reseaux_locaux(runner: Runner) -> list[ipaddress.IPv4Network]:
    """Les réseaux IPv4 de la machine, ramenés à /24 au plus large (pour un balayage raisonnable)."""
    _, sortie = runner.query(["ip", "-j", "-4", "addr", "show", "scope", "global"])
    try:
        interfaces = json.loads(sortie or "[]")
    except ValueError:
        return []
    reseaux = []
    for itf in interfaces:
        for a in itf.get("addr_info", []):
            net = ipaddress.ip_interface(f"{a['local']}/{max(int(a['prefixlen']), 24)}").network
            if net.is_private and net not in reseaux:
                reseaux.append(net)
    return reseaux


def balayer(reseau: ipaddress.IPv4Network) -> None:
    """Un ping à chaque adresse : les appareils répondent et entrent dans la table des voisins."""
    def ping(ip):
        subprocess.run(["ping", "-c", "1", "-W", "1", "-n", str(ip)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    with ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(ping, list(reseau.hosts())[:254]))


def voisins(runner: Runner, scan: bool = False) -> list[Voisin]:
    if scan:
        for reseau in reseaux_locaux(runner):
            balayer(reseau)
    _, sortie = runner.query(["ip", "-j", "neigh", "show"])
    liste = parse_neigh(sortie)
    table = parse_oui(common.read_text(OUI)) if OUI.exists() else {}
    for v in liste:
        v.fabricant = fabricant(v.mac, table)
        try:
            v.nom = socket.gethostbyaddr(v.ip)[0]
        except OSError:
            v.nom = ""
    return liste


def cmd_voisins(args, runner: Runner) -> int:
    liste = voisins(runner, scan=args.scan)
    connus = set(charger_etat().get("voisins", {}))
    common.title("Qui est sur ton réseau ?")
    if not liste:
        common.info("Aucun appareil vu récemment. « heimdall voisins --scan » interroge tout le réseau local.")
        return 0
    rows = [(v.ip, v.nom or "-", v.fabricant or "-", v.mac,
             "" if not connus or v.mac in connus else "nouveau") for v in liste]
    print(common.table(rows, headers=("adresse", "nom", "fabricant", "adresse matérielle", "")))
    if not OUI.exists():
        common.info(common.dim("Pour voir les fabricants : ygg install ieee-data"))
    if not args.scan:
        common.info(common.dim("Seuls les appareils qui ont parlé récemment apparaissent : --scan pour tous."))
    return 0


# --------------------------------------------------------------------------
# La ronde
# --------------------------------------------------------------------------

SSH_RE = re.compile(r"(?:Failed password|Invalid user|authentication failure).*?(?:from|rhost=)\s*(\S+)")


def echecs_ssh(journal: str) -> Counter:
    return Counter(m.group(1) for m in SSH_RE.finditer(journal))


def ecoutes_exposees(runner: Runner) -> dict[str, str]:
    """Services à l'écoute hors de la boucle locale : clé → description."""
    from . import heimdall

    _, sortie = runner.query(["ss", "-H", "-tulnp"])
    cfg = heimdall.load_config()
    resultat = {}
    for l in heimdall.parse_ss(sortie):  # noqa: E741
        if heimdall.is_loopback(l.address):
            continue
        cle = f"{l.proto}:{l.port}:{l.process or '?'}"
        resultat[cle] = f"{l.port}/{l.proto} ({l.process or 'programme inconnu'}) — {heimdall.exposure(l, cfg)}"
    # Sans root, ss ne nomme pas les programmes des autres comptes : un port déjà nommé
    # (une autre socket du même port) ne réapparaît pas en « programme inconnu »
    nommes = {c.rsplit(":", 1)[0] for c in resultat if not c.endswith(":?")}
    return {c: t for c, t in resultat.items() if not (c.endswith(":?") and c.rsplit(":", 1)[0] in nommes)}


def ronde(runner: Runner, maintenant: float | None = None) -> list[tuple[str, str, str]]:
    """Une ronde de Gjallarhorn : renvoie les alertes (urgence, message, clé) et met l'état à jour."""
    from . import materiel

    maintenant = maintenant or time.time()
    etat = charger_etat()
    premiere = not etat
    alertes: list[tuple[str, str, str]] = []

    ecoutes = ecoutes_exposees(runner)
    for cle, texte in ecoutes.items():
        if not premiere and cle not in etat.get("ecoute", {}):
            alertes.append(("normal", f"nouveau service à l'écoute : {texte}", f"ecoute:{cle}"))

    _, journal = runner.query(["journalctl", "-u", "ssh.service", "-u", "sshd.service", "--since", "-15min",
                               "-o", "cat", "--no-pager"], timeout=30)
    heure = time.strftime("%Y%m%d%H", time.localtime(maintenant))
    for ip, nombre in echecs_ssh(journal).items():
        if nombre >= SEUIL_SSH:
            alertes.append(("critical", f"SSH : {nombre} tentatives de connexion ratées en 15 min depuis {ip} "
                            "(« heimdall guard ssh » les bannit)", f"ssh:{ip}:{heure}"))

    _, sortie = runner.query(["ip", "-j", "neigh", "show"])
    vus = {v.mac: v.ip for v in parse_neigh(sortie)}
    connus = dict(etat.get("voisins", {}))
    table = parse_oui(common.read_text(OUI)) if OUI.exists() else {}
    for mac, ip in vus.items():
        if not premiere and mac not in connus:
            fab = fabricant(mac, table)
            alertes.append(("normal", f"nouvel appareil sur le réseau : {ip}" + (f" ({fab})" if fab else ""),
                            f"voisin:{mac}"))
        connus[mac] = ip

    if common.which("smartctl") or Path("/usr/sbin/smartctl").exists():
        _, lsblk = runner.query(["lsblk", "-J", "-d", "-o", "NAME,SIZE,MODEL,ROTA,TRAN,TYPE"])
        for d in materiel.parse_lsblk(lsblk):
            _, sante = runner.query(["smartctl", "-H", f"/dev/{d.nom}"], timeout=20)
            if materiel.parse_smart_health(sante) == "DÉFAILLANTE":
                alertes.append(("critical", f"le disque {d.nom} ({d.modele}) annonce une défaillance : "
                                "sauvegarde tes données maintenant (norns backup)", f"smart:{d.nom}"))

    nouvel_etat = {"ecoute": ecoutes, "voisins": connus, "date": maintenant}
    try:
        etat_path().parent.mkdir(parents=True, exist_ok=True)
        etat_path().write_text(json.dumps(nouvel_etat, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return alertes


def cmd_gjallarhorn(args, runner: Runner) -> int:
    alertes = ronde(runner)
    for urgence, message, cle in alertes:
        common.alerter("heimdall", urgence, message, systeme=True, cle=cle)
        print(("[!] " if urgence == "critical" else "[ ] ") + message)
    if not alertes:
        print("Gjallarhorn reste silencieux.")
    return 0
