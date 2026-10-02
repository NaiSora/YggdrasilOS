#!/bin/bash
# Skíðblaðnir pour de vrai : l'ISO d'Yggdrasil écrite sur une « clé » (périphérique loop),
# avec un espace persistant chiffré puis en clair. À lancer dans le conteneur --privileged :
#   scripts/test-skidbladnir.sh [dossier_de_sortie]   (YGG_CLE_IMAGE=1 : garde l'image de la clé)
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$REPO/out}
ISO=$(find "$OUT" -maxdepth 1 -name 'yggdrasil-*-amd64.iso' -print -quit)
[ -n "$ISO" ] || { echo "✘ aucune ISO dans $OUT (./build.sh)" >&2; exit 1; }

step() { printf '\n\033[1;33m» %s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
die() { printf '  \033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }
s() { PYTHONPATH="$REPO/src" YGG_DATA_DIR="$REPO/data" NO_COLOR=1 python3 -m yggdrasil.skidbladnir "$@"; }

TRAVAIL=$(mktemp -d)
CLE=$TRAVAIL/cle.img
LOOP=""
nettoyer() {
    umount "$TRAVAIL/m" 2>/dev/null || true
    cryptsetup close verif 2>/dev/null || true
    if [ -n "$LOOP" ]; then losetup -d "$LOOP" 2>/dev/null || true; fi
    rm -rf "$TRAVAIL"
}
trap nettoyer EXIT

# Le conteneur n'a pas forcément de nœuds /dev/loop* : on les crée
[ -e /dev/loop-control ] || mknod /dev/loop-control c 10 237
for i in $(seq 0 15); do [ -e "/dev/loop$i" ] || mknod "/dev/loop$i" b 7 "$i"; done

TAILLE_ISO=$(stat -c %s "$ISO")
truncate -s $((TAILLE_ISO + 1536 * 1024 * 1024)) "$CLE"
LOOP=$(losetup -f --show "$CLE")
NOM=${LOOP#/dev/}
echo "  clé : $LOOP ($(du -h --apparent-size "$CLE" | cut -f1)), image : $(basename "$ISO")"

step "Refus : une image qui n'est pas Yggdrasil, une clé sans confirmation"
head -c 40000 /dev/zero > "$TRAVAIL/faux.iso"
if s ecrire "$NOM" "$TRAVAIL/faux.iso" --loop -y 2>/dev/null; then die "image quelconque acceptée"; fi
if s ecrire "$NOM" "$ISO" --loop </dev/null 2>/dev/null; then die "écriture sans confirmation"; fi
ok "refusé, rien d'écrit"

step "Écriture avec un espace persistant chiffré (LUKS)"
printf 'graine-de-frene' > "$TRAVAIL/phrase"
s ecrire "$NOM" "$ISO" --loop -y --chiffrer --mot-de-passe "$TRAVAIL/phrase"
# Tout est identique à l'ISO, sauf la 3e entrée de la table de partitions (octets 478 à 493)
cmp -i 512 -n $((TAILLE_ISO - 512)) "$ISO" "$LOOP" || die "l'image écrite diffère de l'ISO"
cmp -n 478 "$ISO" "$LOOP" || die "le début du MBR a changé"
cmp -i 494 -n 18 "$ISO" "$LOOP" || die "la fin du MBR a changé"
sfdisk -d "$LOOP" | grep -q 'type=83' || die "pas de partition Linux ajoutée"
P3=${LOOP}p3
[ -b "$P3" ] || die "$P3 absent"
[ "$(blkid -o value -s TYPE "$P3")" = crypto_LUKS ] || die "$P3 n'est pas chiffrée"
cryptsetup open --key-file "$TRAVAIL/phrase" "$P3" verif
[ "$(blkid -o value -s LABEL /dev/mapper/verif)" = persistence ] || die "étiquette « persistence » absente"
mkdir -p "$TRAVAIL/m"
mount /dev/mapper/verif "$TRAVAIL/m"
[ "$(cat "$TRAVAIL/m/persistence.conf")" = "/ union" ] || die "persistence.conf inattendu"
umount "$TRAVAIL/m"
cryptsetup close verif
ok "image identique à l'ISO, partition 3 chiffrée, ext4 « persistence », / union"

step "Réécriture : 1 Go en clair"
s ecrire "$NOM" "$ISO" --loop -y --persistance 1G
[ "$(blkid -o value -s LABEL "$P3")" = persistence ] || die "étiquette absente"
TAILLE_P3=$(( $(cat "/sys/class/block/${NOM}p3/size") * 512 ))
[ "$TAILLE_P3" -eq $((1024 * 1024 * 1024)) ] || die "taille inattendue : $TAILLE_P3"
mount "$P3" "$TRAVAIL/m"
[ "$(cat "$TRAVAIL/m/persistence.conf")" = "/ union" ] || die "persistence.conf inattendu"
umount "$TRAVAIL/m"
ok "partition de 1 Gio en clair"

if [ "${YGG_CLE_IMAGE:-0}" = "1" ]; then
    losetup -d "$LOOP"
    LOOP=""
    cp --sparse=always "$CLE" "$OUT/cle-persistante.img"
    ok "image de la clé : $OUT/cle-persistante.img"
fi
printf '\n\033[1;32mSkíðblaðnir : tout passe.\033[0m\n'
