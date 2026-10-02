#!/usr/bin/env python3
"""Génère l'identité visuelle d'Yggdrasil à partir du logo vectoriel.

    python3 assets/generate.py [dossier_de_sortie]

Tout part de assets/logo.svg (tracé fidèle du logo, voir assets/trace_logo.py).
Produit des SVG, rendus en PNG par scripts/build-packages.sh (rsvg-convert) :

  emblem.svg              le logo seul, fond transparent
  icon.svg                le logo sur un disque nuit (icône d'application, avatar)
  icon-qt.svg             variante sans masque ni dégradé, que Qt sait afficher
  icon-alerte.svg         la même, marquée d'une braise (la barre système signale un souci)
  wallpaper-LxH.svg       fonds d'écran (plusieurs formats)
  login.svg               fond de l'écran de connexion et de verrouillage
  grub.svg, grub-4x3.svg  fond du menu de démarrage du système installé
  bootsplash.svg          fond du menu de démarrage de l'ISO (@VERSION@ remplacé)
  grub-select-{w,c,e}.svg sélection dans le menu GRUB
  title.svg               « Yggdrasil » en lettres gravées (Plymouth, écran de session)
  plymouth-progress-*.svg fil de progression de Plymouth
  calamares-welcome.svg   bannière de l'installateur
  preview.svg             aperçu du thème (Paramètres du système)
  arbre/arbre-N.svg       animation : l'arbre pousse (Plymouth, écran de session)
  halo.svg                halo de l'étoile seul (respiration en fin d'animation)
  arbre-vivant.svg        fond d'écran dont neuf feuilles (une par royaume) s'allument en or

Tout est déterministe : même logo, mêmes images.
"""

from __future__ import annotations

import math
import random
import re
import sys
from pathlib import Path

LOGO = Path(__file__).with_name("logo.svg")

NIGHT = "#091C30"
NIGHT_LIGHT = "#0F2742"
GOLD = "#E8CC8C"
GOLD_DEEP = "#D8BC80"
STAR = "#FBE39B"
SAGE = "#5B8B7B"
SAGE_LIGHT = "#79AC99"
PARCHMENT = "#F2EAD7"
MIST = "#9DBFB2"
TITLE_FONT = "EB Garamond"
TEXT_FONT = "DejaVu Sans"

FRAMES = 48  # images de l'animation
TRUNK_BASE = (500.0, 698.0)  # naissance des racines, dans le repère 1000 × 1000 du logo


def fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def svg(width: float, height: float, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(width)}" height="{fmt(height)}" '
        f'viewBox="0 0 {fmt(width)} {fmt(height)}">{body}</svg>\n'
    )


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease(x: float) -> float:
    """Accélère puis ralentit (cubique)."""
    x = clamp(x)
    return 4 * x**3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


# --------------------------------------------------------------------------
# Le logo, découpé en couches
# --------------------------------------------------------------------------

class Logo:
    """Couches du logo vectoriel : anneau, points, arbre, feuilles, halo, étoile.

    assets/logo.svg écrit un élément de premier niveau par ligne, chacun
    portant son id : on les retrouve sans analyseur XML.
    """

    LAYERS = ("anneau", "points", "arbre", "feuilles", "halo", "etoile")

    def __init__(self, text: str) -> None:
        self.defs = re.search(r"<defs>.*?</defs>", text, flags=re.S).group(0)
        self.layers: dict[str, str] = {}
        for line in text.splitlines():
            for name in self.LAYERS:
                if f'id="{name}"' in line:
                    self.layers[name] = line
        missing = set(self.LAYERS) - set(self.layers)
        if missing:
            raise SystemExit(f"logo.svg : couches introuvables : {', '.join(sorted(missing))}")
        m = re.search(r'<ellipse id="anneau" cx="([\d.]+)" cy="([\d.]+)" rx="([\d.]+)" ry="([\d.]+)"', text)
        self.ring = tuple(float(v) for v in m.groups())
        m = re.search(r'<circle id="halo" cx="([\d.]+)" cy="([\d.]+)"', text)
        self.star_center = (float(m.group(1)), float(m.group(2)))

    def body(self, *names: str) -> str:
        return "".join(self.layers[n] for n in (names or self.LAYERS))

    def place(self, x: float, y: float, size: float, prefix: str, body: str | None = None,
              defs: str | None = None) -> str:
        """Le logo (ou une partie) dans un carré de côté `size` centré en (x, y).

        Les id sont préfixés : plusieurs logos peuvent cohabiter dans un même SVG.
        """
        inner = (defs if defs is not None else self.defs) + (body if body is not None else self.body())
        inner = re.sub(r'id="([^"]+)"', lambda m: f'id="{prefix}-{m.group(1)}"', inner)
        inner = inner.replace("url(#", f"url(#{prefix}-").replace('href="#', f'href="#{prefix}-')
        return (
            f'<svg x="{fmt(x - size / 2)}" y="{fmt(y - size / 2)}" width="{fmt(size)}" height="{fmt(size)}" '
            f'viewBox="0 0 1000 1000">{inner}</svg>'
        )


def stars(w: float, h: float, seed: int, count: int, *, avoid: tuple[float, float, float] | None = None) -> str:
    """Points d'or épars, comme ceux du logo (évite le disque `avoid` = (x, y, r))."""
    rng = random.Random(seed)
    dots = []
    while len(dots) < count:
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        if avoid and math.hypot(x - avoid[0], y - avoid[1]) < avoid[2]:
            continue
        r = rng.choice((0.9, 1.1, 1.3, 1.6, 2.0)) * h / 1080
        op = rng.uniform(0.25, 0.75)
        dots.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r)}" fill="{GOLD}" opacity="{op:.2f}"/>')
    return "".join(dots)


def text(x: float, y: float, content: str, size: float, color: str, *, font: str = TEXT_FONT,
         spacing: float = 0, anchor: str = "middle", weight: str = "normal") -> str:
    return (
        f'<text x="{fmt(x)}" y="{fmt(y)}" text-anchor="{anchor}" font-family="{font}" font-size="{fmt(size)}" '
        f'font-weight="{weight}" letter-spacing="{fmt(spacing)}" fill="{color}">{content}</text>'
    )


# --------------------------------------------------------------------------
# Images fixes
# --------------------------------------------------------------------------

def emblem(logo: Logo) -> str:
    return svg(1000, 1000, logo.place(500, 500, 1000, "e"))


def icon(logo: Logo) -> str:
    """Logo sur un disque nuit : lisible sur un fond clair comme sombre."""
    return svg(1000, 1000, f'<circle cx="500" cy="500" r="498" fill="{NIGHT}"/>' + logo.place(500, 500, 1000, "i"))


def icon_qt(logo: Logo) -> str:
    """Variante pour Qt (icônes, SDDM) : ni masque, ni dégradé en boîte englobante."""
    body = logo.body().replace('mask="url(#ygg-fondu)"', "").replace('fill="url(#ygg-or)"', f'fill="{GOLD}"')
    defs = re.sub(r'<linearGradient id="ygg-or".*?</linearGradient>', "", logo.defs, flags=re.S)
    defs = re.sub(r"<mask .*?</mask>", "", defs, flags=re.S)
    disc = f'<circle cx="500" cy="500" r="498" fill="{NIGHT}"/>'
    return svg(1000, 1000, disc + logo.place(500, 500, 1000, "q", body=body, defs=defs))


def icon_alert(logo: Logo) -> str:
    """L'icône de la barre système quand quelque chose demande attention : une braise."""
    ember = f'<circle cx="790" cy="790" r="190" fill="{NIGHT}"/><circle cx="790" cy="790" r="150" fill="#E2774E"/>'
    return icon_qt(logo).replace("</svg>", ember + "</svg>")


def wallpaper(logo: Logo, w: int, h: int) -> str:
    size = h * 0.66
    cx, cy = w / 2, h * 0.47
    body = f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>'
    body += stars(w, h, seed=w * 7 + h, count=int(w * h / 26000), avoid=(cx, cy, size * 0.5))
    body += logo.place(cx, cy, size, "w")
    return svg(w, h, body)


# --------------------------------------------------------------------------
# L'arbre vivant : une feuille d'or par royaume installé (ygg realm arbre)
# --------------------------------------------------------------------------

# Les neuf mondes, de gauche à droite dans la couronne (Ásgard au sommet)
ROYAUMES_FEUILLES = (
    ("niflheim", "ᛁ"), ("helheim", "ᛇ"), ("jotunheim", "ᚦ"), ("vanaheim", "ᚨ"), ("asgard", "ᛉ"),
    ("alfheim", "ᛊ"), ("muspelheim", "ᛈ"), ("nidavellir", "ᚲ"), ("midgard", "ᛗ"),
)


def _transform(attr: str) -> tuple[float, float, float, float]:
    """« translate(a b) scale(s[, t]) » → (a, b, s, t)."""
    tx, ty = (float(v) for v in re.search(r"translate\(([-\d.]+)[ ,]([-\d.]+)\)", attr).groups())
    m = re.search(r"scale\(([-\d.]+)(?:[ ,]([-\d.]+))?\)", attr)
    sx = float(m.group(1))
    sy = float(m.group(2)) if m.group(2) else sx
    return tx, ty, sx, sy


def path_bbox(d: str) -> tuple[float, float, float, float]:
    """Boîte englobante (approchée par les points de contrôle) d'un tracé potrace : M, m, c, l, z."""
    tokens = re.findall(r"[MmCcLlZz]|-?\d+(?:\.\d+)?", d)
    x = y = sx = sy = 0.0
    xs, ys = [], []
    cmd, i = "", 0
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                x, y = sx, sy
            continue
        if cmd in "Mm":
            nx, ny = float(tokens[i]), float(tokens[i + 1])
            x, y = (nx, ny) if cmd == "M" else (x + nx, y + ny)
            sx, sy = x, y
            xs.append(x)
            ys.append(y)
            cmd = "l" if cmd == "m" else "L"
            i += 2
        elif cmd in "Cc":
            pts = [float(t) for t in tokens[i:i + 6]]
            for k in range(0, 6, 2):
                xs.append(x + pts[k] if cmd == "c" else pts[k])
                ys.append(y + pts[k + 1] if cmd == "c" else pts[k + 1])
            x, y = xs[-1], ys[-1]
            i += 6
        elif cmd in "Ll":
            nx, ny = float(tokens[i]), float(tokens[i + 1])
            x, y = (x + nx, y + ny) if cmd == "l" else (nx, ny)
            xs.append(x)
            ys.append(y)
            i += 2
        else:
            raise ValueError(f"commande de tracé non gérée : {cmd}")
    return min(xs), min(ys), max(xs), max(ys)


def leaves(logo: Logo) -> list[tuple[str, str, float, float]]:
    """Chaque feuille : (attribut fill, tracé, centre x, centre y dans le repère 1000 × 1000 du logo)."""
    line = logo.layers["feuilles"]
    outer = _transform(re.search(r'<g transform="([^"]+)"><g id="feuilles"', line).group(1))
    inner = _transform(re.search(r'<g id="feuilles" transform="([^"]+)"', line).group(1))
    result = []
    for fill, d in re.findall(r'<path fill="([^"]+)" d="([^"]+)"', line):
        x0, y0, x1, y1 = path_bbox(d)
        px, py = (x0 + x1) / 2, (y0 + y1) / 2
        ix, iy = inner[0] + inner[2] * px, inner[1] + inner[3] * py
        result.append((fill, d, outer[0] + outer[2] * ix, outer[1] + outer[3] * iy))
    return result


def realm_leaves(logo: Logo) -> list[tuple[str, str, str, float, float]]:
    """Neuf feuilles bien réparties dans la couronne : (royaume, rune, tracé, x, y).

    Ásgard prend la feuille la plus haute ; on ajoute ensuite, tour à tour, la feuille
    la plus éloignée de celles déjà prises, et les autres mondes se rangent de gauche
    à droite autour de l'étoile.
    """
    cx, cy = logo.star_center
    feuilles = leaves(logo)
    choisies = [min(feuilles, key=lambda f: f[3])]
    while len(choisies) < len(ROYAUMES_FEUILLES):
        reste = [f for f in feuilles if f not in choisies]
        choisies.append(max(reste, key=lambda f: min(math.hypot(f[2] - c[2], f[3] - c[3]) for c in choisies)))
    sommet = choisies[0]
    autres = sorted(choisies[1:], key=lambda f: f[2])  # de gauche à droite
    noms = [r for r in ROYAUMES_FEUILLES if r[0] != "asgard"]
    resultat = [("asgard", "ᛉ", sommet[1], sommet[2], sommet[3])]
    resultat += [(nom, rune, d, x, y) for (nom, rune), (_, d, x, y) in zip(noms, autres)]
    return resultat


def living_tree(logo: Logo, w: int = 2560, h: int = 1440) -> str:
    """Le fond d'écran, avec pour chaque royaume une feuille d'or et sa rune, éteintes (opacity 0).

    yggdrasil.arbre allume celles des royaumes installés.
    """
    line = logo.layers["feuilles"]
    outer = re.search(r'<g transform="([^"]+)"><g id="feuilles"', line).group(1)
    inner = re.search(r'<g id="feuilles" transform="([^"]+)"', line).group(1)
    cx, cy = logo.star_center
    lumieres, runes = [], []
    for nom, rune, d, x, y in realm_leaves(logo):
        lumieres.append(f'<path id="lumiere-{nom}" d="{d}" fill="{STAR}" opacity="0" filter="url(#lueur)"/>')
        dist = math.hypot(x - cx, y - cy) or 1
        rx, ry = x + (x - cx) / dist * 34, y + (y - cy) / dist * 34
        runes.append(f'<text id="rune-{nom}" x="{fmt(rx)}" y="{fmt(ry + 10)}" text-anchor="middle" '
                     f'font-family="Noto Sans Runic" font-size="30" fill="{GOLD}" opacity="0">{rune}</text>')
    overlay = (f'<g transform="{outer}"><g transform="{inner}">' + "".join(lumieres) + "</g></g>"
               + '<g id="runes">' + "".join(runes) + "</g>")
    lueur = ('<filter id="lueur" x="-60%" y="-60%" width="220%" height="220%">'
             '<feGaussianBlur in="SourceGraphic" stdDeviation="90" result="flou"/>'
             '<feMerge><feMergeNode in="flou"/><feMergeNode in="flou"/><feMergeNode in="SourceGraphic"/></feMerge>'
             "</filter>")
    defs = logo.defs.replace("</defs>", lueur + "</defs>")
    size = h * 0.66
    pcx, pcy = w / 2, h * 0.47
    body = f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>'
    body += stars(w, h, seed=w * 7 + h, count=int(w * h / 26000), avoid=(pcx, pcy, size * 0.5))
    body += logo.place(pcx, pcy, size, "v", body=logo.body() + overlay, defs=defs)
    return svg(w, h, body)


def login_background(w: int = 1920, h: int = 1080) -> str:
    """L'écran de connexion dessine lui-même le logo : ici, le ciel seul."""
    body = f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>' + stars(w, h, seed=21, count=90)
    return svg(w, h, body)


def grub_background(logo: Logo, w: int = 1920, h: int = 1080) -> str:
    size = h * 0.3
    body = f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>'
    body += stars(w, h, seed=5, count=60, avoid=(w / 2, h * 0.22, size * 0.6))
    body += logo.place(w / 2, h * 0.22, size, "g")
    body += text(w / 2, h * 0.43, "Yggdrasil", h * 0.055, GOLD, font=TITLE_FONT, spacing=h * 0.006)
    return svg(w, h, body)


def bootsplash(logo: Logo, w: int = 1024, h: int = 768) -> str:
    """Fond du menu de démarrage de l'ISO (live-build remplace @VERSION@)."""
    body = f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>'
    body += stars(w, h, seed=3, count=40, avoid=(w / 2, 165, 150))
    body += logo.place(w / 2, 165, 250, "b")
    body += text(w / 2, 338, "Yggdrasil", 48, GOLD, font=TITLE_FONT, spacing=4)
    body += text(w / 2, 368, "@VERSION@ « Midgard » — basé sur Debian", 18, MIST)
    return svg(w, h, body)


def grub_select(part: str) -> str:
    """Sélection : fine bordure dorée arrondie, fond nuit clair (9 tranches GRUB)."""
    h = 40
    if part == "c":
        return svg(4, h, f'<rect width="4" height="{h}" fill="{NIGHT_LIGHT}"/>'
                         f'<rect width="4" height="1.5" fill="{GOLD}"/>'
                         f'<rect y="{h - 1.5}" width="4" height="1.5" fill="{GOLD}"/>')
    w = 10
    left = part == "w"
    x0 = 0.75 if left else -w
    shape = (f'<rect x="{fmt(x0)}" y="0.75" width="{2 * w - 1.5}" height="{h - 1.5}" rx="8" '
             f'fill="{NIGHT_LIGHT}" stroke="{GOLD}" stroke-width="1.5"/>')
    return svg(w, h, shape)


def title() -> str:
    return svg(560, 110, text(280, 80, "Yggdrasil", 76, GOLD, font=TITLE_FONT, spacing=6))


def progress_piece(fg: bool) -> str:
    """Fine barre de progression de Plymouth : un fil d'or sur la nuit."""
    color, opacity = (GOLD, 1) if fg else (PARCHMENT, 0.14)
    return svg(240, 3, f'<rect width="240" height="3" rx="1.5" fill="{color}" fill-opacity="{opacity}"/>')


def calamares_welcome(logo: Logo, w: int = 600, h: int = 300) -> str:
    body = f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>' + stars(w, h, seed=11, count=18, avoid=(150, h / 2, 130))
    body += logo.place(150, h / 2, 250, "c")
    body += text(300, h / 2 + 4, "Yggdrasil", 48, GOLD, font=TITLE_FONT, spacing=3, anchor="start")
    body += text(302, h / 2 + 38, "l'arbre qui relie tes mondes", 16, MIST, anchor="start")
    return svg(w, h, body)


def preview(logo: Logo, w: int = 1280, h: int = 720) -> str:
    """Aperçu du thème : fond d'écran, panneau en bas, une fenêtre."""
    body = wallpaper(logo, w, h).split(">", 1)[1].rsplit("</svg>", 1)[0]
    panel_h = 40
    body += f'<rect x="0" y="{h - panel_h}" width="{w}" height="{panel_h}" fill="{NIGHT_LIGHT}" opacity="0.92"/>'
    body += f'<rect x="0" y="{h - panel_h}" width="{w}" height="1" fill="{GOLD}" opacity="0.5"/>'
    body += logo.place(24, h - panel_h / 2, 30, "p")
    for i in range(5):
        body += f'<rect x="{60 + i * 38}" y="{h - panel_h + 9}" width="22" height="22" rx="5" fill="none" stroke="{SAGE_LIGHT}" stroke-width="1.5"/>'
    body += text(w - 20, h - panel_h / 2 + 5, "21:42", 15, PARCHMENT, anchor="end")
    wx, wy, ww, wh = w * 0.56, h * 0.18, w * 0.36, h * 0.42
    body += f'<rect x="{fmt(wx)}" y="{fmt(wy)}" width="{fmt(ww)}" height="{fmt(wh)}" rx="10" fill="{NIGHT_LIGHT}" stroke="{GOLD}" stroke-opacity="0.35"/>'
    body += f'<rect x="{fmt(wx)}" y="{fmt(wy)}" width="{fmt(ww)}" height="34" rx="10" fill="#0B2036"/>'
    for i, c in enumerate((GOLD, GOLD, GOLD)):
        body += f'<circle cx="{fmt(wx + ww - 20 - i * 24)}" cy="{fmt(wy + 17)}" r="6" fill="none" stroke="{c}" stroke-width="1.5"/>'
    body += text(wx + 18, wy + 22, "Centre Yggdrasil", 14, PARCHMENT, anchor="start")
    for i in range(4):
        body += f'<rect x="{fmt(wx + 18)}" y="{fmt(wy + 56 + i * 34)}" width="{fmt(ww * (0.75 - i * 0.12))}" height="12" rx="6" fill="{SAGE}" opacity="0.55"/>'
    return svg(w, h, body)


# --------------------------------------------------------------------------
# Animation : l'arbre pousse
# --------------------------------------------------------------------------

def ellipse_halves(cx: float, cy: float, rx: float, ry: float) -> tuple[str, str, float]:
    """Deux demi-ellipses partant du bas et se rejoignant en haut ; longueur de chacune."""
    right = f"M{fmt(cx)} {fmt(cy + ry)}A{fmt(rx)} {fmt(ry)} 0 0 0 {fmt(cx)} {fmt(cy - ry)}"
    left = f"M{fmt(cx)} {fmt(cy + ry)}A{fmt(rx)} {fmt(ry)} 0 0 1 {fmt(cx)} {fmt(cy - ry)}"
    length = math.pi * (3 * (rx + ry) - math.sqrt((3 * rx + ry) * (rx + 3 * ry))) / 2  # Ramanujan
    return right, left, length


def frame(logo: Logo, t: float) -> str:
    """Image de l'animation à l'instant t ∈ [0, 1].

    0 → 0,35 : l'anneau se trace depuis le bas ; 0,15 → 0,8 : l'arbre grandit à
    partir de la naissance des racines (racines vers le bas, ramure vers le haut) ;
    0,7 → 0,85 : les points d'or apparaissent ; 0,8 → 1 : l'étoile s'allume.
    """
    cx, cy, rx, ry = logo.ring
    width = re.search(r'stroke-width="([\d.]+)"', logo.layers["anneau"]).group(1)
    color = re.search(r'stroke="(#[0-9A-Fa-f]+)"', logo.layers["anneau"]).group(1)
    right, left, half = ellipse_halves(cx, cy, rx, ry)
    p_ring = ease(t / 0.35)
    ring = "".join(
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-dasharray="{fmt(half)} {fmt(half)}" stroke-dashoffset="{fmt(half * (1 - p_ring))}"/>'
        for d in (right, left)
    ) if p_ring > 0 else ""
    radius = 660 * ease((t - 0.15) / 0.65)
    grow = (f'<clipPath id="pousse"><circle cx="{fmt(TRUNK_BASE[0])}" cy="{fmt(TRUNK_BASE[1])}" '
            f'r="{fmt(radius)}"/></clipPath>')
    tree = f'<g clip-path="url(#pousse)">{logo.body("arbre", "feuilles")}</g>' if radius > 0 else ""
    p_dots = clamp((t - 0.7) / 0.15)
    dots = f'<g opacity="{p_dots:.3f}">{logo.layers["points"]}</g>' if p_dots > 0 else ""
    p_star = ease((t - 0.8) / 0.2)
    star = ""
    if p_star > 0:
        sx, sy = logo.star_center
        scale = 0.4 + 0.6 * p_star
        star = (f'<g opacity="{p_star:.3f}" transform="translate({fmt(sx)} {fmt(sy)}) scale({scale:.3f}) '
                f'translate({fmt(-sx)} {fmt(-sy)})">{logo.body("halo", "etoile")}</g>')
    defs = logo.defs.replace("</defs>", grow + "</defs>")
    body = ring + tree + dots + star
    return svg(1000, 1000, logo.place(500, 500, 1000, "a", body=body, defs=defs))


def halo_only(logo: Logo) -> str:
    return svg(1000, 1000, logo.place(500, 500, 1000, "h", body=logo.layers["halo"]))


# --------------------------------------------------------------------------

WALLPAPERS = ((1920, 1080), (2560, 1440), (3840, 2160), (1920, 1200), (2560, 1600), (3440, 1440), (1280, 1024))


def main(out_dir: str) -> None:
    out = Path(out_dir)
    (out / "arbre").mkdir(parents=True, exist_ok=True)
    logo = Logo(LOGO.read_text(encoding="utf-8"))
    files = {
        "emblem.svg": emblem(logo),
        "icon.svg": icon(logo),
        "icon-qt.svg": icon_qt(logo),
        "icon-alerte.svg": icon_alert(logo),
        "login.svg": login_background(),
        "grub.svg": grub_background(logo),
        "grub-4x3.svg": grub_background(logo, 1024, 768),
        "bootsplash.svg": bootsplash(logo),
        "grub-select-w.svg": grub_select("w"),
        "grub-select-c.svg": grub_select("c"),
        "grub-select-e.svg": grub_select("e"),
        "title.svg": title(),
        "plymouth-progress-bg.svg": progress_piece(False),
        "plymouth-progress-fg.svg": progress_piece(True),
        "calamares-welcome.svg": calamares_welcome(logo),
        "preview.svg": preview(logo),
        "halo.svg": halo_only(logo),
        "arbre-vivant.svg": living_tree(logo),
    }
    for w, h in WALLPAPERS:
        files[f"wallpaper-{w}x{h}.svg"] = wallpaper(logo, w, h)
    for i in range(FRAMES):
        files[f"arbre/arbre-{i}.svg"] = frame(logo, i / (FRAMES - 1))
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
    print(f"{len(files)} images dans {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("svg")))
