from pathlib import Path

import yggdrasil
from yggdrasil import ratatoskr, sysinfo, ygg


def test_ratatoskr_should_notify():
    msgs = [("normal", "3 mises à jour")]
    assert not ratatoskr.should_notify([], {}, 24, 1000)
    assert ratatoskr.should_notify(msgs, {}, 24, 1000)
    import hashlib
    import json
    digest = hashlib.sha256(json.dumps(msgs).encode()).hexdigest()
    state = {"digest": digest, "time": 1000}
    assert not ratatoskr.should_notify(msgs, state, 24, 1000 + 3600)
    assert ratatoskr.should_notify(msgs, state, 24, 1000 + 25 * 3600)
    assert ratatoskr.should_notify([("critical", "autre")], state, 24, 1001)


def test_ratatoskr_waits_for_boot_refresh(fake_runner, monkeypatch):
    """Au démarrage, Ratatoskr attend la fin du rafraîchissement de la liste des paquets."""
    monkeypatch.setattr(ratatoskr.common, "which", lambda name: None)  # pas de nm-online
    states = iter(["activating", "activating", "inactive"])
    runner = fake_runner()
    runner.query = lambda cmd, **kw: (0, next(states)) if "is-active" in cmd else (1, "")
    slept = []
    ratatoskr.wait_until_ready(runner, sleep=slept.append, clock=lambda: 0.0)
    assert slept == [5, 5]


def test_ratatoskr_wait_gives_up(fake_runner, monkeypatch):
    """Le rafraîchissement ne bloque jamais la vérification plus longtemps que prévu."""
    monkeypatch.setattr(ratatoskr.common, "which", lambda name: None)
    runner = fake_runner({"systemctl is-active": (0, "activating")})
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    ratatoskr.wait_until_ready(runner, refresh_timeout=30, sleep=sleep, clock=lambda: now[0])
    assert now[0] == 30


def test_sysinfo_parsers():
    mem = sysinfo.parse_meminfo("MemTotal:       16303296 kB\nMemAvailable:    9000000 kB\nHugePages_Total: 0\n")
    assert mem["MemTotal"] == 16303296 * 1024
    assert mem["HugePages_Total"] == 0
    model, cores = sysinfo.parse_cpu_model(
        "processor\t: 0\nmodel name\t: AMD Ryzen 7 5800X 8-Core Processor\nprocessor\t: 1\nmodel name\t: AMD Ryzen 7 5800X 8-Core Processor\n"
    )
    assert model == "AMD Ryzen 7 5800X 8-Core Processor" and cores == 2
    gpus = sysinfo.parse_lspci_gpus(
        "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics 630\n"
        "01:00.0 3D controller: NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile]\n"
        "00:1f.3 Audio device: Intel Corporation Cannon Lake PCH cAVS\n"
    )
    assert gpus == ["Intel Corporation UHD Graphics 630", "NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile]"]
    assert sysinfo.parse_uptime("12345.67 99999.0") == 12345.67


def test_sysinfo_render_minimal():
    info = {
        "os": "Yggdrasil 1.0 (Midgard)", "version": "1.0", "codename": "Midgard", "debian": "13.7",
        "kernel": "6.12.0", "hostname": "pc", "user": "alice", "uptime": 3600, "cpu": "CPU", "cores": 4,
        "mem_total": 8 * 1024**3, "mem_available": 4 * 1024**3, "swap_total": 0, "swap_free": 0,
        "desktop": "XFCE", "session": "x11", "shell": "bash", "live": True,
        "disks": [{"mount": "/", "total": 100, "used": 50, "free": 50}], "gpus": ["GPU"], "packages": 1500, "flatpaks": 3,
    }
    out = sysinfo.render(info)
    assert "Yggdrasil" in out
    assert "Debian 13.7" in out
    assert "1500 paquets" in out
    assert "live (rien" in out


def test_ygg_cli_parsing_and_split():
    parser = ygg.build_parser()
    args = parser.parse_args(["realm", "add", "muspelheim", "nidavellir", "-y"])
    assert args.names == ["muspelheim", "nidavellir"] and args.yes
    args = parser.parse_args(["update", "--no-snapshot", "-n"])
    assert args.no_snapshot and args.dry_run
    assert ygg.split_targets(["vlc", "org.gimp.GIMP", "g++"]) == (["vlc", "g++"], ["org.gimp.GIMP"])


def test_ygg_version_and_delegation(capsys):
    # Le fichier VERSION (ISO, paquets) et le module Python avancent ensemble
    version = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
    assert yggdrasil.__version__ == version
    assert ygg.main(["version"]) == 0
    assert f"Yggdrasil {version}" in capsys.readouterr().out
    assert ygg.main(["new", "list"]) == 0
    assert "discord-bot" in capsys.readouterr().out
    assert ygg.main(["stack", "info", "valheim"]) == 0
    assert "Valheim" in capsys.readouterr().out
    assert ygg.main(["fw", "render"]) == 0
    assert "table inet heimdall" in capsys.readouterr().out
    assert ygg.main(["realm", "show", "inconnu"]) == 1


def test_session_persistante(tmp_path):
    from yggdrasil import common
    cmdline, mounts = tmp_path / "cmdline", tmp_path / "mounts"
    cmdline.write_text("BOOT_IMAGE=/live/vmlinuz boot=live persistence components quiet")
    mounts.write_text("/dev/sdb3 /run/live/persistence/sdb3 ext4 rw,noatime 0 0\noverlay / overlay rw 0 0\n")
    assert common.is_persistent_session(cmdline, mounts)
    mounts.write_text("overlay / overlay rw 0 0\n")  # entrée « clé persistante » sur un DVD : rien de gardé
    assert not common.is_persistent_session(cmdline, mounts)
    cmdline.write_text("BOOT_IMAGE=/boot/vmlinuz root=UUID=1234 ro quiet")
    assert not common.is_persistent_session(cmdline, mounts)
