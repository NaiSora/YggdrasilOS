"""Skíðblaðnir : reconnaître les clés, lire l'image hybride, ajouter l'espace persistant."""

import json

import pytest

from yggdrasil import common, skidbladnir
from yggdrasil.common import YggError

LSBLK = json.dumps({"blockdevices": [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 512110190592, "tran": "nvme", "rm": False,
     "hotplug": False, "type": "disk", "model": "Samsung SSD 980", "label": None, "fstype": None,
     "mountpoints": [None], "children": [
         {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 536870912, "type": "part", "label": None,
          "fstype": "vfat", "mountpoints": ["/boot/efi"]},
         {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": 511571771392, "type": "part", "label": None,
          "fstype": "ext4", "mountpoints": ["/"]}]},
    {"name": "sdb", "path": "/dev/sdb", "size": 31037849600, "tran": "usb", "rm": True, "hotplug": True,
     "type": "disk", "model": "Cruzer Blade    ", "label": None, "fstype": None, "mountpoints": [None],
     "children": [
         {"name": "sdb1", "path": "/dev/sdb1", "size": 3044507648, "type": "part", "label": "YGGDRASIL_1_0",
          "fstype": "iso9660", "mountpoints": ["/media/ygg/YGGDRASIL_1_0"]},
         {"name": "sdb3", "path": "/dev/sdb3", "size": 27000000000, "type": "part", "label": "persistence",
          "fstype": "ext4", "mountpoints": [None]}]},
    {"name": "sdc", "path": "/dev/sdc", "size": 8000000000, "tran": "usb", "rm": "1", "type": "disk",
     "model": "Clé", "label": None, "fstype": None, "mountpoints": [None], "children": [
         {"name": "sdc1", "path": "/dev/sdc1", "size": 8000000000, "type": "part", "label": "PHOTOS",
          "fstype": "vfat", "mountpoints": ["/media/ygg/PHOTOS"]}]},
    {"name": "loop0", "path": "/dev/loop0", "size": 4294967296, "type": "loop", "mountpoints": [None]},
]})


def image_hybride(taille_mo: int = 8, volume: str = "YGGDRASIL_1_0") -> bytes:
    """Une petite image comme celles de live-build : MBR (partition ISO + partition EFI), puis l'ISO 9660."""
    taille = taille_mo * 1024 * 1024
    image = bytearray(taille)
    secteurs = taille // 512
    def entree(i, boot, type_, debut, nombre):
        o = 446 + 16 * i
        image[o] = boot
        image[o + 4] = type_
        image[o + 8:o + 12] = debut.to_bytes(4, "little")
        image[o + 12:o + 16] = nombre.to_bytes(4, "little")
    entree(0, 0x80, 0x00, 64, secteurs - 64)
    entree(1, 0x00, 0xEF, 2484, 6656 if secteurs > 9140 else 100)
    image[510:512] = b"\x55\xaa"
    pvd = 16 * 2048
    image[pvd] = 1
    image[pvd + 1:pvd + 6] = b"CD001"
    image[pvd + 40:pvd + 72] = volume.ljust(32).encode()
    image[pvd + 80:pvd + 84] = (taille // 2048).to_bytes(4, "little")
    image[pvd + 128:pvd + 130] = (2048).to_bytes(2, "little")
    return bytes(image)


def test_les_cles():
    disques = skidbladnir.parse_lsblk(LSBLK)
    cles = [d for d in disques if d.est_cle]
    assert [d.nom for d in cles] == ["sdb", "sdc"]
    sdb, sdc = cles
    assert sdb.porte_yggdrasil and sdb.persistante and sdb.modele == "Cruzer Blade"
    assert not sdc.porte_yggdrasil and sdc.montages == ["/media/ygg/PHOTOS"]
    systeme = skidbladnir.trouver("/dev/nvme0n1", disques)
    assert "/" in systeme.montages and not systeme.est_cle
    assert skidbladnir.parse_lsblk("pas du json") == []


def test_cibles_refusees():
    disques = skidbladnir.parse_lsblk(LSBLK)
    with pytest.raises(YggError, match="n'est pas une clé"):
        skidbladnir.verifier_cible(skidbladnir.trouver("nvme0n1", disques), "/tmp/x.iso")
    with pytest.raises(YggError, match="n'est pas une clé"):
        skidbladnir.verifier_cible(skidbladnir.trouver("loop0", disques), "/tmp/x.iso")
    skidbladnir.verifier_cible(skidbladnir.trouver("loop0", disques), "/tmp/x.iso", loop_permis=True)
    with pytest.raises(YggError, match="système en marche"):  # la clé d'où l'on a démarré
        skidbladnir.verifier_cible(skidbladnir.trouver("sdb", disques), "/dev/sdb")
    with pytest.raises(YggError, match="aucun disque"):
        skidbladnir.trouver("sdz", disques)


def test_image_hybride():
    image = image_hybride()
    taille, volume = skidbladnir.lire_pvd(image[32768:34816])
    assert taille == 8 * 1024 * 1024 and volume == "YGGDRASIL_1_0"
    with pytest.raises(YggError):
        skidbladnir.lire_pvd(b"\0" * 2048)
    entrees = skidbladnir.entrees_mbr(image[:512])
    assert entrees[0] == (0, 64, 16384 - 64) and entrees[2] == (0, 0, 0)


def test_mbr_avec_persistance():
    mbr = image_hybride()[:512]
    debut = skidbladnir.aligner(16384)
    assert debut == 16384 and skidbladnir.aligner(16385) == 18432
    nouveau, numero = skidbladnir.mbr_avec_persistance(mbr, debut, 1024 * 2048)
    assert numero == 3 and len(nouveau) == 512 and nouveau[510:] == b"\x55\xaa"
    assert skidbladnir.entrees_mbr(nouveau)[2] == (0x83, 16384, 1024 * 2048)
    assert nouveau[:446 + 32] == mbr[:446 + 32]  # le reste de l'image est intact
    with pytest.raises(YggError, match="chevaucherait"):
        skidbladnir.mbr_avec_persistance(mbr, 2048, 100)


def test_tailles_et_partitions():
    assert skidbladnir.parse_taille("8G") == 8 * 1024 ** 3
    assert skidbladnir.parse_taille("500M") == 500 * 1024 ** 2
    assert skidbladnir.parse_taille("1,5 Go") == int(1.5 * 1024 ** 3)
    assert skidbladnir.parse_taille("tout") is None and skidbladnir.parse_taille("0") == 0
    with pytest.raises(YggError):
        skidbladnir.parse_taille("beaucoup")
    assert skidbladnir.partition("/dev/sdb", 3) == "/dev/sdb3"
    assert skidbladnir.partition("/dev/loop0", 3) == "/dev/loop0p3"
    assert skidbladnir.partition("/dev/mmcblk0", 3) == "/dev/mmcblk0p3"


def test_ecrire_simulation(tmp_path, fake_runner, monkeypatch, capsys):
    iso = tmp_path / "yggdrasil.iso"
    iso.write_bytes(image_hybride())
    lsblk = json.dumps({"blockdevices": [{"name": "sdc", "path": "/dev/sdc", "size": 64 * 1024 * 1024 * 1024,
                                          "tran": "usb", "rm": True, "type": "disk", "model": "Clé",
                                          "mountpoints": [None], "children": [
                                              {"name": "sdc1", "path": "/dev/sdc1", "type": "part",
                                               "mountpoints": ["/media/ygg/PHOTOS"]}]}]})
    runner = fake_runner({"lsblk": (0, lsblk)})
    runner.dry_run = True
    monkeypatch.setattr(skidbladnir, "Runner", lambda **kw: runner)
    monkeypatch.setattr(common, "load_config", lambda: {})
    assert skidbladnir.main(["ecrire", "sdc", str(iso), "--persistance", "8G", "-y", "-n"]) == 0
    commandes = [c[1] for c in runner.calls if c[0] == "run"]
    assert commandes[0] == "umount /media/ygg/PHOTOS"
    assert commandes[1].startswith(f"dd if={iso} of=/dev/sdc bs=4M")
    assert any(c.startswith("dd if=") and "count=1 conv=notrunc" in c for c in commandes)  # le nouveau MBR
    assert "mkfs.ext4 -F -q -L persistence /dev/sdc3" in commandes
    ecrits = [c for c in runner.calls if c[0] == "write"]
    assert ecrits and ecrits[0][1].endswith("persistence.conf") and ecrits[0][2] == "/ union\n"
    assert "8.0 Go" in capsys.readouterr().out


def test_ecrire_refuse(tmp_path, fake_runner, monkeypatch):
    autre = tmp_path / "autre.iso"
    autre.write_bytes(image_hybride(volume="UBUNTU"))
    runner = fake_runner({"lsblk": (0, LSBLK)})
    monkeypatch.setattr(skidbladnir, "Runner", lambda **kw: runner)
    monkeypatch.setattr(common, "load_config", lambda: {})
    assert skidbladnir.main(["ecrire", "sdc", str(autre), "-y"]) == 1  # pas Yggdrasil
    iso = tmp_path / "yggdrasil.iso"
    iso.write_bytes(image_hybride())
    assert skidbladnir.main(["ecrire", "nvme0n1", str(iso), "-y"]) == 1  # le disque du système
    assert skidbladnir.main(["ecrire", "sdc", str(iso), "--persistance", "0", "--chiffrer", "-y"]) == 1
    assert not [c for c in runner.calls if c[0] == "run"]  # rien n'a été écrit
