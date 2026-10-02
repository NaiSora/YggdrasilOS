#!/bin/bash
# Assemble le site d'Yggdrasil (GitHub Pages) : les pages de site/, le logo, les captures
# d'écran, le guide hors ligne et le dépôt APT signé (out/depot, fait par ./build.sh depot).
# Les versions et leurs fichiers ne sont pas copiés : les pages les lisent dans les releases.
#
#   scripts/build-site.sh [SORTIE]          (défaut : out/site)
#   YGG_DEPOT=chemin/du/depot scripts/build-site.sh
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
SORTIE=${1:-$REPO/out/site}
DEPOT=${YGG_DEPOT:-$REPO/out/depot}

rm -rf "$SORTIE"
mkdir -p "$SORTIE/img/captures"
cp -r "$REPO/site/." "$SORTIE/"
cp "$REPO/assets/logo.svg" "$SORTIE/img/logo.svg"
cp "$REPO/docs/captures/"*.png "$SORTIE/img/captures/"
# Le guide hors ligne (le même que dans /usr/share/doc/yggdrasil), avec un chemin vers le site
cp "$REPO/assets/logo.svg" "$SORTIE/logo.svg"
sed 's|<body>|<body>\n<p style="max-width:56rem;margin:1rem auto 0;padding:0 1.25rem"><a href="./" style="color:inherit">← Le site d'"'"'Yggdrasil</a></p>|' \
    "$REPO/docs/index.html" > "$SORTIE/guide.html"
# GitHub Pages sans Jekyll : tout est servi tel quel
touch "$SORTIE/.nojekyll"
if [ -d "$DEPOT/dists" ]; then
    cp -r "$DEPOT" "$SORTIE/depot"
else
    echo "⚠ pas de dépôt APT dans $DEPOT (./build.sh depot) : le site n'en aura pas" >&2
fi
echo "site prêt dans $SORTIE ($(du -sh "$SORTIE" | cut -f1))"
