#!/usr/bin/env python3
"""Met en couleurs l'arbre ASCII fourni (assets/source/arbre-ascii.txt).

    python3 assets/coloriser_ascii.py assets/source/arbre-ascii.txt assets/source/logo.webp > assets/arbre-grand.txt

Les caractères ne changent pas : chaque caractère est placé sur le logo
d'origine (l'anneau de l'ASCII est calé sur l'ellipse de l'anneau du logo),
puis prend la couleur de ce qu'il recouvre : or ($1), feuille ($2) ou étoile ($3),
au format des logos fastfetch. Dépendances : python3-numpy, python3-pil.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Mesures du logo (assets/trace_logo.py) : anneau et étoile, en pixels de l'image
RING_CX, RING_CY, RING_RX, RING_RY, RING_W = 625.4, 605.0, 453.8, 462.3, 6.05
STAR_CX, STAR_CY, STAR_ZONE = 626.0, 596.0, 38.0
NIGHT = np.array([9, 28, 49], float)
GOLD = np.array([232, 204, 140], float)
GREEN = np.array([100, 150, 133], float)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    lines = [line.rstrip() for line in Path(argv[1]).read_text(encoding="utf-8").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    indent = min(len(line) - len(line.lstrip()) for line in lines if line)
    lines = [line[indent:] for line in lines]

    img = np.asarray(Image.open(argv[2]).convert("RGB"), dtype=float)
    basis = np.stack([GOLD - NIGHT, GREEN - NIGHT], axis=1)
    coeffs = (img - NIGHT) @ np.linalg.pinv(basis).T
    a_gold, a_green = coeffs[..., 0], coeffs[..., 1]

    # Calage : bords extérieurs de l'anneau ASCII ↔ bords extérieurs de l'anneau du logo
    left = min(len(line) - len(line.lstrip()) for line in lines if line)
    right = max(len(line) for line in lines)
    top, bottom = 0, len(lines)
    px_col = (RING_RX + RING_W / 2) * 2 / (right - left)
    px_row = (RING_RY + RING_W / 2) * 2 / (bottom - top)
    mid_col, mid_row = (left + right) / 2, (top + bottom) / 2

    out = []
    for r, line in enumerate(lines):
        parts, current = [], None
        for c, ch in enumerate(line):
            if ch == " ":
                parts.append(ch)
                continue
            x = RING_CX + (c + 0.5 - mid_col) * px_col
            y = RING_CY + (r + 0.5 - mid_row) * px_row
            x0, x1 = int(x - px_col / 2), int(x + px_col / 2) + 1
            y0, y1 = int(y - px_row / 2), int(y + px_row / 2) + 1
            gold, green = a_gold[y0:y1, x0:x1].clip(0).mean(), a_green[y0:y1, x0:x1].clip(0).mean()
            if np.hypot(x - STAR_CX, (y - STAR_CY)) < STAR_ZONE:
                color = "$3"
            elif green > gold and green > 0.12:
                color = "$2"
            else:
                color = "$1"
            if color != current:
                parts.append(color)
                current = color
            parts.append(ch)
        out.append("".join(parts))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
