#!/bin/bash
# Assemble le site d'Yggdrasil (GitHub Pages) : les pages de site/, le logo et les images
# (captures d'écran en WebP, icônes, image de partage), le guide hors ligne, le plan du site et
# le dépôt APT signé (out/depot, fait par ./build.sh depot). Les versions et leurs fichiers ne
# sont pas copiés : les pages les lisent dans les releases.
#
#   ./build.sh site                     (dans le conteneur, dans out/site, puis vérifié)
#   scripts/build-site.sh [SORTIE]      (défaut : out/site ; il faut rsvg-convert et ImageMagick)
#   YGG_DEPOT=chemin/du/depot scripts/build-site.sh
set -euo pipefail

# YGG_SRC : le dépôt, quand ce script tourne depuis une copie (build.sh)
REPO=${YGG_SRC:-$(cd "$(dirname "$0")/.." && pwd)}
SORTIE=${1:-$REPO/out/site}
DEPOT=${YGG_DEPOT:-$REPO/out/depot}
# L'adresse publique du site : adresses canoniques, aperçus de partage, plan du site
ADRESSE=https://naisora.github.io/YggdrasilOS/

for outil in python3 rsvg-convert magick; do
    command -v "$outil" >/dev/null \
        || { echo "✘ $outil manque : ./build.sh site assemble le site dans le conteneur" >&2; exit 1; }
done
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

rm -rf "$SORTIE"
mkdir -p "$SORTIE/img/captures"
cp -r "$REPO/site/." "$SORTIE/"
cp "$REPO/assets/logo.svg" "$SORTIE/img/logo.svg"

# Icônes et image de partage, d'après le logo (assets/generate.py)
python3 "$REPO/assets/generate.py" "$TMP/svg" >/dev/null
cp "$TMP/svg/favicon.svg" "$SORTIE/favicon.svg"
for taille in 16 32 48; do
    rsvg-convert -w "$taille" -h "$taille" "$TMP/svg/favicon.svg" -o "$TMP/favicon-$taille.png"
done
magick "$TMP/favicon-16.png" "$TMP/favicon-32.png" "$TMP/favicon-48.png" "$SORTIE/favicon.ico"
rsvg-convert -w 180 -h 180 "$TMP/svg/icone-apple.svg" -o "$SORTIE/img/apple-touch-icon.png"
rsvg-convert -w 1280 -h 640 "$TMP/svg/partage.svg" -o "$TMP/partage.png"
magick "$TMP/partage.png" -strip -define png:compression-level=9 "$SORTIE/img/partage.png"

# Les captures d'écran (docs/captures, celles du README) en WebP : pour chacune, la plus légère
# de deux compressions, avec pertes (qualité 82 : rien ne se voit) ou sans (imbattable sur une
# console), et une variante de 1024 px de large pour les vignettes et les petits écrans
webp() {  # webp SOURCE SORTIE [LARGEUR]
    local redim=()
    if [ -n "${3:-}" ]; then redim=(-resize "${3}x"); fi
    magick "$1" "${redim[@]}" -strip -quality 82 -define webp:method=6 "$TMP/avec-pertes.webp"
    magick "$1" "${redim[@]}" -strip -define webp:lossless=true -define webp:method=6 "$TMP/sans-pertes.webp"
    if [ "$(stat -c%s "$TMP/sans-pertes.webp")" -le "$(stat -c%s "$TMP/avec-pertes.webp")" ]; then
        mv "$TMP/sans-pertes.webp" "$2"
    else
        mv "$TMP/avec-pertes.webp" "$2"
    fi
}
for png in "$REPO"/docs/captures/*.png; do
    nom=$(basename "$png" .png)
    webp "$png" "$SORTIE/img/captures/$nom.webp"
    if [ "$(magick identify -format %w "$png")" -gt 1024 ]; then
        webp "$png" "$SORTIE/img/captures/$nom-1024.webp" 1024
    fi
done

# Le guide hors ligne (le même que dans /usr/share/doc/yggdrasil) et le dépôt APT
cp "$REPO/assets/logo.svg" "$SORTIE/logo.svg"
cp "$REPO/docs/index.html" "$SORTIE/guide.html"
if [ -d "$DEPOT/dists" ]; then
    cp -r "$DEPOT" "$SORTIE/depot"
else
    echo "⚠ pas de dépôt APT dans $DEPOT (./build.sh depot) : le site n'en aura pas" >&2
fi

# L'en-tête commun, ajouté à chaque page (la 404 a le sien) : adresse canonique, aperçu de
# partage (Open Graph), icônes. Puis le chemin du guide vers le site, et le plan du site.
python3 - "$SORTIE" "$ADRESSE" <<'EOF'
import html
import re
import sys
from pathlib import Path

sortie, adresse = Path(sys.argv[1]), sys.argv[2]
# Les pages faites ailleurs (le guide vient de docs/, la page du dépôt de build-repo.sh)
DESCRIPTIONS = {
    "guide.html": "Le mode d'emploi complet d'Yggdrasil : débuter, ygg, les royaumes, Mímir, "
                  "Heimdall, Norns, Bifröst, installer, et les questions fréquentes.",
    "depot/index.html": "Le dépôt APT signé d'Yggdrasil : les outils de l'arbre pour Debian 13, "
                        "sa clé, son empreinte, et comment l'ajouter à une autre Debian.",
}
PARTAGE = "Le logo d'Yggdrasil, l'arbre-monde d'or dans son anneau, et sa devise : l'arbre qui relie tes mondes"


def attribut(texte):
    return texte.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


plan = []
for page in sorted(sortie.rglob("*.html")):
    nom = page.relative_to(sortie).as_posix()
    if nom == "404.html":
        continue
    texte = page.read_text(encoding="utf-8")
    chemin = adresse + re.sub(r"(^|/)index\.html$", r"\1", nom)
    racine = "../" * nom.count("/")
    titre = html.unescape(re.search(r"<title>(.*?)</title>", texte, re.S).group(1).strip())
    ajout = []
    m = re.search(r'<meta name="description" content="([^"]*)">', texte)
    if m:
        description = html.unescape(m.group(1))
    else:
        description = DESCRIPTIONS[nom]
        ajout.append(f'<meta name="description" content="{attribut(description)}">')
    ajout += [
        f'<link rel="canonical" href="{chemin}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Yggdrasil">',
        '<meta property="og:locale" content="fr_FR">',
        f'<meta property="og:url" content="{chemin}">',
        f'<meta property="og:title" content="{attribut(titre)}">',
        f'<meta property="og:description" content="{attribut(description)}">',
        f'<meta property="og:image" content="{adresse}img/partage.png">',
        '<meta property="og:image:width" content="1280">',
        '<meta property="og:image:height" content="640">',
        f'<meta property="og:image:alt" content="{attribut(PARTAGE)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<link rel="icon" href="{racine}favicon.ico" sizes="32x32">',
        f'<link rel="icon" href="{racine}favicon.svg" type="image/svg+xml">',
        f'<link rel="apple-touch-icon" href="{racine}img/apple-touch-icon.png">',
    ]
    texte = re.sub(r'<link rel="icon"[^>]*>\n?', "", texte)
    texte = texte.replace("</head>", "\n".join(ajout) + "\n</head>", 1)
    if nom == "guide.html":
        texte = texte.replace("<body>", '<body>\n<p style="max-width:56rem;margin:1rem auto 0;padding:0 1.25rem">'
                              "<a href=\"./\">← Le site d'Yggdrasil</a></p>", 1)
        texte = texte.replace("</footer>", '<br><a href="confidentialite.html">Confidentialité</a> · '
                              "<a href=\"conditions.html\">Conditions d'utilisation</a></footer>", 1)
    page.write_text(texte, encoding="utf-8")
    plan.append(chemin)

lignes = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
lignes += [f"  <url><loc>{p}</loc></url>" for p in plan]
(sortie / "sitemap.xml").write_text("\n".join(lignes + ["</urlset>"]) + "\n", encoding="utf-8")
EOF

# GitHub Pages sans Jekyll : tout est servi tel quel
touch "$SORTIE/.nojekyll"
echo "site prêt dans $SORTIE ($(du -sh "$SORTIE" | cut -f1))"
