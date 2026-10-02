"""L'arbre vivant : chaque royaume installé allume une feuille d'or sur le fond d'écran.

    ygg realm arbre          quelles feuilles brillent, et redessiner le fond
    ygg realm arbre non      revenir au fond d'écran fixe (oui pour rallumer)

Le modèle /usr/share/yggdrasil/arbre-vivant.svg (assets/generate.py) porte neuf
feuilles éteintes, une par monde ; on rallume celles des royaumes installés, on rend
l'image avec rsvg-convert et Plasma l'affiche. Rien n'est fait hors d'une session
Plasma, ni si tu as coupé l'arbre vivant.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from . import common, realms
from .common import DATA_DIR, Runner

MODELE = "arbre-vivant.svg"
TAILLE = (2560, 1440)


def allumer(modele: str, noms: Iterable[str]) -> str:
    """Le SVG du fond, avec les feuilles (et runes) de ces royaumes allumées."""
    svg = modele
    for nom in noms:
        for genre in ("lumiere", "rune"):
            svg = re.sub(rf'(id="[\w-]*{genre}-{re.escape(nom)}"[^>]*?)opacity="0"', r'\1opacity="1"', svg)
    return svg


def royaumes_allumes(runner: Runner, tous: dict[str, realms.Realm] | None = None) -> list[str]:
    """Les royaumes installés : par « ygg realm add », ou dont tout le choix par défaut est là."""
    tous = tous if tous is not None else realms.load_realms()
    etat = realms.load_state()
    flatpaks = realms.installed_flatpaks(runner)
    allumes = []
    for nom, realm in tous.items():
        if realm.perso:
            continue
        if nom in etat or realms.realm_status(realm, runner, flatpaks).installed:
            allumes.append(nom)
    return allumes


def actif(config: dict) -> bool:
    return bool(config.get("arbre", {}).get("vivant", True))


def en_session_plasma() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")) \
        and "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "") and bool(common.which("plasma-apply-wallpaperimage"))


def dossier() -> Path:
    return common.user_data_dir() / "wallpapers"


def rafraichir(runner: Runner, config: dict, *, forcer: bool = False) -> Path | None:
    """Redessine le fond si l'arbre vivant est actif et qu'une session Plasma est là."""
    modele = DATA_DIR / MODELE
    if not (forcer or actif(config)) or not modele.exists() or not common.which("rsvg-convert"):
        return None
    if not en_session_plasma():
        return None
    allumes = royaumes_allumes(runner)
    sortie = dossier()
    sortie.mkdir(parents=True, exist_ok=True)
    svg = sortie / "yggdrasil-arbre-vivant.svg"
    svg.write_text(allumer(modele.read_text(encoding="utf-8"), allumes), encoding="utf-8")
    # Un nom par état : Plasma garde l'image en cache tant que le chemin ne change pas
    png = sortie / f"yggdrasil-arbre-vivant-{len(allumes)}-{'-'.join(allumes) or 'nu'}.png"
    for ancien in sortie.glob("yggdrasil-arbre-vivant-*.png"):
        if ancien != png:
            ancien.unlink(missing_ok=True)
    runner.run(["rsvg-convert", "-w", str(TAILLE[0]), "-h", str(TAILLE[1]), str(svg), "-o", str(png)],
               check=False, capture=True)
    runner.run(["plasma-apply-wallpaperimage", str(png)], check=False, capture=True)
    return png


def cmd_arbre(args, runner: Runner, config: dict) -> int:
    if args.etat:
        if not runner.dry_run:
            common.save_user_config({"arbre": {"vivant": args.etat == "oui"}})
        if args.etat == "non":
            common.ok("l'arbre vivant se repose : ton fond d'écran ne changera plus "
                      "(Clic droit sur le bureau → Configurer le bureau pour en choisir un autre).")
            return 0
        config = {**config, "arbre": {"vivant": True}}
    tous = realms.load_realms()
    allumes = royaumes_allumes(runner, tous)
    common.title("L'arbre vivant")
    for nom, realm in tous.items():
        if realm.perso:
            continue
        marque = common.style(f"{realm.rune} ✦", "gold") if nom in allumes else common.dim(f"{realm.rune} ·")
        print(f"  {marque} {realm.nom_complet}")
    common.info(f"{len(allumes)} feuille(s) d'or sur neuf.")
    png = rafraichir(runner, config, forcer=bool(args.etat))
    if png:
        common.ok(f"fond d'écran redessiné : {png}")
    elif not actif(config):
        common.info(common.dim("l'arbre vivant est coupé : « ygg realm arbre oui » pour le rallumer."))
    elif not en_session_plasma():
        common.info(common.dim("le fond sera redessiné depuis une session Plasma."))
    return 0
