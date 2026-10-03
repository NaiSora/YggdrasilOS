"""scripts/sources-completes.py : les sources que live-build ne joint pas à une image."""
import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sources-completes.py"
spec = importlib.util.spec_from_file_location("sources_completes", SCRIPT)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def test_paragraphe_lit_les_lignes_de_suite():
    c = sc.paragraphe("Package: docker.io\nBuilt-Using: continuity (= 0.3.0-1),\n docker-registry (= 2.8.3+ds1-2)\n")
    assert c["Package"] == "docker.io"
    assert c["Built-Using"] == "continuity (= 0.3.0-1), docker-registry (= 2.8.3+ds1-2)"


def test_ajouter_suit_source_et_built_using():
    sources = set()
    sc.ajouter(sources, {"Package": "busybox", "Version": "1:1.37.0-6+b9", "Source": "busybox (1:1.37.0-6)"})
    sc.ajouter(sources, {"Package": "grub-efi-amd64-signed", "Version": "1+2.12+9+deb13u2",
                         "Built-Using": "grub2 (= 2.12-9+deb13u2)"})
    sc.ajouter(sources, {"Package": "nano", "Version": "8.4-1"})
    assert sources == {("busybox", "1:1.37.0-6"), ("grub-efi-amd64-signed", "1+2.12+9+deb13u2"),
                       ("grub2", "2.12-9+deb13u2"), ("nano", "8.4-1")}


def test_un_noyau_signe_vient_du_paquet_linux():
    sources = {("linux-signed-amd64", "6.12.107+1"), ("linux-signed-amd64", "6.12.94+1"), ("nano", "8.4-1")}
    assert sc.noyaux_signes(sources) == {("linux", "6.12.107-1"), ("linux", "6.12.94-1")}


def test_prefixe_comme_l_archive_debian():
    assert sc.prefixe("linux") == "l"
    assert sc.prefixe("libselinux") == "libs"
    assert sc.sans_epoque("1:1.37.0-6") == "1.37.0-6"


def test_complet_verifie_les_sommes_du_dsc(tmp_path):
    contenu = b"le code source"
    (tmp_path / "nano_8.4.orig.tar.xz").write_bytes(contenu)
    somme = hashlib.sha256(contenu).hexdigest()
    (tmp_path / "nano_8.4-1.dsc").write_text(
        f"Source: nano\nChecksums-Sha256:\n {somme} {len(contenu)} nano_8.4.orig.tar.xz\nFiles:\n", encoding="utf-8")
    assert sc.complet(tmp_path, "nano", "8.4-1")
    (tmp_path / "nano_8.4.orig.tar.xz").write_bytes(b"altere")
    assert not sc.complet(tmp_path, "nano", "8.4-1")
    assert not sc.complet(tmp_path, "nano", "8.5-1")


def test_versions_des_chargeurs_dans_le_journal(tmp_path):
    journal = tmp_path / "build.log"
    journal.write_text("Setting up loadlin (1.6e-1) ...\n"  # avant la phase binary : ignoré
                       "[2026-10-02 16:30:01] lb binary_grub-efi\n"
                       "Setting up shim-signed:amd64 (1.51~1+deb13u1+16.1-2~deb13u1) ...\n"
                       "Setting up mtools (4.0.48-1) ...\n"
                       "[2026-10-02 16:31:00] lb binary_loadlin\n"
                       "Setting up loadlin (1.6f-13) ...\n"
                       "[2026-10-02 16:40:00] lb source\n"
                       "Setting up isolinux (3:6.04) ...\n", encoding="utf-8")
    assert sc.versions_du_journal(str(journal)) == {"shim-signed": "1.51~1+deb13u1+16.1-2~deb13u1",
                                                    "loadlin": "1.6f-13"}


def test_reprendre_lit_une_archive_en_morceaux(tmp_path):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for nom, contenu in (("source/debian/n/nano/nano_8.4-1.dsc", b"dsc"),
                             ("source/debian/n/nano/nano_8.4.orig.tar.xz", b"x" * 5000),
                             ("source/debian/v/vim/vim_9.1-1.dsc", b"autre")):
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            tar.addfile(info, io.BytesIO(contenu))
    donnees = archive.getvalue()
    for i in range(0, len(donnees), 4096):  # comme split -b
        (tmp_path / f"a.tar.{i // 4096 + 1:03d}").write_bytes(donnees[i:i + 4096])
    cache = tmp_path / "cache"
    assert sc.reprendre(str(tmp_path / "a.tar.*"), {"nano"}, cache) == 2
    assert (cache / "source/debian/n/nano/nano_8.4.orig.tar.xz").read_bytes() == b"x" * 5000
    assert not (cache / "source/debian/v").exists()
    assert sc.reprendre(str(tmp_path / "a.tar.*"), {"nano"}, cache) == 0  # déjà là


def test_sans_archive_de_lb_source_rien_n_est_deja_la():
    assert sc.deja_la("-") == set()


def test_deja_la_lit_les_dsc_de_lb_source(tmp_path):
    archive = tmp_path / "source.debian.tar"
    with tarfile.open(archive, "w") as tar:
        for nom in ("source/debian/l/linux/linux_6.12.111-1.dsc", "source/debian/l/linux/linux_6.12.111.orig.tar.xz"):
            info = tarfile.TarInfo(nom)
            tar.addfile(info, io.BytesIO(b""))
    assert sc.deja_la(str(archive)) == {("linux", "6.12.111-1")}
