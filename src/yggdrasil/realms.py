"""Royaumes : les neuf mondes de l'arbre, des ensembles de logiciels prêts à l'emploi.

    ygg realm add muspelheim                 les logiciels cochés par défaut
    ygg realm add muspelheim --sans heroic   à la carte (--avec, --sans, --seulement, --choisir)

Chaque royaume est décrit par un fichier TOML dans /usr/share/yggdrasil/realms (et
~/.local/share/yggdrasil/realms pour les tiens). Un fichier de royaume est une donnée :
il ne déclare que des paquets, des applications Flatpak, des groupes, des services et
des actions choisies dans une liste fixe (ACTIONS) — jamais de commande arbitraire.
"""

from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import common
from .common import DATA_DIR, STATE_DIR, Runner, YggError

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
APT_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]+(:[a-z0-9]+)?$")
FLATPAK_RE = re.compile(r"^[A-Za-z][\w-]*(\.[\w-]+){2,}$")
UNIT_RE = re.compile(r"^[\w@.-]+$")
GROUP_RE = re.compile(r"^[a-z_][a-z0-9_-]*$")

FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"


# --------------------------------------------------------------------------
# Description des royaumes
# --------------------------------------------------------------------------

@dataclass
class Logiciel:
    """Un élément à cocher d'un royaume."""

    id: str
    nom: str
    description: str = ""
    apt: list[str] = field(default_factory=list)
    flatpak: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    defaut: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "Logiciel":
        return cls(
            id=str(data.get("id", "")),
            nom=str(data.get("nom", data.get("id", ""))),
            description=str(data.get("description", "")).strip(),
            apt=list(data.get("apt", [])),
            flatpak=list(data.get("flatpak", [])),
            groups=list(data.get("groups", [])),
            services=list(data.get("services", [])),
            actions=list(data.get("actions", [])),
            defaut=bool(data.get("defaut", True)),
        )

    def problemes(self) -> list[str]:
        p = []
        if not NAME_RE.match(self.id):
            p.append(f"identifiant de logiciel invalide « {self.id} »")
        p += [f"paquet apt invalide « {x} »" for x in self.apt if not APT_RE.match(x)]
        p += [f"identifiant flatpak invalide « {x} »" for x in self.flatpak if not FLATPAK_RE.match(x)]
        p += [f"groupe invalide « {g} »" for g in self.groups if not GROUP_RE.match(g)]
        p += [f"service invalide « {s} »" for s in self.services if not UNIT_RE.match(s)]
        p += [f"action inconnue « {a} »" for a in self.actions if a not in ACTIONS]
        if not (self.apt or self.flatpak or self.actions):
            p.append(f"« {self.id} » ne déclare aucun logiciel")
        return p


@dataclass
class Realm:
    name: str
    title: str
    description: str
    logiciels: list[Logiciel] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)  # actions du royaume entier
    next_steps: str = ""
    icon: str = "applications-other"
    surnom: str = ""
    theme: str = ""
    rune: str = ""
    rune_nom: str = ""
    rune_sens: str = ""
    voyageurs: list[str] = field(default_factory=list)
    perso: bool = False  # royaume créé ou importé par l'utilisateur

    @classmethod
    def from_dict(cls, data: dict, source: str = "?", perso: bool = False) -> "Realm":
        try:
            logiciels = [Logiciel.from_dict(d) for d in data.get("logiciels", [])]
            # Ancien format (et royaumes personnels simples) : paquets au niveau du royaume
            if any(data.get(k) for k in ("apt", "flatpak")):
                logiciels.insert(0, Logiciel(
                    id="base", nom=data["title"], apt=list(data.get("apt", [])),
                    flatpak=list(data.get("flatpak", [])), groups=list(data.get("groups", [])),
                    services=list(data.get("services", []))))
            realm = cls(
                name=data["name"],
                title=data["title"],
                description=data["description"].strip(),
                logiciels=logiciels,
                actions=list(data.get("actions", [])),
                next_steps=data.get("next_steps", "").strip(),
                icon=data.get("icon", "applications-other"),
                surnom=data.get("surnom", ""),
                theme=data.get("theme", ""),
                rune=data.get("rune", ""),
                rune_nom=data.get("rune_nom", ""),
                rune_sens=data.get("rune_sens", ""),
                voyageurs=list(data.get("voyageurs", [])),
                perso=perso,
            )
        except KeyError as exc:
            raise YggError(f"royaume {source} : champ obligatoire manquant {exc}") from exc
        realm.validate(source)
        return realm

    def validate(self, source: str = "?") -> None:
        problems = []
        if not NAME_RE.match(self.name):
            problems.append(f"nom invalide « {self.name} »")
        for logiciel in self.logiciels:
            problems += logiciel.problemes()
        ids = [x.id for x in self.logiciels]
        problems += [f"logiciel en double « {i} »" for i in sorted({i for i in ids if ids.count(i) > 1})]
        problems += [f"action inconnue « {a} »" for a in self.actions if a not in ACTIONS]
        if not self.logiciels:
            problems.append("aucun logiciel déclaré")
        if problems:
            raise YggError(f"royaume {source} : " + "; ".join(problems))

    @property
    def nom_complet(self) -> str:
        return f"{self.title} — {self.surnom}" if self.surnom else self.title

    def choisir(self, avec: set[str] | None = None, sans: set[str] | None = None,
                seulement: set[str] | None = None) -> list[Logiciel]:
        """Les logiciels retenus : ceux cochés par défaut, modifiés par avec/sans, ou seulement ceux-là."""
        ids = {x.id for x in self.logiciels}
        inconnus = ((avec or set()) | (sans or set()) | (seulement or set())) - ids
        if inconnus:
            raise YggError(f"{self.title} n'a pas de logiciel « {', '.join(sorted(inconnus))} » "
                           f"(disponibles : {', '.join(x.id for x in self.logiciels)})")
        if seulement:
            return [x for x in self.logiciels if x.id in seulement]
        return [x for x in self.logiciels
                if (x.defaut or x.id in (avec or set())) and x.id not in (sans or set())]

    # Vue d'ensemble (tous les logiciels) : statut, retrait, Centre
    @property
    def apt(self) -> list[str]:
        return _union(x.apt for x in self.logiciels)

    @property
    def flatpak(self) -> list[str]:
        return _union(x.flatpak for x in self.logiciels)

    @property
    def groups(self) -> list[str]:
        return _union(x.groups for x in self.logiciels)

    @property
    def services(self) -> list[str]:
        return _union(x.services for x in self.logiciels)


def _union(listes) -> list[str]:
    vus: list[str] = []
    for liste in listes:
        vus += [x for x in liste if x not in vus]
    return vus


def realms_dir() -> Path:
    return DATA_DIR / "realms"


def user_realms_dir() -> Path:
    return common.user_data_dir() / "yggdrasil" / "realms"


ORDRE = ("asgard", "midgard", "nidavellir", "muspelheim", "alfheim", "vanaheim", "jotunheim", "niflheim", "helheim")


def load_realms(directory: Path | None = None, user_directory: Path | None = None) -> dict[str, Realm]:
    """Les royaumes livrés, dans l'ordre des neuf mondes, puis les tiens."""
    directory = directory or realms_dir()
    realms: dict[str, Realm] = {}
    for path in sorted(directory.glob("*.toml")):
        realm = Realm.from_dict(common.load_toml(path), source=path.name)
        if realm.name in realms:
            raise YggError(f"royaume en double : {realm.name}")
        realms[realm.name] = realm
    perso_dir = user_directory if user_directory is not None else user_realms_dir()
    for path in sorted(perso_dir.glob("*.toml")) if perso_dir.is_dir() else []:
        try:
            realm = Realm.from_dict(common.load_toml(path), source=path.name, perso=True)
        except YggError as exc:
            common.warn(f"royaume personnel ignoré : {exc}")
            continue
        if realm.name in realms:
            common.warn(f"royaume personnel « {realm.name} » ignoré : ce nom est déjà pris.")
            continue
        realms[realm.name] = realm
    rang = {nom: i for i, nom in enumerate(ORDRE)}
    return dict(sorted(realms.items(), key=lambda kv: (kv[1].perso, rang.get(kv[0], 99), kv[0])))


def get_realm(name: str, realms: dict[str, Realm] | None = None) -> Realm:
    realms = realms if realms is not None else load_realms()
    nom = sans_accents(name.lower())
    if nom not in realms:
        known = ", ".join(realms) or "aucun"
        raise YggError(f"royaume inconnu « {name} » (disponibles : {known})")
    return realms[nom]


def sans_accents(texte: str) -> str:
    """« Ásgard », « Jötunheim » → asgard, jotunheim (on tape le nom comme on peut)."""
    import unicodedata

    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()


# --------------------------------------------------------------------------
# Voyageurs (« Quel voyageur es-tu ? »)
# --------------------------------------------------------------------------

@dataclass
class Voyageur:
    id: str
    nom: str
    description: str
    icon: str = "user-identity"


def load_voyageurs(path: Path | None = None) -> list[Voyageur]:
    data = common.load_toml(path or DATA_DIR / "voyageurs.toml")
    return [Voyageur(v["id"], v["nom"], v.get("description", ""), v.get("icon", "user-identity"))
            for v in data.get("voyageur", [])]


def royaumes_pour(voyageurs: list[str], realms: dict[str, Realm]) -> list[str]:
    """Les royaumes à pré-cocher pour ces voyageurs, dans l'ordre des mondes."""
    return [nom for nom, r in realms.items() if set(r.voyageurs) & set(voyageurs)]


# --------------------------------------------------------------------------
# État des paquets
# --------------------------------------------------------------------------

def parse_dpkg_status(output: str) -> set[str]:
    """Analyse « dpkg-query -W -f '${Package}\\t${db:Status-Abbrev}\\n' »."""
    installed = set()
    for line in output.splitlines():
        if "\t" not in line:
            continue
        pkg, status = line.split("\t", 1)
        if status.startswith("ii"):
            installed.add(pkg.split(":")[0])
    return installed


def installed_apt(packages: list[str], runner: Runner) -> set[str]:
    if not packages or not common.which("dpkg-query"):
        return set()
    names = [p.split(":")[0] for p in packages]
    _, out = runner.query(["dpkg-query", "-W", "-f", "${Package}\t${db:Status-Abbrev}\n", *names])
    return parse_dpkg_status(out)


def installed_flatpaks(runner: Runner) -> set[str]:
    if not common.which("flatpak"):
        return set()
    _, out = runner.query(["flatpak", "list", "--app", "--columns=application"])
    return {line.strip() for line in out.splitlines() if line.strip()}


@dataclass
class RealmStatus:
    realm: Realm
    missing_apt: list[str]
    missing_flatpak: list[str]
    choix: list[Logiciel] = field(default_factory=list)
    installes: set[str] = field(default_factory=set)  # identifiants des logiciels déjà là

    @property
    def installed(self) -> bool:
        return not self.missing_apt and not self.missing_flatpak

    @property
    def partial(self) -> bool:
        return not self.installed and bool(self.installes)

    @property
    def label(self) -> str:
        if self.installed:
            return "installé"
        if self.partial:
            return "partiel"
        return "—"


def realm_status(realm: Realm, runner: Runner, flatpaks: set[str] | None = None,
                 choix: list[Logiciel] | None = None) -> RealmStatus:
    """Ce qui manque des logiciels choisis (par défaut : ceux cochés d'office)."""
    choix = choix if choix is not None else realm.choisir()
    have_apt = installed_apt(realm.apt, runner)
    have_flat = flatpaks if flatpaks is not None else installed_flatpaks(runner)
    present = {x.id for x in realm.logiciels
               if (x.apt or x.flatpak)
               and all(p.split(":")[0] in have_apt for p in x.apt) and all(f in have_flat for f in x.flatpak)}
    return RealmStatus(
        realm,
        missing_apt=[p for p in _union(x.apt for x in choix) if p.split(":")[0] not in have_apt],
        missing_flatpak=[a for a in _union(x.flatpak for x in choix) if a not in have_flat],
        choix=choix,
        installes=present,
    )


# --------------------------------------------------------------------------
# Mémoire des installations (pour une désinstallation propre, et l'arbre vivant)
# --------------------------------------------------------------------------

def state_file() -> Path:
    return STATE_DIR / "realms.json"


def load_state() -> dict[str, dict]:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict, runner: Runner) -> None:
    runner.write_file(state_file(), json.dumps(state, indent=2, ensure_ascii=False) + "\n", root=True)


# --------------------------------------------------------------------------
# Actions : ce qu'un royaume configure (liste fixe, jamais lue dans un fichier)
# --------------------------------------------------------------------------

def en_utilisateur(cmd: list[str]) -> tuple[list[str], bool]:
    """Une commande à lancer au nom de l'utilisateur, même si ygg tourne en root (sudo)."""
    user = common.target_user()
    if common.is_root() and user != "root":
        return ["runuser", "-u", user, "--", *cmd], True
    return cmd, False


def maison_utilisateur() -> Path:
    try:
        return Path(f"~{common.target_user()}").expanduser()
    except RuntimeError:
        return Path.home()


def action_i386(runner: Runner, assume_yes: bool) -> None:
    _, archs = runner.query(["dpkg", "--print-foreign-architectures"])
    if "i386" not in archs.split():
        runner.run(["dpkg", "--add-architecture", "i386"], root=True)
        runner.run(["apt-get", "update"], root=True)
    runner.run(["apt-get", "install", "-y", "libgl1-mesa-dri:i386", "mesa-vulkan-drivers:i386"], root=True)


def action_cle_ssh(runner: Runner, assume_yes: bool) -> None:
    cle = maison_utilisateur() / ".ssh" / "id_ed25519"
    if cle.exists():
        common.ok(f"clé SSH déjà présente : {cle}.pub")
        return
    common.info("Une phrase de passe protège ta clé si on te la vole (Entrée pour s'en passer).")
    cmd, root = en_utilisateur(["ssh-keygen", "-t", "ed25519", "-C",
                                f"{common.target_user()}@{socket.gethostname()}", "-f", str(cle)])
    runner.run(cmd, root=root)
    common.ok(f"clé publique : {cle}.pub")


def action_identite_git(runner: Runner, assume_yes: bool) -> None:
    lire, _ = en_utilisateur(["git", "config", "--global", "user.name"])
    _, nom = runner.query(lire)
    if nom.strip():
        common.ok(f"git te connaît déjà : {nom.strip()}")
        return
    nom = common.ask("Ton nom pour git (prénom et nom)")
    courriel = common.ask("Ton courriel pour git")
    if not nom or not courriel:
        common.info("identité git laissée vide : « git config --global user.name » plus tard.")
        return
    for cle, valeur in (("user.name", nom), ("user.email", courriel), ("init.defaultBranch", "main")):
        cmd, root = en_utilisateur(["git", "config", "--global", cle, valeur])
        runner.run(cmd, root=root)


def action_mimir(runner: Runner, assume_yes: bool) -> None:
    from . import mimir

    argv = ["install"] + (["--yes"] if assume_yes else []) + (["--dry-run"] if runner.dry_run else [])
    mimir.main(argv)


def action_ssh(runner: Runner, assume_yes: bool) -> None:
    from types import SimpleNamespace

    from . import partage

    partage.cmd_ssh(SimpleNamespace(action="activer", cles_seulement=False, internet=False, yes=assume_yes),
                    runner, common.target_user())


ACTIONS: dict[str, tuple[str, Callable[[Runner, bool], None]]] = {
    "architecture-i386": ("bibliothèques 32 bits (architecture i386), pour les jeux hors Flatpak", action_i386),
    "cle-ssh": ("une clé SSH ed25519 à ton nom, si tu n'en as pas", action_cle_ssh),
    "identite-git": ("ton nom et ton courriel pour git, s'ils manquent", action_identite_git),
    "mimir": ("Ollama et le modèle recommandé pour Mímir", action_mimir),
    "ssh": ("le serveur SSH, ouvert au réseau local seulement", action_ssh),
}


# --------------------------------------------------------------------------
# Actions sur les royaumes
# --------------------------------------------------------------------------

def ensure_flathub(runner: Runner) -> None:
    if not common.which("flatpak"):
        runner.run(["apt-get", "install", "-y", "flatpak"], root=True)
    runner.run(
        ["flatpak", "remote-add", "--system", "--if-not-exists", "flathub", FLATHUB_URL],
        root=True,
    )


def actions_de(realm: Realm, choix: list[Logiciel]) -> list[str]:
    return _union([realm.actions] + [x.actions for x in choix])


def plan_lines(status: RealmStatus, user: str) -> list[str]:
    realm, choix = status.realm, status.choix or status.realm.choisir()
    lines = []
    if status.missing_apt:
        lines.append(f"paquets Debian à installer ({len(status.missing_apt)}) : " + " ".join(status.missing_apt))
    if status.missing_flatpak:
        lines.append(f"applications Flatpak à installer ({len(status.missing_flatpak)}) : "
                     + " ".join(status.missing_flatpak))
    groupes = _union(x.groups for x in choix)
    if groupes:
        lines.append(f"ajout de « {user} » aux groupes : " + ", ".join(groupes))
    services = _union(x.services for x in choix)
    if services:
        lines.append("services activés au démarrage : " + ", ".join(services))
    for action in actions_de(realm, choix):
        lines.append("configuration : " + ACTIONS[action][0])
    return lines


def afficher_choix(realm: Realm, choix: list[Logiciel], installes: set[str] | None = None) -> None:
    retenus = {x.id for x in choix}
    for x in realm.logiciels:
        if x.id in (installes or set()):
            marque = common.style("✔", "green")
        elif x.id in retenus:
            marque = common.style("●", "gold")
        else:
            marque = common.dim("○")
        print(f"    {marque} {x.nom:<30} {common.dim(x.description)}")


def choisir_interactif(realm: Realm, choix: list[Logiciel]) -> list[Logiciel]:
    """Liste à cocher dans le terminal : on bascule un logiciel en tapant son numéro."""
    retenus = {x.id for x in choix}
    while True:
        print()
        for i, x in enumerate(realm.logiciels, 1):
            marque = "[x]" if x.id in retenus else "[ ]"
            print(f"  {i:>2} {marque} {x.nom:<30} {common.dim(x.description)}")
        reponse = common.ask("Numéros à cocher ou décocher (Entrée pour valider)")
        if not reponse:
            return [x for x in realm.logiciels if x.id in retenus]
        for morceau in re.split(r"[\s,]+", reponse):
            if morceau.isdigit() and 1 <= int(morceau) <= len(realm.logiciels):
                retenus ^= {realm.logiciels[int(morceau) - 1].id}


def add_realm(realm: Realm, runner: Runner, *, assume_yes: bool = False,
              choix: list[Logiciel] | None = None, interactif: bool = False) -> bool:
    choix = choix if choix is not None else realm.choisir()
    status = realm_status(realm, runner, choix=choix)
    user = common.target_user()
    common.title(f"{realm.rune} Royaume {realm.nom_complet}".strip())
    common.info(realm.description)
    print()
    afficher_choix(realm, choix, status.installes)
    if interactif:
        choix = choisir_interactif(realm, choix)
        status = realm_status(realm, runner, choix=choix)
    if not choix:
        common.warn("aucun logiciel choisi.")
        return False
    lines = plan_lines(status, user)
    if not lines:
        common.ok("déjà installé.")
        return True
    print()
    for line in lines:
        common.step(line)
    if not common.confirm("Lancer l'installation ?", assume_yes=assume_yes):
        common.warn("installation annulée.")
        return False

    if status.missing_apt:
        runner.run(["apt-get", "update"], root=True)
        runner.run(["apt-get", "install", "-y", *status.missing_apt], root=True)
    if status.missing_flatpak:
        ensure_flathub(runner)
        runner.run(
            ["flatpak", "install", "--system", "-y", "--noninteractive", "flathub", *status.missing_flatpak],
            root=True,
        )
    groupes = _union(x.groups for x in choix)
    for group in groupes:
        code, _ = runner.query(["getent", "group", group])
        if code != 0:
            runner.run(["groupadd", "--system", group], root=True)
        runner.run(["usermod", "-aG", group, user], root=True)
    for service in _union(x.services for x in choix):
        runner.run(["systemctl", "enable", "--now", service], root=True)
    for action in actions_de(realm, choix):
        common.title(ACTIONS[action][0].capitalize())
        try:
            ACTIONS[action][1](runner, assume_yes)
        except YggError as exc:
            common.warn(f"{action} : {exc}")

    state = load_state()
    previous = state.get(realm.name, {"apt": [], "flatpak": [], "logiciels": []})
    state[realm.name] = {
        "apt": sorted(set(previous.get("apt", [])) | set(status.missing_apt)),
        "flatpak": sorted(set(previous.get("flatpak", [])) | set(status.missing_flatpak)),
        "logiciels": sorted(set(previous.get("logiciels", [])) | {x.id for x in choix}),
    }
    save_state(state, runner)

    common.ok(f"royaume {realm.title} installé.")
    if groupes:
        common.warn("déconnecte-toi puis reconnecte-toi pour que les nouveaux groupes soient pris en compte.")
    if realm.next_steps:
        common.title("Et maintenant ?")
        for line in realm.next_steps.splitlines():
            common.info(line)
    return True


def remove_realm(realm: Realm, runner: Runner, *, assume_yes: bool = False, purge: bool = False) -> bool:
    state = load_state()
    recorded = state.get(realm.name)
    common.title(f"Retrait du royaume {realm.title}")
    if not recorded:
        common.warn(
            "ce royaume n'a pas été installé par « ygg realm add » : par prudence, "
            "rien ne sera désinstallé automatiquement."
        )
        common.info("Paquets du royaume : " + " ".join(realm.apt + realm.flatpak))
        return False
    apt_pkgs = sorted(set(recorded.get("apt", [])) & installed_apt(recorded.get("apt", []), runner))
    flat = sorted(set(recorded.get("flatpak", [])) & installed_flatpaks(runner))
    if not apt_pkgs and not flat:
        common.ok("rien à retirer.")
        state.pop(realm.name, None)
        save_state(state, runner)
        return True
    if apt_pkgs:
        common.step("paquets Debian retirés : " + " ".join(apt_pkgs))
    if flat:
        common.step("applications Flatpak retirées : " + " ".join(flat))
    if not common.confirm("Confirmer le retrait ?", assume_yes=assume_yes):
        common.warn("retrait annulé.")
        return False
    if apt_pkgs:
        runner.run(["apt-get", "purge" if purge else "remove", "-y", *apt_pkgs], root=True)
        runner.run(["apt-get", "autoremove", "-y"], root=True)
    if flat:
        runner.run(["flatpak", "uninstall", "--system", "-y", "--noninteractive", *flat], root=True)
    state.pop(realm.name, None)
    save_state(state, runner)
    common.ok(f"royaume {realm.title} retiré.")
    return True


# --------------------------------------------------------------------------
# Royaumes personnels : créer, exporter, importer
# --------------------------------------------------------------------------

def _toml_liste(valeurs: list[str]) -> str:
    return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in valeurs) + "]"


def to_toml(realm: Realm) -> str:
    """Un royaume en TOML (partageable : un seul fichier)."""
    lignes = [f"name = {json.dumps(realm.name)}", f"title = {json.dumps(realm.title, ensure_ascii=False)}"]
    for cle in ("surnom", "theme", "rune", "rune_nom", "rune_sens", "icon"):
        if getattr(realm, cle):
            lignes.append(f"{cle} = {json.dumps(getattr(realm, cle), ensure_ascii=False)}")
    if realm.voyageurs:
        lignes.append(f"voyageurs = {_toml_liste(realm.voyageurs)}")
    if realm.actions:
        lignes.append(f"actions = {_toml_liste(realm.actions)}")
    lignes.append(f'description = """\n{realm.description}\n"""')
    if realm.next_steps:
        lignes.append(f'next_steps = """\n{realm.next_steps}\n"""')
    for x in realm.logiciels:
        lignes += ["", "[[logiciels]]", f"id = {json.dumps(x.id)}", f"nom = {json.dumps(x.nom, ensure_ascii=False)}"]
        if x.description:
            lignes.append(f"description = {json.dumps(x.description, ensure_ascii=False)}")
        for cle in ("apt", "flatpak", "groups", "services", "actions"):
            if getattr(x, cle):
                lignes.append(f"{cle} = {_toml_liste(getattr(x, cle))}")
        if not x.defaut:
            lignes.append("defaut = false")
    return "\n".join(lignes) + "\n"


def royaume_depuis(nom: str, titre: str, paquets: list[str], flatpaks: list[tuple[str, str]]) -> Realm:
    """Un royaume personnel fait de ce que tu as installé toi-même (un logiciel par élément)."""
    logiciels = [Logiciel(id=_ident(p), nom=p, apt=[p]) for p in paquets]
    logiciels += [Logiciel(id=_ident(ident.split(".")[-1]), nom=libelle or ident, flatpak=[ident])
                  for ident, libelle in flatpaks]
    vus: set[str] = set()
    for x in logiciels:  # identifiants uniques
        base, i = x.id, 2
        while x.id in vus:
            x.id, i = f"{base}-{i}", i + 1
        vus.add(x.id)
    realm = Realm(name=nom, title=titre, description=f"Royaume personnel : {titre}.", logiciels=logiciels,
                  icon="user-identity", perso=True)
    realm.validate(nom)
    return realm


def _ident(texte: str) -> str:
    ident = re.sub(r"[^a-z0-9-]+", "-", sans_accents(texte.lower())).strip("-")
    return ident if ident and ident[0].isalpha() else f"l-{ident or 'x'}"
