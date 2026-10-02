"""Huginn, Muninn et Gleipnir."""

import json

from yggdrasil import corbeaux, gleipnir

STAT_1 = "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0 0 0\n"
STAT_2 = "cpu  200 0 150 850 0 0 0 0 0 0\n"
NET = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 9999 10 0 0 0 0 0 0 9999 10 0 0 0 0 0 0
 wlan0: 1000 10 0 0 0 0 0 0 500 5 0 0 0 0 0 0
docker0: 777 1 0 0 0 0 0 0 777 1 0 0 0 0 0 0
"""


def test_cpu_and_network_counters():
    assert corbeaux.lire_cpu(STAT_1) == (200, 1000)
    assert corbeaux.pourcent(corbeaux.lire_cpu(STAT_1), corbeaux.lire_cpu(STAT_2)) == 75.0
    assert corbeaux.pourcent((5, 10), (5, 10)) == 0.0
    assert corbeaux.lire_reseau(NET) == (1000, 500)


def test_huginn_reading(tmp_path, fake_runner, monkeypatch):
    (tmp_path / "net").mkdir()
    (tmp_path / "stat").write_text(STAT_1)
    (tmp_path / "net" / "dev").write_text(NET)
    (tmp_path / "meminfo").write_text("MemTotal: 8000000 kB\nMemAvailable: 2000000 kB\n")
    (tmp_path / "uptime").write_text("3600.0 100.0\n")
    (tmp_path / "loadavg").write_text("0.50 0.40 0.30 1/200 999\n")
    monkeypatch.setattr(corbeaux.common, "which", lambda cmd: None)
    runner = fake_runner({"systemctl --failed": (0, "nginx.service loaded failed failed X\n"),
                          "ps": (0, " 42.0  3.1 firefox\n 10.5  1.0 kwin_wayland\n")})
    r = corbeaux.releve(runner, tmp_path, intervalle=0.01)
    assert r["charge"] == [0.5, 0.4, 0.3] and r["echecs"] == ["nginx.service"]
    assert r["processus"][0] == ["42.0", "3.1", "firefox"]
    texte = corbeaux.afficher(r)
    assert "75.0 %" in texte and "nginx.service" in texte and "firefox 42.0 %" in texte
    assert "1.9 Go disponibles" in texte
    json.dumps(r)  # le relevé voyage en JSON (huginn moi@serveur)


def test_muninn_remembers_changes():
    hier = {"noyau": "6.12.38+deb13-amd64", "paquets": {"vim": "9.1", "curl": "8.0", "nano": "8.4"},
            "flatpaks": {"org.gimp.GIMP": "3.0"}, "services": ["ssh.service"], "ports": ["22/tcp"],
            "disque_utilise": 10 * 1024 ** 3}
    aujourdhui = {"noyau": "6.12.41+deb13-amd64", "paquets": {"vim": "9.1", "curl": "8.1", "steam": "1"},
                  "flatpaks": {"org.kde.krita": "5.2"}, "services": ["ssh.service", "docker.service"],
                  "ports": ["22/tcp", "25565/tcp"], "disque_utilise": 13 * 1024 ** 3}
    lignes = corbeaux.differences(hier, aujourdhui)
    assert "1 paquet(s) installé(s) : steam" in lignes
    assert "1 paquet(s) retiré(s) : nano" in lignes
    assert "1 paquet(s) mis à jour : curl" in lignes
    assert "application Flatpak installée : org.kde.krita" in lignes
    assert "application Flatpak retirée : org.gimp.GIMP" in lignes
    assert "nouveau noyau : 6.12.38+deb13-amd64 → 6.12.41+deb13-amd64" in lignes
    assert "service activé au démarrage : docker.service" in lignes
    assert "port ouvert à l'écoute : 25565/tcp" in lignes
    assert "disque : +3.0 Go" in lignes
    assert corbeaux.differences(hier, hier) == []
    beaucoup = corbeaux.differences({"paquets": {}}, {"paquets": {f"p{i:02}": "1" for i in range(20)}})
    assert beaucoup == ["20 paquet(s) installé(s) : p00, p01, p02, p03, p04, p05, p06, p07 et 12 autres"]


def test_muninn_keeps_daily_memories(fake_runner, monkeypatch):
    monkeypatch.setattr(corbeaux, "souvenir", lambda runner: {"paquets": {"vim": "1"}})
    chemin = corbeaux.noter(fake_runner())
    assert chemin.exists() and corbeaux.souvenirs() == [chemin]
    for i in range(5):
        (corbeaux.dossier() / f"2026-01-0{i + 1}.json").write_text("{}")
    corbeaux.noter(fake_runner(), garder=3)
    assert len(corbeaux.souvenirs()) == 3


PASSWD = "astrid:x:1000:1000:Astrid:/home/astrid:/bin/bash\nleif:x:1001:1001:Leif:/home/leif:/bin/bash\n"
GROUP = "sudo:x:27:astrid\ndocker:x:990:leif\nadm:x:4:syslog,astrid\n"


def test_gleipnir_accounts():
    s = gleipnir.section_comptes(PASSWD, GROUP)
    par_sujet = {c.sujet: c for c in s.constats}
    assert "sudo" in par_sujet["astrid"].detail and "adm" in par_sujet["astrid"].detail
    assert par_sujet["leif"].risque and "administrateur" in par_sujet["leif"].detail
    assert par_sujet["groupe adm"].detail == "comptes de service : syslog"


def test_gleipnir_ssh_and_flatpak_parsers(tmp_path):
    reglages = gleipnir.parse_sshd_effectif("port 22\npasswordauthentication no\npermitrootlogin no\n")
    assert reglages["passwordauthentication"] == "no"
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "authorized_keys").write_text(
        "# commentaire\nssh-ed25519 AAAAC3Nza astrid@portable\n"
        'from="192.168.1.0/24" ssh-rsa AAAAB3Nza\n')
    assert gleipnir.cles_ssh(tmp_path) == ["ssh-ed25519 astrid@portable", "ssh-rsa (sans commentaire)"]
    perms = "[Context]\nshared=network;ipc;\nsockets=x11;wayland;\ndevices=all;\nfilesystems=host;\n"
    assert gleipnir.permissions_risquees(perms) == ["tous les périphériques (webcam, micro…)", "tous tes fichiers"]
    assert gleipnir.permissions_risquees("filesystems=xdg-download;\n") == []
