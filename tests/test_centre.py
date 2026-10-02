"""Hliðskjálf, le Centre : fonctions pures, réglages, assistant « Bienvenue, voyageur »."""

import pytest

from yggdrasil import common, welcome
from yggdrasil.common import YggError


def test_terminal_command_keeps_the_window_open(monkeypatch):
    monkeypatch.setattr(welcome.common, "which", lambda cmd: "/usr/bin/konsole" if cmd == "konsole" else None)
    cmd = welcome.terminal_command("ygg update", "Mises à jour")
    assert cmd[:2] == ["konsole", "--hide-menubar"]
    assert cmd[-3:-1] == ["bash", "-lc"] and cmd[-1].startswith("ygg update; echo; read")
    monkeypatch.setattr(welcome.common, "which", lambda cmd: None)
    with pytest.raises(YggError):
        welcome.terminal_command("true")


def test_software_search_parsers():
    apt = welcome.parse_apt_search("vlc - lecteur multimédia\nvlc-bin - binaires\n\nbizarre sans tiret\n")
    assert [x["id"] for x in apt] == ["vlc", "vlc-bin"] and apt[0]["source"] == "Debian"
    flat = welcome.parse_flatpak_search("org.videolan.VLC\tVLC\tLecteur\nNo matches found\nNom Avec Espace\tx\n")
    assert flat == [{"source": "Flathub", "id": "org.videolan.VLC", "nom": "VLC", "description": "Lecteur"}]


def test_settings_are_personal_and_reversible(fake_runner):
    runner = fake_runner()
    assert "sobrement" in welcome.apply_setting("ton", "sobre", runner)
    assert common.load_config()["general"]["ton"] == "sobre"
    welcome.apply_setting("presage", False, runner)
    assert welcome.presage_off_flag().exists()
    welcome.apply_setting("presage", True, runner)
    assert not welcome.presage_off_flag().exists()
    welcome.apply_setting("autostart", False, runner)
    assert welcome.welcome_flag().exists()
    welcome.apply_setting("theme", "auto", runner)
    assert ("run", "ygg theme auto", False, None) in runner.calls
    with pytest.raises(YggError):
        welcome.apply_setting("inconnu", 1, runner)


def test_realm_cards_describe_the_nine_worlds(fake_runner, monkeypatch):
    monkeypatch.setattr(welcome.common, "which", lambda cmd: "/usr/bin/" + cmd)
    runner = fake_runner({"dpkg-query": (0, "keepassxc\tii \n"), "flatpak list": (0, "com.github.tchx84.Flatseal\n")})
    cartes = welcome.realm_cards(runner)
    assert [c["nom"] for c in cartes][:3] == ["asgard", "midgard", "nidavellir"]
    asgard = cartes[0]
    assert asgard["rune"] == "ᛉ" and asgard["runeNom"] == "Algiz" and asgard["etat"] == "partiel"
    assert "\n" not in asgard["description"]
    installes = {x["id"] for x in asgard["logiciels"] if x["installe"]}
    assert installes == {"keepassxc", "flatseal"}
    assert any(not x["defaut"] for x in asgard["logiciels"])
    assert {v["id"] for v in welcome.voyageur_cards()} == {"joueur", "createur", "developpeur", "gardien"}


def test_welcome_plan():
    plan = welcome.plan_accueil({
        "royaumes": {"muspelheim": ["steam", "prism", "inexistant"], "alfheim": []},
        "theme": "auto", "instantanes": True, "ratatoskr": False, "arbre": True,
    })
    assert plan == [
        "ygg realm add muspelheim --seulement steam,prism -y",
        "ygg theme auto",
        "norns setup -y",
        "ratatoskr disable",
        "ygg realm arbre oui",
    ]
    # En session live, pas d'instantanés (rien n'est conservé)
    assert "norns setup -y" not in welcome.plan_accueil({"instantanes": True}, live=True)
    with pytest.raises(YggError):
        welcome.plan_accueil({"royaumes": {"muspelheim": ["; rm -rf /"]}})
    with pytest.raises(YggError):
        welcome.plan_accueil({"royaumes": {"valhalla": ["steam"]}})


@pytest.mark.parametrize("live, accueil_fait, centre_masque, attendu", [
    (False, False, False, "Accueil.qml"),   # première session d'un système installé
    (False, False, True, "Accueil.qml"),
    (False, True, False, "Main.qml"),
    (False, True, True, None),              # le Centre a été masqué au démarrage
    (True, False, False, "Main.qml"),       # session live : le Centre (bouton Installer)
    (True, False, True, "Main.qml"),
])
def test_autostart_opens_the_wizard_once(monkeypatch, live, accueil_fait, centre_masque, attendu):
    monkeypatch.setattr(welcome.common, "is_live_session", lambda *a: live)
    if accueil_fait:
        welcome.accueil_flag().parent.mkdir(parents=True, exist_ok=True)
        welcome.accueil_flag().write_text("x")
    if centre_masque:
        welcome.welcome_flag().parent.mkdir(parents=True, exist_ok=True)
        welcome.welcome_flag().write_text("x")
    ouvert = []
    monkeypatch.setattr(welcome, "run_window", lambda page, racine="Main.qml": ouvert.append(racine) or 0)
    assert welcome.main(["--autostart"]) == 0
    assert ouvert == ([attendu] if attendu else [])
    ouvert.clear()
    welcome.main(["--accueil"])
    assert ouvert == ["Accueil.qml"]
