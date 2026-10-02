"""{{name}} — une fenêtre Qt : colle un texte, obtiens ses statistiques."""

from __future__ import annotations

import sys

from .core import word_stats


def main() -> int:
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

    app = QApplication(sys.argv)
    app.setApplicationName("{{name}}")
    app.setDesktopFileName("{{slug}}")
    fenetre = QMainWindow()
    fenetre.setWindowTitle("{{name}}")
    zone = QPlainTextEdit()
    zone.setPlaceholderText("Colle un texte ici…")
    resultat = QLabel("—")
    bouton = QPushButton("Analyser")

    def analyser() -> None:
        stats = word_stats(zone.toPlainText(), top=3)
        mots = ", ".join(f"{m} ({n})" for m, n in stats.most_common) or "aucun"
        resultat.setText(f"{stats.lines} lignes, {stats.words} mots — les plus fréquents : {mots}")

    bouton.clicked.connect(analyser)
    contenu = QWidget()
    disposition = QVBoxLayout(contenu)
    for w in (zone, bouton, resultat):
        disposition.addWidget(w)
    fenetre.setCentralWidget(contenu)
    fenetre.resize(640, 420)
    fenetre.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
