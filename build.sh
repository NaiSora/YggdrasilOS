#!/bin/bash
# Construit Yggdrasil depuis Linux (ou WSL / Git Bash) avec Docker.
#
#   ./build.sh            paquets + ISO (édition bureau) dans ./out
#   ./build.sh serveur    ISO de l'édition serveur (sans bureau, installateur texte)
#   ./build.sh test       tests automatiques
#   ./build.sh debs       paquets .deb seulement
#   ./build.sh paquets    paquets .deb, installés, exercés puis purgés dans un Debian 13 vierge
#   ./build.sh boot [scénario…]  démarre les ISO dans QEMU, captures d'écran (live, serveur-live,
#                         serveur-install, cle, pilote ; voir scripts/test-iso.sh)
#   ./build.sh depot      dépôt APT signé dans ./out/depot (clé : ./out/cles, à garder)
#   ./build.sh cle        Skíðblaðnir : écrit l'ISO sur une clé virtuelle (loop) avec persistance
#   YGG_CLEAN=1 ./build.sh   repart de zéro
#   YGG_RESUME=1 ./build.sh  reprend une construction interrompue
#   YGG_SOURCES=true ./build.sh   joint les sources des paquets Debian (pour une publication)
set -euo pipefail

# Tout est dans une fonction, lue en entier avant de s'exécuter : modifier ce fichier
# pendant une construction ne la dérange pas (bash lit sinon les scripts au fil de l'eau).
main() {
    local REPO TARGET IMAGE VOLUME CONTEXT EDITION
    REPO=$(cd "$(dirname "$0")" && pwd)
    TARGET=${1:-iso}
    IMAGE=yggdrasil-builder
    VOLUME=yggdrasil-build
    export MSYS_NO_PATHCONV=1  # Git Bash : ne pas réécrire les chemins /src, /out…

    CONTEXT=$REPO/docker
    # Git Bash : docker build veut un chemin Windows (C:\…) pour le contexte
    if command -v cygpath >/dev/null 2>&1; then CONTEXT=$(cygpath -w "$CONTEXT"); fi
    docker build -t "$IMAGE" "$CONTEXT"
    mkdir -p "$REPO/out"
    docker volume create "$VOLUME" >/dev/null
    local COMMON=(--rm -v "$REPO:/src:ro" -v "$REPO/out:/out" -v "$VOLUME:/build")
    # Dans le conteneur, les scripts longs tournent depuis une copie : le dépôt peut changer pendant ce temps
    # shellcheck disable=SC2016  # $0 et $@ sont ceux du bash du conteneur
    local COPIE='cp "$0" /tmp/script.sh && exec bash /tmp/script.sh "$@"'

    case "$TARGET" in
        test) docker run "${COMMON[@]}" --privileged "$IMAGE" bash /src/scripts/test.sh ;;
        debs) docker run "${COMMON[@]}" "$IMAGE" bash -c "cp -r /src /tmp/src && bash /tmp/src/scripts/build-packages.sh /tmp/src /out/debs" ;;
        paquets)
              docker run "${COMMON[@]}" "$IMAGE" bash -c "cp -r /src /tmp/src && bash /tmp/src/scripts/build-packages.sh /tmp/src /out/debs"
              docker run --rm -v "$REPO/out/debs:/debs:ro" -v "$REPO:/src:ro" debian:trixie bash -c "$COPIE" /src/scripts/test-packages.sh ;;
        boot) docker run "${COMMON[@]}" --privileged -e YGG_SRC=/src -e "YGG_PILOTE_ISO=${YGG_PILOTE_ISO:-}" "$IMAGE" \
                  bash -c "$COPIE" /src/scripts/test-iso.sh /out "${@:2}" ;;
        depot) docker run "${COMMON[@]}" "$IMAGE" bash -c "cp -r /src /tmp/src && bash /tmp/src/scripts/build-packages.sh /tmp/src /tmp/debs \
                  && bash /tmp/src/scripts/build-repo.sh /tmp/debs /out/depot" ;;
        cle)  docker run "${COMMON[@]}" --privileged -e "YGG_CLE_IMAGE=${YGG_CLE_IMAGE:-0}" "$IMAGE" \
                  bash /src/scripts/test-skidbladnir.sh /out ;;
        iso|serveur)
              EDITION=bureau
              [ "$TARGET" = serveur ] && EDITION=serveur
              docker run "${COMMON[@]}" --privileged -e "MIRROR=${MIRROR:-http://deb.debian.org/debian/}" \
                  -e "YGG_CLEAN=${YGG_CLEAN:-0}" -e "YGG_RESUME=${YGG_RESUME:-0}" -e "YGG_EDITION=$EDITION" -e YGG_SRC=/src \
                  -e "YGG_SOURCES=${YGG_SOURCES:-false}" \
                  "$IMAGE" bash -c "$COPIE" /src/scripts/build-iso.sh /build /out ;;
        *) echo "cible inconnue : $TARGET (iso, serveur, debs, paquets, test, boot, cle, depot)" >&2; exit 1 ;;
    esac
}

main "$@"
exit
