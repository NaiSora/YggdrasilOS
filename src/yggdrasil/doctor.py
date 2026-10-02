"""« ygg doctor » : diagnostic de santé du système.

Chaque vérification est indépendante et ne lève jamais d'exception : un test
qui plante devient un avertissement, le diagnostic continue.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import common
from .common import Runner
from .sysinfo import parse_meminfo

OK, INFO, WARN, FAIL = "ok", "info", "warn", "fail"
SYMBOLS = {OK: ("✔", "green"), INFO: ("•", "cyan"), WARN: ("⚠", "yellow"), FAIL: ("✘", "red")}


@dataclass
class Check:
    key: str
    label: str
    status: str
    message: str
    hint: str = ""


def parse_upgradable(output: str) -> tuple[int, int]:
    """Analyse « apt list --upgradable » : (total, dont sécurité)."""
    total = security = 0
    for line in output.splitlines():
        if "/" not in line or "[" not in line:
            continue
        total += 1
        source = line.split("/", 1)[1].split(" ", 1)[0]
        if "security" in source:
            security += 1
    return total, security


def parse_failed_units(output: str) -> list[str]:
    units = []
    for line in output.splitlines():
        parts = line.split()
        if parts and (parts[0].endswith((".service", ".socket", ".mount", ".timer", ".target", ".path", ".scope"))):
            units.append(parts[0])
    return units


class Doctor:
    def __init__(self, runner: Runner, root: Path = Path("/")):
        self.runner = runner
        self.root = root

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    # ---- vérifications ---------------------------------------------------

    def check_disk(self) -> list[Check]:
        checks = []
        seen = set()
        for mount in ("/", "/home"):
            target = self.path(mount.lstrip("/")) if mount != "/" else self.root
            try:
                dev = os.stat(target).st_dev
                if dev in seen:
                    continue
                seen.add(dev)
                usage = shutil.disk_usage(target)
            except OSError:
                continue
            free_pct = 100 * usage.free / usage.total if usage.total else 100
            msg = f"{common.human_size(usage.free)} libres ({free_pct:.0f} %)"
            if free_pct < 5:
                checks.append(Check(f"disk{mount}", f"Espace disque {mount}", FAIL, msg, "ygg clean, puis vide tes Téléchargements"))
            elif free_pct < 12:
                checks.append(Check(f"disk{mount}", f"Espace disque {mount}", WARN, msg, "ygg clean"))
            else:
                checks.append(Check(f"disk{mount}", f"Espace disque {mount}", OK, msg))
        return checks

    def check_memory(self) -> list[Check]:
        mem = parse_meminfo(common.read_text(self.path("proc", "meminfo")))
        checks = []
        total = mem.get("MemTotal", 0)
        if total:
            avail = mem.get("MemAvailable", 0)
            pct = 100 * avail / total
            status = WARN if pct < 10 else OK
            checks.append(Check("memory", "Mémoire vive", status, f"{common.human_size(avail)} disponibles ({pct:.0f} %)",
                                "ferme des applications ou regarde « btop »" if status == WARN else ""))
            if mem.get("SwapTotal", 0) == 0:
                checks.append(Check("swap", "Swap / zram", WARN, "aucune mémoire d'échange",
                                    "sudo apt install zram-tools"))
            else:
                checks.append(Check("swap", "Swap / zram", OK, common.human_size(mem["SwapTotal"]) + " configurés"))
        return checks

    def check_failed_units(self) -> list[Check]:
        if not common.which("systemctl"):
            return []
        _, out = self.runner.query(["systemctl", "--failed", "--no-legend", "--plain"])
        units = parse_failed_units(out)
        if units:
            return [Check("units", "Services système", FAIL, "en échec : " + ", ".join(units),
                          f"journalctl -b -u {units[0]}")]
        return [Check("units", "Services système", OK, "aucun service en échec")]

    def check_dpkg(self) -> list[Check]:
        if not common.which("dpkg"):
            return []
        _, out = self.runner.query(["dpkg", "--audit"])
        if out.strip():
            return [Check("dpkg", "Paquets", FAIL, "installation de paquets inachevée", "sudo dpkg --configure -a")]
        return [Check("dpkg", "Paquets", OK, "base dpkg cohérente")]

    def check_updates(self) -> list[Check]:
        if not common.which("apt"):
            return []
        _, out = self.runner.query(["apt", "list", "--upgradable"], timeout=60)
        total, security = parse_upgradable(out)
        if security:
            return [Check("updates", "Mises à jour", WARN, f"{total} en attente dont {security} de sécurité", "ygg update")]
        if total:
            return [Check("updates", "Mises à jour", INFO, f"{total} en attente", "ygg update")]
        return [Check("updates", "Mises à jour", OK, "système à jour (selon le dernier rafraîchissement)")]

    def check_reboot(self) -> list[Check]:
        flag = self.path("run", "reboot-required")
        if flag.exists():
            pkgs = common.read_text(self.path("run", "reboot-required.pkgs")).split()
            detail = f" ({', '.join(sorted(set(pkgs)))})" if pkgs else ""
            return [Check("reboot", "Redémarrage", WARN, "redémarrage nécessaire" + detail, "sudo reboot")]
        return [Check("reboot", "Redémarrage", OK, "pas nécessaire")]

    def check_time(self) -> list[Check]:
        if not common.which("timedatectl"):
            return []
        _, out = self.runner.query(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
        if out.strip() == "yes":
            return [Check("time", "Horloge", OK, "synchronisée (NTP)")]
        return [Check("time", "Horloge", WARN, "non synchronisée", "sudo timedatectl set-ntp true")]

    def check_firewall(self) -> list[Check]:
        if not common.which("systemctl"):
            return []
        _, out = self.runner.query(["systemctl", "is-active", "heimdall.service"])
        if out.strip() == "active":
            return [Check("firewall", "Pare-feu Heimdall", OK, "actif")]
        return [Check("firewall", "Pare-feu Heimdall", WARN, "inactif", "heimdall enable")]

    def check_security_sources(self) -> list[Check]:
        texts = [common.read_text(self.path("etc", "apt", "sources.list"))]
        sources_d = self.path("etc", "apt", "sources.list.d")
        if sources_d.is_dir():
            texts += [common.read_text(p) for p in sorted(sources_d.iterdir()) if p.suffix in (".list", ".sources")]
        joined = "\n".join(texts)
        if not joined.strip():
            return []
        if "security" in joined:
            return [Check("security-repo", "Dépôt de sécurité", OK, "configuré")]
        return [Check("security-repo", "Dépôt de sécurité", FAIL, "absent des sources APT",
                      "ajoute « deb http://security.debian.org/debian-security trixie-security main »")]

    def check_snapshots(self) -> list[Check]:
        if common.is_live_session(self.path("proc", "cmdline")):
            return [Check("snapshots", "Instantanés Norns", INFO, "session live : sans objet")]
        from .norns import instantane_demarre, libelle_instantane

        nom = instantane_demarre(self.path("proc", "self", "mountinfo"))
        if nom:
            return [Check("snapshots", "Instantanés Norns", WARN, f"démarré sur l'instantané {libelle_instantane(nom)}",
                          f"norns restore {nom} pour le garder, sinon redémarre")]
        if not self.path("etc", "timeshift", "timeshift.json").exists():
            return [Check("snapshots", "Instantanés Norns", WARN, "non configurés", "norns setup")]
        return [Check("snapshots", "Instantanés Norns", OK, "configurés")]

    def check_drivers(self) -> list[Check]:
        if not common.which("lspci"):
            return []
        from .materiel import pilotes_manquants

        manquants = pilotes_manquants(self.runner)
        if not manquants:
            return [Check("drivers", "Pilotes", OK, "le matériel détecté a ses pilotes")]
        nvidia = any("nvidia-driver" in c.paquets for c in manquants)
        paquets = ", ".join(p for c in manquants for p in c.paquets)
        return [Check("drivers", "Pilotes", WARN if nvidia else INFO,
                      ("pilote NVIDIA à installer" if nvidia else "micrologiciels conseillés") + f" ({paquets})",
                      "ygg pilotes installer")]

    def check_temperature(self) -> list[Check]:
        zones = sorted(self.path("sys", "class", "thermal").glob("thermal_zone*/temp"))
        temps = []
        for zone in zones:
            raw = common.read_text(zone).strip()
            if raw.lstrip("-").isdigit():
                temps.append(int(raw) / 1000)
        if not temps:
            return []
        hottest = max(temps)
        if hottest >= 90:
            return [Check("temperature", "Température", WARN, f"{hottest:.0f} °C au plus chaud", "vérifie la ventilation")]
        return [Check("temperature", "Température", OK, f"{hottest:.0f} °C au plus chaud")]

    def check_journal(self) -> list[Check]:
        if not common.which("journalctl"):
            return []
        code, out = self.runner.query(["journalctl", "-b", "-p", "3", "-q", "--no-pager", "-o", "cat"])
        if code != 0:
            return []
        count = sum(1 for line in out.splitlines() if line.strip())
        status = WARN if count > 50 else INFO if count else OK
        return [Check("journal", "Journal système", status, f"{count} erreurs depuis le démarrage",
                      "mimir logs   (résumé par l'IA locale)" if count else "")]

    def all_checks(self) -> list[Callable[[], list[Check]]]:
        return [
            self.check_disk,
            self.check_memory,
            self.check_failed_units,
            self.check_dpkg,
            self.check_updates,
            self.check_reboot,
            self.check_security_sources,
            self.check_firewall,
            self.check_snapshots,
            self.check_drivers,
            self.check_time,
            self.check_temperature,
            self.check_journal,
        ]

    def run(self) -> list[Check]:
        results: list[Check] = []
        for func in self.all_checks():
            try:
                results.extend(func())
            except Exception as exc:  # un test ne doit jamais casser le diagnostic
                results.append(Check(func.__name__, func.__name__, WARN, f"vérification impossible : {exc}"))
        return results


def exit_code(checks: list[Check]) -> int:
    if any(c.status == FAIL for c in checks):
        return 2
    if any(c.status == WARN for c in checks):
        return 1
    return 0


def render(checks: list[Check], quiet: bool = False) -> str:
    s = common.style
    lines = []
    for c in checks:
        if quiet and c.status in (OK, INFO):
            continue
        symbol, color = SYMBOLS[c.status]
        line = f"  {s(symbol, color)} {s(c.label, 'bold')} : {c.message}"
        if c.hint and c.status != OK:
            line += "\n      " + s("→ " + c.hint, "dim")
        lines.append(line)
    counts = {k: sum(1 for c in checks if c.status == k) for k in SYMBOLS}
    summary = f"{counts[OK]} ok, {counts[INFO]} info, {counts[WARN]} avertissement(s), {counts[FAIL]} problème(s)"
    if not quiet or counts[WARN] or counts[FAIL]:
        lines.append("\n  " + s(summary, "bold"))
    return "\n".join(lines)


def to_json(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
