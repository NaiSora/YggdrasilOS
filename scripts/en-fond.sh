#!/bin/bash
# Enchaîne des cibles de build.sh, chacune avec son journal dans out/<cible>.log et une
# dernière ligne « code N ». Fait pour tourner détaché (une construction dure une heure) :
#   scripts/en-fond.sh iso serveur "boot serveur-live"
set -uo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO" || exit 1
# Fins de ligne Unix pour tout ce qui part dans le conteneur
find scripts live packages -type f \( -name '*.sh' -o -name '*.chroot' -o -name '*.binary' -o -path '*/DEBIAN/*' \
    -o -path '*grub.d*' -o -name '*.cfg' -o -name '*.conf' -o -name '*.qss' \) -exec sed -i 's/\r$//' {} +
for cible in "$@"; do
    journal="out/$(echo "$cible" | tr ' ' '-').log"
    # shellcheck disable=SC2086  # « boot serveur-live » : la cible et ses arguments
    ./build.sh $cible > "$journal" 2>&1
    echo "code $?" >> "$journal"
done
