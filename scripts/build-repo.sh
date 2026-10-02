#!/bin/bash
# Construit le dépôt APT signé d'Yggdrasil à partir des paquets .deb.
#
#   scripts/build-repo.sh DOSSIER_DES_DEBS DOSSIER_DU_DÉPÔT
#
# Le dossier produit se publie tel quel sur un serveur web ; son adresse va dans
# depot.conf (DEPOT_URL) avant la construction de l'ISO.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
DEBS=$(cd "$1" && pwd)
DEPOT=$2
SUITE=trixie
VERSION=$(tr -d ' \r\n' < "$REPO/VERSION")

command -v apt-ftparchive >/dev/null || { echo "✘ apt-ftparchive est nécessaire (paquet apt-utils)" >&2; exit 1; }
ls "$DEBS"/*.deb >/dev/null 2>&1 || { echo "✘ aucun paquet dans $DEBS" >&2; exit 1; }

rm -rf "$DEPOT"
mkdir -p "$DEPOT/pool/main" "$DEPOT/dists/$SUITE/main/binary-amd64" "$DEPOT/dists/$SUITE/main/binary-all"
cp "$DEBS"/*.deb "$DEPOT/pool/main/"

cd "$DEPOT"
for arch in amd64 all; do
    apt-ftparchive packages pool/main > "dists/$SUITE/main/binary-$arch/Packages"
    gzip -9kn "dists/$SUITE/main/binary-$arch/Packages"
    xz -kf "dists/$SUITE/main/binary-$arch/Packages"
done
apt-ftparchive \
    -o APT::FTPArchive::Release::Origin=Yggdrasil \
    -o APT::FTPArchive::Release::Label=Yggdrasil \
    -o APT::FTPArchive::Release::Suite="$SUITE" \
    -o APT::FTPArchive::Release::Codename="$SUITE" \
    -o APT::FTPArchive::Release::Version="$VERSION" \
    -o APT::FTPArchive::Release::Architectures="amd64 all" \
    -o APT::FTPArchive::Release::Components=main \
    -o APT::FTPArchive::Release::Description="Yggdrasil $VERSION — les outils de l'arbre" \
    release "dists/$SUITE" > "dists/$SUITE/Release"
bash "$REPO/scripts/cle-depot.sh" signer "$DEPOT/dists/$SUITE/Release"
bash "$REPO/scripts/cle-depot.sh" exporter "$DEPOT/yggdrasil-archive-keyring.gpg"
EMPREINTE=$(bash "$REPO/scripts/cle-depot.sh" empreinte)
PAQUETS=$(find pool/main -name '*.deb' -printf '%f\n' | sed 's/_.*//' | sort -u | paste -sd, - | sed 's/,/, /g')
ADRESSE=$(sed -n 's/^DEPOT_URL=//p' "$REPO/depot.conf" 2>/dev/null | tr -d ' \r"')
ADRESSE=${ADRESSE%/}

# La page du dépôt, aux couleurs du site qui l'héberge (style.css, un dossier plus haut)
cat > index.html <<EOF
<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dépôt APT — Yggdrasil</title><meta name="theme-color" content="#091c30">
<link rel="icon" href="../img/logo.svg" type="image/svg+xml"><link rel="stylesheet" href="../style.css"></head>
<body><main><section class="section">
<p><a href="../">← Le site d'Yggdrasil</a></p>
<h1 class="titre-section">Le dépôt APT d'Yggdrasil $VERSION</h1>
<p class="chapeau">Les machines Yggdrasil l'utilisent d'elles-mêmes (paquet <code>yggdrasil-archive-keyring</code>) :
<code>ygg update</code> y prend les nouvelles versions des outils. Il est signé : APT refuse tout paquet que
cette clé n'a pas signé. Sur une autre Debian 13 :</p>
<pre><code>sudo curl -fsSLo /usr/share/keyrings/yggdrasil-archive-keyring.gpg ${ADRESSE:-ADRESSE}/yggdrasil-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/yggdrasil-archive-keyring.gpg] ${ADRESSE:-ADRESSE} $SUITE main" \\
  | sudo tee /etc/apt/sources.list.d/yggdrasil.list
sudo apt update</code></pre>
<p>Empreinte de la clé : <code>$EMPREINTE</code></p>
<p class="muet">Paquets : $PAQUETS.</p>
</section></main></body></html>
EOF
echo "  ✔ dépôt $SUITE signé ($(find pool -name '*.deb' | wc -l) paquets) dans $DEPOT"
echo "    clé : $EMPREINTE"
