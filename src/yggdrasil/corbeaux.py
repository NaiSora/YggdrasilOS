"""Huginn et Muninn, les corbeaux d'Odin : la pensée et la mémoire.

Chaque jour, ils volent sur le monde et reviennent raconter ce qu'ils ont vu.

    huginn                       tes machines en direct (processeur, mémoire, disque, réseau,
    huginn moi@serveur …         températures, services) ; plusieurs machines par SSH
    huginn --une-fois [--json]   un seul relevé

    muninn                       ce qui a changé depuis le dernier souvenir (hier, le plus souvent)
    muninn noter                 garder le souvenir du jour (fait chaque jour par muninn.timer)
    muninn depuis 2026-09-01     ce qui a changé depuis cette date

Les souvenirs de Muninn sont dans ~/.local/state/yggdrasil/muninn/ (un fichier JSON par jour).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import common
from .common import Runner, YggError

# --------------------------------------------------------------------------
# Huginn : le relevé du moment
# --------------------------------------------------------------------------


def lire_cpu(texte: str) -> tuple[int, int]:
    """Ligne « cpu » de /proc/stat → (temps actif, temps total)."""
    for line in texte.splitlines():
        if line.startswith("cpu "):
            valeurs = [int(x) for x in line.split()[1:]]
            inactif = valeurs[3] + (valeurs[4] if len(valeurs) > 4 else 0)
            return sum(valeurs) - inactif, sum(valeurs)
    return 0, 0


def lire_reseau(texte: str) -> tuple[int, int]:
    """/proc/net/dev → octets reçus et envoyés (hors boucle locale et interfaces virtuelles)."""
    rx = tx = 0
    for line in texte.splitlines()[2:]:
        nom, _, reste = line.partition(":")
        nom = nom.strip()
        if not reste or nom == "lo" or nom.startswith(("veth", "docker", "br-", "virbr")):
            continue
        champs = reste.split()
        rx += int(champs[0])
        tx += int(champs[8])
    return rx, tx


def pourcent(avant: tuple[int, int], apres: tuple[int, int]) -> float:
    actif, total = apres[0] - avant[0], apres[1] - avant[1]
    return round(100 * actif / total, 1) if total > 0 else 0.0


def releve(runner: Runner, proc: Path = Path("/proc"), intervalle: float = 0.5) -> dict:
    """Un relevé de la machine. Deux mesures à `intervalle` d'écart pour le processeur et le réseau."""
    from . import materiel, sysinfo

    cpu1, net1 = lire_cpu(common.read_text(proc / "stat")), lire_reseau(common.read_text(proc / "net/dev"))
    time.sleep(intervalle)
    cpu2, net2 = lire_cpu(common.read_text(proc / "stat")), lire_reseau(common.read_text(proc / "net/dev"))
    mem = sysinfo.parse_meminfo(common.read_text(proc / "meminfo"))
    disque = shutil.disk_usage("/")
    _, sensors = runner.query(["sensors", "-j"]) if common.which("sensors") else (1, "")
    temps = materiel.parse_sensors(sensors) or materiel.thermal_zones()
    _, echecs = runner.query(["systemctl", "--failed", "--no-legend", "--plain"])
    _, top = runner.query(["ps", "-eo", "pcpu,pmem,comm", "--sort=-pcpu", "--no-headers"])
    charge = common.read_text(proc / "loadavg").split()[:3]
    return {
        "machine": socket.gethostname(),
        "date": time.time(),
        "processeur": pourcent(cpu1, cpu2),
        "charge": [float(x) for x in charge] if charge else [],
        "memoire": {"totale": mem.get("MemTotal", 0), "disponible": mem.get("MemAvailable", 0)},
        "disque": {"total": disque.total, "utilise": disque.used},
        "reseau": {"recu": max(net2[0] - net1[0], 0) / intervalle, "envoye": max(net2[1] - net1[1], 0) / intervalle},
        "temperature": max((t for _, t in temps), default=None),
        "allume": sysinfo.parse_uptime(common.read_text(proc / "uptime")),
        "echecs": [l.split()[0] for l in echecs.splitlines() if l.strip()],  # noqa: E741
        "processus": [l.split(None, 2) for l in top.splitlines()[:5] if len(l.split(None, 2)) == 3],  # noqa: E741
    }


def jauge(valeur: float, largeur: int = 20) -> str:
    plein = max(0, min(largeur, round(valeur / 100 * largeur)))
    couleur = "red" if valeur >= 90 else "yellow" if valeur >= 70 else "leaf"
    return common.style("█" * plein, couleur) + common.dim("░" * (largeur - plein))


def afficher(r: dict) -> str:
    mem_pct = 100 * (1 - r["memoire"]["disponible"] / r["memoire"]["totale"]) if r["memoire"]["totale"] else 0
    dsk_pct = 100 * r["disque"]["utilise"] / r["disque"]["total"] if r["disque"]["total"] else 0
    lignes = [common.style(f"  ✦ {r['machine']}", "bold", "gold")
              + common.dim(f"   allumée depuis {common.human_duration(r['allume'])}")]
    lignes.append(f"  processeur {jauge(r['processeur'])} {r['processeur']:5.1f} %"
                  + common.dim(f"   charge {' '.join(f'{c:.2f}' for c in r['charge'])}"))
    lignes.append(f"  mémoire    {jauge(mem_pct)} {mem_pct:5.1f} %"
                  + common.dim(f"   {common.human_size(r['memoire']['disponible'])} disponibles"))
    lignes.append(f"  disque /   {jauge(dsk_pct)} {dsk_pct:5.1f} %"
                  + common.dim(f"   {common.human_size(r['disque']['total'] - r['disque']['utilise'])} libres"))
    lignes.append(f"  réseau     ↓ {common.human_size(r['reseau']['recu'])}/s   ↑ {common.human_size(r['reseau']['envoye'])}/s")
    if r.get("temperature") is not None:
        t = r["temperature"]
        lignes.append(f"  chaleur    {common.style(f'{t:.0f} °C', 'red' if t >= 90 else 'yellow' if t >= 75 else 'leaf')}")
    if r["echecs"]:
        lignes.append(common.style(f"  ✘ services en échec : {', '.join(r['echecs'])}", "red"))
    if r["processus"]:
        lignes.append(common.dim("  les plus gourmands : " + ", ".join(f"{p[2]} {p[0]} %" for p in r["processus"][:3])))
    return "\n".join(lignes)


def releve_distant(cible: str) -> dict:
    """Le relevé d'une autre machine Yggdrasil, par SSH (clé conseillée)."""
    try:
        proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", cible,
                               "huginn", "--une-fois", "--json"], capture_output=True, text=True, timeout=20)
        return json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"machine": cible, "erreur": "injoignable (SSH par clé, et Yggdrasil installé là-bas ?)"}


def cmd_huginn(args) -> int:
    runner = Runner()
    if args.une_fois:
        r = releve(runner)
        print(json.dumps(r, ensure_ascii=False) if args.json else afficher(r))
        return 0
    try:
        while True:
            blocs = [afficher(releve(runner))]
            for cible in args.machines:
                r = releve_distant(cible)
                blocs.append(afficher(r) if "erreur" not in r else common.style(f"  ✦ {cible} : {r['erreur']}", "red"))
            sys.stdout.write("\033[H\033[2J" + common.style("  Huginn veille — Ctrl+C pour le renvoyer\n\n", "dim")
                             + "\n\n".join(blocs) + "\n")
            sys.stdout.flush()
            time.sleep(max(args.intervalle - 0.5, 0.5))
    except KeyboardInterrupt:
        print()
        return 0


# --------------------------------------------------------------------------
# Muninn : la mémoire
# --------------------------------------------------------------------------

def dossier() -> Path:
    return common.user_state_dir() / "yggdrasil" / "muninn"


def souvenir(runner: Runner) -> dict:
    """Ce qu'on garde chaque jour : de quoi raconter, demain, ce qui a changé."""
    from . import heimdall

    _, paquets = runner.query(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${db:Status-Abbrev}\n"])
    _, flatpaks = runner.query(["flatpak", "list", "--app", "--columns=application,version"])
    _, services = runner.query(["systemctl", "list-unit-files", "--type=service", "--state=enabled",
                                "--no-legend", "--plain"])
    _, ecoute = runner.query(["ss", "-H", "-tuln"])
    disque = shutil.disk_usage("/")
    ports = sorted({f"{l.port}/{l.proto}" for l in heimdall.parse_ss(ecoute)  # noqa: E741
                    if not heimdall.is_loopback(l.address)})
    return {
        "date": dt.datetime.now().isoformat(timespec="seconds"),
        "noyau": os.uname().release,
        "paquets": dict(sorted((l.split("\t")[0], l.split("\t")[1]) for l in paquets.splitlines()  # noqa: E741
                               if l.count("\t") == 2 and l.split("\t")[2].startswith("ii"))),
        "flatpaks": dict(sorted((l.split("\t")[0], l.split("\t")[1] if "\t" in l else "")  # noqa: E741
                                for l in flatpaks.splitlines() if l.strip())),  # noqa: E741
        "services": sorted(l.split()[0] for l in services.splitlines() if l.strip()),  # noqa: E741
        "ports": ports,
        "disque_utilise": disque.used,
    }


def differences(avant: dict, apres: dict) -> list[str]:
    """Ce qui a changé entre deux souvenirs, en phrases."""
    lignes = []
    pa, pb = avant.get("paquets", {}), apres.get("paquets", {})
    ajoutes = sorted(set(pb) - set(pa))
    retires = sorted(set(pa) - set(pb))
    maj = sorted(p for p in set(pa) & set(pb) if pa[p] != pb[p])

    def liste(noms: list[str], n: int = 8) -> str:
        return ", ".join(noms[:n]) + (f" et {len(noms) - n} autres" if len(noms) > n else "")

    if ajoutes:
        lignes.append(f"{len(ajoutes)} paquet(s) installé(s) : {liste(ajoutes)}")
    if retires:
        lignes.append(f"{len(retires)} paquet(s) retiré(s) : {liste(retires)}")
    if maj:
        lignes.append(f"{len(maj)} paquet(s) mis à jour : {liste(maj)}")
    fa, fb = avant.get("flatpaks", {}), apres.get("flatpaks", {})
    for nom in sorted(set(fb) - set(fa)):
        lignes.append(f"application Flatpak installée : {nom}")
    for nom in sorted(set(fa) - set(fb)):
        lignes.append(f"application Flatpak retirée : {nom}")
    if avant.get("noyau") and avant.get("noyau") != apres.get("noyau"):
        lignes.append(f"nouveau noyau : {avant['noyau']} → {apres['noyau']}")
    for s in sorted(set(apres.get("services", [])) - set(avant.get("services", []))):
        lignes.append(f"service activé au démarrage : {s}")
    for s in sorted(set(avant.get("services", [])) - set(apres.get("services", []))):
        lignes.append(f"service désactivé : {s}")
    for p in sorted(set(apres.get("ports", [])) - set(avant.get("ports", []))):
        lignes.append(f"port ouvert à l'écoute : {p}")
    for p in sorted(set(avant.get("ports", [])) - set(apres.get("ports", []))):
        lignes.append(f"port refermé : {p}")
    delta = apres.get("disque_utilise", 0) - avant.get("disque_utilise", 0)
    if abs(delta) >= 1024 ** 3:
        lignes.append(("disque : +" if delta > 0 else "disque : −") + common.human_size(abs(delta)))
    return lignes


def souvenirs() -> list[Path]:
    return sorted(dossier().glob("*.json")) if dossier().is_dir() else []


def noter(runner: Runner, garder: int = 90) -> Path:
    chemin = dossier() / f"{dt.date.today().isoformat()}.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(souvenir(runner), ensure_ascii=False), encoding="utf-8")
    for vieux in souvenirs()[:-garder]:
        vieux.unlink(missing_ok=True)
    return chemin


def cmd_muninn(args) -> int:
    runner = Runner()
    if args.action == "noter":
        chemin = noter(runner)
        print(f"Muninn se souviendra de ce jour : {chemin}")
        return 0
    anciens = souvenirs()
    aujourdhui = souvenir(runner)
    if args.action == "depuis":
        if not args.date:
            raise YggError("muninn depuis AAAA-MM-JJ")
        candidats = [p for p in anciens if p.stem <= args.date]
        if not candidats:
            raise YggError(f"Muninn n'a pas de souvenir du {args.date} ou d'avant (le premier : "
                           f"{anciens[0].stem if anciens else 'aucun'}).")
        reference = candidats[-1]
    else:
        passes = [p for p in anciens if p.stem < dt.date.today().isoformat()]
        if not passes:
            common.info("Muninn n'a encore aucun souvenir d'un jour passé : il notera celui-ci.")
            noter(runner)
            return 0
        reference = passes[-1]
    avant = json.loads(reference.read_text(encoding="utf-8"))
    common.title(f"Muninn se souvient : ce qui a changé depuis le {reference.stem}")
    lignes = differences(avant, aujourdhui)
    for ligne in lignes:
        common.step(ligne)
    if not lignes:
        common.info("Rien n'a changé : le monde est tel que Muninn l'a laissé.")
    return 0


def main_huginn(argv=None) -> int:
    p = argparse.ArgumentParser(prog="huginn", description="Huginn, la pensée : tes machines en direct.")
    p.add_argument("machines", nargs="*", help="autres machines Yggdrasil à surveiller (moi@serveur, par SSH)")
    p.add_argument("--une-fois", action="store_true", help="un seul relevé")
    p.add_argument("--json", action="store_true", help="relevé en JSON (avec --une-fois)")
    p.add_argument("--intervalle", type=float, default=2.0, help="secondes entre deux relevés (2)")
    return common.run_main(lambda a: cmd_huginn(p.parse_args(a)), argv)


def main_muninn(argv=None) -> int:
    p = argparse.ArgumentParser(prog="muninn", description="Muninn, la mémoire : ce qui a changé.")
    p.add_argument("action", nargs="?", choices=["noter", "depuis"])
    p.add_argument("date", nargs="?", help="avec « depuis » : AAAA-MM-JJ")
    return common.run_main(lambda a: cmd_muninn(p.parse_args(a)), argv)
