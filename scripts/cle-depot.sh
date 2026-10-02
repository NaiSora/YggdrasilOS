#!/bin/bash
# La clé qui signe le dépôt APT d'Yggdrasil : créée une fois, puis réutilisée.
#
#   scripts/cle-depot.sh exporter FICHIER   clé publique (format binaire, pour Signed-By)
#   scripts/cle-depot.sh signer RELEASE     InRelease et Release.gpg à côté de RELEASE
#   scripts/cle-depot.sh empreinte          l'empreinte de la clé
#
# La clé privée vit dans YGG_CLES (défaut : out/cles du dépôt, ou /out/cles dans le
# conteneur). Garde ce dossier précieusement : sans lui, les machines installées
# refuseront les paquets signés par une nouvelle clé.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
if [ -n "${YGG_CLES:-}" ]; then
    CLES=$YGG_CLES
elif [ -d /out ] && [ -w /out ]; then
    CLES=/out/cles
else
    CLES=$REPO/out/cles
fi
IDENTITE="Yggdrasil (dépôt APT) <depot@yggdrasil.invalid>"

command -v gpg >/dev/null || { echo "✘ gpg est nécessaire (paquet gnupg)" >&2; exit 1; }
mkdir -p "$CLES"
chmod 700 "$CLES"
g() { gpg --homedir "$CLES" --batch --quiet "$@"; }

if ! g --list-secret-keys "$IDENTITE" >/dev/null 2>&1; then
    echo "» Nouvelle clé de signature du dépôt dans $CLES" >&2
    g --passphrase '' --quick-gen-key "$IDENTITE" ed25519 sign never
fi

case "${1:-}" in
    exporter) g --export "$IDENTITE" > "$2" ;;
    signer)
        dossier=$(dirname "$2")
        g --yes --local-user "$IDENTITE" --clearsign --output "$dossier/InRelease" "$2"
        g --yes --local-user "$IDENTITE" --armor --detach-sign --output "$dossier/Release.gpg" "$2"
        ;;
    empreinte) g --with-colons --fingerprint "$IDENTITE" | awk -F: '/^fpr/ {print $10; exit}' ;;
    *) echo "usage : $0 exporter FICHIER | signer RELEASE | empreinte" >&2; exit 1 ;;
esac
