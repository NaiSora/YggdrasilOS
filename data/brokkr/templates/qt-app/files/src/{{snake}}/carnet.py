"""La logique de l'application, sans Qt : un carnet de notes. Testable sans fenêtre."""

from __future__ import annotations

import json
from pathlib import Path


class Carnet:
    def __init__(self, fichier: Path) -> None:
        self.fichier = fichier
        try:
            self.notes: list[str] = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.notes = []

    def ajouter(self, texte: str) -> bool:
        texte = texte.strip()
        if not texte:
            return False
        self.notes.insert(0, texte)
        self.garder()
        return True

    def retirer(self, rang: int) -> None:
        if 0 <= rang < len(self.notes):
            del self.notes[rang]
            self.garder()

    def garder(self) -> None:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        self.fichier.write_text(json.dumps(self.notes, ensure_ascii=False), encoding="utf-8")
