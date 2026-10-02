"""Le menu de « ygg » sans argument : les gestes courants, un chiffre pour chacun.

Chaque entrée lance la commande « ygg … » correspondante, affichée en clair pour
qu'on l'apprenne au passage.
"""

from __future__ import annotations

import shlex
from typing import Callable

from . import CODENAME, __version__, common

ENTREES: tuple[tuple[str, str, list[str]], ...] = (
    ("Entretien", "Mettre à jour tout le système", ["update"]),
    ("Entretien", "Diagnostic de santé", ["doctor"]),
    ("Entretien", "Réparer (paquets, Flatpak)", ["reparer"]),
    ("Entretien", "Níðhöggr : faire de la place", ["nettoyer"]),
    ("Entretien", "Défaire la dernière action", ["annuler"]),
    ("Logiciels", "Les royaumes", ["realm", "list"]),
    ("Logiciels", "Chercher un logiciel", ["search"]),
    ("Machine", "Matériel, disques, températures", ["materiel"]),
    ("Machine", "Pilotes manquants", ["pilotes"]),
    ("Machine", "Énergie", ["energie"]),
    ("Machine", "Durée du démarrage", ["demarrage"]),
    ("Réseau", "Pare-feu (Heimdall)", ["fw", "status"]),
    ("Réseau", "Dossiers partagés (Windows, Linux, Mac)", ["partage"]),
    ("Réseau", "Accès à distance (SSH, WireGuard)", ["distance"]),
    ("Mémoire", "Instantanés et sauvegardes (Norns)", ["snap", "status"]),
    ("Mémoire", "La saga : ce que les outils ont fait", ["saga"]),
    ("Aide", "Consulter Mímir", ["ai", "chat"]),
    ("Aide", "Rapport pour demander de l'aide", ["rapport"]),
)


def afficher() -> None:
    s = common.style
    print(s(f"\n  ✦ Yggdrasil {__version__} « {CODENAME} »", "bold", "gold") if common.unicode_ok()
          else f"\n  Yggdrasil {__version__}")
    groupe = ""
    for i, (g, libelle, _) in enumerate(ENTREES, 1):
        if g != groupe:
            groupe = g
            print("\n  " + s(g, "leaf"))
        print(f"   {s(f'{i:>2}', 'gold')}  {libelle}")
    print(f"\n   {s(' 0', 'gold')}  Quitter")


def boucle(lancer: Callable[[list[str]], int], lire: Callable[[str], str] = input) -> int:
    """Affiche le menu jusqu'à « 0 » (ou Ctrl+D) ; `lancer` exécute « ygg ARGS »."""
    while True:
        afficher()
        try:
            choix = lire(common.style("\n  Ton choix : ", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choix in ("0", "q", "quitter", ""):
            return 0
        if not choix.isdigit() or not 1 <= int(choix) <= len(ENTREES):
            common.warn(f"choisis un nombre entre 0 et {len(ENTREES)}.")
            continue
        _, libelle, argv = ENTREES[int(choix) - 1]
        argv = list(argv)
        if argv == ["search"]:
            try:
                terme = lire("  Quel logiciel ? ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not terme:
                continue
            argv.append(terme)
        print(common.dim(f"\n  $ ygg {shlex.join(argv)}"))
        try:
            lancer(argv)
        except KeyboardInterrupt:
            print()
        try:
            lire(common.dim("\n  Entrée pour revenir au menu… "))
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
