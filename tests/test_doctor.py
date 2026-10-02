from yggdrasil import doctor

APT_LIST = """Listing... Done
openssl/trixie-security 3.5.1-1+deb13u2 amd64 [upgradable from: 3.5.1-1+deb13u1]
firefox-esr/trixie-security 140.4.0esr-1~deb13u1 amd64 [upgradable from: 140.3.0esr-1~deb13u1]
tzdata/trixie-updates 2026a-0+deb13u1 all [upgradable from: 2025b-4]
"""


def test_parse_upgradable_counts_security():
    assert doctor.parse_upgradable(APT_LIST) == (3, 2)
    assert doctor.parse_upgradable("Listing... Done\n") == (0, 0)


def test_parse_failed_units():
    out = "docker.service loaded failed failed Docker\nfoo.mount loaded failed failed Foo\n"
    assert doctor.parse_failed_units(out) == ["docker.service", "foo.mount"]


def make_root(tmp_path, *, reboot=False, security=True, swap=True):
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "meminfo").write_text(
        "MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n"
        f"SwapTotal: {'4000000' if swap else '0'} kB\nSwapFree: 4000000 kB\n"
    )
    (tmp_path / "proc" / "cmdline").write_text("BOOT_IMAGE=/vmlinuz quiet splash\n")
    (tmp_path / "run").mkdir()
    if reboot:
        (tmp_path / "run" / "reboot-required").write_text("")
        (tmp_path / "run" / "reboot-required.pkgs").write_text("linux-image-amd64\n")
    apt = tmp_path / "etc" / "apt" / "sources.list.d"
    apt.mkdir(parents=True)
    suites = "trixie trixie-updates trixie-security" if security else "trixie trixie-updates"
    (apt / "debian.sources").write_text(f"Types: deb\nSuites: {suites}\n")
    return tmp_path


def test_doctor_detects_problems(tmp_path, fake_runner, monkeypatch):
    monkeypatch.setattr(doctor.common, "which", lambda cmd: "/usr/bin/" + cmd)
    root = make_root(tmp_path, reboot=True, security=False, swap=False)
    runner = fake_runner({
        "systemctl --failed": (0, "docker.service loaded failed failed Docker\n"),
        "dpkg --audit": (0, ""),
        "apt list": (0, APT_LIST),
        "timedatectl": (0, "yes\n"),
        "systemctl is-active heimdall.service": (3, "inactive\n"),
        "journalctl": (0, ""),
    })
    checks = {c.key: c for c in doctor.Doctor(runner, root).run()}
    assert checks["units"].status == doctor.FAIL
    assert checks["reboot"].status == doctor.WARN
    assert "linux-image-amd64" in checks["reboot"].message
    assert checks["security-repo"].status == doctor.FAIL
    assert checks["firewall"].status == doctor.WARN
    assert checks["updates"].status == doctor.WARN
    assert checks["swap"].status == doctor.WARN
    assert checks["time"].status == doctor.OK
    assert doctor.exit_code(list(checks.values())) == 2


def test_doctor_healthy_system(tmp_path, fake_runner, monkeypatch):
    monkeypatch.setattr(doctor.common, "which", lambda cmd: "/usr/bin/" + cmd)
    root = make_root(tmp_path)
    (root / "etc" / "timeshift").mkdir()
    (root / "etc" / "timeshift" / "timeshift.json").write_text("{}")
    runner = fake_runner({
        "systemctl --failed": (0, ""),
        "dpkg --audit": (0, ""),
        "apt list": (0, "Listing... Done\n"),
        "timedatectl": (0, "yes\n"),
        "systemctl is-active heimdall.service": (0, "active\n"),
        "journalctl": (0, ""),
    })
    checks = doctor.Doctor(runner, root).run()
    bad = [c for c in checks if c.status in (doctor.WARN, doctor.FAIL) and not c.key.startswith("disk")]
    assert bad == []
    rendered = doctor.render(checks)
    assert "problème(s)" in rendered


def test_a_crashing_check_becomes_a_warning(tmp_path, fake_runner, monkeypatch):
    doc = doctor.Doctor(fake_runner(), make_root(tmp_path))

    def boom():
        raise RuntimeError("panne")

    monkeypatch.setattr(doc, "all_checks", lambda: [boom])
    checks = doc.run()
    assert checks[0].status == doctor.WARN and "panne" in checks[0].message


def test_doctor_demarre_sur_un_instantane(tmp_path, fake_runner):
    root = make_root(tmp_path)
    (root / "proc" / "self").mkdir()
    (root / "proc" / "self" / "mountinfo").write_text(
        "26 1 0:25 /timeshift-btrfs/snapshots/2026-10-02_06-00-02/@ / rw,relatime - btrfs /dev/vda3 rw\n")
    [check] = doctor.Doctor(fake_runner({}), root).check_snapshots()
    assert check.status == doctor.WARN and "02/10/2026 à 06:00" in check.message
    assert check.hint.startswith("norns restore 2026-10-02_06-00-02")
