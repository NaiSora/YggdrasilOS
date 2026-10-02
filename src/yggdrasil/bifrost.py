"""bifrost — le pont arc-en-ciel : tes services en conteneurs, chacun en une commande.

    bifrost list                                   les services, par domaine, et ce qui tourne
    bifrost up minecraft --nom survie --type fabric --version 1.21.4 --memoire 6G
    bifrost up minecraft --nom pack --modpack modrinth:cobblemon-fabric
    bifrost up valheim | open-webui | metube | fileshare --windows | …
    bifrost logs survie -f        bifrost console survie        bifrost commande survie "op Astrid"
    bifrost mods survie ajouter lithium sodium     (Modrinth : version compatible choisie seule)
    bifrost sauvegarder survie                     (le monde est copié sans couper le serveur)
    bifrost redemarrage survie 04:00               bifrost discord survie <webhook>
    bifrost reseau proxy survie creatif            (Velocity : plusieurs serveurs, une adresse)
    bifrost deploy ~/Projets/MonBot                (héberge un projet Brokkr : relancé s'il plante)
    bifrost portail                                (https://nom.localhost pour chaque interface web)
    bifrost update | down | restart | remove [--purge] <nom>

Chaque service vit dans ~/bifrost/<nom>/ : compose.yml, .env et ses données. Rien n'est
installé d'avance : chaque service arrive avec sa commande. Par défaut, les ports ne sont
ouverts que sur 127.0.0.1 ; bifrost demande s'il faut les exposer au réseau local.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import common, voix
from .common import DATA_DIR, Runner, YggError

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
NOM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
RESEAU = "bifrost"
CATEGORIES = {
    "jeux": "Serveurs de jeu",
    "ia": "Intelligence artificielle",
    "creation": "Création et diffusion",
    "dev": "Développement",
    "partage": "Partage et notifications",
    "reseau": "Réseau",
}


@dataclass
class EnvVar:
    name: str
    description: str = ""
    default: str = ""
    kind: str = "string"  # string | path | secret | choice | port
    choices: list[str] = field(default_factory=list)
    ask: bool = False
    option: str = ""  # nom de l'option en ligne de commande (« type » → --type)


@dataclass
class Eula:
    var: str
    text: str
    url: str


@dataclass
class Stack:
    name: str
    title: str
    description: str
    directory: Path
    categorie: str = "dev"
    url: str = ""
    ports: list[str] = field(default_factory=list)
    host_network: bool = False
    heimdall_service: str = ""
    lan_default: bool = False
    notes: str = ""
    console: list[str] = field(default_factory=list)
    env: list[EnvVar] = field(default_factory=list)
    eula: Eula | None = None
    instances: bool = False  # plusieurs exemplaires côte à côte (--nom)
    web: dict = field(default_factory=dict)  # {"conteneur": …, "port": …} pour le portail
    windows_partage: str = ""  # variable du dossier à rendre visible depuis Windows (--windows)

    @classmethod
    def load(cls, directory: Path) -> "Stack":
        meta = common.load_toml(directory / "stack.toml")
        if not (directory / "compose.yml").is_file():
            raise YggError(f"service {directory.name} : compose.yml manquant")
        try:
            env = [EnvVar(**e) for e in meta.get("env", [])]
            eula = Eula(**meta["eula"]) if "eula" in meta else None
            stack = cls(
                name=meta["name"],
                title=meta["title"],
                description=meta["description"].strip(),
                directory=directory,
                categorie=meta.get("categorie", "dev"),
                url=meta.get("url", ""),
                ports=list(meta.get("ports", [])),
                host_network=bool(meta.get("host_network", False)),
                heimdall_service=meta.get("heimdall_service", ""),
                lan_default=bool(meta.get("lan_default", False)),
                notes=meta.get("notes", "").strip(),
                console=list(meta.get("console", [])),
                env=env,
                eula=eula,
                instances=bool(meta.get("instances", False)),
                web=dict(meta.get("web", {})),
                windows_partage=meta.get("windows_partage", ""),
            )
        except (KeyError, TypeError) as exc:
            raise YggError(f"service {directory.name} : stack.toml invalide ({exc})") from exc
        if stack.name != directory.name:
            raise YggError(f"service {directory.name} : le nom déclaré ({stack.name}) ne correspond pas au dossier")
        if stack.categorie not in CATEGORIES:
            raise YggError(f"service {stack.name} : catégorie inconnue {stack.categorie}")
        for var in stack.env:
            if not ENV_NAME_RE.match(var.name):
                raise YggError(f"service {stack.name} : variable invalide {var.name}")
        return stack

    def option(self, nom: str) -> EnvVar | None:
        return next((v for v in self.env if v.option == nom), None)


def stacks_dir() -> Path:
    return DATA_DIR / "bifrost" / "stacks"


def load_stacks(directory: Path | None = None) -> dict[str, Stack]:
    directory = directory or stacks_dir()
    stacks = {}
    if directory.is_dir():
        for sub in sorted(directory.iterdir()):
            if sub.is_dir() and (sub / "stack.toml").exists():
                stack = Stack.load(sub)
                stacks[stack.name] = stack
    return stacks


def get_stack(name: str, stacks: dict[str, Stack]) -> Stack:
    if name not in stacks:
        raise YggError(f"service inconnu « {name} » (disponibles : {', '.join(stacks) or 'aucun'})")
    return stacks[name]


def home_dir(config) -> Path:
    return common.expand(config.get("bifrost", {}).get("home", "~/bifrost"))


# --------------------------------------------------------------------------
# Déploiements : un dossier par service ou par exemplaire
# --------------------------------------------------------------------------

META = ".bifrost.json"


def meta_de(dest: Path) -> dict:
    try:
        return json.loads((dest / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def deploiements(config) -> dict[str, str]:
    """Nom du déploiement → modèle (minecraft, valheim…)."""
    racine = home_dir(config)
    resultat = {}
    if racine.is_dir():
        for d in sorted(racine.iterdir()):
            if (d / "compose.yml").exists():
                resultat[d.name] = meta_de(d).get("modele", d.name)
    return resultat


def resoudre(nom: str, config) -> tuple[Stack, Path]:
    """Un déploiement (« survie ») ou un service (« open-webui ») → son modèle et son dossier."""
    stacks = load_stacks()
    dest = home_dir(config) / nom
    if (dest / "compose.yml").exists():
        return get_stack(meta_de(dest).get("modele", nom), stacks), dest
    stack = get_stack(nom, stacks)
    raise YggError(f"{stack.title} n'est pas déployé (bifrost up {stack.name}).")


# --------------------------------------------------------------------------
# Fichier .env
# --------------------------------------------------------------------------

def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def quote_env(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@+,-]*", value):
        return value
    return "'" + value.replace("'", "") + "'"


def render_env(values: dict[str, str], stack: Stack) -> str:
    lines = [f"# Configuration de {stack.title} — générée par bifrost, modifiable à la main.", ""]
    described = {v.name: v for v in stack.env}
    for key, value in values.items():
        var = described.get(key)
        if var and var.description:
            lines.append(f"# {var.description}")
        lines.append(f"{key}={quote_env(value)}")
    return "\n".join(lines) + "\n"


def system_timezone() -> str:
    tz = common.read_text("/etc/timezone").strip()
    if tz:
        return tz
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "Europe/Paris"


def default_value(var: EnvVar) -> str:
    if var.kind == "secret":
        return secrets.token_urlsafe(24)
    return var.default


def ports_pris(config, exclure: str = "") -> set[int]:
    """Ports déjà réservés par les autres déploiements, et ceux où un programme écoute."""
    pris: set[int] = set()
    stacks = load_stacks()
    for nom, modele in deploiements(config).items():
        if nom == exclure or modele not in stacks:
            continue
        valeurs = parse_env(common.read_text(home_dir(config) / nom / ".env"))
        for var in stacks[modele].env:
            if var.kind == "port" and valeurs.get(var.name, "").isdigit():
                pris.add(int(valeurs[var.name]))
    try:
        sortie = subprocess.run(["ss", "-H", "-tuln"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        sortie = ""
    for line in sortie.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[4].rsplit(":", 1)[-1].isdigit():
            pris.add(int(parts[4].rsplit(":", 1)[-1]))
    return pris


def port_libre(depart: int, pris: set[int]) -> int:
    port = depart
    while port in pris:
        port += 1
    return port


def build_env(stack: Stack, existing: dict[str, str], *, bind_addr: str, interactive: bool,
              options: dict[str, str] | None = None, instance: str = "", pris: set[int] | None = None
              ) -> dict[str, str]:
    values: dict[str, str] = {}
    options = options or {}
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    base = {"BIND_ADDR": bind_addr, "PUID": str(uid), "PGID": str(gid), "TZ": system_timezone(),
            "INSTANCE": instance or stack.name}
    for key, value in base.items():
        values[key] = existing.get(key, value) if key not in ("BIND_ADDR", "INSTANCE") else value
    pris = set(pris or ())
    for var in stack.env:
        if var.option and var.option in options:
            value = options[var.option]
        elif var.name in existing:
            values[var.name] = existing[var.name]
            continue
        else:
            value = default_value(var)
            if var.kind == "port" and value.isdigit():
                value = str(port_libre(int(value), pris))
            if var.ask and interactive and var.kind != "secret":
                label = var.description or var.name
                if var.choices:
                    label += f" ({'/'.join(var.choices)})"
                value = common.ask(label, value)
        if var.choices and value not in var.choices:
            raise YggError(f"valeur invalide pour {var.option or var.name} : {value} "
                           f"(possibles : {', '.join(var.choices)})")
        if var.kind == "port":
            if not value.isdigit() or not 1 <= int(value) <= 65535:
                raise YggError(f"port invalide pour {var.name} : {value}")
            pris.add(int(value))
        if var.kind == "path":
            value = str(common.expand(value))
        values[var.name] = value
    for key, value in existing.items():
        values.setdefault(key, value)
    return values


# --------------------------------------------------------------------------
# Minecraft : saveurs, modpacks, Bedrock, carte
# --------------------------------------------------------------------------

SAVEURS = {"vanilla": "VANILLA", "paper": "PAPER", "spigot": "SPIGOT", "purpur": "PURPUR", "folia": "FOLIA",
           "forge": "FORGE", "neoforge": "NEOFORGE", "fabric": "FABRIC", "quilt": "QUILT"}
AVEC_PLUGINS = {"PAPER", "SPIGOT", "PURPUR", "FOLIA"}


def ajuster_minecraft(options: dict[str, str]) -> dict[str, str]:
    """Traduit les options lisibles (--type fabric, --modpack modrinth:…, --bedrock, --carte)."""
    o = dict(options)
    if "type" in o:
        saveur = o["type"].lower()
        if saveur not in SAVEURS:
            raise YggError(f"saveur inconnue « {o['type']} » : {', '.join(SAVEURS)}")
        o["type"] = SAVEURS[saveur]
    if "modpack" in o:
        source, _, slug = o.pop("modpack").partition(":")
        if source == "modrinth" and slug:
            o["type"], o["modpack-modrinth"] = "MODRINTH", slug
        elif source == "curseforge" and slug:
            o["type"], o["modpack-curseforge"] = "AUTO_CURSEFORGE", slug
        else:
            raise YggError("modpack : modrinth:<projet> ou curseforge:<projet>")
    mods = [m for m in o.get("mods", "").split(",") if m]
    saveur = o.get("type", "PAPER")
    if o.pop("bedrock", None) is not None:
        mods += ["geyser", "floodgate"]
    if o.pop("carte", None) is not None:
        mods += ["bluemap"]
    if mods:
        o["mods"] = ",".join(dict.fromkeys(mods))
    if saveur == "VANILLA" and mods:
        raise YggError("Vanilla n'accepte ni mods ni plugins : choisis paper, fabric, forge…")
    return o


def modrinth_compatible(projet: str, saveur: str, version: str) -> bool:
    """Le projet Modrinth existe-t-il pour cette saveur et cette version ? (vérification en ligne)"""
    chargeur = {"PAPER": "paper", "SPIGOT": "spigot", "PURPUR": "purpur", "FOLIA": "folia", "FABRIC": "fabric",
                "FORGE": "forge", "NEOFORGE": "neoforge", "QUILT": "quilt"}.get(saveur)
    if not chargeur:
        return True
    params = f'loaders=["{chargeur}"]' + (f'&game_versions=["{version}"]' if version not in ("", "LATEST") else "")
    url = f"https://api.modrinth.com/v2/project/{urllib.request.quote(projet)}/version?{params}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bifrost (Yggdrasil)"}),
                                    timeout=10) as reponse:
            return bool(json.loads(reponse.read()))
    except (OSError, ValueError):
        return True  # hors ligne : le serveur le dira au démarrage


# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------

class Docker:
    def __init__(self, runner: Runner):
        self.runner = runner
        self._compose: list[str] | None = None
        self._sudo: bool | None = None

    def ensure(self) -> None:
        if not common.which("docker"):
            raise YggError("Docker n'est pas installé : « ygg realm add jotunheim --seulement docker » "
                           "puis reconnecte-toi.")
        code, _ = self.runner.query(["docker", "info", "--format", "{{.ServerVersion}}"])
        if code == 0:
            self._sudo = False
        else:
            code_root, _ = self.runner.query(["docker", "info", "--format", "{{.ServerVersion}}"], root=True)
            if code_root != 0:
                raise YggError("le service Docker ne répond pas (sudo systemctl start docker).")
            common.warn("ton compte n'a pas accès à Docker sans sudo : « sudo usermod -aG docker $USER » "
                        "puis reconnecte-toi.")
            self._sudo = True

    def docker(self, *args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
        if self._sudo is None:
            self.ensure()
        return self.runner.run(["docker", *args], root=bool(self._sudo), check=check, capture=capture)

    def reseau(self) -> None:
        """Le réseau commun : les services se joignent par leur nom (proxy, portail…)."""
        code, _ = self.runner.query(["docker", "network", "inspect", RESEAU], root=bool(self._sudo))
        if code != 0:
            self.docker("network", "create", RESEAU, check=False, capture=True)

    def compose_base(self) -> list[str]:
        if self._compose is None:
            if self.runner.query(["docker", "compose", "version"])[0] == 0:
                self._compose = ["docker", "compose"]
            elif common.which("docker-compose"):
                self._compose = ["docker-compose"]
            else:
                raise YggError("Docker Compose est absent : sudo apt install docker-compose")
        return list(self._compose)

    def compose(self, directory: Path, *args: str, check: bool = True, capture: bool = False
                ) -> subprocess.CompletedProcess:
        if self._sudo is None:
            self.ensure()
        cmd = self.compose_base() + ["--project-name", directory.name, "--project-directory", str(directory),
                                     "-f", str(directory / "compose.yml"), *args]
        return self.runner.run(cmd, root=bool(self._sudo), check=check, capture=capture, cwd=directory)

    def running(self, directory: Path) -> bool:
        if not (directory / "compose.yml").exists() or not common.which("docker"):
            return False
        try:
            proc = self.compose(directory, "ps", "-q", "--status", "running", check=False, capture=True)
        except YggError:
            return False
        return bool((proc.stdout or "").strip())


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def install_files(stack: Stack, dest: Path) -> list[str]:
    """Copie les fichiers du service sans écraser ceux que l'utilisateur a modifiés."""
    copied = []
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(stack.directory.rglob("*")):
        rel = src.relative_to(stack.directory)
        if rel.name == "stack.toml" or src.is_dir():
            continue
        target = dest / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(str(rel))
    return copied


def cmd_list(args, runner: Runner, config) -> int:
    stacks = load_stacks()
    docker = Docker(runner)
    have_docker = common.which("docker") is not None
    deployes = deploiements(config)
    common.title("Bifröst, le pont arc-en-ciel")
    for cat, titre in CATEGORIES.items():
        rows = []
        for stack in (s for s in stacks.values() if s.categorie == cat):
            instances = [n for n, m in deployes.items() if m == stack.name]
            if stack.instances or not instances:
                compte = f"{len(instances)} exemplaire(s)" if stack.instances and instances else "—"
                rows.append((stack.name, stack.title, compte))
            for nom in instances:
                etat = "en marche" if have_docker and docker.running(home_dir(config) / nom) else "arrêté"
                rows.append(("  ↳ " + nom if stack.instances else nom, "" if stack.instances else stack.title, etat))
        if rows:
            print("\n  " + common.style(titre, "leaf"))
            print("\n".join("  " + line for line in common.table(rows).splitlines()))
    print()
    common.info(common.dim("bifrost info <service> pour le détail, bifrost up <service> pour l'installer."))
    if not have_docker:
        common.warn("Docker n'est pas installé : ygg realm add jotunheim --seulement docker")
    return 0


def cmd_info(args, runner: Runner, config) -> int:
    stack = get_stack(args.stack, load_stacks())
    common.title(f"{stack.title} ({stack.name})")
    common.info(stack.description)
    if stack.url:
        print(f"\n  Adresse : {stack.url}")
    if stack.ports:
        print(f"  Ports   : {', '.join(stack.ports)}")
    options = [v for v in stack.env if v.option]
    if options:
        print("\n  Options de « bifrost up " + stack.name + " » :")
        for var in options:
            choix = f" ({'/'.join(c.lower() for c in var.choices)})" if var.choices else ""
            print(f"    --{var.option:<14} {var.description}{choix} [{var.default or '-'}]")
    if stack.name == "minecraft":
        print("    --modpack       modrinth:<projet> ou curseforge:<projet>")
        print("    --bedrock       joueurs Bedrock (consoles, mobiles) avec Geyser")
        print("    --carte         la carte du monde dans le navigateur (BlueMap)")
    if stack.instances:
        print("    --nom           un nom pour cet exemplaire (plusieurs peuvent tourner côte à côte)")
    if stack.windows_partage:
        print("    --windows       rendre le dossier visible aussi depuis Windows (Samba)")
    if stack.notes:
        print()
        for line in stack.notes.splitlines():
            common.info(line)
    return 0


def ask_eula(stack: Stack, values: dict[str, str], assume_yes: bool) -> None:
    if not stack.eula:
        return
    if values.get(stack.eula.var, "").upper() == "TRUE":
        return
    common.title("Licence à accepter")
    for line in stack.eula.text.strip().splitlines():
        common.info(line)
    common.info(f"Texte complet : {stack.eula.url}")
    # L'acceptation d'une licence ne se fait jamais implicitement, même avec --yes.
    if not common.confirm("Acceptes-tu cette licence ?", assume_yes=False):
        raise YggError("licence refusée : déploiement annulé.")
    values[stack.eula.var] = "TRUE"


def parse_options(reste: list[str]) -> dict[str, str]:
    """« --type fabric --bedrock --mods a,b » → {"type": "fabric", "bedrock": "", "mods": "a,b"}."""
    options: dict[str, str] = {}
    i = 0
    while i < len(reste):
        mot = reste[i]
        if not mot.startswith("--") or len(mot) < 3:
            raise YggError(f"argument inattendu « {mot} »")
        nom, egal, valeur = mot[2:].partition("=")
        if not egal and i + 1 < len(reste) and not reste[i + 1].startswith("--"):
            valeur = reste[i + 1]
            i += 1
        options[nom] = valeur
        i += 1
    return options


def cmd_up(args, runner: Runner, config) -> int:
    stacks = load_stacks()
    stack = get_stack(args.stack, stacks)
    options = parse_options(getattr(args, "options", []) or [])
    windows = options.pop("windows", None) is not None
    if stack.name == "minecraft":
        options = ajuster_minecraft(options)
    connues = {v.option for v in stack.env if v.option}
    inconnues = set(options) - connues
    if inconnues:
        raise YggError(f"option inconnue pour {stack.name} : --{', --'.join(sorted(inconnues))} (bifrost info "
                       f"{stack.name})")
    nom = args.nom or stack.name
    if not NOM_RE.match(nom):
        raise YggError("nom invalide : minuscules, chiffres et tirets.")
    if args.nom and not stack.instances:
        raise YggError(f"{stack.title} ne se déploie qu'en un exemplaire.")
    autre = meta_de(home_dir(config) / nom).get("modele")
    if autre and autre != stack.name:
        raise YggError(f"« {nom} » est déjà un déploiement de {autre}.")
    docker = Docker(runner)
    if not runner.dry_run:
        docker.ensure()
    dest = home_dir(config) / nom
    first_time = not (dest / ".env").exists()
    existing = parse_env(common.read_text(dest / ".env"))

    common.title(f"Déploiement de {stack.title}" + (f" « {nom} »" if nom != stack.name else ""))
    if args.lan is not None:
        expose = args.lan
    elif "BIND_ADDR" in existing:
        expose = existing["BIND_ADDR"] == "0.0.0.0"
    elif stack.host_network:
        expose = True
    else:
        expose = common.confirm("Rendre ce service accessible depuis les autres appareils du réseau local ?",
                                default=stack.lan_default, assume_yes=False) if sys.stdin.isatty() else stack.lan_default
    bind_addr = "0.0.0.0" if expose else "127.0.0.1"
    values = build_env(stack, existing, bind_addr=bind_addr, interactive=first_time and not args.yes,
                       options=options, instance=nom,
                       pris=ports_pris(config, exclure=nom) if first_time else set())
    if runner.dry_run:
        if stack.eula and values.get(stack.eula.var, "").upper() != "TRUE":
            common.info(f"(la licence {stack.eula.url} sera demandée au vrai déploiement)")
    else:
        ask_eula(stack, values, args.yes)
    if stack.name == "minecraft":
        for projet in [m for m in values.get("MODRINTH_PROJECTS", "").split(",") if m]:
            if not modrinth_compatible(projet, values.get("TYPE", ""), values.get("VERSION", "")):
                common.warn(f"« {projet} » n'existe pas sur Modrinth pour {values.get('TYPE')} "
                            f"{values.get('VERSION')} : le serveur pourrait refuser de démarrer.")

    if runner.dry_run:
        print(render_env(values, stack))
        common.ok("simulation : rien n'a été déployé.")
        return 0

    copied = install_files(stack, dest)
    (dest / META).write_text(json.dumps({"modele": stack.name, "cree": dt.datetime.now().isoformat(
        timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
    for var in stack.env:
        if var.kind == "path" and values.get(var.name):
            Path(values[var.name]).mkdir(parents=True, exist_ok=True)
    env_path = dest / ".env"
    env_path.write_text(render_env(values, stack), encoding="utf-8")
    os.chmod(env_path, 0o600)
    if copied:
        common.step(f"fichiers installés dans {dest}")

    docker.reseau()
    docker.compose(dest, "pull")
    docker.compose(dest, "up", "-d", "--remove-orphans")
    common.ok(f"{stack.title} est lancé.")
    voix.annoncer("bifrost", "ouvert", config=config, nom=stack.title)

    # Les ports publiés par Docker contournent la chaîne d'entrée de Heimdall : seuls les
    # services en réseau hôte ont besoin d'une ouverture dans le pare-feu.
    if stack.host_network and stack.heimdall_service:
        from . import heimdall

        cfg = heimdall.load_config()
        if cfg.enabled and common.confirm(f"Ouvrir {stack.title} dans le pare-feu, pour le réseau local seulement ?",
                                          default=True, assume_yes=args.yes):
            heimdall.ouvrir(runner, stack.heimdall_service, "lan", nom)
    if windows and stack.windows_partage and values.get(stack.windows_partage):
        from . import ygg

        ygg.main(["partage", "ajouter", values[stack.windows_partage], "--nom", nom] + (["-y"] if args.yes else []))
    if stack.url:
        url = stack.url
        for var in stack.env:
            url = url.replace("${" + var.name + "}", values.get(var.name, ""))
        if expose:
            url += "   (et depuis le réseau : remplace localhost par l'adresse IP de cette machine)"
        common.info(f"Adresse : {url}")
    if stack.notes and first_time:
        common.title("À savoir")
        for line in stack.notes.replace("<nom>", nom).splitlines():
            common.info(line)
    return 0


def cmd_down(args, runner: Runner, config) -> int:
    _, dest = resoudre(args.stack, config)
    Docker(runner).compose(dest, "down")
    common.ok("service arrêté (les données sont conservées).")
    voix.annoncer("bifrost", "ferme", config=config, nom=args.stack)
    return 0


def cmd_start(args, runner: Runner, config) -> int:
    """Relancer un service arrêté, ou replanté par Draupnir (ses conteneurs sont recréés)."""
    _, dest = resoudre(args.stack, config)
    docker = Docker(runner)
    docker.reseau()
    docker.compose(dest, "up", "-d")
    common.ok("service lancé.")
    return 0


def cmd_restart(args, runner: Runner, config) -> int:
    _, dest = resoudre(args.stack, config)
    Docker(runner).compose(dest, "restart")
    common.ok("service redémarré.")
    return 0


def cmd_logs(args, runner: Runner, config) -> int:
    _, dest = resoudre(args.stack, config)
    extra = ["--tail", str(args.lines)]
    if args.follow:
        extra.append("-f")
    return Docker(runner).compose(dest, "logs", *extra, check=False).returncode


def cmd_ps(args, runner: Runner, config) -> int:
    _, dest = resoudre(args.stack, config)
    return Docker(runner).compose(dest, "ps", check=False).returncode


def cmd_update(args, runner: Runner, config) -> int:
    _, dest = resoudre(args.stack, config)
    docker = Docker(runner)
    docker.compose(dest, "pull")
    docker.compose(dest, "up", "-d", "--remove-orphans")
    common.ok("service mis à jour.")
    if common.confirm("Supprimer les anciennes images devenues inutiles ?", default=True, assume_yes=args.yes):
        docker.docker("image", "prune", "-f", check=False)
    return 0


def cmd_remove(args, runner: Runner, config) -> int:
    _, dest = resoudre(args.stack, config)
    if args.purge:
        common.warn(f"TOUTES les données de {dest} seront supprimées définitivement.")
    if not common.confirm("Confirmer la suppression ?", assume_yes=args.yes):
        return 1
    Docker(runner).compose(dest, "down", "--remove-orphans", check=False)
    if args.purge:
        if runner.dry_run:
            print(f"  [simulation] suppression de {dest}")
        else:
            try:
                shutil.rmtree(dest)
            except PermissionError:
                # Certains conteneurs écrivent leurs données en root.
                runner.run(["rm", "-rf", "--one-file-system", str(dest)], root=True)
        common.ok("service et données supprimés.")
    else:
        common.ok(f"service retiré ; ses données restent dans {dest}.")
    return 0


def conteneur_principal(stack: Stack, nom: str) -> str:
    return {"minecraft": f"mc-{nom}", "minecraft-proxy": f"mc-{nom}"}.get(stack.name, nom)


def cmd_console(args, runner: Runner, config) -> int:
    stack, _ = resoudre(args.stack, config)
    if not stack.console:
        raise YggError(f"{stack.title} n'a pas de console.")
    docker = Docker(runner)
    docker.ensure()
    cmd = [x.replace("<conteneur>", conteneur_principal(stack, args.stack)) for x in stack.console]
    return runner.run(cmd, root=bool(docker._sudo), check=False).returncode


def cmd_commande(args, runner: Runner, config) -> int:
    """Une commande de serveur Minecraft, sans ouvrir la console (« op Astrid », « whitelist add Leif »)."""
    stack, _ = resoudre(args.stack, config)
    if stack.name != "minecraft":
        raise YggError("seuls les serveurs Minecraft reçoivent des commandes.")
    docker = Docker(runner)
    return docker.docker("exec", conteneur_principal(stack, args.stack), "rcon-cli", *shlex.split(args.texte),
                         check=False).returncode


def cmd_open(args, runner: Runner, config) -> int:
    stack = get_stack(args.stack, load_stacks())
    if not stack.url:
        raise YggError(f"{stack.title} n'a pas d'interface web.")
    runner.run(["xdg-open", stack.url.split()[0]], check=False)
    return 0


def ajuster_env(dest: Path, changements: dict[str, str]) -> dict[str, str]:
    """Modifie quelques valeurs du .env d'un déploiement, en gardant le reste."""
    stack = get_stack(meta_de(dest).get("modele", dest.name), load_stacks())
    valeurs = parse_env(common.read_text(dest / ".env"))
    valeurs.update(changements)
    (dest / ".env").write_text(render_env(valeurs, stack), encoding="utf-8")
    return valeurs


def cmd_mods(args, runner: Runner, config) -> int:
    stack, dest = resoudre(args.stack, config)
    if stack.name != "minecraft":
        raise YggError("les mods et plugins ne concernent que les serveurs Minecraft.")
    valeurs = parse_env(common.read_text(dest / ".env"))
    mods = [m for m in valeurs.get("MODRINTH_PROJECTS", "").split(",") if m]
    if args.action in (None, "liste"):
        common.title(f"Mods et plugins de « {args.stack} » ({valeurs.get('TYPE', '?')} {valeurs.get('VERSION', '')})")
        for m in mods:
            print(f"  · {m}   https://modrinth.com/project/{m}")
        if not mods:
            common.info("aucun : bifrost mods " + args.stack + " ajouter lithium")
        return 0
    if valeurs.get("TYPE") == "VANILLA":
        raise YggError("un serveur Vanilla n'accepte ni mods ni plugins.")
    if args.action == "ajouter":
        for projet in args.projets:
            if not modrinth_compatible(projet, valeurs.get("TYPE", ""), valeurs.get("VERSION", "")):
                raise YggError(f"« {projet} » n'a pas de version pour {valeurs.get('TYPE')} {valeurs.get('VERSION')} "
                               "sur Modrinth.")
        mods += [p for p in args.projets if p not in mods]
    elif args.action == "retirer":
        mods = [m for m in mods if m not in args.projets]
    if runner.dry_run:
        common.info("MODRINTH_PROJECTS=" + ",".join(mods))
        return 0
    ajuster_env(dest, {"MODRINTH_PROJECTS": ",".join(mods)})
    Docker(runner).compose(dest, "up", "-d")
    common.ok(f"mods de « {args.stack} » : {', '.join(mods) or 'aucun'} (le serveur redémarre et les télécharge).")
    return 0


def cmd_sauvegarder(args, runner: Runner, config) -> int:
    """Le monde copié sans couper le serveur (save-off, save-all, copie, save-on : mc-backup)."""
    stack, _ = resoudre(args.stack, config)
    if stack.name != "minecraft":
        raise YggError("la sauvegarde à chaud concerne les serveurs Minecraft.")
    code = Docker(runner).docker("exec", f"mc-{args.stack}-sauvegardes", "backup", "now", check=False).returncode
    if code == 0:
        common.ok(f"monde sauvegardé dans ~/bifrost/{args.stack}/sauvegardes (le serveur n'a pas été arrêté).")
    return code


def cmd_redemarrage(args, runner: Runner, config) -> int:
    from . import taches

    resoudre(args.stack, config)
    nom = f"bifrost-redemarrage-{args.stack}"
    dossier = taches.dossier_unites()
    if args.heure == "non":
        runner.run(["systemctl", "--user", "disable", "--now", f"{nom}.timer"], check=False)
        if not runner.dry_run:
            for suffixe in (".timer", ".service"):
                (dossier / f"{nom}{suffixe}").unlink(missing_ok=True)
        common.ok("plus de redémarrage planifié.")
        return 0
    service, timer = taches.unites(nom.removeprefix("bifrost-"), f"bifrost restart {args.stack}", args.heure)
    runner.write_file(dossier / f"{nom}.service", service)
    runner.write_file(dossier / f"{nom}.timer", timer)
    runner.run(["systemctl", "--user", "daemon-reload"])
    runner.run(["systemctl", "--user", "enable", "--now", f"{nom}.timer"])
    common.ok(f"« {args.stack} » redémarrera chaque jour à {args.heure}.")
    return 0


# --------------------------------------------------------------------------
# Discord : le serveur raconte sa vie
# --------------------------------------------------------------------------

EVENEMENTS = (
    (re.compile(r"Done \([\d.]+s\)! For help"), "🟢 Le serveur **{nom}** est prêt."),
    (re.compile(r"(\w{2,16}) joined the game"), "➡️ **{0}** a rejoint **{nom}**."),
    (re.compile(r"(\w{2,16}) left the game"), "⬅️ **{0}** a quitté **{nom}**."),
    (re.compile(r"Stopping server"), "🔴 Le serveur **{nom}** s'arrête."),
)


def evenement(ligne: str, nom: str) -> str:
    for motif, texte in EVENEMENTS:
        m = motif.search(ligne)
        if m:
            return texte.format(*m.groups(), nom=nom)
    return ""


def envoyer_discord(webhook: str, message: str) -> bool:
    req = urllib.request.Request(webhook, data=json.dumps({"content": message, "username": "Bifröst"}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "bifrost (Yggdrasil)"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):  # noqa: S310
            return True
    except OSError:
        return False


def cmd_discord(args, runner: Runner, config) -> int:
    stack, dest = resoudre(args.stack, config)
    if stack.name != "minecraft":
        raise YggError("les annonces Discord concernent les serveurs Minecraft.")
    unite = f"bifrost-veille@{args.stack}.service"
    if args.webhook == "non":
        ajuster_env(dest, {"DISCORD_WEBHOOK": ""})
        runner.run(["systemctl", "--user", "disable", "--now", unite], check=False)
        common.ok("plus d'annonces sur Discord.")
        return 0
    if not args.webhook.startswith("https://discord.com/api/webhooks/"):
        raise YggError("adresse de webhook Discord attendue (Paramètres du salon → Intégrations → Webhooks).")
    if not runner.dry_run:
        ajuster_env(dest, {"DISCORD_WEBHOOK": args.webhook})
    runner.run(["systemctl", "--user", "enable", "--now", unite])
    common.ok(f"« {args.stack} » annoncera sur Discord : démarrage, arrivées, départs, arrêts et plantages.")
    return 0


def cmd_veille(args, runner: Runner, config) -> int:
    """Suit le journal d'un serveur et raconte (Discord) ; signale les plantages à Ratatoskr."""
    _, dest = resoudre(args.stack, config)
    webhook = parse_env(common.read_text(dest / ".env")).get("DISCORD_WEBHOOK", "")
    docker = Docker(runner)
    docker.ensure()
    conteneur = f"mc-{args.stack}"
    cmd = (["sudo"] if docker._sudo else []) + ["docker", "logs", "-f", "--since", "1s", conteneur]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
        for ligne in proc.stdout or []:
            message = evenement(ligne, args.stack)
            if message and webhook:
                envoyer_discord(webhook, message)
    _, etat = runner.query(["docker", "inspect", "-f", "{{.State.ExitCode}} {{.State.Status}}", conteneur],
                           root=bool(docker._sudo))
    code, _, statut = etat.strip().partition(" ")
    if code not in ("", "0") and statut != "running":
        texte = f"le serveur Minecraft « {args.stack} » s'est arrêté brutalement (code {code})"
        common.alerter("bifrost", "critical", texte, cle=f"crash:{args.stack}:{dt.datetime.now():%Y%m%d%H%M}")
        if webhook:
            envoyer_discord(webhook, f"💥 Le serveur **{args.stack}** a planté (code {code}).")
    return 0


# --------------------------------------------------------------------------
# Velocity : plusieurs serveurs derrière une seule adresse
# --------------------------------------------------------------------------

def velocity_serveurs(texte: str, serveurs: list[str]) -> str:
    """Réécrit les sections [servers] et forced-hosts d'un velocity.toml."""
    bloc = ["[servers]"] + [f'{s} = "mc-{s}:25565"' for s in serveurs] + [
        "try = [" + ", ".join(f'"{s}"' for s in serveurs[:1]) + "]", ""]
    texte = re.sub(r"(?ms)^\[servers\].*?(?=^\[|\Z)", "\n".join(bloc) + "\n", texte)
    return texte


def cmd_reseau(args, runner: Runner, config) -> int:
    stack, dest = resoudre(args.proxy, config)
    if stack.name != "minecraft-proxy":
        raise YggError(f"« {args.proxy} » n'est pas un proxy Velocity (bifrost up minecraft-proxy).")
    for s in args.serveurs:
        modele, _ = resoudre(s, config)
        if modele.name != "minecraft":
            raise YggError(f"« {s} » n'est pas un serveur Minecraft.")
    fichier = dest / "data" / "velocity.toml"
    if not fichier.exists():
        raise YggError("velocity.toml n'existe pas encore : laisse le proxy démarrer une fois (bifrost logs).")
    if runner.dry_run:
        print(velocity_serveurs(fichier.read_text(encoding="utf-8"), args.serveurs))
        return 0
    fichier.write_text(velocity_serveurs(fichier.read_text(encoding="utf-8"), args.serveurs), encoding="utf-8")
    for s in args.serveurs:
        # Derrière le proxy, les serveurs ne parlent qu'à lui : plus d'accès direct depuis le réseau
        ajuster_env(home_dir(config) / s, {"ONLINE_MODE": "FALSE", "BIND_ADDR": "127.0.0.1"})
        Docker(runner).compose(home_dir(config) / s, "up", "-d")
    Docker(runner).compose(dest, "restart")
    common.ok(f"réseau prêt : {', '.join(args.serveurs)} derrière « {args.proxy} » (« /server {args.serveurs[0]} » "
              "en jeu pour changer de monde).")
    return 0


# --------------------------------------------------------------------------
# Héberger un projet Brokkr (B17)
# --------------------------------------------------------------------------

def compose_projet(nom: str, chemin: Path) -> str:
    env = "\n    env_file: .env" if (chemin / ".env").exists() else ""
    return (f"# Projet « {nom} » hébergé par bifrost (relancé s'il plante, journaux : bifrost logs {nom})\n"
            f"services:\n  {nom}:\n    build: {json.dumps(str(chemin))}\n    container_name: {nom}\n"
            f"    restart: unless-stopped{env}\n"
            f"networks:\n  default:\n    name: {RESEAU}\n    external: true\n")


def cmd_deploy(args, runner: Runner, config) -> int:
    chemin = common.expand(args.chemin).resolve()
    if not (chemin / "Dockerfile").exists():
        raise YggError(f"{chemin} n'a pas de Dockerfile (« brokkr add docker » en ajoute un).")
    nom = args.nom or re.sub(r"[^a-z0-9-]+", "-", chemin.name.lower()).strip("-")[:30] or "projet"
    if not NOM_RE.match(nom):
        raise YggError("nom invalide : minuscules, chiffres et tirets.")
    dest = home_dir(config) / nom
    autre = meta_de(dest).get("modele")
    if autre and autre != "projet":
        raise YggError(f"« {nom} » est déjà un déploiement de {autre} : --nom autre-nom")
    common.title(f"Bifröst héberge « {nom} »")
    common.step(f"construit l'image depuis {chemin}")
    common.step("lance le conteneur, relancé automatiquement s'il plante")
    if runner.dry_run:
        print(compose_projet(nom, chemin))
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "compose.yml").write_text(compose_projet(nom, chemin), encoding="utf-8")
    if (chemin / ".env").exists() and not (dest / ".env").exists():
        shutil.copy2(chemin / ".env", dest / ".env")
        os.chmod(dest / ".env", 0o600)
    (dest / META).write_text(json.dumps({"modele": "projet", "source": str(chemin)}), encoding="utf-8")
    docker = Docker(runner)
    docker.reseau()
    docker.compose(dest, "up", "-d", "--build")
    common.ok(f"« {nom} » tourne. Journaux : bifrost logs {nom} -f ; mise à jour du code : bifrost deploy {chemin}")
    return 0


# --------------------------------------------------------------------------
# Le portail : https://nom.localhost pour chaque interface web (B18)
# --------------------------------------------------------------------------

def caddyfile(entrees: list[tuple[str, str, int]]) -> str:
    """(nom, conteneur, port) → Caddyfile : chaque service en HTTPS local, certificat interne."""
    blocs = ["# Généré par « bifrost portail » — ne pas modifier à la main.",
             "{\n\tlocal_certs\n}\n"]
    for nom, conteneur, port in sorted(entrees):
        blocs.append(f"{nom}.localhost {{\n\treverse_proxy {conteneur}:{port}\n}}\n")
    return "\n".join(blocs)


def cmd_portail(args, runner: Runner, config) -> int:
    stacks = load_stacks()
    entrees = []
    for nom, modele in deploiements(config).items():
        stack = stacks.get(modele)
        if stack and stack.web and modele != "portail":
            conteneur = stack.web.get("conteneur", nom).replace("<nom>", nom)
            entrees.append((nom, conteneur, int(stack.web.get("port", 80))))
    if not entrees:
        common.info("aucun service web déployé pour l'instant (open-webui, metube, n8n…).")
        return 0
    texte = caddyfile(entrees)
    dest = home_dir(config) / "portail"
    if runner.dry_run:
        print(texte)
        return 0
    if not (dest / "compose.yml").exists():
        cmd_up(argparse.Namespace(stack="portail", nom=None, lan=False, yes=True, options=[]), runner, config)
    (dest / "Caddyfile").write_text(texte, encoding="utf-8")
    Docker(runner).compose(dest, "restart")
    common.ok("portail à jour :")
    for nom, _, _ in sorted(entrees):
        common.info(f"https://{nom}.localhost")
    common.info(common.dim("Le premier passage, le navigateur demande d'accepter le certificat local de Caddy."))
    return 0


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-y", "--yes", action="store_true", help="valider automatiquement")
    opts.add_argument("-n", "--dry-run", action="store_true", help="simuler")
    opts.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="bifrost", description="Services en conteneurs pour Yggdrasil.")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    sub.add_parser("list", help="services disponibles et déployés", parents=[opts]).set_defaults(func=cmd_list)

    def stack_cmd(name, help_text, func):
        p = sub.add_parser(name, help=help_text, parents=[opts])
        p.add_argument("stack")
        p.set_defaults(func=func)
        return p

    stack_cmd("info", "détail d'un service et de ses options", cmd_info)
    p = stack_cmd("up", "installer et lancer un service (options : bifrost info <service>)", cmd_up)
    p.add_argument("--nom", help="nom de l'exemplaire (plusieurs serveurs Minecraft côte à côte)")
    lan = p.add_mutually_exclusive_group()
    lan.add_argument("--lan", dest="lan", action="store_true", default=None, help="exposer au réseau local")
    lan.add_argument("--local", dest="lan", action="store_false", help="limiter à cette machine")
    stack_cmd("start", "relancer un service arrêté (ou replanté par Draupnir)", cmd_start)
    stack_cmd("down", "arrêter un service", cmd_down)
    stack_cmd("restart", "redémarrer un service", cmd_restart)
    p = stack_cmd("logs", "journaux d'un service", cmd_logs)
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("--lines", type=int, default=100)
    stack_cmd("ps", "conteneurs d'un service", cmd_ps)
    stack_cmd("update", "mettre à jour les images d'un service", cmd_update)
    p = stack_cmd("remove", "retirer un service", cmd_remove)
    p.add_argument("--purge", action="store_true", help="supprimer aussi les données")
    stack_cmd("console", "la console d'un serveur de jeu", cmd_console)
    p = stack_cmd("commande", "une commande au serveur Minecraft (« op Astrid »)", cmd_commande)
    p.add_argument("texte")
    stack_cmd("open", "ouvrir l'interface web", cmd_open)
    p = stack_cmd("mods", "mods et plugins Modrinth d'un serveur Minecraft", cmd_mods)
    p.add_argument("action", nargs="?", choices=["liste", "ajouter", "retirer"])
    p.add_argument("projets", nargs="*")
    stack_cmd("sauvegarder", "sauvegarder le monde sans couper le serveur", cmd_sauvegarder)
    p = stack_cmd("redemarrage", "redémarrage quotidien (HH:MM, ou non)", cmd_redemarrage)
    p.add_argument("heure")
    p = stack_cmd("discord", "annonces Discord d'un serveur Minecraft (webhook, ou non)", cmd_discord)
    p.add_argument("webhook")
    stack_cmd("veille", argparse.SUPPRESS, cmd_veille)
    p = sub.add_parser("reseau", help="relier des serveurs Minecraft derrière un proxy Velocity", parents=[opts])
    p.add_argument("proxy")
    p.add_argument("serveurs", nargs="+")
    p.set_defaults(func=cmd_reseau)
    p = sub.add_parser("deploy", help="héberger un projet (Brokkr) qui a un Dockerfile", parents=[opts])
    p.add_argument("chemin")
    p.add_argument("--nom")
    p.set_defaults(func=cmd_deploy)
    sub.add_parser("portail", help="https://nom.localhost pour chaque interface web",
                   parents=[opts]).set_defaults(func=cmd_portail)
    return parser


def _main(argv) -> int:
    parser = build_parser()
    args, reste = parser.parse_known_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["list"])
    if reste:
        if args.func is not cmd_up:
            parser.error(f"arguments inconnus : {' '.join(reste)}")
        args.options = reste
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner, common.load_config())


def main(argv=None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
