"""Le partage et l'accès à distance.

    ygg partage                         état : dossiers partagés, adresse à taper sous Windows
    ygg partage ajouter DOSSIER         partager un dossier sur le réseau local (visible depuis
          [--nom N] [--ecriture]        Windows dans « Réseau », comme depuis Linux et macOS)
          [--invites]
    ygg partage retirer NOM

    ygg distance                        état de SSH et de WireGuard
    ygg distance ssh activer|desactiver [--cles-seulement] [--internet]
    ygg distance wireguard init [--hote ADRESSE] [--port 51820]
    ygg distance wireguard client NOM   un appareil de plus (fichier + QR code pour le téléphone)

Le partage passe par Samba (« usershares » : chaque utilisateur partage ses propres
dossiers, sans toucher à smb.conf) et wsdd2, qui annonce la machine aux Windows 10/11.
Heimdall n'ouvre les ports qu'au réseau local.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import common, heimdall
from .common import Runner, YggError

NOM_PARTAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")


# --------------------------------------------------------------------------
# Partage de dossiers (Samba)
# --------------------------------------------------------------------------

@dataclass
class Partage:
    nom: str
    chemin: str
    commentaire: str = ""
    acl: str = ""
    invites: bool = False

    @property
    def ecriture(self) -> bool:
        return ":F" in self.acl.upper() or ":C" in self.acl.upper()


def parse_usershares(text: str) -> list[Partage]:
    """Sortie de « net usershare info » (format ini) → partages."""
    partages: list[Partage] = []
    courant: Partage | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            courant = Partage(line[1:-1], "")
            partages.append(courant)
        elif courant and "=" in line:
            cle, _, valeur = line.partition("=")
            if cle == "path":
                courant.chemin = valeur
            elif cle == "comment":
                courant.commentaire = valeur
            elif cle == "usershare_acl":
                courant.acl = valeur
            elif cle == "guest_ok":
                courant.invites = valeur.lower() == "y"
    return partages


def nom_de_partage(dossier: Path, nom: str | None = None) -> str:
    """Le nom vu depuis le réseau : donné, ou tiré du dossier (sans accents ni espaces)."""
    if nom:
        if not NOM_PARTAGE_RE.match(nom):
            raise YggError(f"nom de partage invalide « {nom} » : lettres, chiffres, - et _ (40 au plus).")
        return nom
    import unicodedata

    base = unicodedata.normalize("NFKD", dossier.name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-_")[:40]
    return base or "partage"


def acl_pour(ecriture: bool) -> str:
    return "Everyone:F" if ecriture else "Everyone:R"


def adresses_ipv4() -> list[str]:
    """Adresses du réseau local (pour « \\\\192.168.1.20\\partage »)."""
    try:
        sortie = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [a for a in sortie.split() if ":" not in a and not a.startswith("127.")]


def paquet_installe(runner: Runner, *paquets: str) -> bool:
    _, out = runner.query(["dpkg-query", "-W", "-f=${Status}\n", *paquets])
    return out.count("install ok installed") == len(paquets)


def assurer_paquets(runner: Runner, paquets: list[str], raison: str, assume_yes: bool) -> None:
    if paquet_installe(runner, *paquets):
        return
    if not common.confirm(f"{raison} : installer {', '.join(paquets)} ?", default=True, assume_yes=assume_yes):
        raise YggError("abandon : paquets nécessaires non installés.")
    runner.run(["apt-get", "install", "-y", *paquets], root=True)


def cmd_partage(args, runner: Runner, config) -> int:
    action = {"status": "etat", "list": "etat", "add": "ajouter", "remove": "retirer"}.get(args.action, args.action)
    utilisateur = common.target_user()
    if action in (None, "etat"):
        return _etat_partage(runner, utilisateur)
    if action == "ajouter":
        return _ajouter_partage(args, runner, utilisateur)
    if action == "retirer":
        if not args.cible:
            raise YggError("indique le nom du partage : ygg partage retirer NOM")
        runner.run(["runuser", "-u", utilisateur, "--", "net", "usershare", "delete", args.cible], root=True)
        common.ok(f"« {args.cible} » n'est plus partagé.")
        return 0
    raise YggError(f"action inconnue : {action}")


def _etat_partage(runner: Runner, utilisateur: str) -> int:
    common.title("Partage de fichiers sur le réseau local")
    if not paquet_installe(runner, "samba"):
        common.info("Aucun dossier partagé (Samba n'est pas installé).")
        common.info(common.dim("ygg partage ajouter ~/Public — le dossier apparaîtra dans « Réseau » sous Windows."))
        return 0
    _, out = runner.query(["net", "usershare", "info"])
    partages = parse_usershares(out)
    hote = socket.gethostname()
    for service in ("smbd", "wsdd2"):
        code, _ = runner.query(["systemctl", "is-active", "--quiet", service])
        etat = common.style("actif", "green") if code == 0 else common.style("arrêté", "yellow")
        print(f"  {service:<7} {etat}")
    if not partages:
        common.info("Aucun dossier partagé pour l'instant.")
        return 0
    rows = [(p.nom, p.chemin, "lecture et écriture" if p.ecriture else "lecture seule",
             "oui" if p.invites else "non") for p in partages]
    print()
    print(common.table(rows, headers=("partage", "dossier", "droits", "sans mot de passe")))
    print()
    common.info(f"Sous Windows : Explorateur → Réseau → {hote.upper()}, ou tape « \\\\{hote}\\{partages[0].nom} ».")
    for ip in adresses_ipv4()[:2]:
        common.info(common.dim(f"par l'adresse : \\\\{ip}\\{partages[0].nom}"))
    common.info(f"Identifiant : {utilisateur} (mot de passe Samba, défini au premier partage).")
    return 0


def _ajouter_partage(args, runner: Runner, utilisateur: str) -> int:
    if not args.cible:
        raise YggError("indique le dossier à partager : ygg partage ajouter ~/Public")
    dossier = common.expand(args.cible).resolve()
    if not dossier.exists() and dossier.is_relative_to(Path.home()) \
            and common.confirm(f"{dossier} n'existe pas : le créer ?", default=True, assume_yes=args.yes):
        if not runner.dry_run:
            dossier.mkdir(parents=True)
    if not dossier.is_dir() and not runner.dry_run:
        raise YggError(f"{dossier} n'est pas un dossier.")
    nom = nom_de_partage(dossier, args.nom)
    common.title(f"Partager {dossier} sous le nom « {nom} »")
    if args.ecriture:
        common.warn("en écriture : les personnes autorisées pourront modifier et supprimer ces fichiers.")
    if args.invites:
        common.warn("sans mot de passe : tout appareil du réseau local y aura accès. "
                    "Windows 10/11 refuse d'ailleurs souvent ces accès « invités ».")

    assurer_paquets(runner, ["samba", "wsdd2"], "le partage passe par Samba et wsdd2", args.yes)
    _, groupes = runner.query(["id", "-nG", utilisateur])
    if "sambashare" not in groupes.split():
        runner.run(["usermod", "-aG", "sambashare", utilisateur], root=True)
    if not args.invites:
        code, _ = runner.query(["pdbedit", "-L", "-u", utilisateur], root=True)
        if code != 0:
            common.info(f"Choisis le mot de passe que Windows demandera pour {utilisateur} :")
            runner.run(["smbpasswd", "-a", utilisateur], root=True)
    # runuser ouvre une session neuve : le groupe sambashare y est déjà pris en compte
    runner.run(["runuser", "-u", utilisateur, "--", "net", "usershare", "add", nom, str(dossier),
                "Partagé avec Yggdrasil", acl_pour(args.ecriture), f"guest_ok={'y' if args.invites else 'n'}"],
               root=True)
    runner.run(["systemctl", "enable", "--now", "smbd", "nmbd", "wsdd2"], root=True, check=False)
    if heimdall.ouvrir(runner, "samba", "lan", "partage de fichiers"):
        common.ok("Heimdall laisse passer le partage, depuis le réseau local seulement.")
    hote = socket.gethostname()
    common.ok(f"« {nom} » est partagé.")
    common.info(f"Sous Windows : Explorateur → Réseau → {hote.upper()}, ou « \\\\{hote}\\{nom} ».")
    common.info(f"Sous Linux : smb://{hote}.local/{nom}")
    return 0


# --------------------------------------------------------------------------
# Accès à distance : SSH
# --------------------------------------------------------------------------

SSHD_YGG = Path("/etc/ssh/sshd_config.d/50-yggdrasil.conf")


def sshd_config(cles_seulement: bool) -> str:
    lignes = [
        "# Écrit par « ygg distance ssh activer » : connexion à distance sécurisée",
        "PermitRootLogin no",
        "MaxAuthTries 4",
        "LoginGraceTime 30",
    ]
    if cles_seulement:
        lignes += ["PasswordAuthentication no", "KbdInteractiveAuthentication no"]
    return "\n".join(lignes) + "\n"


def cles_autorisees(utilisateur: str) -> int:
    try:
        maison = Path(f"~{utilisateur}").expanduser()
    except RuntimeError:
        return 0
    texte = common.read_text(maison / ".ssh" / "authorized_keys")
    return sum(1 for line in texte.splitlines() if line.strip() and not line.startswith("#"))


def cmd_ssh(args, runner: Runner, utilisateur: str) -> int:
    if args.action in (None, "etat"):
        return _etat_distance(runner, utilisateur)
    if args.action == "activer":
        if args.cles_seulement and cles_autorisees(utilisateur) == 0:
            raise YggError("aucune clé dans ~/.ssh/authorized_keys : sans elle, tu ne pourrais plus te connecter. "
                           "Depuis ton autre ordinateur : ssh-copy-id " + f"{utilisateur}@{socket.gethostname()}.local")
        assurer_paquets(runner, ["openssh-server"], "le serveur SSH", args.yes)
        runner.write_file(SSHD_YGG, sshd_config(args.cles_seulement), root=True)
        runner.run(["systemctl", "enable", "--now", "ssh"], root=True)
        runner.run(["systemctl", "reload", "ssh"], root=True, check=False)
        source = "any" if args.internet else "lan"
        heimdall.ouvrir(runner, "ssh", source, "acces a distance")
        common.ok(f"SSH actif ({'clés seulement' if args.cles_seulement else 'mot de passe ou clé'}), "
                  f"ouvert {'à Internet' if args.internet else 'au réseau local'}.")
        common.info(f"Depuis un autre ordinateur : ssh {utilisateur}@{socket.gethostname()}.local")
        if args.internet and not args.cles_seulement:
            common.warn("ouvert à Internet avec mot de passe : préfère --cles-seulement, ou WireGuard.")
        return 0
    if args.action == "desactiver":
        runner.run(["systemctl", "disable", "--now", "ssh"], root=True, check=False)
        heimdall.fermer(runner, "ssh")
        common.ok("SSH arrêté, et le port refermé.")
        return 0
    raise YggError(f"action inconnue : {args.action}")


# --------------------------------------------------------------------------
# Accès à distance : WireGuard (un tunnel vers cette machine)
# --------------------------------------------------------------------------

WG_NOM = "wg-ygg"
WG_DIR = Path("/etc/wireguard")
WG_CONF = WG_DIR / f"{WG_NOM}.conf"
WG_PUB = WG_DIR / f"{WG_NOM}.pub"
WG_RESEAU = "10.66.66.0/24"
NOM_CLIENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def wg_serveur(reseau: str, port: int, cle_privee: str) -> str:
    net = ipaddress.ip_network(reseau, strict=False)
    adresse = next(net.hosts())
    return (f"# Yggdrasil — accès à distance à cette machine (ygg distance wireguard)\n"
            f"[Interface]\nAddress = {adresse}/{net.prefixlen}\nListenPort = {port}\nPrivateKey = {cle_privee}\n")


def wg_pair(nom: str, cle_publique: str, ip: str) -> str:
    return f"\n# client : {nom}\n[Peer]\nPublicKey = {cle_publique}\nAllowedIPs = {ip}/32\n"


def wg_client(cle_privee: str, ip: str, cle_serveur: str, hote: str, port: int, ip_serveur: str) -> str:
    return (f"# Accès à {socket.gethostname()} (Yggdrasil) par WireGuard\n"
            f"[Interface]\nPrivateKey = {cle_privee}\nAddress = {ip}/32\n\n"
            f"[Peer]\nPublicKey = {cle_serveur}\nEndpoint = {hote}:{port}\n"
            f"AllowedIPs = {ip_serveur}/32\nPersistentKeepalive = 25\n")


def wg_infos(conf: str) -> dict:
    """Adresse, port et clients d'une configuration serveur."""
    infos: dict = {"adresse": "", "port": 51820, "clients": []}
    nom = ""
    for line in conf.splitlines():
        line = line.strip()
        if line.startswith("# client :"):
            nom = line.split(":", 1)[1].strip()
        elif line.startswith("Address"):
            infos["adresse"] = line.split("=", 1)[1].strip()
        elif line.startswith("ListenPort"):
            infos["port"] = int(line.split("=", 1)[1])
        elif line.startswith("AllowedIPs"):
            infos["clients"].append((nom or "?", line.split("=", 1)[1].strip().split("/")[0]))
            nom = ""
    return infos


def wg_ip_libre(conf: str) -> str:
    infos = wg_infos(conf)
    if not infos["adresse"]:
        raise YggError("configuration WireGuard sans adresse : relance « ygg distance wireguard init ».")
    interface = ipaddress.ip_interface(infos["adresse"])
    prises = {str(interface.ip)} | {ip for _, ip in infos["clients"]}
    for hote in interface.network.hosts():
        if str(hote) not in prises:
            return str(hote)
    raise YggError("plus aucune adresse libre dans le réseau WireGuard.")


def _wg(runner: Runner, argv: list[str], entree: str | None = None) -> str:
    if runner.dry_run:
        return "CLE-SIMULEE="
    try:
        proc = subprocess.run(["wg", *argv], input=entree, capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise YggError("la commande wg a échoué (paquet wireguard-tools installé ?)") from exc
    return proc.stdout.strip()


def cmd_wireguard(args, runner: Runner, utilisateur: str) -> int:
    if args.action in (None, "etat"):
        return _etat_distance(runner, utilisateur)
    if args.action == "init":
        assurer_paquets(runner, ["wireguard-tools", "qrencode"], "WireGuard", args.yes)
        code, _ = runner.query(["test", "-e", str(WG_CONF)], root=True)
        if code == 0 and not common.confirm(f"{WG_CONF} existe déjà : le remplacer (les clients actuels "
                                            "ne pourront plus se connecter) ?", assume_yes=False):
            return 1
        privee = _wg(runner, ["genkey"])
        publique = _wg(runner, ["pubkey"], privee + "\n")
        runner.write_file(WG_CONF, wg_serveur(args.reseau, args.port, privee), root=True, mode="600")
        runner.write_file(WG_PUB, publique + "\n", root=True, mode="644")
        runner.run(["systemctl", "enable", "--now", f"wg-quick@{WG_NOM}"], root=True)
        heimdall.ouvrir(runner, f"{args.port}/udp", "any", "wireguard")
        # Les appareils du tunnel joignent tous les services de cette machine
        heimdall.ouvrir(runner, "1-65535/both", args.reseau, "clients wireguard")
        common.ok(f"tunnel WireGuard prêt sur le port {args.port}/udp.")
        common.info(f"Sur ta box, redirige le port UDP {args.port} vers cette machine.")
        common.info("Puis ajoute un appareil : ygg distance wireguard client telephone")
        return 0
    if args.action == "client":
        if not args.nom or not NOM_CLIENT_RE.match(args.nom):
            raise YggError("donne un nom à l'appareil (minuscules, chiffres, tirets) : ygg distance wireguard "
                           "client telephone")
        code, conf = runner.query(["cat", str(WG_CONF)], root=True)
        if code != 0:
            raise YggError("WireGuard n'est pas encore prêt : ygg distance wireguard init")
        infos = wg_infos(conf)
        if any(nom == args.nom for nom, _ in infos["clients"]):
            raise YggError(f"un appareil s'appelle déjà « {args.nom} ».")
        ip = wg_ip_libre(conf)
        privee = _wg(runner, ["genkey"])
        publique = _wg(runner, ["pubkey"], privee + "\n")
        runner.write_file(WG_CONF, conf + wg_pair(args.nom, publique, ip), root=True, mode="600")
        runner.run(["systemctl", "restart", f"wg-quick@{WG_NOM}"], root=True)
        hote = args.hote or f"{socket.gethostname()}.example.org"
        serveur = str(ipaddress.ip_interface(infos["adresse"]).ip)
        texte = wg_client(privee, ip, common.read_text(WG_PUB).strip() or "CLE-SERVEUR", hote, infos["port"], serveur)
        dossier = Path.home() / "yggdrasil-wireguard"
        fichier = dossier / f"{args.nom}.conf"
        runner.write_file(fichier, texte, mode="600")
        common.ok(f"appareil « {args.nom} » ajouté ({ip}). Sa configuration : {fichier}")
        if not args.hote:
            common.warn(f"remplace « {hote} » par ton adresse publique ou ton nom de domaine dans ce fichier.")
        if common.which("qrencode") and not runner.dry_run:
            common.info("Sur le téléphone, application WireGuard → « + » → scanner ce code :")
            subprocess.run(["qrencode", "-t", "ansiutf8", "-r", str(fichier)], check=False)
        return 0
    raise YggError(f"action inconnue : {args.action}")


def _etat_distance(runner: Runner, utilisateur: str) -> int:
    common.title("Accès à distance")
    if paquet_installe(runner, "openssh-server"):
        code, _ = runner.query(["systemctl", "is-active", "--quiet", "ssh"])
        cles_seules = "PasswordAuthentication no" in common.read_text(SSHD_YGG)
        etat = common.style("actif", "green") if code == 0 else common.style("arrêté", "yellow")
        print(f"  SSH        {etat}" + (" — clés seulement" if cles_seules else "")
              + f", {cles_autorisees(utilisateur)} clé(s) autorisée(s)")
    else:
        print("  SSH        non installé (ygg distance ssh activer)")
    code, conf = runner.query(["cat", str(WG_CONF)], root=common.is_root())
    if code == 0 and conf:
        infos = wg_infos(conf)
        actif, _ = runner.query(["systemctl", "is-active", "--quiet", f"wg-quick@{WG_NOM}"])
        etat = common.style("actif", "green") if actif == 0 else common.style("arrêté", "yellow")
        print(f"  WireGuard  {etat}, port {infos['port']}/udp, {len(infos['clients'])} appareil(s)")
        for nom, ip in infos["clients"]:
            print(f"               {nom:<16} {ip}")
    elif WG_PUB.exists():
        print("  WireGuard  configuré (sudo ygg distance pour le détail)")
    else:
        print("  WireGuard  non configuré (ygg distance wireguard init)")
    return 0


def cmd_distance(args, runner: Runner, config) -> int:
    utilisateur = common.target_user()
    if args.moyen == "ssh":
        return cmd_ssh(args, runner, utilisateur)
    if args.moyen == "wireguard":
        return cmd_wireguard(args, runner, utilisateur)
    return _etat_distance(runner, utilisateur)


def ajouter_commandes(sub, common_opts) -> None:
    p = sub.add_parser("partage", aliases=["share"], help="partager des dossiers sur le réseau (visibles depuis Windows)",
                       parents=[common_opts])
    p.add_argument("action", nargs="?", choices=["etat", "ajouter", "retirer", "status", "list", "add", "remove"])
    p.add_argument("cible", nargs="?", help="dossier à partager, ou nom du partage à retirer")
    p.add_argument("--nom", help="nom vu depuis le réseau")
    p.add_argument("--ecriture", action="store_true", help="autoriser la modification des fichiers")
    p.add_argument("--invites", action="store_true", help="sans mot de passe (déconseillé)")
    p.set_defaults(func=cmd_partage)
    p = sub.add_parser("distance", aliases=["remote"], help="accès à distance : SSH, WireGuard", parents=[common_opts])
    msub = p.add_subparsers(dest="moyen", metavar="moyen")
    s = msub.add_parser("ssh", help="serveur SSH", parents=[common_opts])
    s.add_argument("action", nargs="?", choices=["etat", "activer", "desactiver"])
    s.add_argument("--cles-seulement", action="store_true", help="refuser les mots de passe")
    s.add_argument("--internet", action="store_true", help="ouvrir aussi à Internet (sinon réseau local)")
    w = msub.add_parser("wireguard", help="tunnel WireGuard vers cette machine", parents=[common_opts])
    w.add_argument("action", nargs="?", choices=["etat", "init", "client"])
    w.add_argument("nom", nargs="?", help="nom de l'appareil (pour « client »)")
    w.add_argument("--hote", help="adresse publique ou nom de domaine de cette machine")
    w.add_argument("--port", type=int, default=51820)
    w.add_argument("--reseau", default=WG_RESEAU, help=f"réseau du tunnel ({WG_RESEAU})")
    p.set_defaults(func=cmd_distance)
