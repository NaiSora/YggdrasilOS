"""{{name}} — un service qui tourne en fond : toutes les minutes, il surveille un dossier.

Arrêt propre sur SIGTERM (systemctl --user stop) ; ses messages vont dans le journal
(journalctl --user -u {{slug}} -f).
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .core import word_stats

log = logging.getLogger("{{slug}}")


def tour(dossier: Path) -> int:
    """Un passage : compte les mots des fichiers texte du dossier."""
    total = 0
    for fichier in sorted(dossier.glob("*.txt")):
        total += word_stats(fichier.read_text(encoding="utf-8", errors="replace")).words
    return total


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s")
    dossier = Path(os.getenv("DOSSIER", Path.home() / "Documents"))
    intervalle = float(os.getenv("INTERVALLE", "60"))
    arret = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: arret.set())
    signal.signal(signal.SIGINT, lambda *_: arret.set())
    log.info("{{name}} veille sur %s (toutes les %.0f s)", dossier, intervalle)
    while not arret.is_set():
        log.info("%d mots dans les fichiers .txt", tour(dossier))
        arret.wait(intervalle)
    log.info("arrêt demandé : au revoir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
