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


def test_deja_la_lit_les_dsc_de_lb_source(tmp_path):
    archive = tmp_path / "source.debian.tar"
    with tarfile.open(archive, "w") as tar:
        for nom in ("source/debian/l/linux/linux_6.12.111-1.dsc", "source/debian/l/linux/linux_6.12.111.orig.tar.xz"):
            info = tarfile.TarInfo(nom)
            tar.addfile(info, io.BytesIO(b""))
    assert sc.deja_la(str(archive)) == {("linux", "6.12.111-1")}
