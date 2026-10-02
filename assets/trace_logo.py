#!/usr/bin/env python3
"""Vectorise le logo d'Yggdrasil (image matricielle) en SVG propre.

    python3 assets/trace_logo.py assets/source/logo.webp assets/logo.svg

Le logo source est une image : on sépare ses couches par démélange des couleurs
(fond nuit, or, sauge), puis :
  - l'anneau et les points d'or deviennent de vrais cercles, ajustés aux pixels ;
  - l'étoile devient une étoile à quatre branches paramétrique, ajustée aux
    pixels, avec son halo (dégradé radial gaussien mesuré sur l'image) ;
  - l'arbre (tronc, branches, racines) et chaque feuille, avec sa propre teinte,
    sont tracés par potrace.

Le résultat est enregistré dans le dépôt (assets/logo.svg) : ce script ne sert
qu'à le régénérer. Dépendances : python3-numpy, python3-pil, python3-scipy, potrace.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

NIGHT = np.array([9, 28, 49], float)
GOLD = np.array([232, 204, 140], float)
GREEN = np.array([100, 150, 133], float)  # entre les teintes des feuilles
AMBER = np.array([249, 184, 61], float)  # lumière du halo (mesurée : R:V:B ≈ 1:0,65:0,05)

GOLD_HEX = "#E8CC8C"
STAR_HEX = "#FBE39B"

UP = 2  # suréchantillonnage avant le tracé (contours plus lisses)
SIZE = 1000  # côté du viewBox final
RING_R = 470  # rayon vertical de l'anneau dans le viewBox final
AMBER_HEX = "#F9B83D"
# Halo de l'étoile, mesuré sur l'image le long des diagonales : opacité de la
# lumière ambrée HALO_AMP·exp(-(d/HALO_SIGMA)²), d en pixels d'origine.
HALO_AMP, HALO_SIGMA = 0.66, 26.7
STAR_ZONE = 48  # rayon (px d'origine) autour de l'étoile où seule la tige est gardée
TIP_EXTRA = 2.5  # px : les pointes très fines s'estompent à l'antialiasing, on les rallonge
# La racine extérieure droite s'efface en fondu : boîte (px d'origine) où on la
# capte avec un seuil bas, puis où l'on applique un dégradé d'opacité.
TAIL = (835, 835, 925, 900)  # x0, y0, x1, y1
TAIL_FADE = (845, 920, 0.3)  # x de début, x de fin, opacité finale


def unmix(img: np.ndarray, *, halo: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Part d'or et part de vert de chaque pixel.

    pixel = nuit + a·(or - nuit) + b·(vert - nuit) [+ c·(ambre - nuit)].
    La composante ambrée absorbe le halo de l'étoile ; on ne l'utilise que près
    de l'étoile, car ailleurs elle confond l'or ombré des racines avec du halo.
    """
    colors = [GOLD, GREEN, AMBER] if halo else [GOLD, GREEN]
    basis = np.stack([c - NIGHT for c in colors], axis=1)
    coeffs = (img - NIGHT) @ np.linalg.pinv(basis).T
    return coeffs[..., 0], coeffs[..., 1]


def upsample(a: np.ndarray) -> np.ndarray:
    h, w = a.shape
    im = Image.fromarray(a.astype(np.float32), mode="F")
    return np.asarray(im.resize((w * UP, h * UP), Image.Resampling.BICUBIC))


def fit_ellipse(ys: np.ndarray, xs: np.ndarray) -> tuple[float, float, float, float]:
    """Ellipse d'axes horizontal et vertical : centre x, centre y, rayons rx, ry.

    L'anneau du logo n'est pas un cercle parfait (2 % plus haut que large) :
    on reproduit l'ellipse telle quelle. Moindres carrés sur A·x² + C·y² + D·x + E·y = 1.
    """
    a = np.column_stack([xs**2, ys**2, xs, ys])
    big_a, big_c, d, e = np.linalg.lstsq(a, np.ones_like(xs), rcond=None)[0]
    x0, y0 = -d / (2 * big_a), -e / (2 * big_c)
    g = 1 + big_a * x0**2 + big_c * y0**2
    return float(x0), float(y0), float(np.sqrt(g / big_a)), float(np.sqrt(g / big_c))


def potrace(mask: np.ndarray) -> tuple[str, str]:
    """Trace un masque binaire ; renvoie (transform, d) du chemin potrace."""
    with tempfile.TemporaryDirectory() as tmp:
        pbm = Path(tmp, "m.pbm")
        Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("1").save(pbm)
        out = subprocess.run(
            ["potrace", "-b", "svg", "--flat", "-t", "6", "-a", "1.0", "-O", "0.2", "-o", "-", str(pbm)],
            check=True, capture_output=True, text=True,
        ).stdout
    transform = re.search(r'<g transform="([^"]+)"', out).group(1)
    d = " ".join(re.findall(r'<path d="([^"]+)"', out, flags=re.S))
    return transform, re.sub(r"\s+", " ", d).strip()


# --------------------------------------------------------------------------
# Étoile à quatre branches
# --------------------------------------------------------------------------

def star_points(cx: float, cy: float, rx: float, ry: float, k: float, n: int = 24) -> list[tuple[float, float]]:
    """Contour échantillonné : 4 courbes quadratiques entre les pointes."""
    tips = [(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]
    ctrl = [(cx + k, cy - k), (cx + k, cy + k), (cx - k, cy + k), (cx - k, cy - k)]
    pts = []
    for i in range(4):
        (x0, y0), (x1, y1), (qx, qy) = tips[i], tips[(i + 1) % 4], ctrl[i]
        for j in range(n):
            t = j / n
            pts.append(((1 - t) ** 2 * x0 + 2 * t * (1 - t) * qx + t * t * x1,
                        (1 - t) ** 2 * y0 + 2 * t * (1 - t) * qy + t * t * y1))
    return pts


def star_path(cx: float, cy: float, rx: float, ry: float, k: float) -> str:
    return (
        f"M{cx:.1f} {cy - ry:.1f}"
        f"Q{cx + k:.1f} {cy - k:.1f} {cx + rx:.1f} {cy:.1f}"
        f"Q{cx + k:.1f} {cy + k:.1f} {cx:.1f} {cy + ry:.1f}"
        f"Q{cx - k:.1f} {cy + k:.1f} {cx - rx:.1f} {cy:.1f}"
        f"Q{cx - k:.1f} {cy - k:.1f} {cx:.1f} {cy - ry:.1f}Z"
    )


def half_width(cx: float, cy: float, rx: float, ry: float, k: float, dy: float) -> float:
    """Demi-largeur de la branche verticale du modèle, à dy du centre."""
    lo, hi = 0.0, 1.0  # t entre la pointe (t = 0) et la branche horizontale (t = 1)
    for _ in range(50):
        t = (lo + hi) / 2
        y = (1 - t) ** 2 * ry + 2 * t * (1 - t) * k
        lo, hi = (t, hi) if y > dy else (lo, t)
    t = (lo + hi) / 2
    return 2 * t * (1 - t) * k + t * t * rx


def fit_star(lum: np.ndarray, cx: float, cy: float) -> tuple[float, float, float]:
    """Mesure l'étoile : longueur des branches, puis cambrure k des côtés.

    Pointes : on suit l'axe tant que la luminance dépasse 170 (le halo reste
    en dessous). Cambrure : on égale la demi-largeur de la branche basse, à
    10 px du centre, mesurée au seuil 200 (entre halo et étoile).
    """
    def walk(dx: int, dy: int) -> int:
        n = 0
        while lum[int(cy) + (n + 1) * dy, int(round(cx)) + (n + 1) * dx] > 170:
            n += 1
        return n

    rx = (walk(-1, 0) + walk(1, 0)) / 2 + 0.5
    ry = walk(0, 1) + 0.5
    row = lum[int(cy) + 10, int(cx) - 30:int(cx) + 31] > 200
    measured = row.sum() / 2
    lo, hi = -10.0, 6.0
    for _ in range(40):
        k = (lo + hi) / 2
        lo, hi = (lo, k) if half_width(cx, cy, rx, ry, k, 10) > measured else (k, hi)
    k = (lo + hi) / 2
    print(f"étoile : rx {rx:.1f} ry {ry:.1f} k {k:.2f} (demi-largeur à 10 px : {measured:.1f})")
    return rx, ry, k


def _dots_mask(dots: list[tuple[float, float, float]], h: int, w: int) -> np.ndarray:
    """Disques des points d'or (coordonnées suréchantillonnées) à la résolution d'origine."""
    yy, xx = np.mgrid[0:h, 0:w]
    mask = np.zeros((h, w), dtype=bool)
    for x, y, r in dots:
        mask |= np.hypot(xx - x / UP, yy - y / UP) < r / UP
    return mask


# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src, dest = Path(argv[1]), Path(argv[2])
    img = np.asarray(Image.open(src).convert("RGB"), dtype=float)
    lum = img @ np.array([0.299, 0.587, 0.114])
    a_gold, a_green = unmix(img)

    # ---- Étoile : la ligne des branches horizontales est la plus large ----
    h, w = lum.shape
    x_lo, x_hi = w // 2 - 50, w // 2 + 50
    rows = range(h // 2 - 50, h // 2 + 10)
    scy = float(max(rows, key=lambda y: (lum[y, x_lo:x_hi] > 190).sum()))
    bright_x = np.nonzero(lum[int(scy), x_lo:x_hi] > 190)[0] + x_lo
    scx = (bright_x.min() + bright_x.max()) / 2
    print(f"étoile : centre ({scx:.1f}, {scy:.1f})")
    yy, xx = np.mgrid[0:h, 0:w]
    near_star = np.hypot(xx - scx, yy - scy) < 2.4 * HALO_SIGMA
    a_gold = np.where(near_star, unmix(img, halo=True)[0], a_gold)
    srx, sry, sk = fit_star(lum, scx, scy)
    srx, sry = srx + TIP_EXTRA, sry + TIP_EXTRA

    # ---- Couche or : anneau, points, arbre --------------------------------
    up_gold = upsample(a_gold)
    gold = up_gold > 0.5
    y2, x2 = np.mgrid[0:h * UP, 0:w * UP]
    tail = (x2 >= TAIL[0] * UP) & (x2 <= TAIL[2] * UP) & (y2 >= TAIL[1] * UP) & (y2 <= TAIL[3] * UP)
    # Seuil abaissé progressivement (0,5 → 0,18 sur 40 px) : pas de marche à l'entrée
    ramp = np.clip((x2 / UP - TAIL[0]) / 40, 0, 1)
    gold |= tail & (up_gold > 0.5 - 0.32 * ramp)
    # L'étoile est dessinée à part, par-dessus. Autour d'elle, on ne garde que
    # la tige qui descend jusqu'à son centre (la tige s'y cache sous l'étoile).
    zone = np.hypot(x2 / UP - scx, y2 / UP - scy) < STAR_ZONE
    stem = (y2 / UP < scy - 3) & (np.abs(x2 / UP - scx) < 14)
    gold &= ~zone | stem
    # Le halo, retiré par le démélange, laisse des encoches dans la tige :
    # fermeture morphologique, puis remplissage ligne par ligne.
    gold |= ndimage.binary_closing(gold & zone & stem, structure=np.ones((9, 9))) & zone & stem
    for row in np.nonzero((zone & stem).any(axis=1))[0]:
        cols = np.nonzero(gold[row] & zone[row] & stem[row])[0]
        if cols.size:
            gold[row, cols.min():cols.max() + 1] = True
    labels, n = ndimage.label(gold)
    slices = ndimage.find_objects(labels)
    areas = ndimage.sum_labels(np.ones_like(labels), labels, range(1, n + 1))
    ring_id = max(range(n), key=lambda i: (slices[i][1].stop - slices[i][1].start))
    ys, xs = np.nonzero(labels == ring_id + 1)
    cx2, cy2, rx2, ry2 = fit_ellipse(ys.astype(float), xs.astype(float))
    perimeter = np.pi * (3 * (rx2 + ry2) - np.sqrt((3 * rx2 + ry2) * (rx2 + 3 * ry2)))  # Ramanujan
    ring_w2 = areas[ring_id] / perimeter
    r2 = ry2  # le plus grand rayon sert d'échelle
    print(f"anneau : centre ({cx2 / UP:.1f}, {cy2 / UP:.1f}) rayons {rx2 / UP:.1f} × {ry2 / UP:.1f}"
          f" épaisseur {ring_w2 / UP:.2f}")

    tree_ids = [i + 1 for i in range(n) if i != ring_id and areas[i] > 2000]
    tree = np.isin(labels, tree_ids)
    dist_tree = ndimage.distance_transform_edt(~tree)
    dots = []
    for i in range(n):
        if i == ring_id or (i + 1) in tree_ids:
            continue
        sy, sx = slices[i]
        bw, bh = sx.stop - sx.start, sy.stop - sy.start
        comp = labels == i + 1
        r = math.sqrt(areas[i] / math.pi) / UP
        if 3 <= r <= 9 and 0.7 < bw / bh < 1.4 and dist_tree[comp].min() > 20 * UP:
            yc, xc = ndimage.center_of_mass(comp)
            dots.append((xc, yc, r * UP))
        else:
            print(f"  ignoré : morceau d'or de rayon {r:.1f} en ({sx.start / UP:.0f}, {sy.start / UP:.0f})")
    print(f"points d'or : {len(dots)} ; morceaux d'arbre : {len(tree_ids)}")

    # ---- Feuilles : chacune sa teinte -------------------------------------
    green = upsample(a_green) > 0.5
    gl, gn = ndimage.label(green)
    leaves = []
    for i in range(1, gn + 1):
        comp = gl == i
        if comp.sum() < 120 * UP * UP:
            continue
        small = comp[::UP, ::UP] & (a_green > 0.6)
        if not small.any():
            continue
        r, g, b = (int(round(v)) for v in img[small].mean(axis=0))
        leaves.append((comp, f"#{r:02X}{g:02X}{b:02X}"))
    print(f"feuilles : {len(leaves)} ; teintes : {' '.join(sorted({c for _, c in leaves}))}")

    # ---- Teintes mesurées --------------------------------------------------
    def mean_hex(mask: np.ndarray) -> str:
        r, g, b = (int(round(v)) for v in img[mask].mean(axis=0))
        return f"#{r:02X}{g:02X}{b:02X}"

    ring_hex = mean_hex((labels == ring_id + 1)[::UP, ::UP] & (a_gold > 0.8))
    dots_hex = mean_hex(_dots_mask(dots, h, w) & (a_gold > 0.8))
    star_im = Image.new("1", (w, h), 0)
    ImageDraw.Draw(star_im).polygon(star_points(scx, scy, srx * 0.6, sry * 0.6, sk * 0.6), fill=1)
    star_hex = mean_hex(np.asarray(star_im, dtype=bool))
    # L'or de l'arbre s'assombrit vers les racines : dégradé vertical mesuré par bandes
    tree1 = tree[::UP, ::UP]
    core = ndimage.binary_erosion(a_gold > 0.85, iterations=2) & tree1 & ~near_star
    rows_with = np.nonzero(tree1.any(axis=1))[0]
    top, bottom = int(rows_with.min()), int(rows_with.max())
    gold_stops = []
    for y0 in range(top, bottom, 60):
        band = core & (yy >= y0) & (yy < y0 + 60)
        if band.sum() > 40:
            gold_stops.append(((y0 + 30 - top) / (bottom - top), mean_hex(band)))
    print(f"teintes : anneau {ring_hex}, points {dots_hex}, étoile {star_hex}, arbre "
          + " ".join(f"{o:.2f}:{c}" for o, c in gold_stops))
    # potrace retourne l'axe vertical : y = 1 de la boîte englobante est en haut à l'écran
    gold_grad = "".join(f'<stop offset="{o:.3f}" stop-color="{c}"/>' for o, c in gold_stops)

    # ---- Assemblage -------------------------------------------------------
    s = RING_R / (r2 / UP)  # pixels d'origine → viewBox
    ox, oy = SIZE / 2 - (cx2 / UP) * s, SIZE / 2 - (cy2 / UP) * s
    outer = f"translate({ox:.2f} {oy:.2f}) scale({s / UP:.5f})"

    def place(px: float, py: float) -> tuple[float, float]:
        """Coordonnées d'origine → viewBox."""
        return ox + px * s, oy + py * s

    tree_t, tree_d = potrace(tree)
    leaf_paths, leaf_t = [], ""
    for comp, color in leaves:
        leaf_t, d = potrace(comp)
        leaf_paths.append(f'<path fill="{color}" d="{d}"/>')
    sx_v, sy_v = place(scx, scy)
    star_d = star_path(sx_v, sy_v, srx * s, sry * s, sk * s)
    dots_svg = "".join(
        f'<circle cx="{place(x / UP, y / UP)[0]:.1f}" cy="{place(x / UP, y / UP)[1]:.1f}" r="{r / UP * s:.2f}"/>'
        for x, y, r in dots
    )
    # Halo gaussien coupé à 2,4 σ
    cut = 2.4
    stops = "".join(
        f'<stop offset="{t:.2f}" stop-color="{AMBER_HEX}" stop-opacity="{HALO_AMP * math.exp(-((t * cut) ** 2)):.3f}"/>'
        for t in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}">
<title>Yggdrasil</title>
<defs><radialGradient id="ygg-halo">{stops}</radialGradient>
<linearGradient id="ygg-or" x1="0" y1="1" x2="0" y2="0">{gold_grad}</linearGradient>
<linearGradient id="ygg-fondu-g" gradientUnits="userSpaceOnUse" x1="{place(TAIL_FADE[0], 0)[0]:.1f}" y1="0" x2="{place(TAIL_FADE[1], 0)[0]:.1f}" y2="0"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="{TAIL_FADE[2]}"/></linearGradient>
<mask id="ygg-fondu" maskUnits="userSpaceOnUse" x="0" y="0" width="{SIZE}" height="{SIZE}"><rect width="{SIZE}" height="{SIZE}" fill="#fff"/><rect x="{place(*TAIL[:2])[0]:.1f}" y="{place(*TAIL[:2])[1]:.1f}" width="{(TAIL[2] - TAIL[0]) * s:.1f}" height="{(TAIL[3] - TAIL[1]) * s:.1f}" fill="#000"/><rect x="{place(*TAIL[:2])[0]:.1f}" y="{place(*TAIL[:2])[1]:.1f}" width="{(TAIL[2] - TAIL[0]) * s:.1f}" height="{(TAIL[3] - TAIL[1]) * s:.1f}" fill="url(#ygg-fondu-g)"/></mask></defs>
<ellipse id="anneau" cx="{SIZE // 2}" cy="{SIZE // 2}" rx="{rx2 / UP * s:.2f}" ry="{RING_R}" fill="none" stroke="{ring_hex}" stroke-width="{ring_w2 / UP * s:.2f}"/>
<g id="points" fill="{dots_hex}">{dots_svg}</g>
<g mask="url(#ygg-fondu)"><g transform="{outer}"><g id="arbre" transform="{tree_t}" fill="url(#ygg-or)"><path d="{tree_d}"/></g></g></g>
<g transform="{outer}"><g id="feuilles" transform="{leaf_t}">{"".join(leaf_paths)}</g></g>
<circle id="halo" cx="{sx_v:.1f}" cy="{sy_v:.1f}" r="{cut * HALO_SIGMA * s:.1f}" fill="url(#ygg-halo)"/>
<path id="etoile" d="{star_d}" fill="{star_hex}"/>
</svg>
"""
    dest.write_text(svg, encoding="utf-8")
    print(f"→ {dest} ({len(svg) // 1024} Ko)")
    # Variante « carrée » : même cadrage et même fond que l'image source
    square = dest.with_name(dest.stem + "-carre.svg")
    vb = f"{ox:.3f} {oy:.3f} {w * s:.3f} {h * s:.3f}"
    sq = svg.replace(f'viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}"',
                     f'viewBox="{vb}" width="{w}" height="{h}"', 1)
    background = f'<rect x="{ox:.3f}" y="{oy:.3f}" width="{w * s:.3f}" height="{h * s:.3f}" fill="#091C30"/>'
    sq = sq.replace("<title>Yggdrasil</title>", "<title>Yggdrasil</title>\n" + background, 1)
    square.write_text(sq, encoding="utf-8")
    print(f"→ {square}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
