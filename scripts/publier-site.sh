#!/bin/bash
# Publie le site sur GitHub Pages (branche gh-pages du dépôt origin).
#
#   scripts/publier-site.sh
#
# La branche gh-pages ne sert qu'au déploiement : elle est remplacée à chaque fois par un
# seul commit (le site et le dépôt APT y sont reconstruits en entier), pour que les .deb
# de chaque version ne s'y accumulent pas. L'historique du site reste sur main (site/).
# Le dépôt APT vient de out/depot, signé avec la clé de out/cles : la clé ne quitte pas
# cette machine.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(tr -d ' \r\n' < "$REPO/VERSION")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

bash "$REPO/scripts/build-site.sh" "$TMP/site"
[ -f "$TMP/site/depot/dists/trixie/InRelease" ] \
    || { echo "✘ le site doit porter le dépôt APT signé : ./build.sh depot d'abord" >&2; exit 1; }
grep -q "^Version: $VERSION$" "$TMP/site/depot/dists/trixie/Release" \
    || { echo "✘ le dépôt APT n'est pas celui de la version $VERSION : ./build.sh depot" >&2; exit 1; }

DISTANT=$(git -C "$REPO" remote get-url origin)
cd "$TMP/site"
git init -q -b gh-pages
git add -A
git -c user.name="$(git -C "$REPO" config user.name)" -c user.email="$(git -C "$REPO" config user.email)" \
    commit -q -m "Site d'Yggdrasil $VERSION (main $(git -C "$REPO" rev-parse --short HEAD))"
git push -q --force "$DISTANT" gh-pages
echo "✔ site publié sur gh-pages ($(du -sh --exclude=.git . | cut -f1))"
