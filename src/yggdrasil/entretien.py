"""L'entretien de l'arbre : réparer, annuler, revenir en arrière, rapporter, choisir un miroir.

    ygg reparer [quoi]       systeme (dpkg, APT, Flatpak), plasma, son, reseau, grub, initramfs, ou tout
    ygg annuler [--liste]    défait la dernière action de la saga (installation, service…)
    ygg retour [instantané]  restaure un instantané système (Norns / Timeshift)
    ygg rapport              un rapport anonymisé à joindre à une demande d'aide
    ygg miroir [--appliquer] le miroir Debian le plus rapide d'ici
    ygg apps                 les logiciels que tu as ajoutés toi-même (sans les dépendances)
    ygg montee               passage guidé à la Debian stable suivante, instantané avant

Les fonctions pures (inverse, anonymiser, rewrite_sources…) sont testées sans système.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
import shlex
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import DEBIAN_BASE, __version__, common
from .common import Runner, YggError

# --------------------------------------------------------------------------
# Réparer
# --------------------------------------------------------------------------

REPARATIONS = {
    "systeme": "paquets à moitié installés (dpkg), dépendances cassées (APT), applications Flatpak",
    "plasma": "bureau qui se comporte mal : redémarre plasmashell (réglages sauvegardés si --reinitialiser)",
    "son": "plus de son : redémarre PipeWire et WirePlumber",
    "reseau": "réseau capricieux : redémarre NetworkManager",
    "grub": "menu de démarrage : régénère la configuration de GRUB",
    "initramfs": "démarrage bloqué après une mise à jour : régénère les images de démarrage (initramfs)",
}

PLASMA_FICHIERS = ("plasma-org.kde.plasma.desktop-appletsrc", "plasmashellrc")


def dpkg_interrompu(updates: Path = Path("/var/lib/dpkg/updates")) -> bool:
    try:
        return any(updates.iterdir())
    except OSError:
        return False


def reparer_systeme(runner: Runner, assume_yes: bool) -> None:
    common.title("Paquets Debian")
    if dpkg_interrompu():
        common.step("une installation a été interrompue : on la termine (dpkg --configure -a)")
        runner.run(["dpkg", "--configure", "-a"], root=True)
    code, _ = runner.query(["apt-get", "check", "-q"])
    if code != 0:
        common.step("dépendances cassées : APT les répare (apt-get -f install)")
        runner.run(["apt-get", "-f", "install", "-y"], root=True)
    else:
        common.ok("dépendances cohérentes.")
    if common.which("flatpak"):
        common.title("Applications Flatpak")
        runner.run(["flatpak", "repair", "--system"], root=True, check=False)
        runner.run(["flatpak", "repair", "--user"], check=False)


def reparer_plasma(runner: Runner, reinitialiser: bool, assume_yes: bool) -> None:
    common.title("Bureau Plasma")
    if reinitialiser:
        config = Path.home() / ".config"
        copie = config / f"plasma-avant-reparation-{dt.datetime.now():%Y%m%d-%H%M%S}"
        common.warn("le tableau de bord et les widgets reviennent à leur état d'origine "
                    f"(l'ancienne disposition est gardée dans {copie}).")
        if not common.confirm("Réinitialiser la disposition du bureau ?", assume_yes=assume_yes):
            return
        if not runner.dry_run:
            copie.mkdir(parents=True, exist_ok=True)
            for nom in PLASMA_FICHIERS:
                if (config / nom).exists():
                    (config / nom).rename(copie / nom)
    runner.run(["systemctl", "--user", "restart", "plasma-plasmashell.service"], check=False)
    common.ok("plasmashell redémarré.")


def cmd_reparer(args, runner: Runner, config) -> int:
    quoi = args.quoi or "systeme"
    if quoi not in (*REPARATIONS, "tout"):
        raise YggError(f"que réparer ? {', '.join(REPARATIONS)}, ou tout")
    cibles = list(REPARATIONS) if quoi == "tout" else [quoi]
    if quoi == "tout":
        cibles = [c for c in cibles if c not in ("grub", "initramfs")]
    for cible in cibles:
        common.info(common.dim(f"{cible} : {REPARATIONS[cible]}"))
    if not common.confirm("Lancer la réparation ?", default=True, assume_yes=args.yes):
        return 1
    for cible in cibles:
        if cible == "systeme":
            reparer_systeme(runner, args.yes)
        elif cible == "plasma":
            reparer_plasma(runner, args.reinitialiser, args.yes)
        elif cible == "son":
            common.title("Son")
            runner.run(["systemctl", "--user", "restart", "wireplumber", "pipewire", "pipewire-pulse"], check=False)
            common.ok("PipeWire redémarré. Vérifie la sortie choisie dans l'icône du son.")
        elif cible == "reseau":
            common.title("Réseau")
            runner.run(["systemctl", "restart", "NetworkManager"], root=True, check=False)
            common.ok("NetworkManager redémarré.")
        elif cible == "grub":
            common.title("Menu de démarrage")
            runner.run(["update-grub"], root=True)
        elif cible == "initramfs":
            common.title("Images de démarrage")
            runner.run(["update-initramfs", "-u", "-k", "all"], root=True)
    common.ok("réparation terminée. Si le souci persiste : ygg rapport, puis demande de l'aide.")
    return 0


# --------------------------------------------------------------------------
# Annuler : défaire la dernière action de la saga
# --------------------------------------------------------------------------

def _paquets(argv: list[str], debut: int) -> list[str]:
    """Les noms (pas les options) après la position `debut`."""
    return [a for a in argv[debut:] if not a.startswith("-")]


def inverse(cmd: list[str]) -> list[str] | None:
    """La commande qui défait `cmd`, ou None si on ne sait pas la défaire proprement."""
    if not cmd:
        return None
    if cmd[0] == "runuser" and "--" in cmd:
        prefixe = cmd[: cmd.index("--") + 1]
        reste = inverse(cmd[cmd.index("--") + 1:])
        return prefixe + reste if reste else None
    if cmd[:2] == ["apt-get", "install"]:
        paquets = _paquets(cmd, 2)
        return ["apt-get", "remove", "-y", *paquets] if paquets else None
    if cmd[:1] == ["apt-get"] and len(cmd) > 1 and cmd[1] in ("remove", "purge"):
        paquets = _paquets(cmd, 2)
        return ["apt-get", "install", "-y", *paquets] if paquets else None
    if cmd[:2] == ["flatpak", "install"]:
        noms = [n for n in _paquets(cmd, 2) if n != "flathub"]
        portee = "--user" if "--user" in cmd else "--system"
        return ["flatpak", "uninstall", portee, "-y", *noms] if noms else None
    if cmd[:2] == ["flatpak", "uninstall"] and "--unused" not in cmd:
        noms = _paquets(cmd, 2)
        portee = "--user" if "--user" in cmd else "--system"
        return ["flatpak", "install", portee, "-y", "flathub", *noms] if noms else None
    if cmd[:1] == ["systemctl"]:
        contraires = {"enable": "disable", "disable": "enable", "start": "stop", "stop": "start"}
        options = [a for a in cmd[1:] if a.startswith("-")]
        reste = [a for a in cmd[1:] if not a.startswith("-")]
        if reste and reste[0] in contraires and len(reste) > 1:
            return ["systemctl", *options, contraires[reste[0]], *reste[1:]]
        return None
    if cmd[:3] == ["net", "usershare", "add"] and len(cmd) > 3:
        return ["net", "usershare", "delete", cmd[3]]
    return None


def reversibles(entries: list[dict]) -> list[tuple[dict, list[str]]]:
    """Les actions réussies qu'on peut encore défaire, de la plus récente à la plus ancienne."""
    annulees = {e.get("annule") for e in entries if e.get("annule")}
    resultat = []
    for e in reversed(entries):
        if e.get("annule") or e.get("code") != 0 or e.get("date") in annulees:
            continue
        inv = inverse([str(c) for c in e.get("commande", [])])
        if inv:
            resultat.append((e, inv))
    return resultat


def cmd_annuler(args, runner: Runner, config) -> int:
    candidats = reversibles(common.saga_read())
    if args.liste:
        common.title("Ce qui peut être défait")
        if not candidats:
            common.info("rien dans la saga ne peut être défait automatiquement.")
        for e, inv in candidats[:10]:
            print(f"  {str(e.get('date', '')).replace('T', ' ')[:16]}  {shlex.join(e['commande'])}")
            print(common.dim(f"      ↩ {shlex.join(inv)}"))
        return 0
    if not candidats:
        common.info("Aucune action récente ne peut être défaite automatiquement.")
        common.info(common.dim("Pour revenir à un état antérieur du système : ygg retour"))
        return 0
    entree, inv = candidats[0]
    common.title("Annuler la dernière action")
    common.info(f"le {str(entree.get('date', '')).replace('T', ' à ')[:19]} : {shlex.join(entree['commande'])}")
    common.info(f"sera défaite par : {common.style(shlex.join(inv), 'leaf')}")
    if not common.confirm("Défaire cette action ?", assume_yes=args.yes):
        return 1
    common.SAGA_CONTEXTE["annule"] = entree.get("date")
    try:
        runner.run(inv, root=bool(entree.get("admin")))
    finally:
        common.SAGA_CONTEXTE.pop("annule", None)
    common.ok("action défaite.")
    return 0


def cmd_retour(args, runner: Runner, config) -> int:
    from . import norns

    argv = ["restore"] + ([args.instantane] if args.instantane else [])
    if args.yes:
        argv.append("--yes")
    if runner.dry_run:
        argv.append("--dry-run")
    return norns.main(argv)


# --------------------------------------------------------------------------
# Rapport anonymisé
# --------------------------------------------------------------------------

IPV4_RE = re.compile(r"\b(?!127\.)(?!0\.0\.0\.0)(?:\d{1,3}\.){3}\d{1,3}\b")
# Candidats IPv6 (au moins deux « : »), validés ensuite : une heure « 10:05:00 » n'en est pas une
IPV6_RE = re.compile(r"(?<![\w:])[0-9a-f]*:[0-9a-f]*:[0-9a-f:]*(?![\w:])", re.I)
MAC_RE = re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.I)
COURRIEL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def _ipv6(m: re.Match) -> str:
    try:
        adresse = ipaddress.IPv6Address(m.group(0))
    except ValueError:
        return m.group(0)
    return m.group(0) if adresse.is_loopback or adresse.is_unspecified else "[ipv6]"


def anonymiser(texte: str, utilisateur: str, hote: str) -> str:
    """Retire ce qui identifie la personne ou la machine (pour un forum, un ticket)."""
    texte = COURRIEL_RE.sub("[courriel]", texte)
    texte = MAC_RE.sub("[mac]", texte)
    texte = UUID_RE.sub("[uuid]", texte)
    texte = IPV6_RE.sub(_ipv6, texte)
    texte = IPV4_RE.sub("[ip]", texte)
    for nom, remplacement in ((hote, "[machine]"), (utilisateur, "[utilisateur]")):
        if nom and len(nom) >= 2:
            texte = re.sub(rf"(?<![\w-]){re.escape(nom)}(?![\w-])", remplacement, texte)
    return texte


def _section(titre: str, contenu: str) -> str:
    contenu = contenu.strip() or "(rien)"
    return f"## {titre}\n\n```\n{contenu}\n```\n"


def construire_rapport(runner: Runner) -> str:
    from . import doctor, sysinfo

    avant = common.style.enabled
    common.style.enabled = False
    try:
        morceaux = [f"# Rapport Yggdrasil {__version__} — {dt.datetime.now():%Y-%m-%d %H:%M}\n",
                    "Rapport anonymisé (adresses, identifiants et noms retirés), à joindre à une demande d'aide.\n"]
        morceaux.append(_section("Système", sysinfo.render(sysinfo.collect(runner))))
        checks = doctor.Doctor(runner).run()
        morceaux.append(_section("Diagnostic (ygg doctor)", doctor.render(checks)))
        _, echecs = runner.query(["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"])
        morceaux.append(_section("Services en échec", echecs))
        _, erreurs = runner.query(["journalctl", "-b", "-p", "err", "-n", "60", "--no-pager", "-o", "short-monotonic"],
                                  timeout=60)
        morceaux.append(_section("Erreurs du journal (ce démarrage)", erreurs))
        _, pci = runner.query(["lspci", "-nn"])
        _, disques = runner.query(["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"])
        morceaux.append(_section("Matériel", pci + "\n" + disques))
        saga = common.saga_read()[-20:]
        lignes = [f"{e.get('date', '')}  {e.get('outil', '?')}  code {e.get('code')}  "
                  f"{shlex.join(str(c) for c in e.get('commande', []))}" for e in saga]
        morceaux.append(_section("Dernières actions des outils Yggdrasil (saga)", "\n".join(lignes)))
    finally:
        common.style.enabled = avant
    return anonymiser("\n".join(morceaux), common.target_user(), socket.gethostname())


def cmd_rapport(args, runner: Runner, config) -> int:
    rapport = construire_rapport(runner)
    if args.sortie == "-":
        print(rapport)
        return 0
    chemin = common.expand(args.sortie) if args.sortie else \
        Path.home() / f"yggdrasil-rapport-{dt.datetime.now():%Y%m%d-%H%M}.md"
    chemin.write_text(rapport, encoding="utf-8")
    common.ok(f"rapport écrit dans {chemin}")
    common.info("Relis-le avant de le partager : adresses, noms et identifiants ont été remplacés.")
    return 0


# --------------------------------------------------------------------------
# Miroir Debian le plus rapide
# --------------------------------------------------------------------------

MIROIRS = (
    "http://deb.debian.org/debian/",
    "http://ftp.fr.debian.org/debian/",
    "http://ftp.be.debian.org/debian/",
    "http://ftp.ch.debian.org/debian/",
    "http://ftp.de.debian.org/debian/",
    "http://ftp.nl.debian.org/debian/",
    "http://ftp.uk.debian.org/debian/",
    "http://ftp.ca.debian.org/debian/",
    "http://ftp.us.debian.org/debian/",
    "http://debian.mirrors.ovh.net/debian/",
    "http://mirror.init7.net/debian/",
)
SOURCES = Path("/etc/apt/sources.list.d/debian.sources")


def mesurer(miroir: str, delai: float = 6.0) -> float | None:
    """Secondes pour télécharger le fichier Release de la version (None si injoignable)."""
    url = f"{miroir}dists/{DEBIAN_BASE}/Release"
    debut = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=delai) as reponse:  # noqa: S310 (URL fixe)
            reponse.read()
    except OSError:
        return None
    return time.monotonic() - debut


def miroir_actuel(sources: str) -> str:
    for line in sources.splitlines():
        if line.lower().startswith("uris:") and "security" not in line:
            return line.split(":", 1)[1].split()[0]
    return ""


def rewrite_sources(sources: str, miroir: str) -> str:
    """Remplace le miroir Debian (pas celui des mises à jour de sécurité)."""
    lignes = []
    for line in sources.splitlines():
        if line.lower().startswith("uris:") and "security" not in line:
            line = f"URIs: {miroir}"
        lignes.append(line)
    return "\n".join(lignes) + ("\n" if sources.endswith("\n") else "")


def cmd_miroir(args, runner: Runner, config) -> int:
    sources = common.read_text(SOURCES)
    actuel = miroir_actuel(sources)
    common.title("À la recherche du miroir le plus proche")
    with ThreadPoolExecutor(max_workers=8) as pool:
        temps = dict(zip(MIROIRS, pool.map(mesurer, MIROIRS)))
    classes = sorted(((t, m) for m, t in temps.items() if t is not None))
    if not classes:
        raise YggError("aucun miroir n'a répondu : vérifie la connexion à Internet.")
    rows = [(f"{t * 1000:.0f} ms", m + ("  (actuel)" if m == actuel else "")) for t, m in classes]
    print(common.table(rows, headers=("temps", "miroir")))
    meilleur = classes[0][1]
    if meilleur == actuel:
        common.ok("tu utilises déjà le plus rapide.")
        return 0
    if not args.appliquer:
        common.info(common.dim(f"« ygg miroir --appliquer » passerait à {meilleur}."))
        return 0
    if not sources:
        raise YggError(f"{SOURCES} est introuvable : rien à modifier.")
    if not common.confirm(f"Utiliser {meilleur} ?", default=True, assume_yes=args.yes):
        return 1
    runner.run(["cp", str(SOURCES), f"{SOURCES}.avant-miroir"], root=True)
    runner.write_file(SOURCES, rewrite_sources(sources, meilleur), root=True)
    runner.run(["apt-get", "update"], root=True)
    common.ok(f"miroir : {meilleur} (l'ancien fichier est gardé en .avant-miroir).")
    return 0


# --------------------------------------------------------------------------
# Tes logiciels : ce que tu as ajouté toi-même
# --------------------------------------------------------------------------

def paquets_de_base() -> set[str]:
    texte = common.read_text(common.STATE_DIR / "paquets-de-base.txt")
    return {ligne.strip() for ligne in texte.splitlines() if ligne.strip()}


def ajoutes(manuels: list[str], base: set[str]) -> list[str]:
    """Les paquets installés à ta demande qui n'étaient pas livrés avec le système."""
    return sorted({p.split(":")[0] for p in manuels if p.strip()} - base)


def parse_flatpak_apps(texte: str) -> list[tuple[str, str, str]]:
    """Sortie de « flatpak list --app --columns=application,name,installation »."""
    applis = []
    for ligne in texte.splitlines():
        parts = ligne.split("\t")
        if len(parts) >= 3 and "." in parts[0]:
            applis.append((parts[0], parts[1], parts[2]))
    return applis


def cmd_apps(args, runner: Runner, config) -> int:
    base = paquets_de_base()
    _, manuels = runner.query(["apt-mark", "showmanual"])
    paquets = ajoutes(manuels.split(), base) if base else []
    common.title("Les logiciels que tu as ajoutés")
    if not base:
        common.info(common.dim("liste des paquets d'origine absente : seules les applications Flatpak sont montrées."))
    elif paquets:
        _, details = runner.query(["dpkg-query", "-W", "-f=${Package}\t${Installed-Size}\t${binary:Summary}\n",
                                   *paquets])
        rows = []
        for ligne in details.splitlines():
            nom, _, reste = ligne.partition("\t")
            taille, _, resume = reste.partition("\t")
            ko = int(taille) if taille.isdigit() else 0
            rows.append((nom, common.human_size(ko * 1024) if ko else "-", resume[:60]))
        print(common.table(rows, headers=("paquet Debian", "taille", "description")))
    else:
        common.info("Aucun paquet Debian ajouté depuis l'installation.")
    _, sortie = runner.query(["flatpak", "list", "--app", "--columns=application,name,installation"])
    applis = parse_flatpak_apps(sortie)
    if applis:
        print()
        print(common.table([(nom, ident, inst) for ident, nom, inst in applis],
                           headers=("application Flatpak", "identifiant", "pour")))
    common.info(common.dim("ygg remove NOM pour en retirer un ; ygg annuler pour défaire la dernière installation."))
    return 0


# --------------------------------------------------------------------------
# La Debian suivante
# --------------------------------------------------------------------------

def stable_actuelle(delai: float = 10.0) -> str:
    """Le nom de code de la Debian stable du moment, lu sur le miroir officiel."""
    try:
        with urllib.request.urlopen("http://deb.debian.org/debian/dists/stable/Release",  # noqa: S310
                                    timeout=delai) as reponse:
            for ligne in reponse.read(4096).decode("utf-8", "replace").splitlines():
                if ligne.startswith("Codename:"):
                    return ligne.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def rewrite_suites(sources: str, ancienne: str, nouvelle: str) -> str:
    """trixie, trixie-updates, trixie-security, trixie-backports → la version suivante."""
    lignes = []
    for line in sources.splitlines():
        if line.lower().startswith("suites:"):
            suites = [re.sub(rf"^{re.escape(ancienne)}(?=$|-)", nouvelle, s) for s in line.split(":", 1)[1].split()]
            line = "Suites: " + " ".join(suites)
        elif line.startswith("deb") and f" {ancienne}" in line:
            line = re.sub(rf"(\s){re.escape(ancienne)}(?=[\s-])", rf"\g<1>{nouvelle}", line)
        lignes.append(line)
    return "\n".join(lignes) + ("\n" if sources.endswith("\n") else "")


def cmd_montee(args, runner: Runner, config) -> int:
    from . import ygg

    common.title("Monter vers la Debian suivante")
    nouvelle = args.vers or stable_actuelle()
    if not nouvelle:
        raise YggError("impossible de joindre deb.debian.org pour connaître la version stable.")
    if nouvelle == DEBIAN_BASE:
        common.ok(f"Debian {DEBIAN_BASE} est toujours la version stable : rien à faire.")
        return 0
    fichiers = sorted(Path("/etc/apt/sources.list.d").glob("*.sources")) + [Path("/etc/apt/sources.list")]
    concernes = [f for f in fichiers if DEBIAN_BASE in common.read_text(f)]
    common.info(f"Debian « {nouvelle} » est sortie. Le passage se fait ainsi :")
    for etape in ("mise à jour complète de la version actuelle, avec un instantané (Norns)",
                  f"les sources APT passent de {DEBIAN_BASE} à {nouvelle} : "
                  + ", ".join(str(f) for f in concernes),
                  "téléchargement et installation de la nouvelle version (une heure ou plus)",
                  "redémarrage"):
        common.step(etape)
    common.warn("garde l'ordinateur branché ; ne l'éteins pas pendant l'installation.")
    common.warn("les paquets d'Yggdrasil doivent aussi exister pour cette version : vérifie l'annonce du projet.")
    if not common.confirm(f"Passer à Debian {nouvelle} ?", assume_yes=args.yes):
        return 1
    ygg.snapshot_before_update(runner, args.yes)
    runner.run(["apt-get", "update"], root=True)
    runner.run(["apt-get", "full-upgrade", "-y"], root=True)
    for fichier in concernes:
        runner.run(["cp", str(fichier), f"{fichier}.avant-{nouvelle}"], root=True)
        runner.write_file(fichier, rewrite_suites(common.read_text(fichier), DEBIAN_BASE, nouvelle), root=True)
    runner.run(["apt-get", "update"], root=True)
    runner.run(["apt-get", "upgrade", "--without-new-pkgs", "-y"], root=True)
    runner.run(["apt-get", "full-upgrade", "-y"], root=True)
    common.ok(f"Debian {nouvelle} est installée : redémarre pour terminer.")
    return 0


def ajouter_commandes(sub, common_opts) -> None:
    p = sub.add_parser("reparer", aliases=["repair"], help="réparer : systeme, plasma, son, reseau, grub, initramfs, tout",
                       parents=[common_opts])
    p.add_argument("quoi", nargs="?", help="systeme (par défaut), plasma, son, reseau, grub, initramfs ou tout")
    p.add_argument("--reinitialiser", action="store_true", help="plasma : remettre la disposition d'origine")
    p.set_defaults(func=cmd_reparer)
    p = sub.add_parser("annuler", aliases=["undo"], help="défaire la dernière action (installation, service…)",
                       parents=[common_opts])
    p.add_argument("--liste", action="store_true", help="voir ce qui peut être défait")
    p.set_defaults(func=cmd_annuler)
    p = sub.add_parser("retour", aliases=["rollback"], help="restaurer un instantané système (Norns)",
                       parents=[common_opts])
    p.add_argument("instantane", nargs="?", help="nom de l'instantané (sinon, l'assistant demande)")
    p.set_defaults(func=cmd_retour)
    p = sub.add_parser("rapport", aliases=["report"], help="rapport anonymisé pour demander de l'aide",
                       parents=[common_opts])
    p.add_argument("-o", "--sortie", help="fichier de sortie (« - » pour l'afficher)")
    p.set_defaults(func=cmd_rapport)
    p = sub.add_parser("miroir", aliases=["mirror"], help="trouver le miroir Debian le plus rapide",
                       parents=[common_opts])
    p.add_argument("--appliquer", action="store_true", help="l'utiliser (sources APT modifiées)")
    p.set_defaults(func=cmd_miroir)
    p = sub.add_parser("apps", help="les logiciels que tu as ajoutés toi-même", parents=[common_opts])
    p.set_defaults(func=cmd_apps)
    p = sub.add_parser("montee", aliases=["release-upgrade"], help="passer à la Debian stable suivante, guidé",
                       parents=[common_opts])
    p.add_argument("--vers", help="nom de code visé (par défaut : la stable du moment)")
    p.set_defaults(func=cmd_montee)


