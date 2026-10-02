"""Skíðblaðnir, le navire de Freyr qui se replie dans une poche : Yggdrasil sur une clé USB.

    skidbladnir                         les clés USB branchées, et ce qu'elles portent
    skidbladnir ecrire CLE [ISO]        y écrire Yggdrasil, avec un espace persistant :
                                        tes fichiers, réglages et logiciels restent d'un
                                        démarrage à l'autre (« clé persistante » au menu)
        --persistance TAILLE            taille de cet espace (8G, 500M…), « tout » (défaut)
                                        ou 0 pour une clé live ordinaire
        --chiffrer                      chiffrer l'espace persistant (LUKS) : la phrase de
                                        passe est demandée à chaque démarrage

Sans ISO, Skíðblaðnir copie la session live en cours (le DVD ou la clé d'où tu as
démarré). Tout ce que contient la clé est effacé : son nom (sdb…) est demandé avant.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import common
from .common import Runner, YggError

ETIQUETTE = "persistence"  # cherchée par live-boot
SECTEUR = 512
ALIGNEMENT = 2048  # 1 Mio
PERSISTANCE_MIN = 256 * 1024 * 1024
MEDIUM_LIVE = Path("/run/live/medium")
MAPPEUR = "skidbladnir-persistance"


@dataclass
class Disque:
    nom: str
    chemin: str
    taille: int
    type: str = "disk"
    transport: str = ""
    amovible: bool = False
    modele: str = ""
    etiquettes: list[str] = field(default_factory=list)
    systemes: list[str] = field(default_factory=list)
    montages: list[str] = field(default_factory=list)

    @property
    def est_cle(self) -> bool:
        return self.type == "disk" and (self.transport == "usb" or self.amovible)

    @property
    def porte_yggdrasil(self) -> bool:
        return any(e.upper().startswith("YGGDRASIL") for e in self.etiquettes)

    @property
    def persistante(self) -> bool:
        return ETIQUETTE in self.etiquettes or "crypto_LUKS" in self.systemes


def _vrai(valeur) -> bool:
    return valeur is True or str(valeur).lower() in ("1", "true")


def parse_lsblk(texte: str) -> list[Disque]:
    """Sortie JSON de « lsblk -J -b -o NAME,PATH,SIZE,TRAN,RM,HOTPLUG,TYPE,MODEL,LABEL,FSTYPE,MOUNTPOINTS »."""
    try:
        data = json.loads(texte or "{}")
    except ValueError:
        return []
    disques = []

    def descendants(dev: dict):
        for enfant in dev.get("children") or []:
            yield enfant
            yield from descendants(enfant)

    for dev in data.get("blockdevices", []):
        tous = [dev, *descendants(dev)]
        montages = []
        for d in tous:
            points = d.get("mountpoints") or ([d["mountpoint"]] if d.get("mountpoint") else [])
            montages += [m for m in points if m]
        disques.append(Disque(
            nom=dev.get("name", ""), chemin=dev.get("path") or f"/dev/{dev.get('name', '')}",
            taille=int(dev.get("size") or 0), type=dev.get("type", ""), transport=dev.get("tran") or "",
            amovible=_vrai(dev.get("rm")) or _vrai(dev.get("hotplug")), modele=(dev.get("model") or "").strip(),
            etiquettes=[d["label"] for d in tous if d.get("label")],
            systemes=[d["fstype"] for d in tous if d.get("fstype")], montages=montages))
    return disques


def lister(runner: Runner) -> list[Disque]:
    _, sortie = runner.query(["lsblk", "-J", "-b", "-o",
                              "NAME,PATH,SIZE,TRAN,RM,HOTPLUG,TYPE,MODEL,LABEL,FSTYPE,MOUNTPOINTS"])
    return parse_lsblk(sortie)


# --------------------------------------------------------------------------
# L'image : ISO 9660 hybride (MBR + ISO), lue sans rien monter
# --------------------------------------------------------------------------

def lire_pvd(pvd: bytes) -> tuple[int, str]:
    """Le descripteur de volume primaire (secteur 16) : taille de l'image en octets, nom du volume."""
    if len(pvd) < 190 or pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise YggError("ce n'est pas une image ISO.")
    blocs = int.from_bytes(pvd[80:84], "little")
    taille_bloc = int.from_bytes(pvd[128:130], "little") or 2048
    return blocs * taille_bloc, pvd[40:72].decode("ascii", errors="replace").strip()


def entrees_mbr(mbr: bytes) -> list[tuple[int, int, int]]:
    """(type, premier secteur, nombre de secteurs) des quatre entrées primaires."""
    if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
        raise YggError("pas de table de partitions MBR sur l'image (ISO non hybride ?).")
    return [(mbr[446 + 16 * i + 4], int.from_bytes(mbr[446 + 16 * i + 8:446 + 16 * i + 12], "little"),
             int.from_bytes(mbr[446 + 16 * i + 12:446 + 16 * i + 16], "little")) for i in range(4)]


def aligner(secteur: int, pas: int = ALIGNEMENT) -> int:
    return -(-secteur // pas) * pas


def mbr_avec_persistance(mbr: bytes, debut: int, secteurs: int) -> tuple[bytes, int]:
    """Le MBR de l'image, plus une partition Linux (0x83) : (nouveau MBR, numéro de la partition)."""
    entrees = entrees_mbr(mbr)
    fin_image = max(d + n for _, d, n in entrees)
    if debut < fin_image:
        raise YggError("l'espace persistant chevaucherait l'image.")
    for i, (_, d, n) in enumerate(entrees):
        if d == 0 and n == 0:
            entree = (b"\x00\xfe\xff\xff\x83\xfe\xff\xff" + debut.to_bytes(4, "little")
                      + secteurs.to_bytes(4, "little"))
            nouveau = mbr[:446 + 16 * i] + entree + mbr[446 + 16 * (i + 1):]
            return nouveau, i + 1
    raise YggError("plus de place dans la table de partitions de l'image.")


def parse_taille(texte: str) -> int | None:
    """« 8G », « 500M », « 0 » → octets ; « tout » → None (toute la place restante)."""
    texte = texte.strip().lower().replace(",", ".")
    if texte in ("tout", "max", "toute"):
        return None
    if texte in ("0", "non", "aucune"):
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgt]?)(?:io|o|b|ib)?", texte)
    if not m:
        raise YggError(f"taille illisible : {texte} (exemples : 8G, 500M, tout, 0)")
    return int(float(m.group(1)) * 1024 ** " kmgt".index(m.group(2) or " "))


def partition(chemin: str, numero: int) -> str:
    return f"{chemin}p{numero}" if chemin[-1].isdigit() else f"{chemin}{numero}"


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------

def lire_octets(runner: Runner, chemin: str, decalage: int, nombre: int) -> bytes:
    """Lire quelques octets d'un périphérique (en administrateur)."""
    script = 'dd if="$1" bs=512 skip="$2" count="$3" status=none | base64 -w0'
    _, sortie = runner.query(["sh", "-c", script, "sh", chemin, str(decalage // 512), str(-(-nombre // 512))],
                             root=not os.access(chemin, os.R_OK))
    try:
        return base64.b64decode(sortie.strip() or b"")[:nombre]
    except ValueError:
        return b""


def source_live(runner: Runner, disques: list[Disque]) -> str:
    """Le disque d'où la session live a démarré (DVD ou clé)."""
    if not common.is_live_session():
        raise YggError("donne le chemin de l'image ISO d'Yggdrasil (skidbladnir ecrire CLE fichier.iso).")
    _, source = runner.query(["findmnt", "-no", "SOURCE", str(MEDIUM_LIVE)])
    source = source.strip()
    if not source:
        raise YggError(f"support de la session live introuvable ({MEDIUM_LIVE}).")
    _, parent = runner.query(["lsblk", "-no", "PKNAME", source])
    parent = parent.strip().splitlines()[0] if parent.strip() else ""
    return f"/dev/{parent}" if parent else source


def trouver(nom: str, disques: list[Disque]) -> Disque:
    nom = nom.removeprefix("/dev/")
    for d in disques:
        if d.nom == nom:
            return d
    raise YggError(f"aucun disque « {nom} » (skidbladnir liste les clés branchées).")


def verifier_cible(cible: Disque, source: str, loop_permis: bool = False) -> None:
    if cible.type == "loop" and loop_permis:
        return
    if not cible.est_cle:
        raise YggError(f"{cible.chemin} n'est pas une clé USB ni un disque amovible : Skíðblaðnir refuse d'y toucher.")
    systeme = [m for m in cible.montages if m in ("/", "/boot", "/boot/efi", "/home", str(MEDIUM_LIVE))]
    if systeme or source == cible.chemin:
        raise YggError(f"{cible.chemin} porte le système en marche ({', '.join(systeme) or 'session live'}).")


def ecrire(runner: Runner, cible: Disque, source: str, taille_image: int, mbr_image: bytes, *,
           persistance: int | None, chiffrer: bool, phrase: Path | None, depuis_peripherique: bool) -> None:
    # 1. Démonter ce que le bureau aurait monté
    for point in sorted(cible.montages, reverse=True):
        runner.run(["umount", point], root=True, check=False)
    if chiffrer:
        runner.run(["cryptsetup", "close", MAPPEUR], root=True, check=False, capture=True)

    # 2. L'image, octet pour octet
    common.step(f"écriture d'Yggdrasil ({common.human_size(taille_image)}) — quelques minutes")
    dd = ["dd", f"if={source}", f"of={cible.chemin}", "bs=4M", "conv=fsync", "status=progress"]
    if depuis_peripherique:
        dd += ["iflag=count_bytes", f"count={taille_image}"]
    runner.run(dd, root=True)
    if persistance == 0:
        runner.run(["sync"])
        return

    # 3. L'espace persistant, juste après l'image
    debut = aligner(max(d + n for _, d, n in entrees_mbr(mbr_image)))
    fin = cible.taille // SECTEUR
    secteurs = (fin - debut) if persistance is None else min(persistance // SECTEUR, fin - debut)
    secteurs -= secteurs % ALIGNEMENT
    if secteurs * SECTEUR < PERSISTANCE_MIN:
        raise YggError("la clé est trop petite pour un espace persistant (256 Mio au moins après l'image).")
    nouveau, numero = mbr_avec_persistance(mbr_image, debut, secteurs)
    common.step(f"espace persistant : {common.human_size(secteurs * SECTEUR)}" + (", chiffré" if chiffrer else ""))
    with tempfile.NamedTemporaryFile(prefix="skidbladnir-", suffix=".mbr", delete=False) as tmp:
        tmp.write(nouveau)
    try:
        runner.run(["dd", f"if={tmp.name}", f"of={cible.chemin}", "bs=512", "count=1", "conv=notrunc,fsync"],
                   root=True)
    finally:
        os.unlink(tmp.name)
    runner.run(["partx", "-u", cible.chemin], root=True, check=False)
    if common.which("udevadm"):
        runner.run(["udevadm", "settle"], root=True, check=False)
    part = partition(cible.chemin, numero)
    creer_noeud(runner, part)

    systeme = part
    if chiffrer:
        cle = ["--key-file", str(phrase)] if phrase else []
        runner.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", *cle, part], root=True)
        runner.run(["cryptsetup", "open", *cle, part, MAPPEUR], root=True)
        systeme = f"/dev/mapper/{MAPPEUR}"
    try:
        runner.run(["mkfs.ext4", "-F", "-q", "-L", ETIQUETTE, systeme], root=True)
        point = tempfile.mkdtemp(prefix="skidbladnir-")
        runner.run(["mount", systeme, point], root=True)
        try:
            # live-boot : tout le système (« / ») garde ses changements sur la clé
            runner.write_file(Path(point) / "persistence.conf", "/ union\n", root=True)
        finally:
            runner.run(["umount", point], root=True, check=False)
            os.rmdir(point)
    finally:
        if chiffrer:
            runner.run(["cryptsetup", "close", MAPPEUR], root=True, check=False)
    runner.run(["sync"])


def creer_noeud(runner: Runner, chemin: str) -> None:
    """Sans udev (conteneur), le nœud de la nouvelle partition est créé (ou recréé) à la main."""
    if runner.dry_run:
        return
    numeros = common.read_text(f"/sys/class/block/{Path(chemin).name}/dev").strip()
    if ":" not in numeros:
        return
    majeur, mineur = (int(x) for x in numeros.split(":"))
    try:
        st = os.stat(chemin)
    except OSError:
        st = None
    if st and stat.S_ISBLK(st.st_mode) and (os.major(st.st_rdev), os.minor(st.st_rdev)) == (majeur, mineur):
        return  # udev l'a fait
    if st:
        runner.run(["rm", "-f", chemin], root=True)  # nœud périmé d'une écriture précédente
    runner.run(["mknod", chemin, "b", str(majeur), str(mineur)], root=True)


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def cmd_liste(args, runner: Runner, config) -> int:
    cles = [d for d in lister(runner) if d.est_cle]
    common.title("Skíðblaðnir : les clés à bord")
    if not cles:
        common.info("Aucune clé USB branchée.")
        return 0
    lignes = []
    for d in cles:
        porte = ("Yggdrasil" + (" persistante" if d.persistante else "")) if d.porte_yggdrasil else \
            (", ".join(sorted(set(d.etiquettes))) or "—")
        lignes.append((d.chemin, common.human_size(d.taille), d.modele or "?", porte))
    print(common.table(lignes, headers=("clé", "taille", "modèle", "contenu")))
    print()
    common.info(common.dim("« skidbladnir ecrire sdX » y met Yggdrasil avec un espace persistant."))
    return 0


def cmd_ecrire(args, runner: Runner, config) -> int:
    disques = lister(runner)
    cible = trouver(args.cle, disques)
    persistance = parse_taille(args.persistance)
    phrase = common.expand(args.mot_de_passe) if args.mot_de_passe else None
    if args.chiffrer and persistance == 0:
        raise YggError("--chiffrer concerne l'espace persistant : il faut --persistance différent de 0.")
    if args.chiffrer and not common.which("cryptsetup"):
        raise YggError("cryptsetup est nécessaire pour chiffrer (sudo apt install cryptsetup).")

    if args.iso:
        source = str(common.expand(args.iso))
        if not Path(source).is_file():
            raise YggError(f"image introuvable : {source}")
        with open(source, "rb") as fh:
            mbr_image = fh.read(SECTEUR)
            fh.seek(16 * 2048)
            pvd = fh.read(2048)
        depuis_peripherique = False
    else:
        source = source_live(runner, disques)
        mbr_image = lire_octets(runner, source, 0, SECTEUR)
        pvd = lire_octets(runner, source, 16 * 2048, 2048)
        depuis_peripherique = True
    taille_image, volume = lire_pvd(pvd)
    if args.iso:
        taille_image = max(taille_image, Path(source).stat().st_size)
    if not volume.upper().startswith("YGGDRASIL"):
        raise YggError(f"cette image n'est pas Yggdrasil (volume « {volume} ») : Skíðblaðnir ne porte que l'arbre.")
    verifier_cible(cible, source, loop_permis=args.loop)
    if cible.taille < taille_image:
        raise YggError(f"{cible.chemin} est trop petite : {common.human_size(cible.taille)} pour une image de "
                       f"{common.human_size(taille_image)}.")

    common.title("Skíðblaðnir met Yggdrasil dans ta poche")
    common.step(f"clé : {cible.chemin} — {cible.modele or 'modèle inconnu'}, {common.human_size(cible.taille)}")
    common.step(f"image : {source if args.iso else 'la session live en cours'} ({volume})")
    reste = cible.taille - aligner(taille_image // SECTEUR) * SECTEUR
    if persistance == 0:
        common.step("sans espace persistant (une clé live ordinaire)")
    else:
        taille_p = reste if persistance is None else min(persistance, reste)
        common.step(f"espace persistant : {common.human_size(max(taille_p, 0))}" + (", chiffré (LUKS)" if args.chiffrer else ""))
    common.warn(f"tout ce que contient {cible.chemin} sera effacé.")
    if not args.yes:
        if not sys.stdin or not sys.stdin.isatty():
            raise YggError("pas de terminal pour confirmer : relance avec --yes si tu es sûr de la clé.")
        if common.ask(f"Pour confirmer, tape le nom de la clé ({cible.nom})") != cible.nom:
            common.warn("abandon : rien n'a été écrit.")
            return 1
    ecrire(runner, cible, source, taille_image, mbr_image, persistance=persistance, chiffrer=args.chiffrer,
           phrase=phrase, depuis_peripherique=depuis_peripherique)
    print()
    common.ok("Yggdrasil est dans ta poche.")
    if persistance != 0:
        common.info("Démarre sur la clé et choisis « clé persistante » dans le menu : ce que tu installes et "
                    "enregistres y restera.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-n", "--dry-run", action="store_true", help="simuler")
    opts.add_argument("-v", "--verbose", action="store_true")
    opts.add_argument("-y", "--yes", action="store_true", help="ne pas demander le nom de la clé")

    parser = argparse.ArgumentParser(prog="skidbladnir", parents=[opts],
                                     description="Skíðblaðnir : Yggdrasil sur une clé USB persistante.")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    sub.add_parser("liste", help="les clés USB branchées", parents=[opts]).set_defaults(func=cmd_liste)
    p = sub.add_parser("ecrire", help="écrire Yggdrasil sur une clé", parents=[opts])
    p.add_argument("cle", help="la clé (sdb, /dev/sdb…)")
    p.add_argument("iso", nargs="?", help="l'image ISO (défaut : la session live en cours)")
    p.add_argument("--persistance", default="tout", metavar="TAILLE", help="8G, 500M, tout (défaut) ou 0")
    p.add_argument("--chiffrer", action="store_true", help="chiffrer l'espace persistant (LUKS)")
    p.add_argument("--mot-de-passe", metavar="FICHIER", help="phrase de passe lue dans un fichier (scripts)")
    p.add_argument("--loop", action="store_true", help=argparse.SUPPRESS)  # tests : périphérique loop permis
    p.set_defaults(func=cmd_ecrire)
    return parser


def _main(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["liste", *(sys.argv[1:] if argv is None else argv)])
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner, common.load_config())


def main(argv=None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
