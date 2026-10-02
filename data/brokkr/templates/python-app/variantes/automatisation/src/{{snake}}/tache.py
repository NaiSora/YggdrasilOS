"""{{name}} — une tâche planifiée : ranger les Téléchargements par type de fichier.

    {{slug}} --simulation     montre ce qui serait rangé
    {{slug}}                  range vraiment
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

CATEGORIES = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"},
    "Documents": {".pdf", ".odt", ".docx", ".txt", ".md", ".ods", ".xlsx"},
    "Archives": {".zip", ".tar", ".gz", ".xz", ".7z", ".rar"},
    "Musique": {".mp3", ".flac", ".ogg", ".wav"},
    "Vidéos": {".mp4", ".mkv", ".webm", ".avi"},
}


def categorie(fichier: Path) -> str | None:
    return next((nom for nom, ext in CATEGORIES.items() if fichier.suffix.lower() in ext), None)


def plan(dossier: Path) -> list[tuple[Path, Path]]:
    """(source, destination) pour chaque fichier à ranger ; jamais d'écrasement."""
    deplacements = []
    for fichier in sorted(p for p in dossier.iterdir() if p.is_file()):
        cat = categorie(fichier)
        if cat:
            cible = dossier / cat / fichier.name
            if not cible.exists():
                deplacements.append((fichier, cible))
    return deplacements


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="{{slug}}", description="Range un dossier par type de fichier.")
    p.add_argument("dossier", nargs="?", default=str(Path.home() / "Téléchargements"))
    p.add_argument("--simulation", action="store_true", help="montrer sans rien déplacer")
    args = p.parse_args(argv)
    for source, cible in plan(Path(args.dossier)):
        print(f"{source.name} → {cible.parent.name}/")
        if not args.simulation:
            cible.parent.mkdir(exist_ok=True)
            shutil.move(source, cible)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
