"""Collecte d'informations système (sans dépendance externe)."""

from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path

from . import CODENAME, __version__, common
from .common import Runner


def parse_meminfo(text: str) -> dict[str, int]:
    """Renvoie les valeurs de /proc/meminfo en octets."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts or not parts[0].isdigit():
            continue
        factor = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        values[key.strip()] = int(parts[0]) * factor
    return values


def parse_cpu_model(text: str) -> tuple[str, int]:
    model = ""
    count = 0
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key == "processor":
            count += 1
        elif key in ("model name", "Hardware", "cpu model") and not model:
            model = " ".join(value.split())
    return model or platform.processor() or "inconnu", count or (os.cpu_count() or 0)


def parse_uptime(text: str) -> float:
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return 0.0


def parse_lspci_gpus(text: str) -> list[str]:
    gpus = []
    markers = ("VGA compatible controller", "3D controller", "Display controller")
    for line in text.splitlines():
        for marker in markers:
            if marker in line:
                gpus.append(line.split(marker + ":", 1)[-1].strip())
                break
    return gpus


def count_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def collect(runner: Runner, proc: Path = Path("/proc")) -> dict:
    release = common.os_release()
    mem = parse_meminfo(common.read_text(proc / "meminfo"))
    cpu, cores = parse_cpu_model(common.read_text(proc / "cpuinfo"))
    info: dict = {
        "os": release.get("PRETTY_NAME", "Yggdrasil"),
        "version": release.get("VERSION_ID", __version__),
        "codename": release.get("YGGDRASIL_CODENAME", CODENAME),
        "debian": common.read_text("/etc/debian_version").strip() or "?",
        "kernel": platform.release(),
        "hostname": socket.gethostname(),
        "user": common.target_user(),
        "uptime": parse_uptime(common.read_text(proc / "uptime")),
        "cpu": cpu,
        "cores": cores,
        "mem_total": mem.get("MemTotal", 0),
        "mem_available": mem.get("MemAvailable", 0),
        "swap_total": mem.get("SwapTotal", 0),
        "swap_free": mem.get("SwapFree", 0),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session": os.environ.get("XDG_SESSION_TYPE", ""),
        "shell": os.path.basename(os.environ.get("SHELL", "")),
        "live": common.is_live_session(proc / "cmdline"),
        "persistante": common.is_persistent_session(proc / "cmdline", proc / "mounts"),
        "disks": [],
        "gpus": [],
        "packages": 0,
        "flatpaks": 0,
    }
    seen = set()
    for mount in ("/", "/home"):
        try:
            st = os.stat(mount)
            if st.st_dev in seen:
                continue
            seen.add(st.st_dev)
            usage = shutil.disk_usage(mount)
            info["disks"].append({"mount": mount, "total": usage.total, "used": usage.used, "free": usage.free})
        except OSError:
            continue
    if common.which("lspci"):
        info["gpus"] = parse_lspci_gpus(runner.query(["lspci"])[1])
    if common.which("dpkg-query"):
        out = runner.query(["dpkg-query", "-f", "${db:Status-Abbrev}\n", "-W"])[1]
        info["packages"] = sum(1 for line in out.splitlines() if line.startswith("ii"))
    if common.which("flatpak"):
        info["flatpaks"] = count_lines(runner.query(["flatpak", "list", "--app", "--columns=application"])[1])
    return info


def render(info: dict) -> str:
    s = common.style
    rows = [
        ("Système", f"{info['os']}"),
        ("Base", f"Debian {info['debian']}"),
        ("Noyau", info["kernel"]),
        ("Machine", f"{info['user']}@{info['hostname']}"),
        ("Allumé depuis", common.human_duration(info["uptime"])),
        ("Processeur", f"{info['cpu']} ({info['cores']} cœurs)"),
    ]
    for gpu in info["gpus"]:
        rows.append(("Carte graphique", gpu))
    if info["mem_total"]:
        used = info["mem_total"] - info["mem_available"]
        rows.append(("Mémoire", f"{common.human_size(used)} / {common.human_size(info['mem_total'])}"))
    if info["swap_total"]:
        used = info["swap_total"] - info["swap_free"]
        rows.append(("Swap", f"{common.human_size(used)} / {common.human_size(info['swap_total'])}"))
    for disk in info["disks"]:
        pct = 100 * disk["used"] / disk["total"] if disk["total"] else 0
        rows.append((f"Disque {disk['mount']}", f"{common.human_size(disk['used'])} / {common.human_size(disk['total'])} ({pct:.0f} %)"))
    if info["desktop"]:
        rows.append(("Bureau", f"{info['desktop']} ({info['session'] or '?'})"))
    if info["shell"]:
        rows.append(("Shell", info["shell"]))
    rows.append(("Logiciels", f"{info['packages']} paquets Debian, {info['flatpaks']} Flatpak"))
    if info["live"]:
        rows.append(("Session", "live, clé persistante (tes changements sont gardés)" if info.get("persistante")
                     else "live (rien n'est conservé à l'extinction)"))
    width = max(len(k) for k, _ in rows)
    head = s("  Yggdrasil", "bold", "gold") + s(f" {info['version']} « {info['codename']} »", "leaf")
    lines = [head, "  " + "─" * 46]
    lines += [f"  {s(k.ljust(width), 'cyan')}  {v}" for k, v in rows]
    return "\n".join(lines)
