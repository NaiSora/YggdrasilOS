#!/usr/bin/env python3
"""Les sources que live-build ne joint pas à une image, aux versions exactes (GPL).

    sources-completes.py ISO DOSSIER_LIVE SOURCES.tar SORTIE.tar [options]

lb source ne prend que les paquets du système live. Une image contient aussi l'installateur
Debian (son initrd et ses paquets udeb, dans /pool-udeb), les paquets de /pool, les chargeurs
d'amorçage copiés pendant la phase binary (shim, GRUB signé, isolinux, loadlin), et du code que
d'autres paquets embarquent (Built-Using ; un noyau signé vient du paquet source linux). Ce script
en dresse l'inventaire, retire ce que SOURCES.tar (fait par lb source) contient déjà, puis
télécharge le reste : depuis l'archive Debian (apt-get source), sinon depuis snapshot.debian.org.
Chaque fichier est vérifié contre les sommes SHA-256 de son .dsc. SORTIE.tar suit la disposition
de live-build (source/debian/<préfixe>/<paquet>/…) et liste son contenu dans COMPLEMENT.txt.

SOURCES.tar vaut « - » pour une image faite sans lb source : SORTIE.tar contient alors toutes les
sources de l'image (et les liste dans SOURCES.txt). SORTIE.tar vaut « - » pour écrire l'archive sur
la sortie standard (à couper en morceaux par split, sans copie intermédiaire).

--cache DOSSIER      garder les téléchargements (une reprise ne retélécharge rien)
--liste              afficher les paquets source manquants, sans rien télécharger
--statut-iso         lire la base dpkg du système dans l'image (filesystem.squashfs) plutôt que dans
                     le chroot de DOSSIER_LIVE : pour une image plus ancienne que l'espace live-build
--journal BUILD.log  les versions des chargeurs d'amorçage, prises dans le journal de construction
                     de l'image (leurs paquets .deb restent pris dans DOSSIER_LIVE/cache)
--reprendre MOTIF    reprendre les fichiers d'archives de sources existantes (MOTIF : leurs morceaux,
                     par exemple « out/yggdrasil-1.0.1-amd64-sources.tar.* ») avant de télécharger
Il faut : python3, osirrox (xorriso), unsquashfs, dpkg-deb, cpio, apt-get, et le réseau.
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

MIROIR = os.environ.get("MIRROR", "http://deb.debian.org/debian/").rstrip("/")
SECURITE = os.environ.get("SECURITY_MIRROR", "http://security.debian.org/debian-security/").rstrip("/")
SUITE = "trixie"
# Copiés dans l'image pendant la phase binary (live-build les installe puis les retire)
CHARGEURS = ("grub-efi-amd64-signed", "grub-efi-amd64-bin", "grub-efi-ia32-bin", "shim-signed",
             "shim-helpers-amd64-signed", "isolinux", "syslinux-common", "loadlin")
BUILT_USING = re.compile(r"([^ ,]+) \(= ([^)]+)\)")


def dire(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def paragraphe(texte: str) -> dict[str, str]:
    champs: dict[str, str] = {}
    cle = None
    for ligne in texte.splitlines():
        if ligne[:1] in (" ", "\t") and cle:
            champs[cle] += " " + ligne.strip()
        elif ":" in ligne:
            cle, valeur = ligne.split(":", 1)
            champs[cle] = valeur.strip()
    return champs


def ajouter(sources: set, champs: dict[str, str]) -> None:
    """Le paquet source d'un paquet binaire, et ceux qu'il embarque (Built-Using)."""
    nom, version = champs.get("Source") or champs["Package"], champs.get("Version", "")
    m = re.match(r"(\S+) \((.+)\)", nom)
    if m:
        nom, version = m.groups()
    sources.add((nom, version))
    sources.update(BUILT_USING.findall(champs.get("Built-Using", "")))


def statut_systeme(iso: str, live: str, depuis_iso: bool) -> str:
    """La base dpkg du système live : celle du chroot, ou celle du squashfs de l'image."""
    if not depuis_iso:
        return Path(live, "chroot/var/lib/dpkg/status").read_text(encoding="utf-8")
    # Le squashfs est d'un seul tenant dans l'ISO : unsquashfs le lit en place, à son décalage
    rapport = subprocess.run(["osirrox", "-indev", iso, "-find", "/live/filesystem.squashfs", "-exec", "report_lba",
                              "--"], capture_output=True, text=True).stdout
    m = re.search(r"File data lba:\s*\d+\s*,\s*(\d+)\s*,", rapport)
    if not m:
        raise SystemExit(f"pas de /live/filesystem.squashfs dans {iso}")
    return subprocess.run(["unsquashfs", "-o", str(int(m.group(1)) * 2048), "-cat", iso, "var/lib/dpkg/status"],
                          capture_output=True, check=True, text=True).stdout


def versions_du_journal(journal: str) -> dict[str, str]:
    """Les versions des chargeurs d'amorçage installés pendant la phase binary, d'après le journal."""
    versions: dict[str, str] = {}
    binaire = False
    for ligne in Path(journal).read_text(encoding="utf-8", errors="replace").splitlines():
        if "lb binary_" in ligne:
            binaire = True
        elif "lb source" in ligne:
            binaire = False
        m = re.search(r"Setting up ([^ :]+)(?::\S+)? \(([^)]+)\)", ligne)
        if binaire and m and m.group(1) in CHARGEURS:
            versions[m.group(1)] = m.group(2)
    return versions


def inventaire(iso: str, live: str, depuis_iso: bool = False, journal: str | None = None) -> set[tuple[str, str]]:
    sources: set[tuple[str, str]] = set()
    # Le système live
    for bloc in statut_systeme(iso, live, depuis_iso).split("\n\n"):
        c = paragraphe(bloc)
        if c.get("Package") and "installed" in c.get("Status", ""):
            ajouter(sources, c)
    with tempfile.TemporaryDirectory() as w:
        subprocess.run(["osirrox", "-indev", iso, "-extract", "/pool", f"{w}/pool", "-extract", "/pool-udeb",
                        f"{w}/pool-udeb", "-extract", "/install/initrd.gz", f"{w}/initrd.gz"], capture_output=True)
        # Les paquets posés dans l'image
        for f in glob.glob(f"{w}/pool*/**/*.*deb", recursive=True):
            ajouter(sources, paragraphe(subprocess.run(["dpkg-deb", "-f", f], capture_output=True, text=True).stdout))
        # L'initrd de l'installateur : sa base dpkg ne note pas le paquet source, l'index des udeb le donne
        if Path(w, "initrd.gz").is_file():
            index: dict = {}
            url = f"{MIROIR}/dists/{SUITE}/main/debian-installer/binary-amd64/Packages.xz"
            for bloc in lzma.decompress(urllib.request.urlopen(url, timeout=300).read()).decode("utf-8").split("\n\n"):
                c = paragraphe(bloc)
                if c.get("Package"):
                    index[(c["Package"], c.get("Version", ""))] = c
            os.makedirs(f"{w}/initrd")
            with gzip.open(f"{w}/initrd.gz") as z:
                subprocess.run(["cpio", "-id", "--quiet", "var/lib/dpkg/status"], input=z.read(), cwd=f"{w}/initrd")
            for bloc in Path(w, "initrd/var/lib/dpkg/status").read_text(encoding="utf-8").split("\n\n"):
                c = paragraphe(bloc)
                if not c.get("Package"):
                    continue
                if c["Package"] == "debian-installer":  # l'identité de l'image : « cdrom-isolinux-20250803+deb13u7 »
                    sources.add(("debian-installer", c["Version"].rsplit("-", 1)[-1]))
                elif (c["Package"], c.get("Version", "")) in index:
                    ajouter(sources, index[(c["Package"], c["Version"])])
                else:
                    raise SystemExit(f"udeb de l'initrd absent de l'index de {SUITE} : {c['Package']} {c.get('Version')}")
    # Les chargeurs d'amorçage (à la version du journal, si on le donne)
    voulues = versions_du_journal(journal) if journal else {}
    for paquet in CHARGEURS:
        candidats = [paragraphe(subprocess.run(["dpkg-deb", "-f", deb], capture_output=True, text=True).stdout)
                     for deb in sorted(glob.glob(f"{live}/cache/packages.binary/{paquet}_*.deb"))]
        if paquet in voulues:
            candidats = [c for c in candidats if c.get("Version") == voulues[paquet]]
            if not candidats:
                raise SystemExit(f"{paquet} {voulues[paquet]} (journal) absent de {live}/cache/packages.binary")
        if candidats:
            ajouter(sources, candidats[-1])
    sources |= noyaux_signes(sources)
    return {(n, v) for n, v in sources if not n.startswith("yggdrasil")}  # le code d'Yggdrasil : ce dépôt


def noyaux_signes(sources: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Un noyau signé (paquets udeb compris, qui ne le disent pas) vient du paquet source linux."""
    return {("linux", v[:-2] + "-1") for n, v in sources if n == "linux-signed-amd64" and v.endswith("+1")}


def deja_la(archive: str) -> set[tuple[str, str]]:
    """Les paquets source (nom, version sans époque) d'une archive de lb source (« - » : aucune)."""
    presents: set[tuple[str, str]] = set()
    if archive == "-":
        return presents
    with tarfile.open(archive) as tar:
        for membre in tar:
            m = re.search(r"/([^/]+)_([^/_]+)\.dsc$", membre.name)
            if m:
                presents.add(m.groups())
    return presents


def sans_epoque(version: str) -> str:
    return version.split(":", 1)[-1]


def prefixe(nom: str) -> str:
    return nom[:4] if nom.startswith("lib") and len(nom) > 3 else nom[0]


def complet(dossier: Path, nom: str, version: str) -> bool:
    """Chaque fichier cité par le .dsc est là, avec la bonne somme SHA-256."""
    dsc = dossier / f"{nom}_{sans_epoque(version)}.dsc"
    if not dsc.is_file():
        return False
    bloc = re.search(r"^Checksums-Sha256:\n((?: .+\n?)+)", dsc.read_text(encoding="utf-8", errors="replace"), re.M)
    if not bloc:
        return False
    for ligne in bloc.group(1).splitlines():
        somme, _taille, fichier = ligne.split()
        f = dossier / fichier
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != somme:
            return False
    return True


class Morceaux(io.RawIOBase):
    """Les morceaux d'une archive, lus d'affilée comme un seul fichier."""

    def __init__(self, chemins: list[str]):
        self.fichiers = [open(c, "rb") for c in chemins]  # noqa: SIM115 — fermés à la fin de la lecture
        self.i = 0

    def readable(self) -> bool:
        return True

    def readinto(self, tampon) -> int:
        while self.i < len(self.fichiers):
            n = self.fichiers[self.i].readinto(tampon)
            if n:
                return n
            self.fichiers[self.i].close()
            self.i += 1
        return 0


def reprendre(motif: str, noms: set[str], cache: Path) -> int:
    """Copie dans le cache les fichiers des paquets source voulus qu'une archive existante contient."""
    morceaux = sorted(glob.glob(motif))
    if not morceaux:
        raise SystemExit(f"aucune archive ne correspond à {motif}")
    copies = 0
    with tarfile.open(fileobj=io.BufferedReader(Morceaux(morceaux), 1 << 20), mode="r|") as tar:
        for membre in tar:
            parties = membre.name.split("/")
            if not membre.isfile() or len(parties) != 5 or parties[:2] != ["source", "debian"] or parties[3] not in noms:
                continue
            cible = cache.joinpath(*parties)
            if cible.is_file() and cible.stat().st_size == membre.size:
                continue
            cible.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(membre) as source, open(cible, "wb") as copie:
                shutil.copyfileobj(source, copie, 1 << 20)
            copies += 1
    return copies


def lire(url: str) -> bytes:
    for essai in range(5):
        try:
            with urllib.request.urlopen(url, timeout=600) as r:
                return r.read()
        except OSError:  # snapshot.debian.org limite les débits : on attend, on réessaie
            time.sleep(15 * (essai + 1))
    raise RuntimeError(f"injoignable : {url}")


def telecharger(dossier: Path, nom: str, version: str) -> str:
    dossier.mkdir(parents=True, exist_ok=True)
    if complet(dossier, nom, version):
        return "cache"
    subprocess.run(["apt-get", "source", "--download-only", "-qq", f"{nom}={version}"], cwd=dossier, capture_output=True)
    if complet(dossier, nom, version):
        return "archive"
    donnees = json.loads(lire(f"https://snapshot.debian.org/mr/package/{nom}/{version}/srcfiles?fileinfo=1"))
    for h in donnees.get("result", []):
        (dossier / donnees["fileinfo"][h["hash"]][0]["name"]).write_bytes(lire(f"https://snapshot.debian.org/file/{h['hash']}"))
    if complet(dossier, nom, version):
        return "snapshot"
    raise RuntimeError(f"sources introuvables ou altérées : {nom} {version}")


def sources_apt() -> None:
    """Les dépôts de sources de Debian, pour apt-get source (le conteneur n'a que les paquets)."""
    depots = "".join(
        f"Types: deb-src\nURIs: {uri}\nSuites: {suites}\nComponents: main contrib non-free non-free-firmware\n"
        "Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp\n\n"
        for uri, suites in ((MIROIR, f"{SUITE} {SUITE}-updates {SUITE}-proposed-updates"),
                            (SECURITE, f"{SUITE}-security")))
    Path("/etc/apt/sources.list.d/yggdrasil-sources.sources").write_text(depots, encoding="utf-8")
    subprocess.run(["apt-get", "update", "-qq"], check=True, capture_output=True)


def option(argv: list[str], nom: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == nom]


def main(argv: list[str]) -> int:
    iso, live, archive, sortie = argv[1:5]
    cache = Path(option(argv, "--cache")[0]) if "--cache" in argv else Path(tempfile.mkdtemp())
    journal = (option(argv, "--journal") or [None])[0]
    besoins = inventaire(iso, live, "--statut-iso" in argv, journal)
    presents = deja_la(archive)
    manquants = sorted((n, v) for n, v in besoins if (n, sans_epoque(v)) not in presents)
    if "--liste" in argv:
        for n, v in manquants:
            print(f"{n}\t{v}")
        return 0
    noms = {n for n, _ in manquants}
    for motif in option(argv, "--reprendre"):
        dire(f"{reprendre(motif, noms, cache)} fichiers repris de {motif}")
    sources_apt()
    origines: dict[str, int] = {}
    for nom, version in manquants:
        origine = telecharger(cache / "source" / "debian" / prefixe(nom) / nom, nom, version)
        origines[origine] = origines.get(origine, 0) + 1
    complete = archive == "-"
    flux = sys.stdout.buffer if sortie == "-" else open(sortie, "wb")  # noqa: SIM115
    with tarfile.open(fileobj=flux, mode="w|") as tar:
        entete = ("Sources de tous les paquets de l'image (système, installateur Debian, chargeurs d'amorçage,\n"
                  "code embarqué par Built-Using). Paquet source et version :\n\n" if complete else
                  "Sources des paquets de l'image que live-build (lb source) ne joint pas : installateur Debian,\n"
                  "chargeurs d'amorçage, code embarqué (Built-Using). Paquet source et version :\n\n")
        texte = (entete + "".join(f"{n} {v}\n" for n, v in manquants)).encode("utf-8")
        info = tarfile.TarInfo("SOURCES.txt" if complete else "COMPLEMENT.txt")
        info.size, info.mtime = len(texte), int(time.time())
        tar.addfile(info, fileobj=io.BytesIO(texte))
        for nom, version in manquants:
            dossier = cache / "source" / "debian" / prefixe(nom) / nom
            dsc = dossier / f"{nom}_{sans_epoque(version)}.dsc"
            fichiers = [dsc.name] + re.findall(r"^ \S+ \d+ (\S+)$", dsc.read_text(encoding="utf-8", errors="replace"), re.M)
            for f in dict.fromkeys(fichiers):
                tar.add(dossier / f, arcname=f"source/debian/{prefixe(nom)}/{nom}/{f}")
    if sortie != "-":
        flux.close()
    detail = ", ".join(f"{n} depuis {o}" for o, n in sorted(origines.items()))
    dire(f"{len(manquants)} paquets source ({detail}) : {sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
