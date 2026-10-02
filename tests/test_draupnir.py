"""Draupnir : la graine se forge, se lit avec méfiance et se replante."""

import io
import json
import tarfile

import pytest

from yggdrasil import common, draupnir, realms
from yggdrasil.common import YggError


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """Une maison, un état des royaumes, un service Bifröst et des règles Heimdall."""
    maison = tmp_path / "maison"
    (maison / ".config/yggdrasil").mkdir(parents=True)
    (maison / ".config/yggdrasil/config.toml").write_text('[mimir]\nprenom = "Astrid"\n')
    (maison / ".config/yggdrasil/norns-distant.motdepasse").write_text("tres-secret\n")
    (maison / ".config/kdeglobals").write_text("[General]\nColorScheme=Yggdrasil\n")
    (maison / ".config/yggdrasil/__pycache__").mkdir()
    (maison / ".config/yggdrasil/__pycache__/x.pyc").write_bytes(b"\0")
    (maison / ".gitconfig").write_text("[user]\n\tname = Astrid\n")
    (maison / ".ssh").mkdir()
    (maison / ".ssh/id_ed25519").write_text("CLÉ PRIVÉE\n")
    etat = tmp_path / "etat"
    etat.mkdir()
    (etat / "paquets-de-base.txt").write_text("bash\ncoreutils\nfirefox-esr\n")
    (etat / "realms.json").write_text(json.dumps({
        "muspelheim": {"apt": ["steam-installer"], "flatpak": ["net.lutris.Lutris"], "logiciels": ["steam"]},
        "inconnu": {"apt": [], "flatpak": [], "logiciels": ["x"]},
    }))
    monkeypatch.setattr(common, "STATE_DIR", etat)
    monkeypatch.setattr(realms, "state_file", lambda: etat / "realms.json")
    heimdall_json = tmp_path / "heimdall.json"
    heimdall_json.write_text('{"enabled": true, "zone": "maison", "rules": []}')
    monkeypatch.setattr(draupnir, "_heimdall_config", lambda: heimdall_json)
    services = tmp_path / "bifrost"
    (services / "survie").mkdir(parents=True)
    (services / "survie/compose.yml").write_text("services: {}\n")
    (services / "survie/.bifrost.json").write_text('{"modele": "minecraft"}')
    (services / "survie/.env").write_text("TYPE=FABRIC\nRCON_PASSWORD=abc123\nDISCORD_WEBHOOK=https://x\n")
    (services / "survie/data").mkdir()
    (services / "survie/data/level.dat").write_bytes(b"monde")
    config = {"bifrost": {"home": str(services)}, "draupnir": {"fichiers": []}}
    return maison, config, heimdall_json


def reponses():
    return {
        "apt-mark showmanual": (0, "bash\nfirefox-esr\nsteam-installer\ngimp\nlinux-image-amd64\nyggdrasil-tools\n"
                                   "htop:amd64\n"),
        "flatpak list": (0, "net.lutris.Lutris\tLutris\tsystem\norg.kde.krita\tKrita\tsystem\n"),
    }


def test_recolte(machine, fake_runner):
    maison, config, _ = machine
    graine, contenu = draupnir.recolter(fake_runner(reponses()), config, maison)
    assert graine.royaumes == {"muspelheim": ["steam"]}  # le royaume inconnu n'est pas emporté
    assert graine.paquets == ["gimp", "htop"]  # ni base, ni royaume, ni noyau, ni Yggdrasil
    assert graine.flatpaks == ["org.kde.krita"]
    assert graine.services == {"survie": "minecraft"}
    assert "maison/.config/kdeglobals" in contenu and "maison/.gitconfig" in contenu
    assert "maison/.config/yggdrasil/norns-distant.motdepasse" not in contenu  # secret : seulement chiffré
    assert not any("__pycache__" in n or ".ssh" in n or "level.dat" in n for n in contenu)
    env = contenu["bifrost/survie/.env"].decode()
    assert "TYPE=FABRIC" in env and "abc123" not in env and "https://x" not in env
    assert "heimdall/heimdall.json" in contenu
    assert any("RCON_PASSWORD" in s for s in graine.secrets_retires)


def test_recolte_chiffree_emporte_les_secrets(machine, fake_runner):
    maison, config, _ = machine
    _, contenu = draupnir.recolter(fake_runner(reponses()), config, maison, chiffree=True, secrets_ssh=True)
    assert "maison/.config/yggdrasil/norns-distant.motdepasse" in contenu
    assert "maison/.ssh/id_ed25519" in contenu
    assert isinstance(contenu["bifrost/survie/.env"], type(maison))  # le .env tel quel


def test_aller_retour(machine, fake_runner, tmp_path):
    maison, config, _ = machine
    graine, contenu = draupnir.recolter(fake_runner(reponses()), config, maison)
    fichier = tmp_path / "graine.tar.gz"
    draupnir.ecrire_archive(graine, contenu, fichier)
    relue, fichiers = draupnir.ouvrir(fichier)
    assert relue.royaumes == graine.royaumes and relue.paquets == graine.paquets
    assert relue.services == {"survie": "minecraft"}
    assert fichiers["maison/.gitconfig"][0] == b"[user]\n\tname = Astrid\n"
    assert fichiers["bifrost/survie/.env"][1] == 0o600


def test_une_graine_piegee_est_lue_avec_mefiance(tmp_path):
    fichier = tmp_path / "piege.tar.gz"
    with tarfile.open(fichier, "w:gz") as tar:
        def ajouter(nom, donnees, type_=tarfile.REGTYPE):
            info = tarfile.TarInfo(nom)
            info.type = type_
            info.size = len(donnees)
            if type_ == tarfile.SYMTYPE:
                info.linkname = "/etc/shadow"
                info.size = 0
            tar.addfile(info, io.BytesIO(donnees))
        ajouter("graine.toml", b'machine = "x"\npaquets = ["gimp", "rm -rf /", "../x"]\n'
                               b'flatpaks = ["org.kde.krita", "--system"]\n'
                               b'[royaumes]\nmidgard = ["firefox", "../../x"]\n')
        ajouter("../../.bashrc", b"piege")
        ajouter("/etc/passwd", b"piege")
        ajouter("maison/.bashrc", b"", tarfile.SYMTYPE)
        ajouter("autre/fichier", b"hors des dossiers permis")
        ajouter("maison/.gitconfig", b"ok")
    graine, fichiers = draupnir.ouvrir(fichier)
    assert list(fichiers) == ["maison/.gitconfig"]
    assert graine.paquets == ["gimp"] and graine.flatpaks == ["org.kde.krita"]
    assert graine.royaumes == {"midgard": ["firefox"]}


def test_pas_une_graine(tmp_path):
    faux = tmp_path / "faux.tar.gz"
    faux.write_text("pas une archive")
    with pytest.raises(YggError):
        draupnir.ouvrir(faux)
    vide = tmp_path / "vide.tar.gz"
    with tarfile.open(vide, "w:gz"):
        pass
    with pytest.raises(YggError, match="graine.toml"):
        draupnir.ouvrir(vide)


def test_disponibles(fake_runner):
    politique = ("gimp:\n  Installé : (aucun)\n  Candidat : 3.0.4-1\n"
                 "paquet-fantome:\n  Installed: (none)\n  Candidate: (none)\n"
                 "htop:\n  Installed: 3.4.1-5\n  Candidate: 3.4.1-5\n")
    runner = fake_runner({"apt-cache policy": (0, politique)})
    assert draupnir.disponibles(["gimp", "paquet-fantome", "htop", "absent"], runner) == (
        ["gimp", "htop"], ["paquet-fantome", "absent"])


def test_planter(machine, fake_runner, tmp_path, monkeypatch):
    maison, config, heimdall_json = machine
    graine, contenu = draupnir.recolter(fake_runner(reponses()), config, maison)
    fichier = tmp_path / "graine.tar.gz"
    draupnir.ecrire_archive(graine, contenu, fichier)
    relue, fichiers = draupnir.ouvrir(fichier)

    # Une machine neuve : autre maison, autres services, rien d'installé
    neuve = tmp_path / "neuve"
    (neuve / ".config").mkdir(parents=True)
    (neuve / ".config/kdeglobals").write_text("[General]\nColorScheme=BreezeDark\n")
    config_neuve = {"bifrost": {"home": str(tmp_path / "bifrost-neuf")}}
    runner = fake_runner({"apt-cache policy": (0, "gimp:\n  Candidate: 3.0\nhtop:\n  Candidate: 3.4\n"),
                          "dpkg-query": (0, "")})
    plantes = []
    monkeypatch.setattr(realms, "add_realm", lambda realm, r, **kw: plantes.append(
        (realm.name, [x.id for x in kw["choix"]])) or True)
    monkeypatch.setattr(common, "which", lambda cmd: None)
    assert draupnir.planter(relue, fichiers, runner, config_neuve, neuve, assume_yes=True) == 0

    assert (neuve / ".gitconfig").read_text() == "[user]\n\tname = Astrid\n"
    assert "Yggdrasil" in (neuve / ".config/kdeglobals").read_text()
    assert "BreezeDark" in (neuve / ".config/kdeglobals.avant-draupnir").read_text()
    assert plantes == [("muspelheim", ["steam"])]
    commandes = [c[1] for c in runner.calls if c[0] == "run"]
    assert "apt-get install -y gimp htop" in commandes
    assert any(c.startswith("flatpak install --system -y --noninteractive flathub org.kde.krita") for c in commandes)
    ecrits = {c[1]: c[2] for c in runner.calls if c[0] == "write"}
    assert json.loads(ecrits[str(heimdall_json)])["zone"] == "maison"
    env = (tmp_path / "bifrost-neuf/survie/.env").read_text()
    assert "TYPE=FABRIC" in env
    rcon = [ligne for ligne in env.splitlines() if ligne.startswith("RCON_PASSWORD=")][0]
    assert len(rcon) > len("RCON_PASSWORD=") + 10  # un mot de passe neuf
    assert "DISCORD_WEBHOOK=\n" in env or env.rstrip().endswith("DISCORD_WEBHOOK=")  # à redonner
    assert (tmp_path / "bifrost-neuf/survie/compose.yml").exists()
    assert not (tmp_path / "bifrost-neuf/survie/data").exists()


def test_planter_simulation_ne_touche_a_rien(machine, fake_runner, tmp_path, monkeypatch):
    maison, config, _ = machine
    graine, contenu = draupnir.recolter(fake_runner(reponses()), config, maison)
    fichier = tmp_path / "graine.tar.gz"
    draupnir.ecrire_archive(graine, contenu, fichier)
    relue, fichiers = draupnir.ouvrir(fichier)
    neuve = tmp_path / "neuve"
    neuve.mkdir()
    runner = fake_runner({})
    runner.dry_run = True
    monkeypatch.setattr(realms, "add_realm", lambda *a, **kw: True)
    draupnir.planter(relue, fichiers, runner, {"bifrost": {"home": str(tmp_path / "b")}}, neuve, assume_yes=True)
    assert list(neuve.iterdir()) == []
    assert not (tmp_path / "b").exists()


def test_cli_graine_et_lire(machine, fake_runner, tmp_path, monkeypatch, capsys):
    maison, config, _ = machine
    monkeypatch.setattr(draupnir, "maison_cible", lambda: maison)
    monkeypatch.setattr(common, "load_config", lambda: config)
    monkeypatch.setattr(draupnir, "Runner", lambda **kw: fake_runner(reponses()))
    sortie = tmp_path / "ma-graine.tar.gz"
    assert draupnir.main(["graine", str(sortie)]) == 0
    assert sortie.stat().st_mode & 0o777 == 0o600
    assert draupnir.main(["lire", str(sortie)]) == 0
    texte = capsys.readouterr().out
    assert "Muspelheim" in texte and "gimp" in texte and "survie" in texte
    assert draupnir.main(["graine", "--secrets"]) == 1  # les clés ne voyagent pas en clair
