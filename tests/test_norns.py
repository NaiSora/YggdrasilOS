import os
from pathlib import Path

import pytest

from yggdrasil import norns
from yggdrasil.common import YggError


def test_build_timeshift_config():
    cfg = norns.build_timeshift_config({"exclude": ["/srv/**"]}, "abcd-1234", daily=5, weekly=0, monthly=2, boot=0)
    assert cfg["backup_device_uuid"] == "abcd-1234"
    assert cfg["schedule_daily"] == "true" and cfg["count_daily"] == "5"
    assert cfg["schedule_weekly"] == "false"
    assert cfg["schedule_monthly"] == "true" and cfg["count_monthly"] == "2"
    assert cfg["btrfs_mode"] == "false"
    assert cfg["exclude"] == ["/srv/**"]
    assert all(isinstance(v, (str, list)) for v in cfg.values())


def test_timeshift_configured(tmp_path):
    path = tmp_path / "timeshift.json"
    assert not norns.timeshift_configured(path)
    path.write_text('{"backup_device_uuid": ""}')
    assert not norns.timeshift_configured(path)
    path.write_text('{"backup_device_uuid": "abcd"}')
    assert norns.timeshift_configured(path)


def make_backup(root: Path, name: str, complete: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if complete:
        (d / norns.COMPLETE_MARKER).write_text("ok")
    return d


def test_list_and_prune_backups(tmp_path):
    for name in ("2026-09-01_120000", "2026-09-15_120000", "2026-09-30_120000"):
        make_backup(tmp_path, name)
    make_backup(tmp_path, "2026-10-01_120000", complete=False)  # interrompue
    make_backup(tmp_path, "pas-une-date")
    backups = norns.list_backups(tmp_path)
    assert [b.name for b in backups] == ["2026-09-01_120000", "2026-09-15_120000", "2026-09-30_120000"]
    assert [b.name for b in norns.to_prune(backups, 2)] == ["2026-09-01_120000"]
    assert norns.to_prune(backups, 0) == backups[:-1]  # on garde toujours la dernière
    assert norns.to_prune(backups, 10) == []


def test_rsync_command():
    cmd = norns.rsync_command(Path("/home/a"), Path("/m/b/new"), Path("/m/b/old"), [".cache/"])
    assert cmd[0] == "rsync" and "--delete" in cmd
    assert "--exclude=.cache/" in cmd
    assert f"--link-dest={Path('/m/b/old')}" in cmd
    assert cmd[-2:] == [f"{Path('/home/a')}/", f"{Path('/m/b/new')}/"]
    no_links = norns.rsync_command(Path("/home/a"), Path("/m/b/new"), Path("/m/b/old"), [], hardlinks_ok=False)
    assert not any(c.startswith("--link-dest") for c in no_links)
    assert "--dry-run" in norns.rsync_command(Path("/a"), Path("/b"), None, [], dry_run=True)


def test_backup_root():
    assert norns.backup_root(Path("/media/disque"), "alice", "pc") == Path("/media/disque/yggdrasil-sauvegardes/pc-alice")


def test_safe_relative(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert norns.safe_relative("Documents/a.txt") == Path("Documents/a.txt")
    assert norns.safe_relative(str(tmp_path / "Images")) == Path("Images")
    with pytest.raises(YggError):
        norns.safe_relative("../../etc/shadow")
    if os.name == "posix":  # sous Windows, « /etc » n'est pas un chemin absolu
        with pytest.raises(YggError):
            norns.safe_relative("/etc/passwd")


def test_racine_btrfs(fake_runner):
    btrfs = "btrfs rw,noatime,compress=lzo,ssd,discard=async,space_cache=v2,subvolid=256,subvol=/@\n"
    assert norns.racine_btrfs(fake_runner({"findmnt": (0, btrfs)}))
    assert not norns.racine_btrfs(fake_runner({"findmnt": (0, "btrfs rw,subvolid=5,subvol=/\n")}))
    assert not norns.racine_btrfs(fake_runner({"findmnt": (0, "btrfs rw,subvol=/@home\n")}))
    assert not norns.racine_btrfs(fake_runner({"findmnt": (0, "ext4 rw,relatime\n")}))
    cfg = norns.build_timeshift_config({}, "abcd", daily=5, weekly=3, monthly=0, boot=0, btrfs=True)
    assert cfg["btrfs_mode"] == "true" and cfg["include_btrfs_home_for_backup"] == "false"


def test_instantane_sans_etiquette(fake_runner, monkeypatch):
    # Timeshift 24.06 refuse « --tags O » à la création : l'instantané à la demande s'en passe
    monkeypatch.setattr(norns, "require_timeshift", lambda: None)
    monkeypatch.setattr(norns, "racine_btrfs", lambda runner: False)
    runner = fake_runner({})
    norns.create_snapshot(runner, "avant la mise à jour")
    [commande] = [c[1] for c in runner.calls if c[0] == "run"]
    assert commande.startswith("timeshift --create --comments") and "--tags" not in commande


MOUNTINFO_INSTANTANE = """\
22 1 0:21 / / rw,relatime shared:1 - overlay overlay rw
26 1 0:25 /timeshift-btrfs/snapshots/2026-10-02_06-00-02/@ / rw,relatime shared:1 - btrfs /dev/mapper/luks-1 rw,subvol=/timeshift-btrfs/snapshots/2026-10-02_06-00-02/@
27 26 0:25 /@home /home rw,relatime shared:2 - btrfs /dev/mapper/luks-1 rw,subvol=/@home
"""


def test_instantane_demarre(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(MOUNTINFO_INSTANTANE)
    assert norns.instantane_demarre(mountinfo) == "2026-10-02_06-00-02"  # le dernier montage sur / l'emporte
    mountinfo.write_text("26 1 0:25 /@ / rw,relatime - btrfs /dev/vda3 rw,subvol=/@\n"
                         "27 26 0:25 /timeshift-btrfs/snapshots/2026-10-02_06-00-02/@ /mnt rw - btrfs /dev/vda3 rw\n")
    assert norns.instantane_demarre(mountinfo) is None  # un instantané monté ailleurs : on n'a pas démarré dessus
    mountinfo.write_text("26 1 8:2 / / rw,relatime - ext4 /dev/sda2 rw\n")
    assert norns.instantane_demarre(mountinfo) is None
    assert norns.instantane_demarre(tmp_path / "absent") is None
    assert norns.libelle_instantane("2026-10-02_06-00-02") == "du 02/10/2026 à 06:00"
    assert norns.libelle_instantane("avant-mise-a-jour") == "« avant-mise-a-jour »"
