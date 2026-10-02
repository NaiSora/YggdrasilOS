"""Hliðskjálf — le Centre d'Yggdrasil (Qt Quick et Kirigami, natif dans Plasma).

Dans le mythe, Hliðskjálf est le trône d'Odin d'où l'on voit les neuf mondes.
Ici : l'état de ta machine d'un coup d'œil (présage, santé, mises à jour,
pare-feu, sauvegardes, services) et chaque action en un clic.

Comme les outils en ligne de commande, le Centre ne fait rien en cachette :
chaque action ouvre un terminal qui montre la commande (ygg, mimir, heimdall…)
et ses demandes de validation. Seuls les réglages personnels (ton des voix,
thème, démarrage automatique) s'appliquent directement.

    yggdrasil-welcome [--autostart] [--page NOM] [--plateau] [--accueil]

Pages : trone, sante, logiciels, gardiens, bifrost, forge, oracle, reglages.
--plateau : une icône dans la barre système (état global et menu rapide).
--accueil : l'assistant « Bienvenue, voyageur » (ouvert seul à la première session
            d'un système installé) : prénom, voyageur, royaumes, thème, gardiens.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from . import CODENAME, __version__, common, voix
from .common import Runner, YggError

DOC_INDEX = Path("/usr/share/doc/yggdrasil/index.html")
QML_DIR = Path(__file__).with_name("qml")
PAGES = ("trone", "sante", "logiciels", "gardiens", "bifrost", "forge", "oracle", "reglages")
# Anciennes adresses de page (centre GTK)
ALIAS = {"home": "trone", "realms": "logiciels", "system": "sante", "ai": "oracle",
         "homelab": "bifrost"}


def welcome_flag() -> Path:
    return common.user_config_dir() / "welcome-hidden"


def presage_off_flag() -> Path:
    """Présence = pas de présage de Mímir à l'ouverture du premier terminal du jour."""
    return common.user_config_dir() / "presage-desactive"


def terminal_command(script: str, title: str = "Yggdrasil") -> list[str]:
    """Commande qui ouvre un terminal, exécute `script` puis attend Entrée."""
    wrapped = f"{script}; echo; read -rp 'Terminé — appuie sur Entrée pour fermer… ' _"
    if common.which("konsole"):
        return ["konsole", "--hide-menubar", "-p", f"tabtitle={title}", "-e", "bash", "-lc", wrapped]
    if common.which("xfce4-terminal"):
        return ["xfce4-terminal", f"--title={title}", "-x", "bash", "-lc", wrapped]
    if common.which("gnome-terminal"):
        return ["gnome-terminal", f"--title={title}", "--", "bash", "-lc", wrapped]
    if common.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", "bash", "-lc", wrapped]
    if common.which("xterm"):
        return ["xterm", "-T", title, "-e", "bash", "-lc", wrapped]
    raise YggError("aucun terminal graphique trouvé.")


def launch_in_terminal(script: str, title: str = "Yggdrasil") -> None:
    subprocess.Popen(terminal_command(script, title), start_new_session=True)


def open_uri(uri: str) -> None:
    subprocess.Popen(["xdg-open", uri], start_new_session=True)


def installer_command() -> str | None:
    for cmd in ("calamares-install-debian", "install-debian"):
        if common.which(cmd):
            return cmd
    return None


# --------------------------------------------------------------------------
# Données affichées (fonctions pures, testées sans Qt)
# --------------------------------------------------------------------------

def machine_state(runner: Runner, config: dict) -> dict[str, Any]:
    """Présage et faits du jour, pour le trône."""
    from . import mimir

    facts = mimir.gather_facts(runner)
    ton = voix.ton_mimir(config)
    return {
        "presage": mimir.presage(facts, ton),
        "majs": facts.updates if facts.updates is not None else -1,
        "securite": facts.security,
        "disque": facts.disk_pct if facts.disk_pct is not None else -1,
        "echecs": facts.failed if facts.failed is not None else -1,
        "parefeu": {True: "actif", False: "désactivé", None: "inconnu"}[facts.firewall],
    }


def health_checks(runner: Runner) -> list[dict[str, str]]:
    from . import doctor

    return [{"cle": c.key, "libelle": c.label, "statut": c.status, "message": c.message, "conseil": c.hint}
            for c in doctor.Doctor(runner).run()]


def realm_cards(runner: Runner) -> list[dict[str, Any]]:
    """Les neuf mondes (et les royaumes personnels), avec leurs logiciels à cocher."""
    from . import realms

    cards = []
    try:
        flatpaks = realms.installed_flatpaks(runner)
    except YggError:
        flatpaks = set()
    for realm in realms.load_realms().values():
        status = realms.realm_status(realm, runner, flatpaks)
        cards.append({
            "nom": realm.name, "titre": realm.title, "surnom": realm.surnom, "theme": realm.theme,
            "rune": realm.rune, "runeNom": realm.rune_nom, "runeSens": realm.rune_sens,
            "description": " ".join(realm.description.split()), "icone": realm.icon, "etat": status.label,
            "perso": realm.perso, "voyageurs": list(realm.voyageurs),
            "logiciels": [{"id": x.id, "nom": x.nom, "description": x.description, "defaut": x.defaut,
                           "installe": x.id in status.installes} for x in realm.logiciels],
        })
    return cards


def voyageur_cards() -> list[dict[str, str]]:
    from . import realms

    return [{"id": v.id, "nom": v.nom, "description": v.description, "icone": v.icon}
            for v in realms.load_voyageurs()]


def accueil_flag() -> Path:
    return common.user_config_dir() / "accueil-fait"


def commande_royaume(nom: str, ids: list[str]) -> str:
    """« ygg realm add NOM --seulement a,b -y » ; les identifiants sont vérifiés."""
    from . import realms

    realm = realms.get_realm(nom)
    connus = {x.id for x in realm.logiciels}
    choisis = [i for i in ids if i in connus]
    if not choisis:
        raise YggError(f"aucun logiciel choisi dans {realm.title}")
    return shlex.join(["ygg", "realm", "add", realm.name, "--seulement", ",".join(choisis), "-y"])


def plan_accueil(choix: dict[str, Any], live: bool = False) -> list[str]:
    """Les commandes qui réalisent les choix de l'assistant « Bienvenue, voyageur ».

    Elles s'exécutent dans un terminal visible : tu vois tout ce qui se passe.
    """
    commandes = [commande_royaume(nom, list(ids)) for nom, ids in (choix.get("royaumes") or {}).items() if ids]
    theme = choix.get("theme", "nuit")
    if theme in ("nuit", "aube", "auto"):
        commandes.append(f"ygg theme {theme}")
    if choix.get("instantanes") and not live:
        commandes.append("norns setup -y")
    commandes.append("ratatoskr enable" if choix.get("ratatoskr", True) else "ratatoskr disable")
    commandes.append(f"ygg realm arbre {'oui' if choix.get('arbre', True) else 'non'}")
    return commandes


ICONES_BIFROST = {"jeux": "applications-games", "ia": "yggdrasil", "creation": "applications-multimedia",
                  "dev": "applications-development", "partage": "folder-cloud", "reseau": "network-server"}


def stack_cards(config: dict | None = None) -> list[dict[str, Any]]:
    """Les services de Bifröst, par domaine, avec ce qui est déjà déployé."""
    from . import bifrost

    config = config if config is not None else common.load_config()
    try:
        deployes = bifrost.deploiements(config)
    except OSError:
        deployes = {}
    return [{"nom": s.name, "titre": s.title, "description": " ".join(s.description.split()),
             "url": s.url if "${" not in s.url else "", "ports": ", ".join(s.ports),
             "categorie": s.categorie, "domaine": bifrost.CATEGORIES[s.categorie],
             "icone": ICONES_BIFROST.get(s.categorie, "network-server"), "instances": s.instances,
             "deployes": [n for n, m in deployes.items() if m == s.name]}
            for s in sorted(bifrost.load_stacks().values(),
                            key=lambda s: (list(bifrost.CATEGORIES).index(s.categorie), s.name))]


def template_cards() -> list[dict[str, Any]]:
    from . import brokkr

    return [{"nom": t.name, "titre": t.title, "description": " ".join(t.description.split()),
             "langage": t.language, "variantes": [{"id": v.id, "nom": v.nom} for v in t.variantes],
             "modules": [{"id": m.id, "nom": m.nom, "defaut": m.defaut} for m in t.modules]}
            for t in brokkr.load_templates().values()]


def parse_apt_search(output: str, limit: int = 30) -> list[dict[str, str]]:
    found = []
    for line in sorted(output.splitlines()):
        name, sep, desc = line.partition(" - ")
        if sep and name.strip():
            found.append({"source": "Debian", "id": name.strip(), "nom": name.strip(), "description": desc.strip()})
    return found[:limit]


def parse_flatpak_search(output: str, limit: int = 30) -> list[dict[str, str]]:
    found = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and "." in parts[0] and " " not in parts[0]:
            found.append({"source": "Flathub", "id": parts[0], "nom": parts[1],
                          "description": parts[2] if len(parts) > 2 else ""})
    return found[:limit]


def search_software(runner: Runner, text: str) -> list[dict[str, str]]:
    """Recherche unifiée : applications Flathub d'abord, puis paquets Debian."""
    text = text.strip()
    if len(text) < 2:
        return []
    results = []
    if common.which("flatpak"):
        _, out = runner.query(["flatpak", "search", "--columns=application,name,description", text], timeout=60)
        results += parse_flatpak_search(out)
    _, out = runner.query(["apt-cache", "search", "--names-only", text], timeout=30)
    results += parse_apt_search(out)
    return results


def oracle_state(runner: Runner, config: dict) -> dict[str, Any]:
    from . import mimir, puits

    m = mimir.Mimir(config, puits_actif=False)
    version = m.client.version()
    models: list[str] = []
    if version:
        try:
            models = [x["name"] for x in m.client.models()]
        except YggError:
            models = []
    fichiers, extraits = puits.Puits().etat()
    return {
        "ollama": bool(common.which("ollama")),
        "eveille": bool(version),
        "modeles": ", ".join(models) or "aucun",
        "recommande": mimir.recommended_model(),
        "puits": f"{fichiers} fichiers, {extraits} extraits" if fichiers else "vide",
        "prenom": mimir.load_profil().get("prenom", ""),
    }


def user_settings(runner: Runner, config: dict) -> dict[str, Any]:
    code, _ = runner.query(["systemctl", "--user", "is-enabled", "ratatoskr.timer"])
    return {
        "ton": voix.ton_general(config),
        "tonMimir": voix.ton_mimir(config) if voix.ton_general(config) != "sobre"
        else config.get("mimir", {}).get("ton", "oracle"),
        "ratatoskr": code == 0,
        "autostart": not welcome_flag().exists(),
        "presage": not presage_off_flag().exists(),
        "theme": config.get("theme", {}).get("mode", "nuit"),
    }


def apply_setting(key: str, value: Any, runner: Runner) -> str:
    """Applique un réglage personnel ; renvoie un message pour l'utilisateur."""
    if key == "ton" and value in voix.TONS_GENERAUX:
        common.save_user_config({"general": {"ton": value}})
        return "Les outils parlent désormais " + ("sobrement." if value == "sobre" else "avec leur voix.")
    if key == "tonMimir" and value in voix.TONS_MIMIR:
        common.save_user_config({"mimir": {"ton": value}})
        return f"Mímir prend le ton « {value} »."
    if key == "ratatoskr":
        action = "enable" if value else "disable"
        runner.run(["systemctl", "--user", action, "--now", "ratatoskr.timer"], check=False)
        return "Ratatoskr court à nouveau le long du tronc." if value else "Ratatoskr se repose."
    if key == "autostart":
        flag = welcome_flag()
        if value:
            flag.unlink(missing_ok=True)
        else:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("masqué depuis le Centre\n", encoding="utf-8")
        return "Le Centre s'ouvrira au démarrage." if value else "Le Centre ne s'ouvrira plus au démarrage."
    if key == "presage":
        flag = presage_off_flag()
        if value:
            flag.unlink(missing_ok=True)
        else:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("présage désactivé depuis le Centre\n", encoding="utf-8")
        return "Le présage reviendra chaque matin." if value else "Plus de présage au premier terminal."
    if key == "theme" and value in ("nuit", "aube", "auto"):
        runner.run(["ygg", "theme", str(value)], check=False)
        return {"nuit": "Thème Nuit.", "aube": "Thème Aube.", "auto": "Aube le jour, nuit le soir."}[value]
    if key == "prenom":
        from . import mimir

        profil = mimir.load_profil()
        profil["prenom"] = str(value).strip()
        mimir.save_profil(profil)
        return f"Mímir t'appellera « {profil['prenom'] or 'voyageur'} »."
    raise YggError(f"réglage inconnu : {key}")


# --------------------------------------------------------------------------
# Le pont entre Python et l'interface QML
# --------------------------------------------------------------------------

def build_backend(runner: Runner, config: dict, initial_page: str):
    from PySide6.QtCore import Property, QObject, Signal, Slot

    class Relais(QObject):
        """Ramène dans le fil principal les résultats calculés en arrière-plan."""
        fini = Signal(str, object)

    class Centre(QObject):
        changed = Signal()
        message = Signal(str)

        def __init__(self):
            super().__init__()
            self._data: dict[str, Any] = {
                "etat": {"presage": "", "majs": -1, "securite": 0, "disque": -1, "echecs": -1, "parefeu": "…"},
                "sante": [], "royaumes": [], "services": [], "modeles": [], "oracle": {}, "reglages": {},
                "resultats": [],
            }
            self._busy: set[str] = set()
            self._relais = Relais()
            self._relais.fini.connect(self._recu)

        # -- arrière-plan -------------------------------------------------
        def _en_fond(self, cle: str, fonction: Callable[[], Any]) -> None:
            if cle in self._busy:
                return
            self._busy.add(cle)
            self.changed.emit()

            def travail():
                try:
                    resultat = fonction()
                except Exception as exc:  # l'interface ne doit jamais tomber
                    resultat = exc
                self._relais.fini.emit(cle, resultat)

            threading.Thread(target=travail, daemon=True).start()

        @Slot(str, object)
        def _recu(self, cle: str, resultat: object) -> None:
            self._busy.discard(cle)
            if isinstance(resultat, Exception):
                self.message.emit(f"{cle} : {resultat}")
            else:
                self._data[cle] = resultat
            self.changed.emit()

        # -- propriétés lues par QML ---------------------------------------
        version = Property(str, lambda self: f"{__version__} « {CODENAME} »", constant=True)
        live = Property(bool, lambda self: common.is_live_session(), constant=True)
        persistante = Property(bool, lambda self: common.is_persistent_session(), constant=True)
        pageInitiale = Property(str, lambda self: initial_page, constant=True)
        etat = Property("QVariantMap", lambda self: self._data["etat"], notify=changed)
        sante = Property("QVariantList", lambda self: self._data["sante"], notify=changed)
        royaumes = Property("QVariantList", lambda self: self._data["royaumes"], notify=changed)
        services = Property("QVariantList", lambda self: self._data["services"], notify=changed)
        modeles = Property("QVariantList", lambda self: self._data["modeles"], notify=changed)
        oracle = Property("QVariantMap", lambda self: self._data["oracle"], notify=changed)
        reglages = Property("QVariantMap", lambda self: self._data["reglages"], notify=changed)
        resultats = Property("QVariantList", lambda self: self._data["resultats"], notify=changed)
        occupe = Property(bool, lambda self: bool(self._busy), notify=changed)
        recherche = Property(bool, lambda self: "resultats" in self._busy, notify=changed)
        voyageurs = Property("QVariantList", lambda self: voyageur_cards(), constant=True)

        # -- l'assistant de premier démarrage ------------------------------
        @Slot("QVariantMap", result="QVariantList")
        def apercu(self, choix):
            """Les commandes que « Planter » lancera (affichées avant, comme toujours)."""
            try:
                return plan_accueil(dict(choix), common.is_live_session())
            except YggError as exc:
                return [f"# {exc}"]

        @Slot("QVariantMap")
        def planter(self, choix):
            choix = dict(choix)
            try:
                commandes = plan_accueil(choix, common.is_live_session())
            except YggError as exc:
                self.message.emit(str(exc))
                return
            for cle, valeur in (("prenom", choix.get("prenom", "")), ("autostart", bool(choix.get("centre", True)))):
                if cle != "prenom" or str(valeur).strip():
                    try:
                        apply_setting(cle, valeur, runner)
                    except (YggError, OSError) as exc:
                        self.message.emit(str(exc))
            script = "; ".join(["echo '✦ Yggdrasil plante ton arbre : chaque étape s’affiche ici.'", *commandes])
            self.lancer(script, "Bienvenue, voyageur")
            self.passerAccueil()

        @Slot()
        def passerAccueil(self):
            drapeau = accueil_flag()
            drapeau.parent.mkdir(parents=True, exist_ok=True)
            drapeau.write_text("assistant de premier démarrage terminé\n", encoding="utf-8")

        # -- actions -------------------------------------------------------
        @Slot()
        def actualiser(self):
            self._en_fond("etat", lambda: machine_state(runner, config))
            self._en_fond("sante", lambda: health_checks(runner))
            self._en_fond("royaumes", lambda: realm_cards(runner))
            self._en_fond("services", lambda: stack_cards(common.load_config()))
            self._en_fond("modeles", template_cards)
            self._en_fond("oracle", lambda: oracle_state(runner, config))
            self._en_fond("reglages", lambda: user_settings(runner, common.load_config()))

        @Slot(str, str)
        def lancer(self, commande: str, titre: str):
            try:
                launch_in_terminal(commande, titre or "Yggdrasil")
            except (YggError, OSError) as exc:
                self.message.emit(str(exc))

        @Slot()
        def installerSysteme(self):
            cmd = installer_command()
            if not cmd:
                self.message.emit("L'installateur n'est disponible que depuis la session live.")
                return
            subprocess.Popen([cmd], start_new_session=True)

        @Slot()
        def ouvrirGuide(self):
            open_uri(DOC_INDEX.as_uri() if DOC_INDEX.exists() else "https://www.debian.org/doc/")

        @Slot(str)
        def ouvrirAdresse(self, adresse: str):
            if adresse:
                open_uri(adresse)

        @Slot(str)
        def chercher(self, texte: str):
            self._busy.discard("resultats")
            self._en_fond("resultats", lambda: search_software(runner, texte))

        @Slot(str, str, str, str)
        def forger(self, modele: str, nom: str, variante: str, modules: str):
            nom = nom.strip()
            if not nom:
                self.message.emit("Donne d'abord un nom à ton projet.")
                return
            cmd = ["brokkr", "new", modele, nom]
            if variante:
                cmd += ["--variante", variante]
            if modules is not None and modele == "discord-bot":
                cmd += ["--modules", modules]
            self.lancer(shlex.join(cmd), "Brokkr")

        @Slot(str, "QVariant")
        def regler(self, cle: str, valeur):
            try:
                self.message.emit(apply_setting(cle, valeur, runner))
            except (YggError, OSError) as exc:
                self.message.emit(str(exc))
            self._en_fond("reglages", lambda: user_settings(runner, common.load_config()))
            self._en_fond("oracle", lambda: oracle_state(runner, config))

    return Centre()


def run_window(page: str, racine: str = "Main.qml") -> int:
    import os

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Hliðskjálf")
    app.setApplicationDisplayName("Centre Yggdrasil")
    app.setDesktopFileName("yggdrasil-welcome")
    app.setWindowIcon(QIcon.fromTheme("yggdrasil"))
    centre = build_backend(Runner(), common.load_config(), page)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("ygg", centre)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / racine)))
    if not engine.rootObjects():
        print("Le Centre n'a pas pu s'afficher (QML).", file=sys.stderr)
        return 1
    centre.actualiser()
    return app.exec()


def run_tray() -> int:
    """L'icône de la barre système : état global et menu rapide (G20)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    runner = Runner()
    tray = QSystemTrayIcon(QIcon.fromTheme("yggdrasil"))
    menu = QMenu()

    def ajouter(texte: str, action: Callable[[], None]) -> None:
        act = QAction(texte, menu)
        act.triggered.connect(action)
        menu.addAction(act)

    ajouter("Ouvrir le Centre", lambda: subprocess.Popen(["yggdrasil-welcome"], start_new_session=True))
    ajouter("Mettre à jour", lambda: launch_in_terminal("ygg update", "Mises à jour"))
    ajouter("Diagnostic", lambda: launch_in_terminal("ygg doctor", "Diagnostic"))
    ajouter("Consulter Mímir", lambda: launch_in_terminal("mimir chat", "Mímir"))
    menu.addSeparator()
    ajouter("Cacher cette icône", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: subprocess.Popen(["yggdrasil-welcome"], start_new_session=True)
                           if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def rafraichir() -> None:
        state = machine_state(runner, common.load_config())
        alerte = state["echecs"] > 0 or state["securite"] > 0 or state["parefeu"] == "désactivé" \
            or state["disque"] >= 90
        tray.setIcon(QIcon.fromTheme("yggdrasil-alerte" if alerte else "yggdrasil"))
        tray.setToolTip("Yggdrasil — " + state["presage"])

    rafraichir()
    timer = QTimer()
    timer.timeout.connect(rafraichir)
    timer.start(30 * 60 * 1000)
    tray.show()
    return app.exec()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="yggdrasil-welcome", description="Hliðskjálf, le Centre d'Yggdrasil.")
    parser.add_argument("--autostart", action="store_true", help="mode démarrage de session")
    parser.add_argument("--page", default="trone", help="page à ouvrir : " + ", ".join(PAGES))
    parser.add_argument("--plateau", action="store_true", help="icône dans la barre système")
    parser.add_argument("--accueil", action="store_true", help="assistant de premier démarrage")
    args = parser.parse_args(argv)
    page = ALIAS.get(args.page, args.page)
    if page not in PAGES:
        parser.error(f"page inconnue « {args.page} »")
    live = common.is_live_session()
    accueil = args.accueil or (args.autostart and not live and not accueil_flag().exists())
    if args.autostart and not accueil and welcome_flag().exists() and not live:
        return 0
    try:
        if args.plateau:
            return run_tray()
        return run_window(page, racine="Accueil.qml" if accueil else "Main.qml")
    except ImportError as exc:
        print(f"Interface graphique indisponible ({exc}). Utilise « ygg --help ».", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
