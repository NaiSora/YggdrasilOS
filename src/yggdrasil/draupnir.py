"""Draupnir, l'anneau d'Odin qui en fait naître huit autres : la graine de ta machine.

    draupnir                       ce que la graine emporterait
    draupnir graine [FICHIER]      forger la graine (.tar.gz, ou .tar.gz.gpg avec --chiffrer)
    draupnir lire FICHIER          ce qu'une graine contient
    draupnir planter FICHIER       la replanter ici (sur un Yggdrasil fraîchement installé)

La graine emporte tes royaumes et leurs logiciels, les paquets Debian et les
applications Flatpak que tu as ajoutés, tes réglages Yggdrasil, les règles de
Heimdall, tes services Bifröst (sans leurs données : « bifrost sauvegarder »
s'en charge), tes modèles Brokkr, tes royaumes personnels et quelques réglages
du bureau (Plasma, Konsole, git). Une graine se replante sur autant de machines
que tu veux. Les mots de passe des services et tes clés SSH n'y entrent qu'avec
--chiffrer (et --secrets pour les clés).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import secrets
import socket
import sys
import tarfile
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from . import __version__, common
from .common import Runner, YggError

MANIFESTE = "graine.toml"
# Réglages de la maison emportés par défaut (relatifs au dossier personnel)
FICHIERS_MAISON = (
    ".bash_aliases", ".gitconfig", ".config/yggdrasil",
    ".config/kdeglobals", ".config/kwinrc", ".config/kglobalshortcutsrc", ".config/plasmarc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc", ".config/plasmashellrc", ".config/kscreenlockerrc",
    ".config/konsolerc", ".local/share/konsole", ".config/dolphinrc", ".config/katerc",
    ".local/share/yggdrasil/brokkr/templates", ".local/share/yggdrasil/realms",
)
# Fichiers secrets : seulement dans une graine chiffrée
MOTS_SECRETS = ("motdepasse", "password", "secret", "token", ".key", ".pem", "credentials")
TAILLE_MAX = 20 * 1024 * 1024  # un fichier plus gros n'est pas un réglage
TAILLE_MAX_SERVICE = 1024 * 1024
IGNORES = {"__pycache__", ".cache", "Cache", "cache"}
PAQUETS_EXCLUS = re.compile(r"^(linux-(image|headers|modules)-|yggdrasil-|live-|calamares)")
VARIABLES_SECRETES = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|WEBHOOK|API_KEY)", re.I)


@dataclass
class Graine:
    machine: str = ""
    version: str = ""
    date: str = ""
    chiffree: bool = False
    royaumes: dict[str, list[str]] = field(default_factory=dict)
    paquets: list[str] = field(default_factory=list)
    flatpaks: list[str] = field(default_factory=list)
    services: dict[str, str] = field(default_factory=dict)
    fichiers: list[str] = field(default_factory=list)
    secrets_retires: list[str] = field(default_factory=list)

    def to_toml(self) -> str:
        data = {k: v for k, v in asdict(self).items() if not isinstance(v, dict)}
        texte = "# La graine de Draupnir : « draupnir lire » la décrit, « draupnir planter » la replante.\n\n"
        texte += common.dump_toml(data) + "\n"
        for table in ("royaumes", "services"):
            valeurs = getattr(self, table)
            if valeurs:
                texte += "\n" + common.dump_toml({table: valeurs}) + "\n"
        return texte

    @classmethod
    def depuis_toml(cls, texte: str) -> Graine:
        try:
            data = tomllib.loads(texte)
        except tomllib.TOMLDecodeError as exc:
            raise YggError(f"graine illisible : {exc}") from exc
        connus = cls.__dataclass_fields__
        graine = cls(**{k: v for k, v in data.items() if k in connus})
        # Une graine vient peut-être d'ailleurs : seuls des noms sages passent
        graine.royaumes = {r: [x for x in ids if re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(x))]
                           for r, ids in graine.royaumes.items() if re.fullmatch(r"[a-z][a-z0-9-]*", r)}
        graine.services = {n: m for n, m in graine.services.items()
                           if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", n) and re.fullmatch(r"[a-z0-9-]+", m)}
        from .realms import APT_RE, FLATPAK_RE
        graine.paquets = [p for p in graine.paquets if APT_RE.match(p)]
        graine.flatpaks = [f for f in graine.flatpaks if FLATPAK_RE.match(f)]
        return graine


# --------------------------------------------------------------------------
# Récolte : ce que la graine emporte
# --------------------------------------------------------------------------

def est_secret(chemin: str) -> bool:
    nom = chemin.lower()
    return any(m in nom for m in MOTS_SECRETS) or "/.ssh/" in f"/{nom}"


def fichiers_de(maison: Path, chemins: list[str]) -> list[Path]:
    """Les fichiers ordinaires sous ces chemins (relatifs à la maison), sans caches ni liens."""
    trouves: list[Path] = []
    for rel in chemins:
        racine = maison / rel
        if racine.is_symlink():
            continue
        if racine.is_file():
            trouves.append(racine)
        elif racine.is_dir():
            for p in sorted(racine.rglob("*")):
                if p.is_file() and not p.is_symlink() and not any(x in IGNORES for x in p.relative_to(maison).parts):
                    trouves.append(p)
    return trouves


def secrets_de_service(modele: str) -> set[str]:
    from . import bifrost
    stack = bifrost.load_stacks().get(modele)
    return {v.name for v in stack.env if v.kind == "secret"} if stack else set()


def nettoyer_env(texte: str, secrets_connus: set[str]) -> tuple[str, list[str]]:
    """Retire les valeurs secrètes d'un .env (elles seront régénérées à la plantation)."""
    lignes, retires = [], []
    for ligne in texte.splitlines():
        cle, sep, valeur = ligne.partition("=")
        cle = cle.strip()
        if sep and not cle.startswith("#") and valeur.strip() and (cle in secrets_connus
                                                                      or VARIABLES_SECRETES.search(cle)):
            lignes.append(f"{cle}=")
            retires.append(cle)
        else:
            lignes.append(ligne)
    return "\n".join(lignes) + "\n", retires


def recolter(runner: Runner, config, maison: Path, *, chiffree: bool = False, secrets_ssh: bool = False,
             avec: list[str] | None = None) -> tuple[Graine, dict[str, bytes | Path]]:
    """La graine et ses fichiers (nom dans l'archive → contenu ou chemin)."""
    from . import bifrost, entretien, realms

    graine = Graine(machine=socket.gethostname(), version=common.os_release().get("VERSION_ID", __version__),
                    date=dt.datetime.now().isoformat(timespec="minutes"), chiffree=chiffree)
    contenu: dict[str, bytes | Path] = {}

    # Royaumes : ceux que l'arbre a plantés, avec les logiciels choisis
    connus = realms.load_realms()
    etat = realms.load_state()
    deja_apt: set[str] = set()
    deja_flatpak: set[str] = set()
    for nom, infos in sorted(etat.items()):
        if nom in connus and infos.get("logiciels"):
            graine.royaumes[nom] = sorted(infos["logiciels"])
            deja_apt |= set(infos.get("apt", []))
            deja_flatpak |= set(infos.get("flatpak", []))

    # Paquets Debian ajoutés depuis l'installation (hors royaumes et noyaux)
    base = entretien.paquets_de_base()
    if base:
        _, manuels = runner.query(["apt-mark", "showmanual"])
        graine.paquets = [p for p in entretien.ajoutes(manuels.split(), base)
                          if p not in deja_apt and not PAQUETS_EXCLUS.match(p)]
    _, sortie = runner.query(["flatpak", "list", "--app", "--columns=application,name,installation"])
    graine.flatpaks = sorted({a for a, _, _ in entretien.parse_flatpak_apps(sortie)} - deja_flatpak)

    # Réglages de la maison
    chemins = list(FICHIERS_MAISON) + list(config.get("draupnir", {}).get("fichiers", [])) + list(avec or [])
    if secrets_ssh:
        chemins.append(".ssh")
    for p in fichiers_de(maison, chemins):
        rel = p.relative_to(maison).as_posix()
        if p.stat().st_size > TAILLE_MAX:
            common.warn(f"{rel} : trop gros pour une graine ({common.human_size(p.stat().st_size)}), laissé")
            continue
        if est_secret(rel) and not chiffree:
            graine.secrets_retires.append(rel)
            continue
        contenu[f"maison/{rel}"] = p

    # Heimdall : ses règles et sa zone
    texte = common.read_text(_heimdall_config())
    if texte.strip():
        contenu["heimdall/heimdall.json"] = texte.encode()

    # Services Bifröst : leur configuration, pas leurs données
    racine = bifrost.home_dir(config)
    for nom, modele in bifrost.deploiements(config).items():
        graine.services[nom] = modele
        for p in sorted((racine / nom).iterdir()):
            if not p.is_file() or p.is_symlink() or p.stat().st_size > TAILLE_MAX_SERVICE:
                continue
            if p.name == ".env" and not chiffree:
                propre, retires = nettoyer_env(p.read_text(encoding="utf-8", errors="replace"),
                                               secrets_de_service(modele))
                graine.secrets_retires += [f"bifrost/{nom}/.env:{c}" for c in retires]
                contenu[f"bifrost/{nom}/.env"] = propre.encode()
            else:
                contenu[f"bifrost/{nom}/{p.name}"] = p
    graine.fichiers = sorted(contenu)
    return graine, contenu


def _heimdall_config() -> Path:
    from . import heimdall
    return heimdall.CONFIG_PATH


def ecrire_archive(graine: Graine, contenu: dict[str, bytes | Path], destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as tar:
        def ajouter(nom: str, donnees: bytes, mode: int = 0o644) -> None:
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            info.mode = mode
            info.mtime = int(dt.datetime.now().timestamp())
            tar.addfile(info, io.BytesIO(donnees))

        ajouter(MANIFESTE, graine.to_toml().encode())
        for nom, source in sorted(contenu.items()):
            if isinstance(source, Path):
                mode = 0o600 if est_secret(nom) or source.stat().st_mode & 0o077 == 0 else 0o644
                if os.access(source, os.X_OK):
                    mode |= 0o100
                ajouter(nom, source.read_bytes(), mode)
            else:
                ajouter(nom, source, 0o600 if nom.endswith(".env") else 0o644)


# --------------------------------------------------------------------------
# Lecture : une graine n'est qu'une archive, on la lit avec méfiance
# --------------------------------------------------------------------------

def nom_sur(nom: str) -> bool:
    chemin = PurePosixPath(nom)
    return (not chemin.is_absolute() and ".." not in chemin.parts and bool(chemin.parts)
            and chemin.parts[0] in ("maison", "heimdall", "bifrost", MANIFESTE))


def ouvrir(fichier: Path) -> tuple[Graine, dict[str, tuple[bytes, int]]]:
    """Le manifeste et les fichiers d'une graine déchiffrée."""
    try:
        tar = tarfile.open(fichier, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise YggError(f"{fichier} n'est pas une graine de Draupnir ({exc}).") from exc
    fichiers: dict[str, tuple[bytes, int]] = {}
    with tar:
        for membre in tar.getmembers():
            if not membre.isfile() or not nom_sur(membre.name):
                continue  # ni liens, ni chemins absolus, ni « .. »
            donnees = tar.extractfile(membre)
            if donnees is not None:
                fichiers[membre.name] = (donnees.read(), membre.mode & 0o777)
    if MANIFESTE not in fichiers:
        raise YggError(f"{fichier} n'a pas de {MANIFESTE} : ce n'est pas une graine.")
    graine = Graine.depuis_toml(fichiers.pop(MANIFESTE)[0].decode("utf-8", errors="replace"))
    return graine, fichiers


def dechiffrer(fichier: Path, runner: Runner, mot_de_passe: Path | None, dossier: Path) -> Path:
    if not fichier.name.endswith(".gpg"):
        return fichier
    if not common.which("gpg"):
        raise YggError("graine chiffrée : gpg est nécessaire (sudo apt install gnupg).")
    sortie = dossier / fichier.name.removesuffix(".gpg")
    runner_lecture = Runner(verbose=runner.verbose)  # déchiffrer ne modifie rien : même en simulation
    runner_lecture.run(_gpg(["--decrypt", "--output", str(sortie), str(fichier)], mot_de_passe),
                       env=_gpg_env())
    return sortie


def _gpg(args: list[str], mot_de_passe: Path | None) -> list[str]:
    cmd = ["gpg", "--quiet", "--yes", "--no-symkey-cache"]  # la phrase de passe ne reste pas en mémoire
    if mot_de_passe:
        cmd += ["--batch", "--pinentry-mode", "loopback", "--passphrase-file", str(mot_de_passe)]
    return cmd + args


def _gpg_env() -> dict[str, str]:
    try:
        return {"GPG_TTY": os.ttyname(sys.stdin.fileno())}
    except (OSError, AttributeError, ValueError):
        return {}


# --------------------------------------------------------------------------
# Affichage
# --------------------------------------------------------------------------

def decrire(graine: Graine, fichiers: list[str]) -> None:
    from . import realms

    connus = realms.load_realms()
    if graine.machine:
        common.info(f"Graine de {common.style(graine.machine, 'gold')}"
                    + (f", Yggdrasil {graine.version}" if graine.version else "")
                    + (f", {graine.date.replace('T', ' à ')}" if graine.date else "")
                    + (" — chiffrée" if graine.chiffree else ""))
    print()
    if graine.royaumes:
        print("  " + common.style("Royaumes", "leaf"))
        for nom, ids in graine.royaumes.items():
            r = connus.get(nom)
            titre = f"{r.rune} {r.title}".strip() if r else nom
            print(f"    · {titre:<22} {', '.join(ids)}")
    for titre, liste in (("Paquets Debian ajoutés", graine.paquets), ("Applications Flatpak", graine.flatpaks)):
        if liste:
            print("  " + common.style(titre, "leaf") + common.dim(f" ({len(liste)})"))
            print("    " + ", ".join(liste))
    if graine.services:
        print("  " + common.style("Services Bifröst", "leaf"))
        for nom, modele in graine.services.items():
            print(f"    · {nom:<22} {modele}" + ("" if nom == modele else common.dim(f" ({modele})")))
    maison = [f.removeprefix("maison/") for f in fichiers if f.startswith("maison/")]
    if maison:
        dossiers = sorted({"/".join(f.split("/")[:2]) if f.startswith((".config/", ".local/")) else f
                           for f in maison})
        print("  " + common.style("Réglages de la maison", "leaf") + common.dim(f" ({len(maison)} fichiers)"))
        print("    " + ", ".join(dossiers))
    if any(f.startswith("heimdall/") for f in fichiers):
        print("  " + common.style("Heimdall", "leaf") + " : règles et zone du pare-feu")
    if graine.secrets_retires:
        print()
        common.info(common.dim(f"{len(graine.secrets_retires)} secret(s) laissé(s) hors de la graine "
                               "(mots de passe régénérés à la plantation ; --chiffrer pour les emporter)."))


# --------------------------------------------------------------------------
# Plantation
# --------------------------------------------------------------------------

def disponibles(paquets: list[str], runner: Runner) -> tuple[list[str], list[str]]:
    """Les paquets que les dépôts de cette machine connaissent, et les autres."""
    if not paquets:
        return [], []
    _, sortie = runner.query(["apt-cache", "policy", *paquets], timeout=120)
    trouves, courant = set(), ""
    for ligne in sortie.splitlines():
        if ligne and not ligne.startswith(" ") and ligne.endswith(":"):
            courant = ligne[:-1].split(":")[0]
        elif courant and ligne.strip().startswith(("Candidate:", "Candidat :", "Candidat:")):
            if "(none)" not in ligne and "(aucun)" not in ligne:
                trouves.add(courant)
    return [p for p in paquets if p in trouves], [p for p in paquets if p not in trouves]


def planter(graine: Graine, fichiers: dict[str, tuple[bytes, int]], runner: Runner, config, maison: Path, *,
            assume_yes: bool = False, demarrer: bool = False) -> int:
    from . import bifrost, realms

    a_installer, inconnus = disponibles(graine.paquets, runner)
    deja = realms.installed_apt(a_installer, runner) if a_installer else set()
    a_installer = [p for p in a_installer if p not in deja]
    deja_flatpaks = realms.installed_flatpaks(runner) if graine.flatpaks else set()
    flatpaks = [f for f in graine.flatpaks if f not in deja_flatpaks]
    maison_f = {n: v for n, v in fichiers.items() if n.startswith("maison/")}
    services = {n: v for n, v in fichiers.items() if n.startswith("bifrost/")}
    racine_services = bifrost.home_dir(config)
    nouveaux_services = [n for n in graine.services if not (racine_services / n / "compose.yml").exists()]

    common.title("Ce que Draupnir va planter")
    if maison_f:
        common.step(f"{len(maison_f)} réglages dans {maison} (les fichiers remplacés sont gardés en .avant-draupnir)")
    if "heimdall/heimdall.json" in fichiers:
        common.step("les règles de Heimdall (pare-feu)")
    if graine.royaumes:
        common.step("royaumes : " + ", ".join(graine.royaumes))
    if a_installer:
        common.step(f"{len(a_installer)} paquets Debian : {', '.join(a_installer)}")
    if inconnus:
        common.warn(f"inconnus des dépôts d'ici, laissés de côté : {', '.join(inconnus)}")
    if flatpaks:
        common.step(f"{len(flatpaks)} applications Flatpak : {', '.join(flatpaks)}")
    if nouveaux_services:
        common.step("services Bifröst : " + ", ".join(nouveaux_services)
                    + ("" if demarrer else common.dim(" (configurés, lancés avec « bifrost start »)")))
    if not common.confirm("Planter la graine ?", default=True, assume_yes=assume_yes):
        common.warn("plantation annulée.")
        return 1

    # 1. Réglages de la maison (d'abord : les royaumes personnels doivent exister)
    for nom, (donnees, mode) in sorted(maison_f.items()):
        cible = maison / nom.removeprefix("maison/")
        if runner.dry_run:
            print(common.style("  [simulation] ", "magenta") + f"écriture de {cible}")
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        if cible.is_file() and cible.read_bytes() != donnees:
            ancien = cible.with_name(cible.name + ".avant-draupnir")
            if not ancien.exists():
                cible.replace(ancien)
        cible.write_bytes(donnees)
        os.chmod(cible, 0o600 if mode & 0o077 == 0 else (0o755 if mode & 0o100 else 0o644))
    if maison_f:
        common.ok("réglages de la maison replantés.")

    # 2. Heimdall
    if "heimdall/heimdall.json" in fichiers:
        texte = fichiers["heimdall/heimdall.json"][0].decode("utf-8", errors="replace")
        try:
            json.loads(texte)
        except ValueError:
            common.warn("règles de Heimdall illisibles : laissées de côté.")
        else:
            runner.write_file(_heimdall_config(), texte, root=True)
            if common.which("heimdall") or runner.dry_run:
                runner.run(["heimdall", "apply"], root=True, check=False)
            common.ok("Heimdall a retrouvé ses règles.")

    # 3. Paquets Debian
    if a_installer:
        runner.run(["apt-get", "update"], root=True)
        runner.run(["apt-get", "install", "-y", *a_installer], root=True)
        common.ok(f"{len(a_installer)} paquets installés.")

    # 4. Royaumes (les royaumes personnels viennent d'être replantés)
    connus = realms.load_realms()
    for nom, ids in graine.royaumes.items():
        realm = connus.get(nom)
        if not realm:
            common.warn(f"royaume inconnu ici : {nom}")
            continue
        choix = [x for x in realm.logiciels if x.id in ids] or realm.choisir()
        try:
            realms.add_realm(realm, runner, assume_yes=True, choix=choix)
        except YggError as exc:
            common.warn(f"royaume {realm.title} : {exc}")

    # 5. Flatpak
    if flatpaks:
        realms.ensure_flathub(runner)
        runner.run(["flatpak", "install", "--system", "-y", "--noninteractive", "flathub", *flatpaks],
                   root=True, check=False)

    # 6. Services Bifröst : leur configuration (mots de passe régénérés s'ils sont restés dehors)
    for nom in nouveaux_services:
        dest = racine_services / nom
        secrets_connus = secrets_de_service(graine.services[nom])
        for chemin, (donnees, _) in services.items():
            if not chemin.startswith(f"bifrost/{nom}/"):
                continue
            cible = dest / chemin.split("/", 2)[2]
            if chemin.endswith("/.env"):
                donnees = completer_env(donnees.decode("utf-8", errors="replace"), secrets_connus).encode()
            if runner.dry_run:
                print(common.style("  [simulation] ", "magenta") + f"écriture de {cible}")
                continue
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(donnees)
            if cible.name == ".env":
                os.chmod(cible, 0o600)
        if demarrer:
            docker = bifrost.Docker(runner)
            docker.reseau()
            docker.compose(dest, "up", "-d")
    if nouveaux_services:
        common.ok("services Bifröst replantés" + ("" if demarrer else " : « bifrost start NOM » les lance."))

    print()
    common.ok("La graine a pris. Ouvre une nouvelle session pour retrouver ton bureau tel quel.")
    return 0


def completer_env(texte: str, secrets_connus: set[str]) -> str:
    """Un mot de passe neuf pour chaque secret resté hors de la graine."""
    lignes = []
    for ligne in texte.splitlines():
        cle, sep, valeur = ligne.partition("=")
        if sep and not valeur.strip() and cle.strip() in secrets_connus:
            ligne = f"{cle.strip()}={secrets.token_urlsafe(24)}"
        lignes.append(ligne)
    return "\n".join(lignes) + "\n"


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def maison_cible() -> Path:
    from . import realms
    return realms.maison_utilisateur()


def nom_par_defaut() -> Path:
    jour = dt.date.today().isoformat()
    return Path.cwd() / f"graine-{socket.gethostname()}-{jour}.tar.gz"


def cmd_apercu(args, runner: Runner, config) -> int:
    graine, contenu = recolter(runner, config, maison_cible())
    common.title("Draupnir : ce que ta graine emporterait")
    decrire(graine, list(contenu))
    print()
    common.info(common.dim("« draupnir graine » la forge ; « draupnir planter FICHIER » la replante ailleurs."))
    return 0


def cmd_graine(args, runner: Runner, config) -> int:
    if args.secrets and not args.chiffrer:
        raise YggError("--secrets (clés SSH) demande --chiffrer : une clé ne voyage jamais en clair.")
    destination = common.expand(args.fichier) if args.fichier else nom_par_defaut()
    if destination.is_dir():
        destination = destination / nom_par_defaut().name
    graine, contenu = recolter(runner, config, maison_cible(), chiffree=args.chiffrer, secrets_ssh=args.secrets,
                               avec=args.avec)
    common.title("Draupnir forge ta graine")
    decrire(graine, list(contenu))
    print()
    if args.chiffrer and not destination.name.endswith(".gpg"):
        destination = destination.with_name(destination.name + ".gpg")
    if runner.dry_run:
        common.info(f"simulation : graine dans {destination}")
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    if args.chiffrer:
        if not common.which("gpg"):
            raise YggError("gpg est nécessaire pour chiffrer (sudo apt install gnupg).")
        with tempfile.TemporaryDirectory(prefix="draupnir-") as tmp:
            clair = Path(tmp) / "graine.tar.gz"
            ecrire_archive(graine, contenu, clair)
            runner.run(_gpg(["--symmetric", "--cipher-algo", "AES256", "--output", str(destination), str(clair)],
                            args.mot_de_passe and common.expand(args.mot_de_passe)), env=_gpg_env())
    else:
        ecrire_archive(graine, contenu, destination)
        os.chmod(destination, 0o600)
    taille = common.human_size(destination.stat().st_size)
    common.ok(f"graine forgée : {destination} ({taille})")
    common.info(common.dim("Sur l'autre machine : draupnir planter " + destination.name))
    return 0


def _ouvrir_graine(args, runner: Runner, tmp: Path) -> tuple[Graine, dict[str, tuple[bytes, int]]]:
    fichier = common.expand(args.fichier)
    if not fichier.is_file():
        raise YggError(f"graine introuvable : {fichier}")
    clair = dechiffrer(fichier, runner, args.mot_de_passe and common.expand(args.mot_de_passe), tmp)
    return ouvrir(clair)


def cmd_lire(args, runner: Runner, config) -> int:
    with tempfile.TemporaryDirectory(prefix="draupnir-") as tmp:
        graine, fichiers = _ouvrir_graine(args, runner, Path(tmp))
    common.title(f"La graine {Path(args.fichier).name}")
    decrire(graine, list(fichiers))
    return 0


def cmd_planter(args, runner: Runner, config) -> int:
    if common.is_root() and os.environ.get("SUDO_USER"):
        raise YggError("lance « draupnir planter » sans sudo : il demandera le mot de passe quand il le faut.")
    with tempfile.TemporaryDirectory(prefix="draupnir-") as tmp:
        graine, fichiers = _ouvrir_graine(args, runner, Path(tmp))
    common.title(f"La graine {Path(args.fichier).name}")
    decrire(graine, list(fichiers))
    return planter(graine, fichiers, runner, config, maison_cible(), assume_yes=args.yes, demarrer=args.demarrer)


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-n", "--dry-run", action="store_true", help="simuler")
    opts.add_argument("-v", "--verbose", action="store_true")
    opts.add_argument("-y", "--yes", action="store_true")
    opts.add_argument("--mot-de-passe", metavar="FICHIER", help="phrase de passe (graine chiffrée) lue dans un fichier")

    parser = argparse.ArgumentParser(prog="draupnir", parents=[opts],
                                     description="Draupnir : la graine de ta machine, à replanter ailleurs.")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    sub.add_parser("apercu", help="ce que la graine emporterait", parents=[opts]).set_defaults(func=cmd_apercu)
    p = sub.add_parser("graine", help="forger la graine", parents=[opts])
    p.add_argument("fichier", nargs="?", help="fichier ou dossier de destination")
    p.add_argument("--chiffrer", action="store_true", help="chiffrer (gpg) : les mots de passe voyagent avec")
    p.add_argument("--secrets", action="store_true", help="emporter aussi ~/.ssh (avec --chiffrer)")
    p.add_argument("--avec", action="append", metavar="CHEMIN", help="un fichier ou dossier de plus (relatif à ~)")
    p.set_defaults(func=cmd_graine)
    p = sub.add_parser("lire", help="ce qu'une graine contient", parents=[opts])
    p.add_argument("fichier")
    p.set_defaults(func=cmd_lire)
    p = sub.add_parser("planter", help="replanter une graine sur cette machine", parents=[opts])
    p.add_argument("fichier")
    p.add_argument("--demarrer", action="store_true", help="lancer aussi les services Bifröst")
    p.set_defaults(func=cmd_planter)
    return parser


def _main(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["apercu", *(sys.argv[1:] if argv is None else argv)])
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner, common.load_config())


def main(argv=None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
