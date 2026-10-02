"""Le gestionnaire système : matériel, partage, accès à distance, entretien, tâches, comptes."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from yggdrasil import comptes, common, entretien, materiel, menu, partage, taches, ygg
from yggdrasil.common import YggError

# --------------------------------------------------------------------------
# Matériel
# --------------------------------------------------------------------------


def test_lsblk_keeps_physical_disks_only():
    sortie = json.dumps({"blockdevices": [
        {"name": "nvme0n1", "size": "476,9G", "model": "Samsung SSD 980 ", "rota": False, "tran": "nvme",
         "type": "disk"},
        {"name": "sda", "size": "1,8T", "model": "WDC WD20EZRZ", "rota": True, "tran": "sata", "type": "disk"},
        {"name": "loop0", "size": "4K", "model": None, "rota": False, "tran": None, "type": "loop"},
        {"name": "zram0", "size": "4G", "model": None, "rota": False, "tran": None, "type": "disk"},
        {"name": "sr0", "size": "1024M", "model": "QEMU DVD", "rota": True, "tran": "ata", "type": "rom"},
    ]})
    disques = materiel.parse_lsblk(sortie)
    assert [d.nom for d in disques] == ["nvme0n1", "sda"]
    assert disques[0].modele == "Samsung SSD 980" and not disques[0].rotatif
    assert disques[1].rotatif and disques[1].transport == "sata"
    assert materiel.parse_lsblk("pas du json") == []


def test_smart_health():
    assert materiel.parse_smart_health("SMART overall-health self-assessment test result: PASSED") == "bonne"
    assert materiel.parse_smart_health("SMART overall-health self-assessment test result: FAILED!") == "DÉFAILLANTE"
    assert materiel.parse_smart_health("SMART Health Status: OK") == "bonne"
    assert materiel.parse_smart_health("Unable to detect device type") == ""


def test_sensors_takes_the_hottest_of_each_chip():
    sortie = json.dumps({
        "coretemp-isa-0000": {"Adapter": "ISA adapter",
                              "Package id 0": {"temp1_input": 61.0, "temp1_max": 100.0},
                              "Core 0": {"temp2_input": 58.0}},
        "nvme-pci-0100": {"Composite": {"temp1_input": 44.85}},
        "acpitz-acpi-0": {"temp1": {}},
    })
    assert materiel.parse_sensors(sortie) == [("coretemp", 61.0), ("nvme", 44.85)]


def test_batteries_from_sysfs(tmp_path):
    bat = tmp_path / "BAT0"
    bat.mkdir()
    for nom, valeur in {"capacity": "83", "status": "Discharging", "energy_full": "40000000",
                        "energy_full_design": "50000000"}.items():
        (bat / nom).write_text(valeur + "\n")
    (tmp_path / "AC").mkdir()
    [b] = materiel.batteries(tmp_path)
    assert (b.nom, b.charge, b.etat, b.usure) == ("BAT0", 83, "sur batterie", 80)


LSPCI = """\
00:02.0 VGA compatible controller [0300]: Intel Corporation Alder Lake-P GT2 [Iris Xe Graphics] [8086:46a6] (rev 0c)
01:00.0 3D controller [0302]: NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile] [10de:25a2] (rev a1)
02:00.0 Network controller [0280]: Intel Corporation Wi-Fi 6 AX201 [8086:a0f0] (rev 20)
"""

NOYAU = """\
iwlwifi 0000:00:14.3: Direct firmware load for iwlwifi-so-a0-gf-a0-86.ucode failed with error -2
bluetooth hci0: Direct firmware load for intel/ibt-0040-0041.sfi failed with error -2
i915 0000:00:02.0: [drm] Finished loading DMC firmware i915/adlp_dmc.bin
r8169 0000:03:00.0: firmware: failed to load rtl_nic/rtl8168h-2.fw (-2)
iwlwifi 0000:00:14.3: Direct firmware load for iwlwifi-so-a0-gf-a0-86.ucode failed with error -2
"""


def test_drivers_recommendations():
    peripheriques = materiel.parse_lspci_nn(LSPCI)
    assert [(p.vendeur, p.produit) for p in peripheriques] == [("8086", "46a6"), ("10de", "25a2"), ("8086", "a0f0")]
    manquants = materiel.parse_missing_firmware(NOYAU)
    assert manquants == ["iwlwifi-so-a0-gf-a0-86.ucode", "intel/ibt-0040-0041.sfi", "rtl_nic/rtl8168h-2.fw"]
    conseils = materiel.recommandations(peripheriques, manquants)
    paquets = [p for c in conseils for p in c.paquets]
    assert "nvidia-driver" in paquets and "intel-media-va-driver-non-free" in paquets
    assert "firmware-iwlwifi" in paquets and "firmware-realtek" in paquets
    # Le Wi-Fi et le Bluetooth Intel viennent du même paquet : un seul conseil
    assert paquets.count("firmware-iwlwifi") == 1
    nvidia = next(c for c in conseils if "nvidia-driver" in c.paquets)
    assert "non-free" in nvidia.composantes and "NVIDIA" in nvidia.raison
    assert materiel.firmware_package("inconnu/truc.bin") == "firmware-misc-nonfree"


def test_add_components_to_deb822_sources():
    sources = ("Types: deb\nURIs: http://deb.debian.org/debian/\nSuites: trixie trixie-updates\n"
               "Components: main non-free-firmware\n\nTypes: deb\nURIs: http://security.debian.org/debian-security/\n"
               "Suites: trixie-security\nComponents: main non-free-firmware\n")
    assert materiel.components_of(sources) == {"main", "non-free-firmware"}
    nouveau = materiel.add_components(sources, ["contrib", "non-free", "non-free-firmware"])
    assert nouveau.count("Components: main non-free-firmware contrib non-free\n") == 2
    assert nouveau.endswith("\n")


def test_boot_analysis_parsers():
    temps = ("Startup finished in 7.012s (firmware) + 2.153s (loader) + 1.902s (kernel) + 850ms (initrd) "
             "+ 1min 2.4s (userspace) = 1min 14.317s\ngraphical.target reached after 1min 2.3s in userspace.")
    etapes = materiel.parse_analyze_time(temps)
    assert etapes == {"firmware": 7.012, "loader": 2.153, "kernel": 1.902, "initrd": 0.85,
                      "userspace": 62.4, "total": 74.317}
    blame = "  1min 3.010s NetworkManager-wait-online.service\n 4.500s apt-daily.service\n 312ms udisks2.service\n"
    assert materiel.parse_blame(blame) == [("NetworkManager-wait-online.service", 63.01),
                                           ("apt-daily.service", 4.5), ("udisks2.service", 0.312)]


def test_kernels_to_remove_never_touches_the_running_one():
    sortie = ("linux-image-6.12.38+deb13-amd64 install ok installed\n"
              "linux-image-6.12.41+deb13-amd64 install ok installed\n"
              "linux-image-6.12.43+deb13-amd64 install ok installed\n"
              "linux-image-6.12.9+deb13-amd64 deinstall ok config-files\n"
              "linux-image-amd64 install ok installed\n")
    installes = materiel.parse_kernels(sortie)
    assert installes == ["6.12.38+deb13-amd64", "6.12.41+deb13-amd64", "6.12.43+deb13-amd64"]
    assert materiel.kernels_to_remove(installes, "6.12.43+deb13-amd64") == ["6.12.38+deb13-amd64"]
    # On a démarré sur le plus ancien : il est gardé, avec les deux plus récents
    assert materiel.kernels_to_remove(installes, "6.12.38+deb13-amd64") == []
    assert materiel.kernels_to_remove(installes, "6.12.43+deb13-amd64", garder=1) == [
        "6.12.38+deb13-amd64", "6.12.41+deb13-amd64"]


# --------------------------------------------------------------------------
# Partage et accès à distance
# --------------------------------------------------------------------------

def test_usershare_parsing_and_names(tmp_path):
    sortie = ("[Public]\npath=/home/astrid/Public\ncomment=Partagé avec Yggdrasil\nusershare_acl=Everyone:R,\n"
              "guest_ok=n\n[Photos-ete]\npath=/home/astrid/Images/Été\ncomment=\nusershare_acl=Everyone:F,\n"
              "guest_ok=y\n")
    public, photos = partage.parse_usershares(sortie)
    assert (public.nom, public.chemin, public.ecriture, public.invites) == ("Public", "/home/astrid/Public", False,
                                                                           False)
    assert photos.ecriture and photos.invites
    assert partage.nom_de_partage(tmp_path / "Photos d'été") == "Photos-d-ete"
    assert partage.nom_de_partage(tmp_path / "x", "Musique_2") == "Musique_2"
    with pytest.raises(YggError):
        partage.nom_de_partage(tmp_path / "x", "pas bien/../")
    assert partage.acl_pour(True) == "Everyone:F" and partage.acl_pour(False) == "Everyone:R"


def test_share_add_flow(tmp_path, fake_runner, monkeypatch):
    dossier = tmp_path / "Public"
    dossier.mkdir()
    runner = fake_runner({"dpkg-query": (0, "install ok installed\ninstall ok installed\n"),
                          "id -nG": (0, "astrid adm sudo"), "pdbedit": (1, "")})
    monkeypatch.setattr(common, "target_user", lambda: "astrid")
    ouverts = []
    monkeypatch.setattr(partage.heimdall, "ouvrir", lambda r, cible, source, c="": ouverts.append((cible, source)) or 5)
    args = SimpleNamespace(action="ajouter", cible=str(dossier), nom=None, ecriture=False, invites=False, yes=True)
    assert partage.cmd_partage(args, runner, {}) == 0
    runs = [c[1] for c in runner.calls if c[0] == "run"]
    assert "usermod -aG sambashare astrid" in runs
    assert "smbpasswd -a astrid" in runs
    assert f"runuser -u astrid -- net usershare add Public {dossier} Partagé avec Yggdrasil Everyone:R guest_ok=n" in runs
    assert any(r.startswith("systemctl enable --now smbd nmbd wsdd2") for r in runs)
    assert ouverts == [("samba", "lan")]


def test_ssh_config_and_key_only_safety(tmp_path, fake_runner, monkeypatch):
    assert "PasswordAuthentication no" in partage.sshd_config(True)
    assert "PasswordAuthentication" not in partage.sshd_config(False)
    assert "PermitRootLogin no" in partage.sshd_config(False)
    monkeypatch.setattr(partage, "cles_autorisees", lambda u: 0)
    args = SimpleNamespace(moyen="ssh", action="activer", cles_seulement=True, internet=False, yes=True)
    with pytest.raises(YggError, match="authorized_keys"):
        partage.cmd_distance(args, fake_runner(), {})


def test_wireguard_configs():
    serveur = partage.wg_serveur("10.66.66.0/24", 51820, "PRIVEE=")
    assert "Address = 10.66.66.1/24" in serveur and "ListenPort = 51820" in serveur
    conf = serveur + partage.wg_pair("telephone", "PUB1=", "10.66.66.2") + partage.wg_pair("portable", "PUB2=",
                                                                                           "10.66.66.3")
    infos = partage.wg_infos(conf)
    assert infos["adresse"] == "10.66.66.1/24" and infos["port"] == 51820
    assert infos["clients"] == [("telephone", "10.66.66.2"), ("portable", "10.66.66.3")]
    assert partage.wg_ip_libre(conf) == "10.66.66.4"
    client = partage.wg_client("CPRIV=", "10.66.66.4", "SPUB=", "maison.example.org", 51820, "10.66.66.1")
    assert "Endpoint = maison.example.org:51820" in client
    assert "AllowedIPs = 10.66.66.1/32" in client and "Address = 10.66.66.4/32" in client
    with pytest.raises(YggError):
        partage.wg_ip_libre("[Interface]\n")


def test_heimdall_open_and_close_for_other_tools(fake_runner, monkeypatch):
    from yggdrasil import heimdall

    cfg = heimdall.Config(enabled=False)
    monkeypatch.setattr(heimdall, "load_config", lambda: cfg)
    monkeypatch.setattr(heimdall, "save_config", lambda c, r: None)
    runner = fake_runner()
    assert heimdall.ouvrir(runner, "samba", "lan") == 5
    assert heimdall.ouvrir(runner, "samba", "lan") == 0
    assert {r.ports for r in cfg.rules} >= {"445", "3702", "5357"}
    assert heimdall.ouvrir(runner, "1-65535/both", "10.66.66.0/24") == 1
    assert heimdall.fermer(runner, "samba") == 5
    assert [r.source for r in cfg.rules] == ["10.66.66.0/24"]


# --------------------------------------------------------------------------
# Entretien
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cmd, attendu", [
    (["apt-get", "install", "-y", "vlc", "gimp"], ["apt-get", "remove", "-y", "vlc", "gimp"]),
    (["apt-get", "purge", "steam"], ["apt-get", "install", "-y", "steam"]),
    (["flatpak", "install", "--system", "-y", "flathub", "org.gimp.GIMP"],
     ["flatpak", "uninstall", "--system", "-y", "org.gimp.GIMP"]),
    (["flatpak", "uninstall", "--user", "com.spotify.Client"],
     ["flatpak", "install", "--user", "-y", "flathub", "com.spotify.Client"]),
    (["systemctl", "enable", "--now", "ssh"], ["systemctl", "--now", "disable", "ssh"]),
    (["systemctl", "--user", "disable", "--now", "ratatoskr.timer"],
     ["systemctl", "--user", "--now", "enable", "ratatoskr.timer"]),
    (["runuser", "-u", "astrid", "--", "net", "usershare", "add", "Public", "/home/astrid/Public", "x", "Everyone:R"],
     ["runuser", "-u", "astrid", "--", "net", "usershare", "delete", "Public"]),
    (["apt-get", "update"], None),
    (["flatpak", "uninstall", "--system", "--unused", "-y"], None),
    (["timeshift", "--create"], None),
    (["systemctl", "daemon-reload"], None),
])
def test_inverse(cmd, attendu):
    assert entretien.inverse(cmd) == attendu


def test_reversibles_skip_failures_and_undone_actions():
    entrees = [
        {"date": "2026-10-01T10:00:00", "commande": ["apt-get", "install", "-y", "vlc"], "code": 0, "admin": True},
        {"date": "2026-10-01T10:05:00", "commande": ["apt-get", "install", "-y", "gimp"], "code": 0, "admin": True},
        {"date": "2026-10-01T10:06:00", "commande": ["apt-get", "remove", "-y", "gimp"], "code": 0, "admin": True,
         "annule": "2026-10-01T10:05:00"},
        {"date": "2026-10-01T10:07:00", "commande": ["apt-get", "install", "-y", "krita"], "code": 100},
        {"date": "2026-10-01T10:08:00", "commande": ["apt-get", "update"], "code": 0},
    ]
    [(entree, inv)] = entretien.reversibles(entrees)
    assert entree["date"] == "2026-10-01T10:00:00" and inv == ["apt-get", "remove", "-y", "vlc"]


def test_undo_runs_the_inverse_and_marks_the_saga(fake_runner, capsys):
    common.saga_path().parent.mkdir(parents=True, exist_ok=True)
    common.saga_path().write_text(json.dumps({"date": "2026-10-01T10:00:00", "outil": "ygg",
                                              "commande": ["apt-get", "install", "-y", "vlc"],
                                              "admin": True, "code": 0}) + "\n", encoding="utf-8")
    runner = fake_runner()
    vus = []
    runner.run = lambda cmd, root=False, **kw: vus.append((cmd, root, dict(common.SAGA_CONTEXTE)))
    assert entretien.cmd_annuler(SimpleNamespace(liste=False, yes=True), runner, {}) == 0
    assert vus == [(["apt-get", "remove", "-y", "vlc"], True, {"annule": "2026-10-01T10:00:00"})]
    assert common.SAGA_CONTEXTE == {}
    # La saga note l'annulation avec la date de l'action défaite
    common.SAGA_CONTEXTE["annule"] = "2026-10-01T10:00:00"
    try:
        common.saga_note(["apt-get", "remove", "-y", "vlc"], 0, root=True)
    finally:
        common.SAGA_CONTEXTE.clear()
    assert entretien.reversibles(common.saga_read()) == []


def test_anonymiser():
    texte = ("astrid@yggdrasil-pc:~$ ping 192.168.1.20 depuis /home/astrid (fe80::1a2b:3c4d:5e6f:7a8b)\n"
             "eth0 aa:bb:cc:dd:ee:ff  UUID=0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0  astrid.dupont@exemple.fr\n"
             "localhost 127.0.0.1 ; astridine reste ; yggdrasil-pc-2 aussi")
    propre = entretien.anonymiser(texte, "astrid", "yggdrasil-pc")
    for secret in ("192.168.1.20", "aa:bb:cc", "0b1c2d3e", "exemple.fr", "/home/astrid ", "fe80::1a2b"):
        assert secret not in propre
    assert "[utilisateur]@[machine]" in propre and "/home/[utilisateur]" in propre
    assert "127.0.0.1" in propre and "astridine" in propre and "yggdrasil-pc-2" in propre


def test_mirror_sources_rewrite():
    sources = ("Types: deb\nURIs: http://deb.debian.org/debian/\nSuites: trixie\nComponents: main\n\n"
               "Types: deb\nURIs: http://security.debian.org/debian-security/\nSuites: trixie-security\n")
    assert entretien.miroir_actuel(sources) == "http://deb.debian.org/debian/"
    nouveau = entretien.rewrite_sources(sources, "http://ftp.fr.debian.org/debian/")
    assert "URIs: http://ftp.fr.debian.org/debian/" in nouveau
    assert "URIs: http://security.debian.org/debian-security/" in nouveau


def test_dpkg_interrupted(tmp_path):
    assert not entretien.dpkg_interrompu(tmp_path)
    (tmp_path / "0001").write_text("x")
    assert entretien.dpkg_interrompu(tmp_path)
    assert not entretien.dpkg_interrompu(tmp_path / "absent")


def test_journal_usage_and_big_caches(tmp_path):
    assert ygg.parse_journal_usage("Archived and active journals take up 1.5G in the file system.") == 1610612736
    assert ygg.parse_journal_usage("Archived and active journals take up 56.0M in the file system.") == 58720256
    assert ygg.parse_journal_usage("rien") == 0
    (tmp_path / "gros").mkdir()
    (tmp_path / "gros" / "f").write_bytes(b"x" * 3000)
    (tmp_path / "petit").mkdir()
    (tmp_path / "thumbnails").mkdir()
    (tmp_path / "thumbnails" / "f").write_bytes(b"x" * 9000)
    assert ygg.gros_caches(tmp_path, seuil=2000) == [("gros", 3000)]


# --------------------------------------------------------------------------
# Tâches et thème
# --------------------------------------------------------------------------

def test_task_units():
    service, timer = taches.unites("sauvegarde", "norns backup --to '/media/disque dur'", "21:00")
    assert "ExecStart=/bin/bash -lc 'norns backup --to '\"'\"'/media/disque dur'\"'\"''" in service
    assert taches.commande_de(service) == "norns backup --to '/media/disque dur'"
    assert "OnCalendar=*-*-* 21:00:00" in timer and "Persistent=true" in timer
    assert taches.quand_de(timer) == "chaque jour à 21:00"
    assert taches.declencheur("hebdomadaire") == "OnCalendar=weekly"
    assert taches.declencheur("au-demarrage") == "OnStartupSec=2min"
    assert taches.declencheur("Mon *-*-* 08:00") == "OnCalendar=Mon *-*-* 08:00"
    for mauvais in ("Bad Name", ""):
        with pytest.raises(YggError):
            taches.unites(mauvais, "true", "quotidien")
    with pytest.raises(YggError):
        taches.unites("x", "a\nb", "quotidien")
    with pytest.raises(YggError):
        taches.declencheur("daily\nExecStart=/bin/evil")


def test_task_add_and_remove(tmp_path, fake_runner):
    runner = fake_runner({"systemd-analyze calendar": (0, "")})
    runner.write_file = common.Runner.write_file.__get__(runner)
    args = SimpleNamespace(action="ajouter", nom="menage", commande="ygg nettoyer -y", quand="hebdomadaire")
    assert taches.cmd_taches(args, runner, {}) == 0
    assert taches.taches() == ["menage"]
    assert ("run", "systemctl --user enable --now ygg-tache-menage.timer", False, None) in runner.calls
    args = SimpleNamespace(action="retirer", nom="menage", commande=None, quand=None)
    assert taches.cmd_taches(args, runner, {}) == 0
    assert taches.taches() == []


@pytest.mark.parametrize("heure, attendu", [
    ("06:59", "Yggdrasil"), ("07:30", "YggdrasilAube"), ("13:00", "YggdrasilAube"), ("19:59", "YggdrasilAube"),
    ("20:00", "Yggdrasil"), ("23:30", "Yggdrasil"),
])
def test_theme_auto(heure, attendu):
    h, m = map(int, heure.split(":"))
    assert taches.schema_pour("auto", dt.time(h, m), "07:30", "20:00") == attendu
    assert taches.schema_pour("nuit", dt.time(h, m)) == "Yggdrasil"
    assert taches.schema_pour("aube", dt.time(h, m)) == "YggdrasilAube"


def test_theme_auto_overnight_day():
    # Un « jour » qui passe minuit (travail de nuit) : aube à 22:00, nuit à 06:00
    assert taches.schema_pour("auto", dt.time(23, 0), "22:00", "06:00") == "YggdrasilAube"
    assert taches.schema_pour("auto", dt.time(12, 0), "22:00", "06:00") == "Yggdrasil"


def test_theme_command_saves_mode(fake_runner):
    runner = fake_runner({"kreadconfig6": (0, "Yggdrasil\n")})
    args = SimpleNamespace(mode="auto", aube="08:00", nuit="19:00", appliquer=False)
    assert taches.cmd_theme(args, runner, {}) == 0
    assert common.load_config()["theme"] == {"mode": "auto", "aube": "08:00", "nuit": "19:00"}
    assert ("run", "systemctl --user enable --now yggdrasil-theme.timer", False, None) in runner.calls
    with pytest.raises(YggError):
        taches.cmd_theme(SimpleNamespace(mode="rose", aube=None, nuit=None, appliquer=False), runner, {})


# --------------------------------------------------------------------------
# Comptes et menu
# --------------------------------------------------------------------------

PASSWD = """root:x:0:0:root:/root:/bin/bash
sddm:x:110:118:Simple Desktop Display Manager:/var/lib/sddm:/bin/false
astrid:x:1000:1000:Astrid Dupont,,,:/home/astrid:/bin/bash
leif:x:1001:1001:Leif:/home/leif:/bin/bash
ancien:x:1002:1002::/home/ancien:/usr/sbin/nologin
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
"""
GROUP = "sudo:x:27:astrid\naudio:x:29:astrid,leif\nsambashare:x:121:\n"


def test_accounts_parsing():
    comptes_ = comptes.parse_passwd(PASSWD, comptes.parse_group(GROUP))
    assert [(c.nom, c.nom_complet, c.admin) for c in comptes_] == [("astrid", "Astrid Dupont", True),
                                                                   ("leif", "Leif", False)]
    assert comptes_[1].groupes == ["audio"]


def test_accounts_protect_the_last_admin(fake_runner, monkeypatch):
    monkeypatch.setattr(comptes, "charger", lambda: (comptes.parse_passwd(PASSWD, comptes.parse_group(GROUP)),
                                                     comptes.parse_group(GROUP)))
    monkeypatch.setattr(common, "target_user", lambda: "leif")
    base = dict(valeur=None, admin=False, nom_complet=None, supprimer_fichiers=False, yes=True)
    with pytest.raises(YggError, match="dernier administrateur"):
        comptes.cmd_comptes(SimpleNamespace(action="admin", nom="astrid", **{**base, "valeur": "non"}),
                            fake_runner(), {})
    with pytest.raises(YggError, match="propre compte"):
        comptes.cmd_comptes(SimpleNamespace(action="retirer", nom="leif", **base), fake_runner(), {})
    with pytest.raises(YggError, match="invalide"):
        comptes.cmd_comptes(SimpleNamespace(action="ajouter", nom="Pas Bien", **base), fake_runner(), {})
    runner = fake_runner()
    assert comptes.cmd_comptes(SimpleNamespace(action="ajouter", nom="sigrid", **{**base, "admin": True}),
                               runner, {}) == 0
    runs = [c[1] for c in runner.calls if c[0] == "run"]
    assert runs[0] == "adduser sigrid" and "adduser --quiet sigrid audio" in runs
    assert runs[-1] == "adduser --quiet sigrid sudo"


def test_menu_loop(capsys):
    lances = []
    reponses = iter(["2", "", "7", "firefox", "", "99", "0"])
    assert menu.boucle(lambda argv: lances.append(argv) or 0, lambda invite: next(reponses)) == 0
    assert lances == [["doctor"], ["search", "firefox"]]
    assert "choisis un nombre" in capsys.readouterr().err


def test_every_menu_entry_is_a_real_command():
    parser = ygg.build_parser()
    for _, _, argv in menu.ENTREES:
        if argv[0] in ygg.DELEGATES:
            continue
        args = parser.parse_args(argv + (["x"] if argv == ["search"] else []))
        assert callable(args.func)


# --------------------------------------------------------------------------
# Compléments : limite de charge, démarrage, noyau récent, apps, Debian suivante
# --------------------------------------------------------------------------

def test_battery_charge_limit(tmp_path, fake_runner, monkeypatch):
    (tmp_path / "BAT0").mkdir()
    (tmp_path / "BAT0" / "charge_control_end_threshold").write_text("100\n")
    (tmp_path / "BAT1").mkdir()
    seuils = materiel.seuils_de_charge(tmp_path)
    assert list(seuils) == ["BAT0"]
    regle = materiel.tmpfiles_limite(seuils, 80)
    assert f"w {tmp_path}/BAT0/charge_control_end_threshold - - - - 80" in regle
    monkeypatch.setattr(materiel, "seuils_de_charge", lambda: seuils)
    runner = fake_runner()
    assert materiel.cmd_limite(SimpleNamespace(valeur="80"), runner) == 0
    assert ("run", f"tee {tmp_path}/BAT0/charge_control_end_threshold", True, "80\n") in runner.calls
    assert any(c[0] == "write" and c[1] == str(materiel.LIMITE_TMPFILES) for c in runner.calls)
    for mauvais in ("30", "abc"):
        with pytest.raises(YggError):
            materiel.cmd_limite(SimpleNamespace(valeur=mauvais), runner)
    runner = fake_runner()
    assert materiel.cmd_limite(SimpleNamespace(valeur="aucune"), runner) == 0
    assert ("run", f"rm -f {materiel.LIMITE_TMPFILES}", True, None) in runner.calls


def test_startup_apps(tmp_path):
    systeme, perso = tmp_path / "xdg", tmp_path / "perso"
    systeme.mkdir()
    perso.mkdir()
    (systeme / "a.desktop").write_text("[Desktop Entry]\nName=Agent A\nExec=a\n[Desktop Action x]\nName=Autre\n")
    (systeme / "gnome.desktop").write_text("[Desktop Entry]\nName=Seulement GNOME\nOnlyShowIn=GNOME;\n")
    (systeme / "b.desktop").write_text("[Desktop Entry]\nName=Agent B\n")
    (perso / "b.desktop").write_text("[Desktop Entry]\nName=Agent B\nHidden=true\n")
    (perso / "c.desktop").write_text("[Desktop Entry]\nName=Mon script\nX-GNOME-Autostart-enabled=true\n")
    assert materiel.applis_au_demarrage(systeme, perso) == [
        ("Agent A", "a.desktop", True), ("Agent B", "b.desktop", False),
        ("Mon script", "c.desktop", True), ("Seulement GNOME", "gnome.desktop", False)]


def test_backports_source():
    texte = materiel.backports_source("trixie")
    assert "Suites: trixie-backports" in texte and "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" in texte


def test_user_added_software():
    base = {"plasma-desktop", "firefox-esr", "vlc"}
    assert entretien.ajoutes(["vlc", "gimp", "steam:i386", "obs-studio", ""], base) == ["gimp", "obs-studio", "steam"]
    sortie = "org.gimp.GIMP\tGIMP\tsystem\ncom.spotify.Client\tSpotify\tuser\nApplication ID\tName\tInstallation\n"
    assert entretien.parse_flatpak_apps(sortie) == [("org.gimp.GIMP", "GIMP", "system"),
                                                    ("com.spotify.Client", "Spotify", "user")]


def test_next_debian_sources():
    sources = ("Types: deb deb-src\nURIs: http://deb.debian.org/debian/\nSuites: trixie trixie-updates\n"
               "Components: main\n\nTypes: deb\nURIs: http://security.debian.org/debian-security/\n"
               "Suites: trixie-security\n")
    nouveau = entretien.rewrite_suites(sources, "trixie", "forky")
    assert "Suites: forky forky-updates" in nouveau and "Suites: forky-security" in nouveau
    assert "trixie" not in nouveau
    ancien = "deb http://deb.debian.org/debian trixie main\ndeb http://security.debian.org/debian-security trixie-security main\n"
    assert entretien.rewrite_suites(ancien, "trixie", "forky") == ancien.replace("trixie", "forky")
    # Un nom qui contient l'ancien sans être lui n'est pas touché
    assert entretien.rewrite_suites("Suites: trixiette\n", "trixie", "forky") == "Suites: trixiette\n"


def test_next_debian_nothing_to_do(fake_runner, capsys):
    assert entretien.cmd_montee(SimpleNamespace(vers="trixie", yes=True), fake_runner(), {}) == 0
    assert "toujours la version stable" in capsys.readouterr().out


def test_doctor_signale_le_pilote_nvidia(fake_runner, monkeypatch):
    from yggdrasil import common, doctor
    monkeypatch.setattr(common, "which", lambda cmd: "/usr/bin/" + cmd)
    runner = fake_runner({"lspci": (0, LSPCI), "journalctl": (0, NOYAU),
                          "dpkg-query": (0, "install ok installed\n")})  # un seul paquet de chaque conseil
    [check] = doctor.Doctor(runner).check_drivers()
    assert check.status == doctor.WARN and "NVIDIA" in check.message and check.hint == "ygg pilotes installer"
    tout = fake_runner({"lspci": (0, LSPCI), "journalctl": (0, ""),
                        "dpkg-query": (0, "install ok installed\n" * 3)})
    [check] = doctor.Doctor(tout).check_drivers()
    assert check.status == doctor.OK


def test_ordre_des_reglages_grub():
    # /etc/default/grub.d/*.cfg est lu par ordre alphabétique, le dernier l'emporte : le délai
    # choisi (ygg demarrage delai) et les réglages locaux doivent passer après ceux d'Yggdrasil
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent / "packages/yggdrasil-base/root/etc/default/grub.d"
    [defaut] = [p.name for p in racine.glob("*.cfg")]
    assert sorted([defaut, materiel.GRUB_DELAI.name, "99-local.cfg"])[0] == defaut
