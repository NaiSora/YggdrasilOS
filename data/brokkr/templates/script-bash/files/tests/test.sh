#!/usr/bin/env bash
# Tests de {{slug}}.sh : ./tests/test.sh
set -euo pipefail
cd "$(dirname "$0")/.."
script=./{{slug}}.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf 'a\nb\n' > "$tmp/deux"
printf 'c\n' > "$tmp/une"

"$script" --help | grep -q "Usage"
"$script" "$tmp/deux" "$tmp/une" | grep -q "3 lignes dans 2 fichier"
"$script" -v "$tmp/une" | grep -q "1 lignes"
if "$script" "$tmp/absent" 2>/dev/null; then echo "un fichier absent doit échouer"; exit 1; fi
if "$script" --inconnue 2>/dev/null; then echo "une option inconnue doit échouer"; exit 1; fi
echo "tous les tests passent"
