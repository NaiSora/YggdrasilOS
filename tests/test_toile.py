"""La toile des Nornes : versions précédentes, disque branché, copie distante, vérification, Skuld."""

import datetime as dt
import os
import random
from types import SimpleNamespace

import pytest

from yggdrasil import common, norns, ratatoskr, toile
from yggdrasil.common import YggError


def sauvegarde(racine, nom, fichiers):
    d = racine / nom
    for rel, (contenu, mtime) in fichiers.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenu)
        os.utime(p, (mtime, mtime))
    (d / norns.COMPLETE_MARKER).write_text("ok")
    return d


def test_previous_versions_skip_identical_copies(tmp_path):
    maison = tmp_path / "maison"
    (maison / "Documents").mkdir(parents=True)
    (maison / "Documents" / "rapport.odt").write_text("v3")
    racine = tmp_path / "disque"
    s1 = sauvegarde(racine, "2026-09-01_090000", {"Documents/rapport.odt": ("v1", 1_756_710_000)})
    s2 = sauvegarde(racine, "2026-09-08_090000", {"Documents/rapport.odt": ("v1", 1_756_710_000)})
    s3 = sauvegarde(racine, "2026-09-15_090000", {"Documents/rapport.odt": ("v2-plus-long", 1_757_900_000)})
    s4 = sauvegarde(racine, "2026-09-22_090000", {"Autre/fichier.txt": ("x", 1_757_900_000)})
    versions = toile.versions_de(maison / "Documents" / "rapport.odt", [s1, s2, s3, s4], maison)
    assert [v.sauvegarde for v in versions] == ["2026-09-15_090000", "2026-09-08_090000"]
    assert versions[0].taille == len("v2-plus-long")
    with pytest.raises(YggError, match="dossier personnel"):
        toile.versions_de(tmp_path / "ailleurs.txt", [s1], maison)


def test_restored_version_name():
    date = dt.datetime(2026, 10, 1, 14, 5)
    assert toile.nom_restauration(common.Path("/h/rapport.odt"), date).name == "rapport (version du 01-10-2026 14h05).odt"
    assert toile.nom_restauration(common.Path("/h/LISEZMOI"), date).name == "LISEZMOI (version du 01-10-2026 14h05)"
    assert toile.nom_restauration(common.Path("/h/a.tar.gz"), date).name == "a.tar (version du 01-10-2026 14h05).gz"


def test_versions_command_restores_next_to_the_original(tmp_path, fake_runner, monkeypatch):
    maison = tmp_path / "maison"
    (maison / "notes").mkdir(parents=True)
    original = maison / "notes" / "idees.md"
    original.write_text("aujourd'hui")
    disque = tmp_path / "disque"
    racine = norns.backup_root(disque)
    sauvegarde(racine, "2026-09-30_200000", {"notes/idees.md": ("hier", 1_759_250_000)})
    monkeypatch.setattr(toile.Path, "home", lambda: maison)
    monkeypatch.setattr(toile.common.Path, "home", lambda: maison)
    config = {"norns": {"backup_target": str(disque)}}
    args = SimpleNamespace(fichier=str(original), gui=False, restaurer=1)
    assert toile.cmd_versions(args, fake_runner(), config) == 0
    copies = [p.name for p in (maison / "notes").iterdir() if p.name != "idees.md"]
    assert len(copies) == 1 and copies[0].startswith("idees (version du ")
    assert (maison / "notes" / copies[0]).read_text() == "hier"


def test_verification_detects_damage(tmp_path):
    maison = tmp_path / "maison"
    maison.mkdir()
    fichiers = {}
    for i in range(30):
        (maison / f"f{i}.txt").write_text(f"contenu {i}")
        os.utime(maison / f"f{i}.txt", (1_759_000_000, 1_759_000_000))
        fichiers[f"f{i}.txt"] = (f"contenu {i}", 1_759_000_000)
    s = sauvegarde(tmp_path / "disque", "2026-10-01_100000", fichiers)
    lus, abimes = toile.verifier(s, maison, nombre=30)
    assert lus == 30 and abimes == []
    # Un bit qui s'est retourné sur le disque : même taille, même date, contenu différent
    abime = s / "f7.txt"
    abime.write_text("contenu X")
    os.utime(abime, (1_759_000_000, 1_759_000_000))
    _, abimes = toile.verifier(s, maison, nombre=30)
    assert abimes == ["f7.txt"]
    assert len(toile.echantillon(s, maison, 5, random.Random(1))) == 5


def test_auto_backup_only_for_the_registered_disk(fake_runner, monkeypatch):
    lances = []
    monkeypatch.setattr(toile.norns, "main", lambda argv: lances.append(argv) or 0)
    monkeypatch.setattr(toile.common, "which", lambda cmd: None)
    config = {"norns": {"disque_uuid": "1234-ABCD", "backup_target": "/media/moi/Sauvegardes"}}
    assert toile.cmd_auto(SimpleNamespace(uuid="9999-0000"), fake_runner(), config) == 0
    assert lances == []
    runner = fake_runner({"findmnt": (0, "/media/moi/Sauvegardes\n")})
    assert toile.cmd_auto(SimpleNamespace(uuid="1234-ABCD"), runner, config) == 0
    assert lances == [["backup", "--yes"]]
    # Rebranché une heure après : pas de seconde sauvegarde le même jour
    toile.cmd_auto(SimpleNamespace(uuid="1234-ABCD"), runner, config)
    assert len(lances) == 1


def test_failed_auto_backup_raises_an_alert(fake_runner, monkeypatch):
    monkeypatch.setattr(toile.norns, "main", lambda argv: 23)
    monkeypatch.setattr(toile.common, "which", lambda cmd: None)
    config = {"norns": {"disque_uuid": "U", "backup_target": "/media/x"}}
    toile.cmd_auto(SimpleNamespace(uuid="U"), fake_runner({"findmnt": (0, "/media/x\n")}), config)
    assert "a échoué" in common.lire_alertes()[-1]["message"]


def test_restic_commands(fake_runner, monkeypatch):
    monkeypatch.setattr(toile.common, "which", lambda cmd: "/usr/bin/" + cmd)
    runner = fake_runner()
    args = SimpleNamespace(action="init", depot="sftp:moi@nas:/sauvegardes", instantane=None, yes=True)
    assert toile.cmd_distant(args, runner, {}) == 0
    mdp = toile.mot_de_passe_distant()
    assert mdp.exists() and oct(mdp.stat().st_mode)[-3:] == "600"
    assert any(c[1].startswith("restic -r sftp:moi@nas:/sauvegardes --password-file") and c[1].endswith(" init")
               for c in runner.calls)
    config = common.load_config()
    assert config["norns"]["distant"] == "sftp:moi@nas:/sauvegardes"
    runner = fake_runner()
    toile.cmd_distant(SimpleNamespace(action="sauvegarder", depot=None, instantane=None, yes=True), runner, config)
    commandes = [c[1] for c in runner.calls if c[0] == "run"]
    assert " backup " in commandes[0] and "--exclude=" in commandes[0] and "--tag yggdrasil" in commandes[0]
    assert "forget --keep-daily 7" in commandes[1]
    with pytest.raises(YggError, match="aucun dépôt"):
        toile.cmd_distant(SimpleNamespace(action="liste", depot=None, instantane=None, yes=True), runner, {})


def test_skuld_plans_user_timers(fake_runner):
    runner = fake_runner()
    runner.write_file = common.Runner.write_file.__get__(runner)
    assert toile.cmd_skuld(SimpleNamespace(quoi="sauvegarde", quand="quotidien"), runner, {}) == 0
    from yggdrasil import taches
    service = (taches.dossier_unites() / "norns-sauvegarde.service").read_text()
    assert "norns backup --yes --si-present" in service
    assert "OnCalendar=daily" in (taches.dossier_unites() / "norns-sauvegarde.timer").read_text()
    with pytest.raises(YggError):
        toile.cmd_skuld(SimpleNamespace(quoi="verification", quand="quotidien"), runner, {})
    toile.cmd_skuld(SimpleNamespace(quoi="sauvegarde", quand="non"), runner, {})
    assert not (taches.dossier_unites() / "norns-sauvegarde.timer").exists()


def test_backup_reminder():
    assert ratatoskr.rappel_sauvegarde({}) == ""
    config = {"norns": {"backup_target": "/media/x"}}
    assert "jamais faite" in ratatoskr.rappel_sauvegarde(config)
    toile.noter(sauvegarde_ok=1_000_000)
    assert "il y a 3 jours" not in ratatoskr.rappel_sauvegarde(config, 1_000_000 + 3 * 86400)
    assert ratatoskr.rappel_sauvegarde(config, 1_000_000 + 3 * 86400) == ""
    assert "il y a 9 jours" in ratatoskr.rappel_sauvegarde(config, 1_000_000 + 9 * 86400)


def test_norn_commands_exist():
    from yggdrasil import skuld, urd, verdandi
    assert urd.main and verdandi.main and skuld.main
    parser = norns.build_parser()
    for argv in (["versions", "x.txt", "--gui"], ["disque", "--non"], ["distant", "init", "/srv/depot"],
                 ["verifier", "--nombre", "5"], ["backup", "--si-present"]):
        assert callable(parser.parse_args(argv).func)
