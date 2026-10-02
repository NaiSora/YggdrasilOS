#!/usr/bin/env bash
# {{name}} — forgé par Brokkr sur Yggdrasil le {{date}}.
set -euo pipefail

VERSION="0.1.0"
NOM=$(basename "$0")
BAVARD=0
TEMP=""

usage() {
    cat <<EOF
Usage : $NOM [options] FICHIER...

Compte les lignes de chaque fichier.

Options :
  -v, --bavard     afficher le détail
  -h, --help       cette aide
      --version    la version
EOF
}

info() { printf '\033[32m✔\033[0m %s\n' "$*"; }
erreur() { printf '\033[31m✘\033[0m %s\n' "$*" >&2; }
detail() { if [ "$BAVARD" -eq 1 ]; then printf '  %s\n' "$*"; fi; }

nettoyer() { if [ -n "$TEMP" ]; then rm -rf "$TEMP"; fi; }
trap nettoyer EXIT

main() {
    local fichiers=()
    while [ $# -gt 0 ]; do
        case $1 in
            -v|--bavard) BAVARD=1 ;;
            -h|--help) usage; return 0 ;;
            --version) echo "$NOM $VERSION"; return 0 ;;
            --) shift; fichiers+=("$@"); break ;;
            -*) erreur "option inconnue : $1"; usage >&2; return 2 ;;
            *) fichiers+=("$1") ;;
        esac
        shift
    done
    if [ ${#fichiers[@]} -eq 0 ]; then
        usage >&2
        return 2
    fi
    TEMP=$(mktemp -d)
    local total=0 f n
    for f in "${fichiers[@]}"; do
        if [ ! -r "$f" ]; then
            erreur "illisible : $f"
            return 1
        fi
        n=$(wc -l < "$f")
        detail "$f : $n lignes"
        total=$((total + n))
    done
    info "$total lignes dans ${#fichiers[@]} fichier(s)"
}

main "$@"
