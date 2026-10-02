#!/usr/bin/env python3
"""Rendu hors écran de chaque page du Centre (Qt Quick, Kirigami), pour les tests.

    rendu-centre.py DOSSIER_SORTIE [RACINE]

Charge le vrai QML avec des données d'exemple, aux couleurs du jeu « Yggdrasil »,
dans le style de Plasma (org.kde.desktop), et enregistre une image par page.
RACINE est l'arborescence extraite des paquets yggdrasil-base et -desktop : ses
icônes et ses réglages par défaut (etc/xdg/yggdrasil) sont alors utilisés.
Échoue si le QML ne se charge pas ou si une page émet une erreur QML.
"""

import os
import sys
from pathlib import Path

RACINE = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QSG_RENDER_LOOP", "basic")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")
if RACINE:
    os.environ["XDG_CONFIG_DIRS"] = f"{RACINE}/etc/xdg/yggdrasil:/etc/xdg"
    os.environ["XDG_DATA_DIRS"] = f"{RACINE}/usr/share:/usr/local/share:/usr/share"
DEPOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("YGG_DATA_DIR", str(DEPOT / "data"))  # les vrais royaumes et voyageurs
sys.path.insert(0, str(DEPOT / "src"))

from PySide6.QtCore import Q_ARG, QMetaObject, Qt, QTimer, QUrl, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402,F401  (fenêtre Qt Quick : grabWindow)

from yggdrasil import welcome  # noqa: E402
from yggdrasil.common import Runner  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
erreurs: list[str] = []
fini = False


def journal(mode, context, message):
    if fini or "not placed in the graphics scene" in message:
        # Destruction des pages à la fermeture (leurs liaisons voient des objets nuls),
        # ou page créée par pageStack avant d'être posée : rien d'anormal
        return
    if "qml" in message.lower() or message.startswith("file:"):
        if any(m in message for m in ("Error", "error", "TypeError", "ReferenceError", "is not defined",
                                      "Cannot assign", "Unable to assign", "Invalid", "not a type")):
            erreurs.append(message)
    print(message, file=sys.stderr)


qInstallMessageHandler(journal)
app = QGuiApplication(sys.argv)
if RACINE:
    QIcon.setThemeSearchPaths([str(RACINE / "usr/share/icons"), *QIcon.themeSearchPaths()])
QIcon.setThemeName("Yggdrasil" if RACINE else "Papirus-Dark")
QIcon.setFallbackThemeName("hicolor")

# Les couleurs du jeu « Yggdrasil » (comme dans Plasma)
pal = QPalette()
for role, couleur in {
    QPalette.Window: "#0F2742", QPalette.WindowText: "#F2EAD7", QPalette.Base: "#0B2036",
    QPalette.AlternateBase: "#0E253E", QPalette.Text: "#F2EAD7", QPalette.Button: "#173656",
    QPalette.ButtonText: "#F2EAD7", QPalette.Highlight: "#5B8B7B", QPalette.HighlightedText: "#FBF7EE",
    QPalette.Link: "#E8CC8C", QPalette.ToolTipBase: "#0F2742", QPalette.ToolTipText: "#F2EAD7",
    QPalette.PlaceholderText: "#9DB3AA",
}.items():
    pal.setColor(role, QColor(couleur))
app.setPalette(pal)

centre = welcome.build_backend(Runner(dry_run=True), {}, "trone")
centre._data.update({
    "etat": {"presage": "12 mises à jour attendent au pied de l'arbre, dont 2 de sécurité (ygg update).",
             "majs": 12, "securite": 2, "disque": 54, "echecs": 0, "parefeu": "actif"},
    "sante": [
        {"cle": "disk", "libelle": "Espace disque", "statut": "ok", "message": "/ : 54 % utilisés", "conseil": ""},
        {"cle": "updates", "libelle": "Mises à jour", "statut": "warn",
         "message": "12 en attente, dont 2 de sécurité", "conseil": "ygg update"},
        {"cle": "time", "libelle": "Horloge", "statut": "fail", "message": "non synchronisée",
         "conseil": "sudo timedatectl set-ntp true"},
    ],
    "royaumes": welcome.realm_cards(Runner(dry_run=True)),
    "services": [dict(c, deployes=["survie", "creatif"] if c["nom"] == "minecraft" else c["deployes"])
                 for c in welcome.stack_cards({"bifrost": {"home": "/nulle-part"}})],
    "modeles": welcome.template_cards(),
    "oracle": {"ollama": True, "eveille": True, "modeles": "qwen3:8b, nomic-embed-text",
               "recommande": "qwen3:8b", "puits": "42 fichiers, 310 extraits", "prenom": "Astrid"},
    "reglages": {"ton": "voix", "tonMimir": "oracle", "ratatoskr": True, "autostart": True,
                 "presage": True, "theme": "nuit"},
    "resultats": [],
})
centre.changed.emit()

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("ygg", centre)
engine.load(QUrl.fromLocalFile(str(welcome.QML_DIR / "Main.qml")))
if not engine.rootObjects():
    print("échec du chargement de Main.qml", file=sys.stderr)
    sys.exit(1)
fenetre = engine.rootObjects()[0]
fenetre.setWidth(1280)
fenetre.setHeight(860)
fenetre.show()
pages = list(welcome.PAGES)


def suivante(i: int = 0) -> None:
    if i >= len(pages):
        accueil()
        return
    QMetaObject.invokeMethod(fenetre, "ouvrir", Qt.DirectConnection, Q_ARG("QVariant", pages[i]))
    QTimer.singleShot(900, lambda: (fenetre.grabWindow().save(str(OUT / f"centre-{i + 1}-{pages[i]}.png")),
                                    suivante(i + 1)))


# L'assistant « Bienvenue, voyageur » : ses cinq étapes, un joueur et un développeur choisis
ETAPES = ("bienvenue", "voyageur", "mondes", "gardiens", "planter")
moteur_accueil = QQmlApplicationEngine()


def accueil() -> None:
    fenetre.hide()
    moteur_accueil.rootContext().setContextProperty("ygg", centre)
    moteur_accueil.load(QUrl.fromLocalFile(str(welcome.QML_DIR / "Accueil.qml")))
    if not moteur_accueil.rootObjects():
        erreurs.append("échec du chargement de Accueil.qml")
        app.quit()
        return
    assistant = moteur_accueil.rootObjects()[0]
    assistant.setWidth(1280)
    assistant.setHeight(860)
    assistant.setProperty("voyageursChoisis", ["joueur", "developpeur"])
    assistant.show()

    def etape(i: int) -> None:
        if i >= len(ETAPES):
            plan = assistant.property("commandes")
            if not plan or not any("ygg realm add muspelheim" in c for c in plan):
                erreurs.append(f"plan de l'assistant inattendu : {plan}")
            app.quit()
            return
        assistant.setProperty("etape", i)
        QTimer.singleShot(900, lambda: (assistant.grabWindow().save(str(OUT / f"accueil-{i + 1}-{ETAPES[i]}.png")),
                                        etape(i + 1)))

    QTimer.singleShot(600, lambda: etape(0))


QTimer.singleShot(800, suivante)
# Garde-fou : jamais plus d'une minute et demie
QTimer.singleShot(90000, lambda: (erreurs.append("délai dépassé"), app.quit()))
app.exec()
fini = True
if erreurs:
    print("\n".join(["Erreurs QML :", *erreurs]), file=sys.stderr)
    sys.exit(1)
print(f"{len(pages)} pages du Centre et {len(ETAPES)} étapes de l'assistant rendues dans {OUT}")
