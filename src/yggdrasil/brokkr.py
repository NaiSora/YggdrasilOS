"""brokkr — le forgeron des nains : des projets prêts à coder, et de quoi les faire vivre.

    brokkr                                   l'assistant : quelques questions, un projet sur mesure
    brokkr list | show discord-bot
    brokkr new discord-bot MonBot --modules moderation,niveaux,musique
    brokkr new discord-bot MonBot --idee "un bot qui gère les tickets et les concours"
    brokkr new python-app Outil --variante gui
    brokkr new site-web Vitrine --variante portfolio

Dans un projet (ou --dir) :
    brokkr add docker | ci | tests | module tickets
    brokkr deploy                            Bifröst l'héberge (relancé s'il plante)
    brokkr package [--format deb|flatpak]    un .deb installable, ou un manifeste Flatpak
    brokkr github [--public]                 le dépôt GitHub, après ta validation
    brokkr save MonModele                    ton projet devient un modèle réutilisable

Les modèles vivent dans /usr/share/yggdrasil/brokkr/templates/<nom>/ (et
~/.local/share/yggdrasil/brokkr/templates pour les tiens) : template.toml, files/
(le tronc commun), variantes/<id>/ et modules/<id>/ (des fichiers posés par-dessus).
Dans les fichiers comme dans les chemins, {{variable}} est remplacé.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import common, voix
from .common import DATA_DIR, Runner, YggError

VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
PROJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
MARQUE = ".brokkr.json"
IGNORES = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", ".pytest_cache",
           ".ruff_cache", "data", ".mypy_cache"}


@dataclass
class Choix:
    id: str
    nom: str
    description: str = ""
    defaut: bool = False
    mots: list[str] = field(default_factory=list)


@dataclass
class Template:
    name: str
    title: str
    description: str
    language: str
    directory: Path
    next_steps: str = ""
    requires: list[str] = field(default_factory=list)
    variantes: list[Choix] = field(default_factory=list)
    modules: list[Choix] = field(default_factory=list)
    perso: bool = False

    @classmethod
    def load(cls, directory: Path, perso: bool = False) -> "Template":
        meta = common.load_toml(directory / "template.toml")
        if not (directory / "files").is_dir():
            raise YggError(f"modèle {directory.name} : dossier files/ manquant")
        try:
            tpl = cls(
                name=meta["name"],
                title=meta["title"],
                description=meta["description"].strip(),
                language=meta.get("language", ""),
                directory=directory,
                next_steps=meta.get("next_steps", "").strip(),
                requires=list(meta.get("requires", [])),
                variantes=[Choix(**v) for v in meta.get("variante", [])],
                modules=[Choix(**m) for m in meta.get("module", [])],
                perso=perso,
            )
        except (KeyError, TypeError) as exc:
            raise YggError(f"modèle {directory.name} : template.toml invalide ({exc})") from exc
        for c in tpl.variantes:
            if not (directory / "variantes" / c.id).is_dir():
                raise YggError(f"modèle {tpl.name} : variante {c.id} sans dossier variantes/{c.id}")
        for c in tpl.modules:
            if not (directory / "modules" / c.id).is_dir():
                raise YggError(f"modèle {tpl.name} : module {c.id} sans dossier modules/{c.id}")
        if tpl.variantes and sum(v.defaut for v in tpl.variantes) != 1:
            raise YggError(f"modèle {tpl.name} : une variante, et une seule, doit être « defaut »")
        return tpl

    def variante(self, choix: str | None) -> Choix | None:
        if not self.variantes:
            if choix:
                raise YggError(f"{self.title} n'a pas de variantes.")
            return None
        if not choix:
            return next(v for v in self.variantes if v.defaut)
        for v in self.variantes:
            if v.id == choix:
                return v
        raise YggError(f"variante inconnue « {choix} » : {', '.join(v.id for v in self.variantes)}")

    def choisir_modules(self, ids: list[str] | None) -> list[Choix]:
        if ids is None:
            return [m for m in self.modules if m.defaut]
        connus = {m.id: m for m in self.modules}
        inconnus = [i for i in ids if i not in connus]
        if inconnus:
            raise YggError(f"module inconnu « {', '.join(inconnus)} » : {', '.join(connus) or 'aucun module'}")
        return [connus[i] for i in dict.fromkeys(ids)]


def templates_dir() -> Path:
    return DATA_DIR / "brokkr" / "templates"


def user_templates_dir() -> Path:
    return common.user_data_dir() / "yggdrasil" / "brokkr" / "templates"


def load_templates(directory: Path | None = None, user_directory: Path | None = None) -> dict[str, Template]:
    found: dict[str, Template] = {}
    for racine, perso in ((directory or templates_dir(), False),
                          (user_directory if user_directory is not None else user_templates_dir(), True)):
        if not racine.is_dir():
            continue
        for sub in sorted(racine.iterdir()):
            if (sub / "template.toml").exists():
                tpl = Template.load(sub, perso=perso)
                if tpl.name in found:
                    if perso:
                        common.warn(f"modèle personnel « {tpl.name} » ignoré : ce nom est déjà pris.")
                        continue
                    raise YggError(f"modèle en double : {tpl.name}")
                found[tpl.name] = tpl
    return found


# --------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------

def slugify(name: str) -> str:
    """« Mon Super-Bot » → « mon-super-bot »."""
    text = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return text or "projet"


def pascal_case(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    result = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not result or not result[0].isalpha():
        result = "Projet" + result
    return result


def snake_case(name: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    if not text or not text[0].isalpha():
        text = "projet_" + text
    return text


def git_author(runner: Runner) -> str:
    if common.which("git"):
        _, out = runner.query(["git", "config", "--get", "user.name"])
        if out.strip():
            return out.strip()
    return common.target_user()


def build_variables(name: str, author: str, variante: Choix | None = None,
                    modules: list[Choix] | None = None) -> dict[str, str]:
    if not PROJECT_NAME_RE.match(name):
        raise YggError("nom de projet invalide : lettres, chiffres, - et _ (commence par une lettre).")
    snake = snake_case(name)
    return {
        "name": name,
        "slug": slugify(name),
        "snake": snake,
        "class": pascal_case(name),
        "author": author,
        "year": str(dt.date.today().year),
        "date": dt.date.today().isoformat(),
        "variante": variante.id if variante else "",
        "modules": ", ".join(m.nom for m in modules or []) or "aucun",
        "app_id": f"io.github.{re.sub(r'[^a-z0-9]', '', author.lower()) or 'yggdrasil'}.{pascal_case(name)}",
    }


def substitute(text: str, variables: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise YggError(f"variable de modèle inconnue : {{{{{key}}}}}")
        return variables[key]

    return VAR_RE.sub(repl, text)


def render_path(rel: Path, variables: dict[str, str]) -> Path:
    parts = []
    for part in rel.parts:
        name = substitute(part, variables)
        # « dot-gitignore » → « .gitignore » (les fichiers cachés survivent mal à l'empaquetage)
        if name.startswith("dot-"):
            name = "." + name[4:]
        parts.append(name)
    return Path(*parts)


def copier_couche(racine: Path, dest: Path, variables: dict[str, str]) -> list[Path]:
    created = []
    for src in sorted(racine.rglob("*")):
        if src.is_dir():
            continue
        target = dest / render_path(src.relative_to(racine), variables)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            target.write_bytes(data)
        else:
            target.write_text(substitute(text, variables), encoding="utf-8", newline="\n")
        shutil.copymode(src, target)
        if target.suffix == ".sh":
            # Les droits se perdent à l'empaquetage : un script forgé doit rester exécutable
            target.chmod(target.stat().st_mode | 0o111)
        created.append(target)
    return created


def render_template(tpl: Template, dest: Path, variables: dict[str, str], variante: Choix | None = None,
                    modules: list[Choix] | None = None) -> list[Path]:
    """Le tronc commun, puis la variante, puis chaque module : chaque couche peut remplacer un fichier."""
    couches = [tpl.directory / "files"]
    if variante:
        couches.append(tpl.directory / "variantes" / variante.id)
    couches += [tpl.directory / "modules" / m.id for m in modules or []]
    created: dict[Path, None] = {}
    for couche in couches:
        for chemin in copier_couche(couche, dest, variables):
            created[chemin] = None
    return list(created)


# --------------------------------------------------------------------------
# L'idée : Mímir propose des modules (sinon, des mots-clés)
# --------------------------------------------------------------------------

def modules_par_mots(tpl: Template, idee: str) -> list[str]:
    texte = idee.lower()
    return [m.id for m in tpl.modules if any(mot in texte for mot in [m.id, m.nom.lower(), *m.mots])]


def modules_par_mimir(tpl: Template, idee: str, config: dict) -> list[str] | None:
    from . import mimir

    try:
        oracle = mimir.Mimir(config)
        catalogue = "\n".join(f"- {m.id} : {m.nom} — {m.description}" for m in tpl.modules)
        reponse = oracle.complete([
            {"role": "system", "content": "Tu choisis des modules pour un projet. Réponds en JSON : "
                                          '{"modules": ["id", ...]}. N\'utilise que les identifiants fournis.'},
            {"role": "user", "content": f"Modules disponibles :\n{catalogue}\n\n<donnees>\n{idee}\n</donnees>"},
        ], fmt="json")
        ids = mimir.parse_json_answer(reponse).get("modules", [])
    except Exception:  # Mímir endormi ou réponse invalide : on se rabat sur les mots-clés
        return None
    connus = {m.id for m in tpl.modules}
    return [i for i in ids if isinstance(i, str) and i in connus] or None


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def get_template(nom: str) -> Template:
    templates = load_templates()
    if nom not in templates:
        raise YggError(f"modèle inconnu « {nom} » (brokkr list)")
    return templates[nom]


def cmd_list(args, runner: Runner, config) -> int:
    templates = load_templates()
    rows = []
    for t in templates.values():
        extra = []
        if t.variantes:
            extra.append(f"{len(t.variantes)} variantes")
        if t.modules:
            extra.append(f"{len(t.modules)} modules")
        rows.append((t.name, t.language, t.title + (" (perso)" if t.perso else ""), ", ".join(extra)))
    print(common.table(rows, headers=("modèle", "langage", "description", "")))
    print()
    common.info(common.dim("brokkr show <modèle> pour le détail ; brokkr new <modèle> <NomDuProjet> ; "
                           "brokkr seul pour l'assistant."))
    return 0


def cmd_show(args, runner: Runner, config) -> int:
    tpl = get_template(args.template)
    common.title(f"{tpl.title} ({tpl.name})")
    common.info(tpl.description)
    if tpl.variantes:
        print("\n  Variantes (--variante) :")
        for v in tpl.variantes:
            print(f"    {v.id:<16} {v.nom}{' (par défaut)' if v.defaut else ''} — {v.description}")
    if tpl.modules:
        print("\n  Modules (--modules a,b,c) :")
        for m in tpl.modules:
            print(f"    {common.style('●', 'gold') if m.defaut else '○'} {m.id:<14} {m.nom} — {m.description}")
    if tpl.requires:
        print("\n  Requiert : " + ", ".join(tpl.requires))
    return 0


def forger(tpl: Template, nom: str, parent: Path, runner: Runner, config: dict, *, variante: str | None = None,
           modules: list[str] | None = None, auteur: str | None = None, git: bool = True) -> Path:
    choix_variante = tpl.variante(variante)
    choix_modules = tpl.choisir_modules(modules)
    variables = build_variables(nom, auteur or git_author(runner), choix_variante, choix_modules)
    dest = parent / variables["slug"]
    if dest.exists() and any(dest.iterdir()):
        raise YggError(f"{dest} existe déjà et n'est pas vide.")
    common.title(f"Forge : {tpl.title}")
    common.step(f"projet   : {nom}")
    common.step(f"dossier  : {dest}")
    if choix_variante:
        common.step(f"variante : {choix_variante.nom}")
    if tpl.modules:
        common.step(f"modules  : {variables['modules']}")
    if runner.dry_run:
        common.ok("simulation : rien n'a été créé.")
        return dest
    created = render_template(tpl, dest, variables, choix_variante, choix_modules)
    (dest / MARQUE).write_text(json.dumps({"modele": tpl.name, "variante": variables["variante"],
                                           "modules": [m.id for m in choix_modules], "nom": nom,
                                           "cree": variables["date"]}, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    common.ok(f"{len(created)} fichiers forgés.")
    voix.annoncer("brokkr", "forge", config=config, nom=variables["name"], chemin=dest)
    if git and common.which("git"):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=False)
        subprocess.run(["git", "add", "-A"], cwd=dest, check=False)
        common.ok("dépôt git initialisé (rien n'est commité : à toi de jouer).")
    missing = [r for r in tpl.requires if not common.which(r)]
    if missing:
        common.warn("outils manquants : " + ", ".join(missing) + " → ygg realm add nidavellir")
    if tpl.next_steps:
        common.title("Pour démarrer")
        for line in substitute(tpl.next_steps, {**variables, "dir": str(dest)}).splitlines():
            common.info(line)
    return dest


def dossier_projets(args, config) -> Path:
    return common.expand(args.dir) if getattr(args, "dir", None) else \
        common.expand(config.get("brokkr", {}).get("projects", "~/Projets"))


def cmd_new(args, runner: Runner, config) -> int:
    tpl = get_template(args.template)
    modules = [m for m in args.modules.split(",") if m] if args.modules is not None else None
    if args.idee and tpl.modules:
        proposes = modules_par_mimir(tpl, args.idee, config)
        source = "Mímir"
        if proposes is None:
            proposes, source = modules_par_mots(tpl, args.idee), "les mots de ton idée"
        modules = sorted(set(modules or []) | set(proposes), key=[m.id for m in tpl.modules].index)
        common.info(f"D'après {source} : {', '.join(modules) or 'aucun module particulier'}.")
    forger(tpl, args.name, dossier_projets(args, config), runner, config, variante=args.variante, modules=modules,
           auteur=args.author, git=not args.no_git)
    return 0


def demander_choix(question: str, options: list[tuple[str, str]], defaut: int = 1) -> str:
    for i, (_, libelle) in enumerate(options, 1):
        print(f"  {common.style(str(i), 'gold')}  {libelle}")
    reponse = common.ask(question, str(defaut))
    if reponse.isdigit() and 1 <= int(reponse) <= len(options):
        return options[int(reponse) - 1][0]
    raise YggError("choix inconnu.")


def cmd_assistant(args, runner: Runner, config) -> int:
    """F15 : quelques questions, puis le projet sur mesure."""
    if not sys.stdin.isatty():
        return cmd_list(args, runner, config)
    templates = load_templates()
    common.title("Brokkr t'écoute : que veux-tu forger ?")
    nom_modele = demander_choix("Ton choix", [(t.name, f"{t.title} ({t.language})") for t in templates.values()])
    tpl = templates[nom_modele]
    variante = None
    if tpl.variantes:
        print()
        defaut = next(i for i, v in enumerate(tpl.variantes, 1) if v.defaut)
        variante = demander_choix("Quelle forme ?", [(v.id, f"{v.nom} — {v.description}") for v in tpl.variantes],
                                  defaut)
    modules = None
    if tpl.modules:
        print()
        idee = common.ask("Décris en une phrase ce qu'il doit faire (Entrée pour choisir toi-même)")
        modules = (modules_par_mimir(tpl, idee, config) or modules_par_mots(tpl, idee)) if idee else None
        retenus = {m.id for m in tpl.choisir_modules(modules)}
        for i, m in enumerate(tpl.modules, 1):
            print(f"  {i:>2} [{'x' if m.id in retenus else ' '}] {m.nom} — {common.dim(m.description)}")
        reponse = common.ask("Numéros à cocher ou décocher (Entrée pour valider)")
        for morceau in re.split(r"[\s,]+", reponse):
            if morceau.isdigit() and 1 <= int(morceau) <= len(tpl.modules):
                retenus ^= {tpl.modules[int(morceau) - 1].id}
        modules = [m.id for m in tpl.modules if m.id in retenus]
    nom = common.ask("Nom du projet", tpl.name.title().replace("-", ""))
    dest = forger(tpl, nom, dossier_projets(args, config), runner, config, variante=variante, modules=modules)
    if not runner.dry_run and common.which("gh") and common.confirm("Créer aussi le dépôt GitHub (privé) ?",
                                                                      assume_yes=False):
        return cmd_github(argparse.Namespace(dir=str(dest), public=False, yes=False), runner, config)
    return 0


# --------------------------------------------------------------------------
# Dans un projet : add, deploy, package, github, save
# --------------------------------------------------------------------------

def projet(args) -> tuple[Path, dict]:
    dossier = common.expand(getattr(args, "dir", None) or ".").resolve()
    if not dossier.is_dir():
        raise YggError(f"pas de projet ici : {dossier} n'existe pas.")
    marque = {}
    try:
        marque = json.loads((dossier / MARQUE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return dossier, marque


def langage(dossier: Path) -> str:
    if (dossier / "pyproject.toml").exists() or (dossier / "requirements.txt").exists():
        return "python"
    if (dossier / "package.json").exists():
        return "node"
    return ""


DOCKER_PY = """FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir {installation}
RUN useradd --create-home --uid 1000 app && mkdir -p data && chown app:app data
USER app
CMD {commande}
"""
DOCKER_NODE = """FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build --if-present
USER node
CMD ["npm", "start"]
"""
CI_PY = """name: tests
on: [push, pull_request]
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install {installation} pytest
      - run: python -m pytest -q
"""
CI_NODE = """name: tests
on: [push, pull_request]
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npm test
"""


def installation_python(dossier: Path) -> str:
    return "-r requirements.txt" if (dossier / "requirements.txt").exists() else "-e ."


def commande_python(dossier: Path) -> str:
    for candidat in ("bot.py", "main.py", "app.py"):
        if (dossier / candidat).exists():
            return json.dumps(["python", candidat])
    texte = common.read_text(dossier / "pyproject.toml")
    m = re.search(r"^\[project\.scripts\]\s*\n\s*([\w-]+)\s*=", texte, re.M)
    return json.dumps([m.group(1)]) if m else json.dumps(["python", "-m", "app"])


def cmd_add(args, runner: Runner, config) -> int:
    dossier, marque = projet(args)
    lang = langage(dossier)
    fichiers: dict[Path, str] = {}
    if args.brique == "docker":
        if lang == "python":
            fichiers[dossier / "Dockerfile"] = DOCKER_PY.format(installation=installation_python(dossier),
                                                                commande=commande_python(dossier))
        elif lang == "node":
            fichiers[dossier / "Dockerfile"] = DOCKER_NODE
        else:
            raise YggError("langage du projet non reconnu (pyproject.toml, requirements.txt ou package.json).")
        fichiers[dossier / ".dockerignore"] = ".git\n.venv\nnode_modules\n__pycache__\n.env\ndata\n"
    elif args.brique == "ci":
        cible = dossier / ".github" / "workflows" / "tests.yml"
        fichiers[cible] = CI_PY.format(installation=installation_python(dossier)) if lang == "python" else CI_NODE
    elif args.brique == "tests":
        if lang != "python":
            raise YggError("« brokkr add tests » prépare pytest pour un projet Python.")
        fichiers[dossier / "tests" / "test_exemple.py"] = (
            '"""Premier test : pytest le trouve tout seul (python -m pytest)."""\n\n\n'
            "def test_addition():\n    assert 1 + 1 == 2\n")
    elif args.brique == "module":
        if not marque.get("modele") or not args.nom:
            raise YggError("brokkr add module <id> s'utilise dans un projet forgé par Brokkr (fichier .brokkr.json).")
        tpl = get_template(marque["modele"])
        [module] = tpl.choisir_modules([args.nom])
        variables = build_variables(marque.get("nom", dossier.name), git_author(runner), tpl.variante(
            marque.get("variante") or None), tpl.choisir_modules(marque.get("modules", []) + [module.id]))
        if runner.dry_run:
            common.info(f"simulation : module {module.nom} ajouté à {dossier}")
            return 0
        ajoutes = copier_couche(tpl.directory / "modules" / module.id, dossier, variables)
        marque["modules"] = list(dict.fromkeys(marque.get("modules", []) + [module.id]))
        (dossier / MARQUE).write_text(json.dumps(marque, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        common.ok(f"module « {module.nom} » forgé : " + ", ".join(str(p.relative_to(dossier)) for p in ajoutes))
        return 0
    else:
        raise YggError("briques : docker, ci, tests, module <id>")
    existants = [p for p in fichiers if p.exists()]
    if existants and not common.confirm("Remplacer " + ", ".join(p.name for p in existants) + " ?",
                                        assume_yes=args.yes):
        return 1
    for chemin, contenu in fichiers.items():
        if runner.dry_run:
            common.info(f"simulation : écriture de {chemin}")
            continue
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8", newline="\n")
    common.ok(f"brique « {args.brique} » ajoutée.")
    return 0


def cmd_deploy(args, runner: Runner, config) -> int:
    dossier, _ = projet(args)
    if not (dossier / "Dockerfile").exists():
        raise YggError("pas de Dockerfile : brokkr add docker")
    from . import bifrost

    argv = ["deploy", str(dossier)] + (["--nom", args.nom] if args.nom else []) + (["-n"] if runner.dry_run else [])
    return bifrost.main(argv)


def lire_pyproject(dossier: Path) -> dict:
    try:
        return common.load_toml(dossier / "pyproject.toml").get("project", {})
    except YggError:
        return {}


def control_deb(nom: str, version: str, description: str, depends: list[str], auteur: str) -> str:
    return (f"Package: {nom}\nVersion: {version}\nArchitecture: all\nMaintainer: {auteur} <{auteur}@localhost>\n"
            f"Depends: {', '.join(depends)}\nSection: misc\nPriority: optional\n"
            f"Description: {description or nom}\n Paquet forgé par Brokkr (Yggdrasil).\n")


def cmd_package(args, runner: Runner, config) -> int:
    dossier, marque = projet(args)
    meta = lire_pyproject(dossier)
    if not meta:
        raise YggError("brokkr package sait empaqueter un projet Python (pyproject.toml).")
    nom = slugify(meta.get("name", dossier.name))
    version = meta.get("version", "0.1.0")
    scripts = meta.get("scripts", {})
    if not scripts:
        raise YggError("aucune commande à installer : ajoute [project.scripts] dans pyproject.toml.")
    paquets = [p for p in (dossier / "src").iterdir() if p.is_dir() and (p / "__init__.py").exists()] \
        if (dossier / "src").is_dir() else []
    if not paquets:
        raise YggError("le code doit être dans src/<paquet>/ (comme les modèles de Brokkr).")
    depends = ["python3 (>= 3.11)"]
    qt = any("PySide6" in d for d in meta.get("dependencies", []))
    if qt:
        depends += ["python3-pyside6.qtcore", "python3-pyside6.qtgui", "python3-pyside6.qtqml",
                    "python3-pyside6.qtquick", "qml6-module-qtquick-controls", "qml6-module-qtquick-layouts"]
    autres = [d for d in meta.get("dependencies", []) if "PySide6" not in d]
    if args.format == "flatpak":
        app_id = f"io.github.{slugify(git_author(runner)).replace('-', '')}.{pascal_case(nom)}"
        manifeste = dossier / f"{app_id}.yml"
        commande = next(iter(scripts))
        texte = (f"# Manifeste Flatpak forgé par Brokkr — flatpak-builder --user --install build {manifeste.name}\n"
                 f"app-id: {app_id}\nruntime: org.kde.Platform\nruntime-version: '6.8'\nsdk: org.kde.Sdk\n"
                 f"base: io.qt.PySide.BaseApp\nbase-version: '6.8'\ncommand: {commande}\n"
                 "finish-args:\n  - --share=ipc\n  - --socket=wayland\n  - --socket=fallback-x11\n  - --device=dri\n"
                 f"modules:\n  - name: {nom}\n    buildsystem: simple\n    build-commands:\n"
                 "      - pip3 install --no-deps --no-build-isolation --prefix=/app .\n"
                 f"    sources:\n      - type: dir\n        path: .\n")
        if not runner.dry_run:
            manifeste.write_text(texte, encoding="utf-8")
        common.ok(f"manifeste Flatpak : {manifeste}")
        common.info("Construction : flatpak-builder --user --install --force-clean build " + manifeste.name)
        return 0
    if autres:
        common.warn("dépendances PyPI non empaquetées : " + ", ".join(autres) + " (à installer à côté, ou à "
                    "remplacer par des paquets Debian python3-…)")
    racine = dossier / "dist" / f"{nom}_{version}_all"
    deb = dossier / "dist" / f"{nom}_{version}_all.deb"
    common.title(f"Brokkr empaquette {nom} {version}")
    if runner.dry_run:
        common.info(f"simulation : {deb}")
        return 0
    shutil.rmtree(racine, ignore_errors=True)
    lib = racine / "usr" / "lib" / nom
    for p in paquets:
        shutil.copytree(p, lib / p.name, ignore=shutil.ignore_patterns("__pycache__"))
    (racine / "usr" / "bin").mkdir(parents=True)
    for commande, cible in scripts.items():
        module, _, fonction = cible.partition(":")
        lanceur = racine / "usr" / "bin" / commande
        lanceur.write_text(f"#!/usr/bin/python3\nimport sys\nsys.path.insert(0, \"/usr/lib/{nom}\")\n"
                           f"from {module} import {fonction or 'main'}\nsys.exit({fonction or 'main'}())\n",
                           encoding="utf-8")
        lanceur.chmod(0o755)
    for desktop in dossier.glob("*.desktop"):
        (racine / "usr" / "share" / "applications").mkdir(parents=True, exist_ok=True)
        shutil.copy2(desktop, racine / "usr" / "share" / "applications" / desktop.name)
    for icone in list(dossier.glob("*.svg"))[:1]:
        cible = racine / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{nom}.svg"
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icone, cible)
    (racine / "DEBIAN").mkdir()
    (racine / "DEBIAN" / "control").write_text(control_deb(nom, version, meta.get("description", ""), depends,
                                                           slugify(git_author(runner))), encoding="utf-8")
    runner.run(["dpkg-deb", "--root-owner-group", "--build", str(racine), str(deb)])
    shutil.rmtree(racine, ignore_errors=True)
    common.ok(f"paquet prêt : {deb}")
    common.info(f"Installation : sudo apt install ./dist/{deb.name}")
    return 0


def cmd_github(args, runner: Runner, config) -> int:
    dossier, _ = projet(args)
    if not common.which("gh"):
        raise YggError("GitHub CLI absent : ygg realm add nidavellir --seulement git")
    code, _ = runner.query(["gh", "auth", "status"])
    if code != 0:
        raise YggError("connecte-toi d'abord : gh auth login")
    visibilite = "--public" if args.public else "--private"
    common.title("Le dépôt GitHub")
    common.step(f"dépôt {'public' if args.public else 'privé'} : {slugify(dossier.name)}")
    common.step("premier commit de tous les fichiers suivis, puis envoi")
    if not common.confirm("Créer le dépôt et y envoyer le projet ?", assume_yes=args.yes):
        return 1
    if not (dossier / ".git").exists():
        runner.run(["git", "init", "-q", "-b", "main"], cwd=dossier)
    runner.run(["git", "add", "-A"], cwd=dossier)
    runner.run(["git", "commit", "-q", "-m", "Premier tour d'enclume (Brokkr)"], cwd=dossier, check=False)
    runner.run(["gh", "repo", "create", slugify(dossier.name), visibilite, "--source", str(dossier),
                "--remote", "origin", "--push"], cwd=dossier)
    common.ok("dépôt créé et envoyé.")
    return 0


def cmd_save(args, runner: Runner, config) -> int:
    """F19 : un projet devient un modèle (le nom du projet devient {{name}}, {{slug}}…)."""
    dossier, marque = projet(args)
    if not ID_RE.match(args.modele):
        raise YggError("nom du modèle : minuscules, chiffres et tirets.")
    nom_projet = marque.get("nom", dossier.name)
    remplacements = sorted({nom_projet: "{{name}}", slugify(nom_projet): "{{slug}}",
                            snake_case(nom_projet): "{{snake}}", pascal_case(nom_projet): "{{class}}"}.items(),
                           key=lambda kv: -len(kv[0]))
    remplacements = [(a, b) for a, b in remplacements if len(a) >= 3]

    def generaliser(texte: str) -> str:
        texte = texte.replace("{{", "{ {")  # les accolades existantes ne deviennent pas des variables
        for avant, apres in remplacements:
            texte = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(avant)}(?![A-Za-z0-9_])", apres, texte)
        return texte

    cible = user_templates_dir() / args.modele
    if cible.exists() and not common.confirm(f"Le modèle {args.modele} existe : le remplacer ?", assume_yes=args.yes):
        return 1
    if runner.dry_run:
        common.info(f"simulation : modèle {args.modele} dans {cible}")
        return 0
    shutil.rmtree(cible, ignore_errors=True)
    nombre = 0
    for src in sorted(dossier.rglob("*")):
        rel = src.relative_to(dossier)
        if (any(p in IGNORES or p.endswith(".egg-info") for p in rel.parts)
                or rel.name in (".env", MARQUE) or src.is_dir()):
            continue
        nom_rel = Path(*[("dot-" + p[1:]) if p.startswith(".") else generaliser(p) for p in rel.parts])
        dest = cible / "files" / nom_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(generaliser(src.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        except UnicodeDecodeError:
            shutil.copy2(src, dest)
        nombre += 1
    if not nombre:
        raise YggError(f"rien à garder dans {dossier} : le modèle serait vide.")
    langue = {"python": "Python", "node": "TypeScript"}.get(langage(dossier), "")
    (cible / "template.toml").write_text(
        f'name = "{args.modele}"\ntitle = {json.dumps(args.titre or nom_projet, ensure_ascii=False)}\n'
        f'language = "{langue}"\ndescription = """\nModèle personnel tiré de « {nom_projet} ».\n"""\n',
        encoding="utf-8")
    common.ok(f"modèle « {args.modele} » forgé ({nombre} fichiers) : brokkr new {args.modele} NouveauProjet")
    return 0


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-n", "--dry-run", action="store_true", help="simuler")
    opts.add_argument("-v", "--verbose", action="store_true")
    opts.add_argument("-y", "--yes", action="store_true")

    parser = argparse.ArgumentParser(prog="brokkr", description="La forge à projets d'Yggdrasil.")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    sub.add_parser("list", help="lister les modèles", parents=[opts]).set_defaults(func=cmd_list)
    p = sub.add_parser("assistant", help="quelques questions, un projet sur mesure", parents=[opts])
    p.add_argument("--dir", help="dossier parent (défaut : ~/Projets)")
    p.set_defaults(func=cmd_assistant)
    p = sub.add_parser("show", help="détailler un modèle", parents=[opts])
    p.add_argument("template")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("new", help="créer un projet", parents=[opts])
    p.add_argument("template")
    p.add_argument("name")
    p.add_argument("--variante", help="forme du projet (brokkr show <modèle>)")
    p.add_argument("--modules", help="modules, séparés par des virgules (vide : aucun)")
    p.add_argument("--idee", help="ce que doit faire le projet, en une phrase (Mímir choisit les modules)")
    p.add_argument("--dir", help="dossier parent (défaut : ~/Projets)")
    p.add_argument("--author", help="auteur (défaut : git config user.name)")
    p.add_argument("--no-git", action="store_true", help="ne pas initialiser de dépôt git")
    p.set_defaults(func=cmd_new)
    p = sub.add_parser("add", help="ajouter une brique à un projet : docker, ci, tests, module", parents=[opts])
    p.add_argument("brique", choices=["docker", "ci", "tests", "module"])
    p.add_argument("nom", nargs="?", help="identifiant du module (avec « module »)")
    p.add_argument("--dir", help="dossier du projet (défaut : le dossier courant)")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("deploy", help="héberger le projet avec Bifröst", parents=[opts])
    p.add_argument("--dir")
    p.add_argument("--nom")
    p.set_defaults(func=cmd_deploy)
    p = sub.add_parser("package", help="empaqueter le projet (.deb, ou manifeste Flatpak)", parents=[opts])
    p.add_argument("--dir")
    p.add_argument("--format", choices=["deb", "flatpak"], default="deb")
    p.set_defaults(func=cmd_package)
    p = sub.add_parser("github", help="créer le dépôt GitHub (avec ta validation)", parents=[opts])
    p.add_argument("--dir")
    p.add_argument("--public", action="store_true")
    p.set_defaults(func=cmd_github)
    p = sub.add_parser("save", help="faire de ce projet un modèle réutilisable", parents=[opts])
    p.add_argument("modele")
    p.add_argument("--titre")
    p.add_argument("--dir")
    p.set_defaults(func=cmd_save)
    return parser


def _main(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["assistant"])
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner, common.load_config())


def main(argv=None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
