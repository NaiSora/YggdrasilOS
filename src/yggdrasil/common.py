"""Briques communes à tous les outils Yggdrasil.

Principes (hérités de l'assistant Yggdrasil) :
  * le programme décide, pas le modèle ni le contenu externe ;
  * rien de destructeur ne s'exécute sans validation explicite ;
  * le contenu externe (pages, journaux, sorties de commandes) est une donnée,
    jamais un ordre.
"""

from __future__ import annotations

import getpass
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import tomllib

# Les chemins sont surchargeables par variables d'environnement pour les tests
# et pour lancer les outils depuis le dépôt sans installer le paquet.
DATA_DIR = Path(os.environ.get("YGG_DATA_DIR", "/usr/share/yggdrasil"))
ETC_DIR = Path(os.environ.get("YGG_ETC_DIR", "/etc/yggdrasil"))
STATE_DIR = Path(os.environ.get("YGG_STATE_DIR", "/var/lib/yggdrasil"))


class YggError(Exception):
    """Erreur destinée à l'utilisateur : affichée proprement, sans trace Python."""


class CommandError(YggError):
    def __init__(self, cmd: Sequence[str], returncode: int, detail: str = ""):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.detail = detail.strip()
        msg = f"la commande « {shlex.join(self.cmd)} » a échoué (code {returncode})"
        if self.detail:
            msg += f"\n{self.detail}"
        super().__init__(msg)


# --------------------------------------------------------------------------
# Affichage
# --------------------------------------------------------------------------

def _color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("YGG_FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def truecolor() -> bool:
    """Le terminal affiche-t-il les 16 millions de couleurs (teintes exactes du logo) ?"""
    return os.environ.get("COLORTERM", "") in ("truecolor", "24bit")


def unicode_ok() -> bool:
    """La console texte de Linux n'a pas les symboles (✦, ✔…) : repli en ASCII."""
    return os.environ.get("TERM") != "linux"


class Style:
    CODES = {
        "bold": "1",
        "dim": "2",
        "italic": "3",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        # Couleurs du logo : or #E8CC8C, sauge #79AC99, étoile #FBE39B
        "gold": "38;5;222",
        "leaf": "38;5;108",
        "star": "38;5;229",
    }
    TRUECOLOR = {"gold": "38;2;232;204;140", "leaf": "38;2;121;172;153", "star": "38;2;251;227;155"}

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.enabled = _color_enabled(self.stream)
        if truecolor():
            self.CODES = {**self.CODES, **self.TRUECOLOR}

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        codes = ";".join(self.CODES[s] for s in styles)
        return f"\033[{codes}m{text}\033[0m"


style = Style()
err_style = Style(sys.stderr)


def title(text: str) -> None:
    mark = "✦" if unicode_ok() else "*"
    print(style(f"\n{mark} {text}", "bold", "gold"))


def step(text: str) -> None:
    print(style("  ➜ ", "cyan") + text)


def ok(text: str) -> None:
    print(style("  ✔ ", "green") + text)


def warn(text: str) -> None:
    print(err_style("  ⚠ ", "yellow") + text, file=sys.stderr)


def error(text: str) -> None:
    print(err_style("  ✘ ", "red") + text, file=sys.stderr)


def info(text: str) -> None:
    print("    " + text)


def dim(text: str) -> str:
    return style(text, "dim")


def table(rows: Iterable[Sequence[str]], headers: Sequence[str] | None = None) -> str:
    """Formate un tableau texte simple (largeurs calculées, sans couleurs)."""
    rows = [list(map(str, r)) for r in rows]
    if headers:
        rows.insert(0, list(headers))
    if not rows:
        return ""
    widths = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(max(map(len, rows)))]
    lines = []
    for idx, r in enumerate(rows):
        cells = [c.ljust(widths[i]) for i, c in enumerate(r)]
        lines.append("  ".join(cells).rstrip())
        if headers and idx == 0:
            lines.append("  ".join("─" * w for w in widths))
    return "\n".join(lines)


def human_size(num: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if abs(num) < 1024 or unit == "To":
            return f"{num:.0f} {unit}" if unit == "o" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} To"


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} j")
    if hours:
        parts.append(f"{hours} h")
    if minutes or not parts:
        parts.append(f"{minutes} min")
    return " ".join(parts)


# --------------------------------------------------------------------------
# Interaction
# --------------------------------------------------------------------------

YES_ANSWERS = {"o", "oui", "y", "yes"}
NO_ANSWERS = {"n", "non", "no"}


def confirm(question: str, *, default: bool = False, assume_yes: bool = False) -> bool:
    """Demande une validation. Sans terminal interactif, on refuse par sécurité."""
    if assume_yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        warn(f"{question} — pas de terminal interactif : refusé (utilise --yes pour valider).")
        return False
    suffix = " [O/n] " if default else " [o/N] "
    while True:
        try:
            answer = input(style(question, "bold") + suffix).strip().lower()
        except EOFError:
            return False
        if not answer:
            return default
        if answer in YES_ANSWERS:
            return True
        if answer in NO_ANSWERS:
            return False
        print("    Réponds par « o » (oui) ou « n » (non).")


def ask(question: str, default: str = "") -> str:
    if not sys.stdin or not sys.stdin.isatty():
        return default
    hint = f" [{default}]" if default else ""
    try:
        answer = input(style(question, "bold") + hint + " : ").strip()
    except EOFError:
        return default
    return answer or default


# --------------------------------------------------------------------------
# Système
# --------------------------------------------------------------------------

def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def target_user() -> str:
    """Utilisateur « réel », même si l'outil est lancé via sudo."""
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()


def is_live_session(cmdline: Path = Path("/proc/cmdline")) -> bool:
    try:
        return "boot=live" in cmdline.read_text()
    except OSError:
        return False


def is_persistent_session(cmdline: Path = Path("/proc/cmdline"), mounts: Path = Path("/proc/mounts")) -> bool:
    """Session live sur une clé persistante (Skíðblaðnir) : les changements y sont gardés."""
    if not is_live_session(cmdline):
        return False
    try:
        return "/run/live/persistence/" in mounts.read_text()
    except OSError:
        return False


def read_text(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default


def parse_os_release(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        try:
            parts = shlex.split(value)
            value = parts[0] if parts else ""
        except ValueError:
            value = value.strip("'\"")
        data[key.strip()] = value
    return data


def os_release() -> dict[str, str]:
    for candidate in ("/etc/os-release", "/usr/lib/os-release"):
        text = read_text(candidate)
        if text:
            return parse_os_release(text)
    return {}


# --------------------------------------------------------------------------
# La saga : le journal de tout ce que les outils Yggdrasil ont fait
# --------------------------------------------------------------------------

def saga_path() -> Path:
    return user_state_dir() / "yggdrasil" / "saga.jsonl"


# Champs ajoutés aux actions notées pendant une opération (ex. {"annule": date} pendant
# « ygg annuler » : l'action défaite n'est plus proposée, ni son inverse).
SAGA_CONTEXTE: dict[str, Any] = {}


def saga_note(cmd: list[str], code: int, *, root: bool = False) -> None:
    """Note une action (jamais une simple lecture) : date, outil, commande, résultat.

    Une ligne JSON par action, dans ~/.local/state/yggdrasil/saga.jsonl. Ne fait
    jamais échouer l'action elle-même.
    """
    import datetime as _dt
    import json as _json

    entry = {
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "outil": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "yggdrasil",
        "commande": cmd,
        "admin": root,
        "code": code,
        **SAGA_CONTEXTE,
    }
    try:
        path = saga_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def saga_read(path: Path | None = None) -> list[dict]:
    import json as _json

    entries = []
    try:
        lines = (path or saga_path()).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            entry = _json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and "commande" in entry:
            entries.append(entry)
    return entries


# --------------------------------------------------------------------------
# Les alertes : ce que les gardiens confient à Ratatoskr
# --------------------------------------------------------------------------

def alertes_systeme() -> Path:
    """Alertes des services système (Gjallarhorn…) : lisibles par tous, écrites par root."""
    return STATE_DIR / "alertes.jsonl"


def alertes_utilisateur() -> Path:
    return user_state_dir() / "yggdrasil" / "alertes.jsonl"


def alerter(source: str, urgence: str, message: str, *, systeme: bool = False, cle: str = "") -> None:
    """Dépose une alerte (urgence : normal ou critical). Ne fait jamais échouer l'appelant.

    `cle` évite les doublons : une alerte de même clé n'est notée qu'une fois.
    """
    import datetime as _dt
    import json as _json

    chemin = alertes_systeme() if systeme else alertes_utilisateur()
    cle = cle or f"{source}:{message}"
    if any(a.get("cle") == cle for a in lire_alertes(chemin)):
        return
    entree = {"date": _dt.datetime.now().isoformat(timespec="seconds"), "source": source,
              "urgence": "critical" if urgence == "critical" else "normal", "message": message, "cle": cle}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(entree, ensure_ascii=False) + "\n")
        if systeme:
            os.chmod(chemin, 0o644)
    except OSError:
        pass


def lire_alertes(*chemins: Path) -> list[dict]:
    import json as _json

    alertes = []
    for chemin in chemins or (alertes_systeme(), alertes_utilisateur()):
        for line in read_text(chemin).splitlines():
            try:
                a = _json.loads(line)
            except ValueError:
                continue
            if isinstance(a, dict) and a.get("message"):
                alertes.append(a)
    return sorted(alertes, key=lambda a: str(a.get("date", "")))


@dataclass
class Runner:
    """Exécute les commandes système, avec un mode simulation (--dry-run).

    `run` est réservé aux commandes qui modifient le système (simulées en
    dry-run) ; `query` aux lectures, toujours exécutées.
    """

    dry_run: bool = False
    verbose: bool = False
    log: list[list[str]] = field(default_factory=list)

    def with_root(self, cmd: Sequence[str]) -> list[str]:
        if is_root():
            return list(cmd)
        if which("sudo"):
            return ["sudo", *cmd]
        if which("pkexec"):
            return ["pkexec", *cmd]
        raise YggError("cette action demande les droits administrateur (sudo introuvable).")

    def run(
        self,
        cmd: Sequence[str],
        *,
        root: bool = False,
        check: bool = True,
        capture: bool = False,
        input: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> subprocess.CompletedProcess:
        full = self.with_root(cmd) if root else list(cmd)
        self.log.append(full)
        if self.dry_run:
            print(style("  [simulation] ", "magenta") + shlex.join(full))
            return subprocess.CompletedProcess(full, 0, "", "")
        if self.verbose:
            print(dim("  $ " + shlex.join(full)))
        merged_env = None
        if env:
            merged_env = dict(os.environ)
            merged_env.update(env)
        try:
            proc = subprocess.run(
                full,
                check=False,
                text=True,
                capture_output=capture,
                input=input,
                env=merged_env,
                cwd=cwd,
            )
        except FileNotFoundError as exc:
            saga_note(list(cmd), 127, root=root)
            raise CommandError(full, 127, f"programme introuvable : {exc.filename}") from exc
        saga_note(list(cmd), proc.returncode, root=root)
        if check and proc.returncode != 0:
            raise CommandError(full, proc.returncode, (proc.stderr or "") if capture else "")
        return proc

    def query(self, cmd: Sequence[str], *, root: bool = False, timeout: float = 30) -> tuple[int, str]:
        """Lecture seule : renvoie (code, stdout). Ne lève jamais d'exception."""
        full = self.with_root(cmd) if root else list(cmd)
        try:
            proc = subprocess.run(full, text=True, capture_output=True, timeout=timeout, check=False)
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            return 127, ""
        return proc.returncode, proc.stdout or ""

    def write_file(self, path: str | Path, content: str, *, root: bool = False, mode: str = "644") -> None:
        """Écrit un fichier, éventuellement avec les droits administrateur."""
        path = Path(path)
        if not root or is_root():
            if self.dry_run:
                print(style("  [simulation] ", "magenta") + f"écriture de {path}")
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            os.chmod(path, int(mode, 8))
            return
        self.run(["install", "-d", "-m", "755", str(path.parent)], root=True)
        self.run(["tee", str(path)], root=True, input=content, capture=True)
        self.run(["chmod", mode, str(path)], root=True)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {"ton": "voix"},
    "update": {"snapshot_before": True, "flatpak": True},
    "mimir": {
        "host": "http://127.0.0.1:11434",
        "model": "",
        "think": False,
        "temperature": 0.4,
        "context_lines": 200,
        "save_conversations": True,
        "vault": "~/Documents/Mimir",
        "ton": "oracle",
        "puits": {"coffre": "", "modele": "nomic-embed-text", "extraits": 4},
    },
    "bifrost": {"home": "~/bifrost"},
    "brokkr": {"projects": "~/Projets"},
    "norns": {"backup_target": "", "keep": 7, "exclude": []},
    "ratatoskr": {"remind_hours": 24},
    "theme": {"mode": "nuit", "aube": "07:30", "nuit": "20:00"},
}


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise YggError(f"fichier de configuration invalide {path} : {exc}") from exc


def user_config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "yggdrasil"


def user_state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


def user_data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def load_config() -> dict[str, Any]:
    config = deep_merge(DEFAULT_CONFIG, load_toml(ETC_DIR / "yggdrasil.toml"))
    return deep_merge(config, load_toml(user_config_dir() / "config.toml"))


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'


def dump_toml(data: dict[str, Any], prefix: str = "") -> str:
    """Écrit un TOML simple (tables imbriquées, chaînes, nombres, booléens, listes)."""
    scalars = [f"{k} = {_toml_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    tables = [(k, v) for k, v in data.items() if isinstance(v, dict)]
    blocks = []
    if scalars or (prefix and not tables):
        blocks.append("\n".join(([f"[{prefix}]"] if prefix else []) + scalars))
    for key, value in tables:
        sub = dump_toml(value, f"{prefix}.{key}" if prefix else key)
        if sub:
            blocks.append(sub)
    return "\n\n".join(blocks)


def save_user_config(changes: dict[str, Any]) -> Path:
    """Fusionne `changes` dans ~/.config/yggdrasil/config.toml (le reste est conservé)."""
    path = user_config_dir() / "config.toml"
    current = load_toml(path)
    merged = deep_merge(current, changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Réglages personnels d'Yggdrasil (écrits par le Centre ou à la main)\n\n"
                    + dump_toml(merged) + "\n", encoding="utf-8")
    return path


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))


# --------------------------------------------------------------------------
# Point d'entrée commun
# --------------------------------------------------------------------------

def run_main(func, argv: Sequence[str] | None = None) -> int:
    """Enveloppe les `main` : erreurs lisibles, Ctrl+C propre, tubes fermés tôt."""
    try:
        code = int(func(argv) or 0)
        sys.stdout.flush()
        return code
    except KeyboardInterrupt:
        print()
        warn("interrompu.")
        return 130
    except YggError as exc:
        error(str(exc))
        return 1
    except BrokenPipeError:
        # Sortie envoyée à une commande qui s'est arrêtée (« ygg realm list | head ») :
        # ce n'est pas une erreur. On neutralise stdout pour la fermeture de Python.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0
