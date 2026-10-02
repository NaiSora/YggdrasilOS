"""{{name}} : la fenêtre QML, reliée à la logique Python (Carnet)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .carnet import Carnet


def main() -> int:
    from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    class Pont(QObject):
        changement = Signal()

        def __init__(self, carnet: Carnet) -> None:
            super().__init__()
            self.carnet = carnet

        notes = Property("QStringList", lambda self: self.carnet.notes, notify=changement)

        @Slot(str)
        def ajouter(self, texte: str) -> None:
            if self.carnet.ajouter(texte):
                self.changement.emit()

        @Slot(int)
        def retirer(self, rang: int) -> None:
            self.carnet.retirer(rang)
            self.changement.emit()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("{{name}}")
    app.setDesktopFileName("{{slug}}")
    app.setWindowIcon(QIcon.fromTheme("{{slug}}"))
    donnees = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "{{slug}}" / "notes.json"
    pont = Pont(Carnet(donnees))
    moteur = QQmlApplicationEngine()
    moteur.rootContext().setContextProperty("pont", pont)
    moteur.load(QUrl.fromLocalFile(str(Path(__file__).with_name("qml") / "Main.qml")))
    if not moteur.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
