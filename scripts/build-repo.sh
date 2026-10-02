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

cat > index.html <<EOF
<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Dépôt Yggdrasil</title>
<style>body{font-family:sans-serif;background:#0B2036;color:#F2EAD7;max-width:46em;margin:3em auto;padding:0 1em}
code,pre{background:#0F2742;color:#E8CC8C;padding:.2em .4em;border-radius:4px}pre{padding:1em;overflow:auto}</style></head>
<body><h1>Dépôt APT d'Yggdrasil $VERSION</h1>
<p>Les machines Yggdrasil l'utilisent d'elles-mêmes (paquet <code>yggdrasil-archive-keyring</code>).
Ailleurs, sur Debian 13 :</p>
<pre>sudo curl -fsSLo /usr/share/keyrings/yggdrasil-archive-keyring.gpg ADRESSE/yggdrasil-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/yggdrasil-archive-keyring.gpg] ADRESSE $SUITE main" \\
  | sudo tee /etc/apt/sources.list.d/yggdrasil.list</pre>
<p>Empreinte de la clé : <code>$EMPREINTE</code></p>
<p>Paquets : $PAQUETS.</p>
</body></html>
EOF
echo "  ✔ dépôt $SUITE signé ($(find pool -name '*.deb' | wc -l) paquets) dans $DEPOT"
echo "    clé : $EMPREINTE"
