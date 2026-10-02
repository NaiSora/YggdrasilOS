#!/usr/bin/env python3
"""Catalogue français complet pour GRUB (paquet yggdrasil-base).

Le catalogue français de GRUB 2.12 ne traduit aucune chaîne des scripts de /etc/grub.d : le
menu affichait « Advanced options for Yggdrasil GNU/Linux ». On forme un catalogue fr_FR,
celui de grub-common complété par assets/grub-fr.po. Avec LANG=fr_FR.UTF-8, gettext le
préfère à fr (grub-mkconfig écrit alors le menu en français), et grub-install le copie dans
/boot/grub/locale, où GRUB le charge à la place de fr.mo. GRUB ne lit qu'un catalogue : d'où
une copie complète, et non nos seuls ajouts.

    catalogue-grub.py fusionner ORIGINE.mo AJOUTS.po SORTIE.mo
    catalogue-grub.py verifier ORIGINE.mo AJOUTS.po SCRIPT...
"""
import re
import struct
import sys
from pathlib import Path

MAGIE = 0x950412DE
ECHAPPEMENTS = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
# Les chaînes données à gettext dans un script shell, entre guillemets doubles
APPEL_SHELL = re.compile(r'gettext(?:_printf|_quoted)?\s+"((?:[^"\\]|\\.)*)"')
# Passées à gettext par une variable : introuvables dans un appel
INDIRECTES = {"recovery mode"}  # GRUB_RECOVERY_TITLE (grub-mkconfig, 10_linux)


def lire_mo(chemin) -> dict[bytes, bytes]:
    """Toutes les entrées d'un .mo, octets bruts (en-tête, pluriels et contextes compris)."""
    donnees = Path(chemin).read_bytes()
    for ordre in "<>":
        if len(donnees) >= 28 and struct.unpack_from(ordre + "I", donnees)[0] == MAGIE:
            break
    else:
        raise ValueError(f"{chemin} : ce n'est pas un catalogue .mo")
    _, nombre, originaux, traductions = struct.unpack_from(ordre + "4I", donnees, 4)
    entrees = {}
    for i in range(nombre):
        lo, po = struct.unpack_from(ordre + "2I", donnees, originaux + 8 * i)
        lt, pt = struct.unpack_from(ordre + "2I", donnees, traductions + 8 * i)
        entrees[donnees[po:po + lo]] = donnees[pt:pt + lt]
    return entrees


def ecrire_mo(entrees: dict[bytes, bytes], chemin) -> None:
    """Un .mo trié (GRUB y cherche par dichotomie), sans table de hachage."""
    cles = sorted(entrees)
    debut = 28 + 16 * len(cles)
    table_o, table_t, corps = [], [], bytearray()
    for cle in cles:
        table_o.append((len(cle), debut + len(corps)))
        corps += cle + b"\0"
    for cle in cles:
        table_t.append((len(entrees[cle]), debut + len(corps)))
        corps += entrees[cle] + b"\0"
    en_tete = struct.pack("<7I", MAGIE, 0, len(cles), 28, 28 + 8 * len(cles), 0, debut)
    tables = b"".join(struct.pack("<2I", *paire) for paire in table_o + table_t)
    Path(chemin).write_bytes(en_tete + tables + bytes(corps))


def texte_po(ligne: str) -> str:
    ligne = ligne.strip()
    if len(ligne) < 2 or ligne[0] != '"' or ligne[-1] != '"':
        raise ValueError(f"chaîne .po attendue : {ligne}")
    return re.sub(r"\\(.)", lambda m: ECHAPPEMENTS[m.group(1)], ligne[1:-1])


def lire_po(chemin) -> list[tuple[str, str]]:
    """Les paires (msgid, msgstr) d'un .po simple, sans pluriels ni contextes ; sans l'en-tête."""
    paires, valeurs, champ = [], {}, None

    def finir():
        if valeurs.get("msgid"):
            paires.append((valeurs["msgid"], valeurs["msgstr"]))
        valeurs.clear()

    for ligne in Path(chemin).read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        mot, _, reste = ligne.partition(" ")
        if mot in ("msgid", "msgstr"):
            if mot == "msgid":
                finir()
            champ = mot
            valeurs[champ] = texte_po(reste)
        elif ligne.startswith('"') and champ:
            valeurs[champ] += texte_po(ligne)
        else:
            raise ValueError(f"{chemin} : ligne inattendue : {ligne}")
    finir()
    return paires


def chaines_shell(scripts) -> list[str]:
    """Les msgid des appels à gettext dans des scripts shell, tels que gettext les reçoit."""
    vues = []
    for script in scripts:
        texte = Path(script).read_text(encoding="utf-8", errors="replace")
        for appel in APPEL_SHELL.finditer(texte):
            # Entre guillemets doubles, le shell ne retire l'antislash que devant \ " ` $
            chaine = re.sub(r'\\([\\"`$])', r"\1", appel.group(1))
            if "$" not in chaine and chaine not in vues:
                vues.append(chaine)
    return vues


def fusionner(origine, ajouts, sortie) -> int:
    entrees = lire_mo(origine)
    for msgid, msgstr in lire_po(ajouts):
        entrees[msgid.encode()] = msgstr.encode()
    ecrire_mo(entrees, sortie)
    return 0


def verifier(origine, ajouts, scripts) -> int:
    """Chaque msgid ajouté doit exister dans les scripts ; signale celles qui restent en anglais."""
    connues = set(chaines_shell(scripts)) | INDIRECTES
    traduites = {k.decode(errors="replace") for k, v in lire_mo(origine).items() if v}
    erreurs = 0
    for msgid, msgstr in lire_po(ajouts):
        if msgid not in connues:
            print(f"absente des scripts : {msgid!r}", file=sys.stderr)
            erreurs += 1
        if msgid.count("%") != msgstr.count("%") or msgid.count("\\n") != msgstr.count("\\n"):
            print(f"formats différents : {msgid!r} → {msgstr!r}", file=sys.stderr)
            erreurs += 1
    ajoutees = {msgid for msgid, _ in lire_po(ajouts)}
    for chaine in sorted(connues - ajoutees - traduites):
        print(f"reste en anglais : {chaine!r}")
    return 1 if erreurs else 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 4 and args[0] == "fusionner":
        return fusionner(*args[1:])
    if len(args) >= 4 and args[0] == "verifier":
        return verifier(args[1], args[2], args[3:])
    print("\n".join(__doc__.strip().splitlines()[-2:]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
