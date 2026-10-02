"""Ratatoskr : relais des gardiens, ne pas déranger, boutons, téléphone (ntfy), bilan."""

import urllib.parse
from types import SimpleNamespace

import pytest

from yggdrasil import common, ratatoskr


def args(**kw):
    return SimpleNamespace(**{"attendre": False, "print": False, "force": False, **kw})


def test_alert_inbox_deduplicates(tmp_path):
    common.alerter("heimdall", "critical", "SSH : 240 tentatives en 10 min depuis 203.0.113.9", cle="ssh-1")
    common.alerter("heimdall", "critical", "SSH : 240 tentatives en 10 min depuis 203.0.113.9", cle="ssh-1")
    common.alerter("norns", "normal", "dernière sauvegarde il y a 12 jours")
    alertes = common.lire_alertes(common.alertes_utilisateur())
    assert [a["source"] for a in alertes] == ["heimdall", "norns"]
    assert alertes[0]["urgence"] == "critical"
    vus = ratatoskr.nouvelles_alertes(alertes, [])
    assert vus[0] == ("critical", "Heimdall : SSH : 240 tentatives en 10 min depuis 203.0.113.9")
    assert vus[1][1].startswith("Les Nornes : ")
    assert ratatoskr.nouvelles_alertes(alertes, [ratatoskr.cle_alerte(a) for a in alertes]) == []


@pytest.mark.parametrize("reponses, attendu", [
    ({"gdbus": (0, "(<true>,)\n")}, "ne pas déranger"),
    ({"gamemoded -s": (0, "gamemode is active\n")}, "GameMode"),
    ({"pgrep -x obs": (0, "4242\n")}, "OBS"),
    ({"gdbus": (0, "(<false>,)\n"), "gamemoded -s": (0, "gamemode is inactive\n")}, ""),
])
def test_do_not_disturb(fake_runner, reponses, attendu):
    pourquoi = ratatoskr.derangement(fake_runner(reponses))
    assert (attendu in pourquoi) if attendu else pourquoi == ""


def test_ntfy_request_keeps_accents():
    req = ratatoskr.requete_ntfy("https://ntfy.example/ygg-abc", "Psst ! Ratatoskr", "2 mises à jour", True)
    url = urllib.parse.urlparse(req.full_url)
    params = urllib.parse.parse_qs(url.query)
    assert url.path == "/ygg-abc" and params["title"] == ["Psst ! Ratatoskr"] and params["priority"] == ["urgent"]
    assert req.data == "2 mises à jour".encode() and req.get_method() == "POST"


@pytest.fixture
def machine(fake_runner, monkeypatch):
    """Une machine installée, une mise à jour en attente, notify-send présent."""
    monkeypatch.setattr(ratatoskr.common, "which", lambda cmd: "/usr/bin/" + cmd)
    monkeypatch.setattr(ratatoskr.common, "is_live_session", lambda *a: False)
    monkeypatch.setattr(ratatoskr, "bilan", lambda runner, config: ["système à jour"])
    monkeypatch.setattr(ratatoskr.doctor.Doctor, "check_disk", lambda self: [])
    monkeypatch.setattr(ratatoskr.doctor.Doctor, "check_failed_units", lambda self: [])
    monkeypatch.setattr(ratatoskr.doctor.Doctor, "check_dpkg", lambda self: [])
    monkeypatch.setattr(ratatoskr.doctor.Doctor, "check_reboot", lambda self: [])

    def fabrique(reponses=None, bouton=""):
        runner = fake_runner({"apt list": (0, "Listing...\nvim/stable 2 amd64 [upgradable from: 1]\n"),
                              **(reponses or {})})
        envoi = runner.run

        def run(cmd, **kw):
            proc = envoi(cmd, **kw)
            if cmd[0] == "notify-send" and "--wait" in cmd:
                proc.stdout = bouton + "\n"
            return proc
        runner.run = run
        return runner
    return fabrique


def notifications(runner):
    return [c for c in runner.calls if c[0] == "run" and c[1].startswith("notify-send")]


def test_check_sends_a_notification_with_buttons_then_stays_quiet(machine, monkeypatch):
    agis = []
    monkeypatch.setattr(ratatoskr, "agir", agis.append)
    runner = machine(bouton="maj")
    assert ratatoskr.cmd_check(args(), runner, {}) == 0
    notifs = notifications(runner)
    assert len(notifs) == 2  # le bilan (une seule fois), puis les nouvelles
    assert "--action=maj=Mettre à jour" in notifs[1][1] and "--action=mimir=Demander à Mímir" in notifs[1][1]
    assert agis == ["maj"]
    runner = machine()
    ratatoskr.cmd_check(args(), runner, {})
    assert notifications(runner) == []  # rien de neuf : pas de nouvelle notification


def test_check_waits_during_a_game_but_still_tells_the_phone(machine, monkeypatch):
    envois = []
    monkeypatch.setattr(ratatoskr, "envoyer_telephone",
                        lambda url, titre, texte, urgent, runner: envois.append((url, texte)) or True)
    config = {"ratatoskr": {"telephone": "https://ntfy.sh/ygg-123"}}
    runner = machine({"gamemoded -s": (0, "gamemode is active")})
    ratatoskr.cmd_check(args(), runner, config)
    assert len(envois) == 1 and "1 mise(s) à jour" in envois[0][1]
    assert len(notifications(runner)) == 1  # seul le bilan est passé, à l'installation
    # La partie finie, la notification arrive ; le téléphone, lui, sait déjà
    runner = machine()
    ratatoskr.cmd_check(args(), runner, config)
    assert len(notifications(runner)) == 1 and len(envois) == 1


def test_relayed_alerts_arrive_once(machine):
    common.alerter("bifrost", "critical", "le serveur minecraft s'est arrêté (code 137)")
    runner = machine()
    ratatoskr.cmd_check(args(), runner, {})
    assert "Bifröst : le serveur minecraft" in notifications(runner)[-1][1]
    common.alerter("heimdall", "normal", "nouvel appareil sur le réseau : 192.168.1.42")
    runner = machine()
    ratatoskr.cmd_check(args(), runner, {})
    texte = notifications(runner)[-1][1]
    assert "Heimdall : nouvel appareil" in texte and "minecraft" not in texte


def test_phone_setup(fake_runner, monkeypatch, capsys):
    monkeypatch.setattr(ratatoskr.common, "which", lambda cmd: None)
    assert ratatoskr.cmd_telephone(SimpleNamespace(cible="ntfy"), fake_runner(), {}) == 0
    url = common.load_config()["ratatoskr"]["telephone"]
    assert url.startswith("https://ntfy.sh/ygg-") and len(url.rsplit("-", 1)[1]) == 16
    ratatoskr.cmd_telephone(SimpleNamespace(cible="non"), fake_runner(), {})
    assert common.load_config()["ratatoskr"]["telephone"] == ""
    with pytest.raises(common.YggError):
        ratatoskr.cmd_telephone(SimpleNamespace(cible="ftp://x"), fake_runner(), {})
