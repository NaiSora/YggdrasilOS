#!/usr/bin/env python3
"""Arbres-monde en ASCII pour le terminal.

    python3 assets/arbre_ascii.py compact > compact.txt       # petit arbre (41 × 20), format fastfetch
    python3 assets/arbre_ascii.py ansi FICHIER > arbre.ansi   # couleurs $1 $2 $3 → ANSI 16 couleurs
    python3 assets/arbre_ascii.py texte FICHIER > arbre.txt   # sans couleur
    python3 assets/arbre_ascii.py issue FICHIER > arbre.issue # console, avant la connexion (agetty)
    python3 assets/arbre_ascii.py apercu FICHIER rendu.png    # rendu de contrôle (python3-pil)

Le grand arbre (assets/arbre-grand.txt) est l'ASCII fourni par l'utilisateur,
mis en couleurs par assets/coloriser_ascii.py. Le petit arbre, pour les
terminaux étroits, est dessiné ici à la main d'après le logo : on ne trace que
la moitié gauche et la colonne centrale, la moitié droite est le miroir exact.
Couleurs : $1 or (anneau, tronc, branches, racines, points), $2 sauge
(feuilles), $3 étoile. Bibliothèque standard uniquement, sauf pour l'aperçu.
"""

from __future__ import annotations

import sys

WIDTH, HEIGHT = 41, 20
CENTER = WIDTH // 2
MIRROR = {"/": "\\", "\\": "/", "(": ")", ")": "(", "<": ">", ">": "<", "`": "'"}
GOLD, LEAF, STAR = "$1", "$2", "$3"
CODES = (GOLD, LEAF, STAR)
# Couleurs de la planche : or #E8CC8C, sauge #79AC99, étoile #FBE39B
PREVIEW = {GOLD: (232, 204, 140), LEAF: (121, 172, 153), STAR: (251, 227, 155)}
# La console Linux ne connaît que 16 couleurs
ANSI = {GOLD: "\033[0;33m", LEAF: "\033[0;32m", STAR: "\033[1;93m"}
RESET = "\033[0m"


class Canvas:
    def __init__(self) -> None:
        self.chars = [[" "] * WIDTH for _ in range(HEIGHT)]
        self.colors = [[GOLD] * WIDTH for _ in range(HEIGHT)]

    def put(self, row: int, col: int, text: str, color: str = GOLD) -> None:
        """Écrit à gauche (ou au centre) et reporte le miroir à droite."""
        for i, ch in enumerate(text):
            x = col + i
            self.chars[row][x], self.colors[row][x] = ch, color
            if x != CENTER:
                self.chars[row][WIDTH - 1 - x] = MIRROR.get(ch, ch)
                self.colors[row][WIDTH - 1 - x] = color

    def text(self) -> str:
        """Le dessin au format des logos fastfetch."""
        out = []
        for chars, colors in zip(self.chars, self.colors, strict=True):
            line, current = [], None
            for ch, color in zip(chars, colors, strict=True):
                if ch != " " and color != current:
                    line.append(color)
                    current = color
                line.append(ch)
            out.append("".join(line).rstrip())
        return "\n".join(out)


def compact() -> Canvas:
    c = Canvas()
    put = c.put
    # Anneau
    put(0, 15, "_____"); put(0, 20, "_")
    put(1, 10, "_.-''")
    put(2, 7, ".-'")
    put(3, 5, ".'")
    put(4, 4, "/")
    put(5, 3, "/")
    put(6, 2, "/")
    for r in range(7, 14):
        put(r, 1, "|")
    put(14, 2, "\\")
    put(15, 3, "\\")
    put(16, 4, "\\")
    put(17, 5, "'.")
    put(18, 7, "'-.")
    put(19, 10, "'-.._"); put(19, 15, "_____"); put(19, 20, "_")
    # Points d'or
    put(2, 13, ".")
    put(6, 6, ".")
    put(13, 8, ".")
    put(13, 14, ".")
    # Tige centrale, étoile dans la fourche, tronc
    put(2, 20, "@", LEAF)
    for r in range(3, 10):
        put(r, 20, "|")
    put(10, 20, "*", STAR)
    put(10, 18, "\\")
    for r in range(11, 14):
        put(r, 19, "|")
    # Couronne : brindille du haut, branche haute courbe
    put(3, 19, "\\"); put(2, 18, "@", LEAF)
    put(6, 19, "\\"); put(5, 16, "'-."); put(4, 15, "@", LEAF); put(3, 16, "@", LEAF)
    # Bras : il monte depuis le tronc puis s'incurve vers l'extérieur
    put(9, 17, "\\"); put(8, 16, "\\"); put(7, 13, "'-."); put(6, 10, "'-."); put(6, 9, "@", LEAF)
    put(5, 11, "@", LEAF); put(4, 12, "@", LEAF)
    # Longue branche, qui remonte vers l'extérieur
    put(9, 9, "'-._____"); put(8, 8, "@", LEAF); put(9, 6, "@", LEAF)
    put(8, 12, "@", LEAF)
    # Branches tombantes
    put(10, 11, "/"); put(11, 10, "@", LEAF)
    put(10, 15, "/"); put(11, 14, "@", LEAF)
    put(10, 7, "@", LEAF)
    # Racines
    put(14, 18, "/"); put(14, 20, "|")
    put(14, 11, "_..--''")
    put(15, 7, "_.-'")
    put(15, 17, "/"); put(15, 20, "|")
    put(16, 13, "_.-'"); put(16, 20, "|")
    put(17, 19, "/"); put(17, 11, ".'")
    put(18, 18, "/")
    return c


def segments(line: str) -> list[tuple[str, str]]:
    """Découpe une ligne au format fastfetch en (code couleur, texte)."""
    out, color, start, i = [], GOLD, 0, 0
    while i < len(line):
        if line[i:i + 2] in CODES:
            if i > start:
                out.append((color, line[start:i]))
            color, i = line[i:i + 2], i + 2
            start = i
        else:
            i += 1
    if start < len(line):
        out.append((color, line[start:]))
    return out


def to_ansi(text: str) -> str:
    lines = ("".join(ANSI[c] + t for c, t in segments(line)) + RESET for line in text.splitlines())
    return "\n".join(lines)


def to_issue(text: str) -> str:
    r"""L'arbre en couleurs pour la console, avant la connexion (agetty, /etc/issue.d).

    agetty lit les « \x » comme des séquences (\n : nom de la machine, \4 : adresse
    IPv4) : les barres obliques inverses de l'arbre sont doublées.
    """
    arbre = to_ansi(text).replace("\\", "\\\\")
    largeur = max(len(to_plain(line)) for line in text.splitlines())
    titre = "Yggdrasil · édition serveur"  # la police de la console n'a pas le tiret cadratin
    marge = " " * max((largeur - len(titre)) // 2, 0)
    adresse = r"machine \n · adresse \4 · ssh ygg@\4"
    marge_adresse = " " * max((largeur - len(adresse) + 4) // 2, 0)
    return (f"{arbre}\n\n{marge}{ANSI[GOLD]}{titre}{RESET}\n"
            f"{marge_adresse}{ANSI[LEAF]}{adresse}{RESET}\n\n")


def to_plain(text: str) -> str:
    return "\n".join("".join(t for _, t in segments(line)) for line in text.splitlines())


def preview(text: str, dest: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    cw, ch = 10, 20
    lines = text.splitlines()
    width = max(len(to_plain(line)) for line in lines)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)
    ascent, descent = font.getmetrics()
    top = (ch - (ascent + descent)) // 2
    im = Image.new("RGB", ((width + 4) * cw, (len(lines) + 2) * ch), (9, 28, 49))
    draw = ImageDraw.Draw(im)
    for r, line in enumerate(lines):
        x = 0
        for color, chunk in segments(line):
            for char in chunk:
                if char != " ":
                    draw.text(((x + 2) * cw, (r + 1) * ch + top), char, font=font, fill=PREVIEW[color])
                x += 1
    im.save(dest)


def main(argv: list[str]) -> int:
    if argv[1:] == ["compact"]:
        print(compact().text())
        return 0
    if len(argv) >= 3 and argv[1] in ("ansi", "texte", "apercu", "issue"):
        with open(argv[2], encoding="utf-8") as f:
            text = f.read().rstrip("\n")
        if argv[1] == "ansi":
            print(to_ansi(text))
            return 0
        if argv[1] == "issue":
            sys.stdout.write(to_issue(text))
            return 0
        if argv[1] == "texte":
            print(to_plain(text))
            return 0
        if len(argv) == 4:
            preview(text, argv[3])
            return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
