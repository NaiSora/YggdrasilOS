#!/bin/bash
# Construit l'image ISO d'Yggdrasil avec live-build.
#
# À lancer en root sur Debian 13 (ou dans le conteneur docker/Dockerfile, en --privileged) :
#   scripts/build-iso.sh [dossier_de_travail] [dossier_de_sortie]
#
# Variables : MIRROR (miroir Debian), YGG_CLEAN=1 (repartir de zéro, cache compris),
#             YGG_RESUME=1 (reprendre une construction interrompue sans tout refaire),
#             YGG_EDITION=bureau (défaut : Plasma, Calamares) ou serveur (sans bureau),
#             YGG_SOURCES=true (les sources des paquets Debian de l'image, pour une publication :
#             la GPL les demande ; plusieurs Go, découpés en morceaux de moins de 2 Gio)
set -euo pipefail

# YGG_SRC : le dépôt, quand ce script tourne depuis une copie (build.sh)
REPO=${YGG_SRC:-$(cd "$(dirname "$0")/.." && pwd)}
WORK=${1:-/build}
OUT=${2:-$REPO/out}
MIRROR=${MIRROR:-http://deb.debian.org/debian/}
SECURITY_MIRROR=${SECURITY_MIRROR:-http://security.debian.org/debian-security/}

VERSION=$(tr -d ' \r\n' < "$REPO/VERSION")
EDITION=${YGG_EDITION:-bureau}
LANGUE="locales=fr_FR.UTF-8 keyboard-layouts=fr timezone=Europe/Paris hostname=yggdrasil username=ygg"
case "$EDITION" in
    bureau)
        NAME="yggdrasil-${VERSION}-amd64"
        VOLUME="YGGDRASIL_${VERSION//./_}"
        APPEND="boot=live components quiet splash $LANGUE"
        ;;
    serveur)
        NAME="yggdrasil-serveur-${VERSION}-amd64"
        VOLUME="YGGDRASIL_SRV_${VERSION//./_}"
        APPEND="boot=live components quiet $LANGUE"
        ;;
    *) printf 'édition inconnue : %s (bureau ou serveur)\n' "$EDITION" >&2; exit 1 ;;
esac

log() { printf '\n\033[1;33m» %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "live-build doit tourner en root (ou dans le conteneur --privileged)."
command -v lb >/dev/null || die "live-build est absent (apt install live-build)."

mkdir -p "$WORK" "$OUT"
# Un espace live-build par édition : chacune garde son cache et peut reprendre
LIVE=$WORK/live
[ "$EDITION" = bureau ] || LIVE=$WORK/live-$EDITION
SRC=$WORK/src

log "Copie du dépôt dans l'espace de travail ($WORK)"
# Le dépôt peut être sur un disque Windows monté : on travaille sur une copie Linux
# (droits d'exécution, fichiers spéciaux de debootstrap…).
rsync -a --delete --exclude out/ --exclude build/ --exclude .git/ --exclude __pycache__/ "$REPO/" "$SRC/"
find "$SRC" -type f \( -name '*.sh' -o -name '*.chroot' -o -name '*.binary' \) -exec sed -i 's/\r$//' {} +

prepare() {
log "Paquets Yggdrasil"
rm -rf "$WORK/debs"
bash "$SRC/scripts/build-packages.sh" "$SRC" "$WORK/debs"

log "Configuration de live-build"
mkdir -p "$LIVE"
cd "$LIVE"
# Une nouvelle édition profite des paquets déjà téléchargés pour l'autre (liens durs)
if [ "$LIVE" != "$WORK/live" ] && [ ! -d cache ] && [ -d "$WORK/live/cache" ]; then
    mkdir -p cache
    for d in packages.bootstrap packages.chroot packages.binary; do
        if [ -d "$WORK/live/cache/$d" ]; then cp -al "$WORK/live/cache/$d" cache/; fi
    done
fi
if [ "${YGG_CLEAN:-0}" = "1" ]; then
    lb clean --purge || true
else
    lb clean || true
fi
rm -rf config auto

lb config \
    --mode debian \
    --distribution trixie \
    --architecture amd64 \
    --archive-areas "main contrib non-free non-free-firmware" \
    --mirror-bootstrap "$MIRROR" \
    --mirror-chroot "$MIRROR" \
    --mirror-binary "http://deb.debian.org/debian/" \
    --mirror-chroot-security "$SECURITY_MIRROR" \
    --mirror-binary-security "http://security.debian.org/debian-security/" \
    --security true \
    --updates true \
    --binary-image iso-hybrid \
    --bootloaders "grub-efi,syslinux" \
    --uefi-secure-boot enable \
    --debian-installer live \
    --debian-installer-gui false \
    --debian-installer-distribution trixie \
    --linux-flavours amd64 \
    --firmware-chroot true \
    --firmware-binary false \
    --apt-recommends true \
    --cache true \
    --cache-packages true \
    --chroot-squashfs-compression-type zstd \
    --memtest none \
    --checksums sha256 \
    --source "${YGG_SOURCES:-false}" \
    --source-images tar \
    --zsync false \
    --iso-application "Yggdrasil" \
    --iso-publisher "Projet Yggdrasil" \
    --iso-volume "$VOLUME" \
    --image-name "${NAME%-amd64}" \
    --bootappend-live "$APPEND" \
    --bootappend-install "locale=fr_FR.UTF-8 keymap=fr" \
    --bootappend-live-failsafe "boot=live components memtest noapic noapm nodma nomce nosmp nosplash vga=788 locales=fr_FR.UTF-8 keyboard-layouts=fr"

log "Habillage et contenu Yggdrasil"
# Menus de démarrage : modèles de live-build + surcharges d'Yggdrasil
mkdir -p config/bootloaders
for d in grub-pc syslinux_common isolinux; do
    cp -a "/usr/share/live/build/bootloaders/$d" config/bootloaders/
done
cp -a "$SRC/live/bootloaders/." config/bootloaders/
python3 "$SRC/assets/generate.py" "$WORK/svg" >/dev/null
cp "$WORK/svg/bootsplash.svg" config/bootloaders/splash.svg
sed -i \
    -e "s/'Utilities\.\.\.'/'Utilitaires…'/" \
    -e 's/"UEFI Firmware Settings"/"Réglages du micrologiciel UEFI"/' \
    config/bootloaders/grub-pc/grub.cfg

cp -a "$SRC/live/package-lists/." config/package-lists/
if [ "$EDITION" = serveur ]; then
    # Ni bureau ni Calamares : l'installateur est le Debian Installer, en mode texte
    rm -f config/package-lists/desktop.list.chroot config/package-lists/installer.list.chroot
    cp -a "$SRC/live/serveur/package-lists/." config/package-lists/
fi
# Debian Installer : réponses par défaut (langue, clavier, sources…)
mkdir -p config/includes.installer
cp "$SRC/live/installer/preseed.cfg" config/includes.installer/preseed.cfg
mkdir -p config/hooks/live config/includes.chroot_after_packages config/packages.chroot
cp -a "$SRC/live/hooks/live/." config/hooks/live/
chmod 0755 config/hooks/live/*
cp -a "$SRC/live/includes.chroot/." config/includes.chroot_after_packages/
if [ "$EDITION" = serveur ]; then
    cp -a "$SRC/live/serveur/includes.chroot/." config/includes.chroot_after_packages/
fi
chmod 0755 config/includes.chroot_after_packages/usr/lib/live/config/*
# live-build installe tout paquet posé dans packages.chroot : chaque édition ne reçoit
# que les siens (le bureau n'a ni SSH ouvert ni Docker ; le serveur n'a ni Plasma ni Calamares)
case "$EDITION" in
    bureau) EXCLUS="yggdrasil-serveur" ;;
    serveur) EXCLUS="yggdrasil-desktop yggdrasil-calamares" ;;
esac
for deb in "$WORK"/debs/*.deb; do
    paquet=$(basename "$deb")
    paquet=${paquet%%_*}
    case " $EXCLUS " in
        *" $paquet "*) echo "  (pas pour l'édition $EDITION : $paquet)" ;;
        *) cp "$deb" config/packages.chroot/ ;;
    esac
done
}

if [ "${YGG_RESUME:-0}" = "1" ] && [ -d "$LIVE/config" ]; then
    # live-build saute les étapes déjà terminées (fichiers .build/*) : on repart de l'échec.
    log "Reprise de la construction là où elle s'était arrêtée"
    cd "$LIVE"
else
    prepare
fi

log "Construction de l'édition $EDITION (comptez 20 à 60 minutes selon la connexion)"
JOURNAL=$WORK/build-$EDITION.log
lb build 2>&1 | tee "$JOURNAL"

ISO=$(find "$LIVE" -maxdepth 1 -name '*.iso' -print -quit)
[ -n "$ISO" ] || die "aucune ISO produite : voir $JOURNAL"
# Garde-fou : chaque édition ne contient que ce qui lui revient
if [ -f "$LIVE/chroot.packages.live" ]; then
    case "$EDITION" in
        bureau) INTERDITS="yggdrasil-serveur" ;;
        serveur) INTERDITS="yggdrasil-desktop yggdrasil-calamares calamares plasma-desktop sddm" ;;
    esac
    for p in $INTERDITS; do
        if awk -v p="$p" '$1 == p { trouve = 1 } END { exit !trouve }' "$LIVE/chroot.packages.live"; then
            die "le paquet $p n'a rien à faire dans l'édition $EDITION"
        fi
    done
fi
cp "$ISO" "$OUT/$NAME.iso"
(cd "$OUT" && sha256sum "$NAME.iso" > "$NAME.iso.sha256")
cp "$JOURNAL" "$OUT/$NAME.build.log"
if [ -f "$LIVE/chroot.packages.live" ]; then
    cp "$LIVE/chroot.packages.live" "$OUT/$NAME.packages"
fi
# Les sources des paquets Debian de l'image, aux versions exactes (lb source) : en morceaux
# de moins de 2 Gio, la taille maximale d'un fichier de release GitHub
rm -f "$OUT/$NAME-sources.tar."*
if [ "${YGG_SOURCES:-false}" = true ]; then
    SOURCES=$(find "$LIVE" -maxdepth 1 -name '*-source.debian.tar' -print -quit)
    [ -n "$SOURCES" ] || die "sources demandées, mais aucune archive : voir $JOURNAL"
    split -b 1900M -d -a 3 --numeric-suffixes=1 "$SOURCES" "$OUT/$NAME-sources.tar."
    log "Sources : $(du -h "$SOURCES" | cut -f1) en $(find "$OUT" -maxdepth 1 -name "$NAME-sources.tar.*" | wc -l) morceaux"
fi

# Le dépôt APT signé qui va avec (à publier à l'adresse de depot.conf)
if [ -d "$WORK/debs" ]; then
    log "Dépôt APT signé"
    bash "$SRC/scripts/build-repo.sh" "$WORK/debs" "$OUT/depot"
fi

log "ISO prête : $OUT/$NAME.iso ($(du -h "$OUT/$NAME.iso" | cut -f1))"
