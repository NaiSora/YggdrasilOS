#!/usr/bin/env python3
"""Les sources que live-build ne joint pas à une image, aux versions exactes (GPL).

    sources-completes.py ISO DOSSIER_LIVE SOURCES.tar SORTIE.tar [--cache DOSSIER] [--liste]

lb source ne prend que les paquets du système live. Une image contient aussi l'installateur
Debian (son initrd et ses paquets udeb, dans /pool-udeb), les paquets de /pool, les chargeurs
d'amorçage copiés pendant la phase binary (shim, GRUB signé, isolinux, loadlin), et du code que
d'autres paquets embarquent (Built-Using ; un noyau signé vient du paquet source linux). Ce script
en dresse l'inventaire, retire ce que SOURCES.tar (fait par lb source) contient déjà, puis
télécharge le reste : depuis l'archive Debian (apt-get source), sinon depuis snapshot.debian.org.
Chaque fichier est vérifié contre les sommes SHA-256 de son .dsc. SORTIE.tar suit la disposition
de live-build (source/debian/<préfixe>/<paquet>/…) et liste son contenu dans COMPLEMENT.txt.

--cache : dossier où garder les téléchargements (une reprise ne retélécharge rien)
--liste : afficher les paquets source manquants, sans rien télécharger
Il faut : python3, osirrox (xorriso), dpkg-deb, cpio, apt-get, et le réseau.
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import json
import lzma
import os
import re
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


def inventaire(iso: str, live: str) -> set[tuple[str, str]]:
    sources: set[tuple[str, str]] = set()
    # Le système live
    statut = Path(live, "chroot/var/lib/dpkg/status").read_text(encoding="utf-8")
    for bloc in statut.split("\n\n"):
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
    # Les chargeurs d'amorçage
    for paquet in CHARGEURS:
        debs = sorted(glob.glob(f"{live}/cache/packages.binary/{paquet}_*.deb"))
        if debs:
            ajouter(sources, paragraphe(subprocess.run(["dpkg-deb", "-f", debs[-1]], capture_output=True,
                                                       text=True).stdout))
    sources |= noyaux_signes(sources)
    return {(n, v) for n, v in sources if not n.startswith("yggdrasil")}  # le code d'Yggdrasil : ce dépôt


def noyaux_signes(sources: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Un noyau signé (paquets udeb compris, qui ne le disent pas) vient du paquet source linux."""
    return {("linux", v[:-2] + "-1") for n, v in sources if n == "linux-signed-amd64" and v.endswith("+1")}


def deja_la(archive: str) -> set[tuple[str, str]]:
    """Les paquets source (nom, version sans époque) d'une archive de lb source."""
    presents = set()
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


def main(argv: list[str]) -> int:
    iso, live, archive, sortie = argv[1:5]
    cache = Path(argv[argv.index("--cache") + 1]) if "--cache" in argv else Path(tempfile.mkdtemp())
    manquants = sorted((n, v) for n, v in inventaire(iso, live) if (n, sans_epoque(v)) not in deja_la(archive))
    if "--liste" in argv:
        for n, v in manquants:
            print(f"{n}\t{v}")
        return 0
    sources_apt()
    origines: dict[str, int] = {}
    for nom, version in manquants:
        origine = telecharger(cache / "source" / "debian" / prefixe(nom) / nom, nom, version)
        origines[origine] = origines.get(origine, 0) + 1
    with tarfile.open(sortie, "w") as tar:
        texte = ("Sources des paquets de l'image que live-build (lb source) ne joint pas : installateur Debian,\n"
                 "chargeurs d'amorçage, code embarqué (Built-Using). Paquet source et version :\n\n"
                 + "".join(f"{n} {v}\n" for n, v in manquants)).encode("utf-8")
        info = tarfile.TarInfo("COMPLEMENT.txt")
        info.size, info.mtime = len(texte), int(time.time())
        tar.addfile(info, fileobj=__import__("io").BytesIO(texte))
        for nom, version in manquants:
            dossier = cache / "source" / "debian" / prefixe(nom) / nom
            dsc = dossier / f"{nom}_{sans_epoque(version)}.dsc"
            fichiers = [dsc.name] + re.findall(r"^ \S+ \d+ (\S+)$", dsc.read_text(encoding="utf-8", errors="replace"), re.M)
            for f in dict.fromkeys(fichiers):
                tar.add(dossier / f, arcname=f"source/debian/{prefixe(nom)}/{nom}/{f}")
    detail = ", ".join(f"{n} depuis {o}" for o, n in sorted(origines.items()))
    print(f"{len(manquants)} paquets source ajoutés ({detail}) : {sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
