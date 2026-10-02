#!/bin/bash
# Construit les paquets .deb d'Yggdrasil.
#
#   scripts/build-packages.sh [dossier_du_dépôt] [dossier_de_sortie]
#
# Prérequis (Debian) : dpkg-dev librsvg2-bin grub-common fonts-dejavu-core
# fonts-ebgaramond papirus-icon-theme imagemagick python3
set -euo pipefail

REPO=$(cd "${1:-$(dirname "$0")/..}" && pwd)
OUT=${2:-$REPO/build/debs}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

VERSION=$(tr -d ' \r\n' < "$REPO/VERSION")
VERSION_SHORT=${VERSION%.*}
PACKAGES=(yggdrasil-base yggdrasil-tools yggdrasil-desktop yggdrasil-calamares yggdrasil-archive-keyring
          yggdrasil-serveur)
TOOLS=(ygg mimir heimdall norns bifrost brokkr ratatoskr urd verdandi skuld huginn muninn gleipnir draupnir skidbladnir)
FONTS=/usr/share/fonts/truetype/dejavu
PAPIRUS=/usr/share/icons/Papirus
FRAMES=48

log() { printf '\033[1;33m» %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "commande manquante : $1 (paquet $2)"; }

need dpkg-deb dpkg
need rsvg-convert librsvg2-bin
need grub-mkfont grub-common
need python3 python3
need convert imagemagick
[ -f "$FONTS/DejaVuSans.ttf" ] || die "polices DejaVu absentes (paquet fonts-dejavu-core)"
fc-list : family | grep -i "EB Garamond" > /dev/null || die "police EB Garamond absente (paquet fonts-ebgaramond)"
[ -d "$PAPIRUS" ] || die "thème d'icônes Papirus absent (paquet papirus-icon-theme)"

# --------------------------------------------------------------------------
log "Visuels (assets/generate.py, d'après assets/logo.svg)"
SVG=$WORK/svg
python3 "$REPO/assets/generate.py" "$SVG" >/dev/null
png() { # png <svg> <largeur> <hauteur|-> <sortie>
    install -d "$(dirname "$4")"
    if [ "$3" = "-" ]; then
        rsvg-convert -w "$2" "$SVG/$1" -o "$4"
    else
        rsvg-convert -w "$2" -h "$3" "$SVG/$1" -o "$4"
    fi
}

stage() {
    local pkg=$1 dest=$WORK/pkg/$1
    mkdir -p "$dest"
    cp -a "$REPO/packages/$pkg/DEBIAN" "$dest/"
    if [ -d "$REPO/packages/$pkg/root" ]; then
        cp -a "$REPO/packages/$pkg/root/." "$dest/"
    fi
    install -d "$dest/usr/share/doc/$pkg"
    {
        echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
        echo "Upstream-Name: Yggdrasil"
        echo
        echo "Files: *"
        echo "Copyright: $(date +%Y) Projet Yggdrasil"
        echo "License: tous-droits-reserves"
        echo " Aucune licence n'est encore accordée pour le code d'Yggdrasil : tous droits réservés."
        echo " Les paquets Debian installés à côté gardent chacun leur propre licence"
        echo " (voir /usr/share/doc/*/copyright)."
    } > "$dest/usr/share/doc/$pkg/copyright"
}

# --------------------------------------------------------------------------
log "yggdrasil-base"
stage yggdrasil-base
B=$WORK/pkg/yggdrasil-base

GT=$B/usr/share/grub/themes/yggdrasil
png grub.svg 1920 1080 "$GT/background.png"
png grub-select-w.svg 10 40 "$GT/select_w.png"
png grub-select-c.svg 4 40 "$GT/select_c.png"
png grub-select-e.svg 10 40 "$GT/select_e.png"
grub-mkfont -s 12 -o "$GT/dejavu_sans_12.pf2" "$FONTS/DejaVuSans.ttf"
grub-mkfont -s 14 -o "$GT/dejavu_sans_14.pf2" "$FONTS/DejaVuSans.ttf"
grub-mkfont -s 16 -o "$GT/dejavu_sans_16.pf2" "$FONTS/DejaVuSans.ttf"
grub-mkfont -s 16 -o "$GT/dejavu_sans_bold_16.pf2" "$FONTS/DejaVuSans-Bold.ttf"
grub-mkfont -s 14 -o "$GT/dejavu_sans_mono_14.pf2" "$FONTS/DejaVuSansMono.ttf"

PT=$B/usr/share/plymouth/themes/yggdrasil
for ((i = 0; i < FRAMES; i++)); do
    png "arbre/arbre-$i.svg" 360 360 "$PT/arbre-$i.png"
done
png halo.svg 360 360 "$PT/halo.png"
png title.svg 240 - "$PT/title.png"
png plymouth-progress-bg.svg 240 3 "$PT/progress-bg.png"
png plymouth-progress-fg.svg 240 3 "$PT/progress-fg.png"

BG=$B/usr/share/backgrounds/yggdrasil
install -d "$BG"
cp "$SVG/wallpaper-1920x1080.svg" "$BG/yggdrasil.svg"
png wallpaper-1920x1080.svg 1920 1080 "$BG/yggdrasil-1920x1080.png"
png wallpaper-3840x2160.svg 3840 2160 "$BG/yggdrasil-3840x2160.png"
cp "$SVG/login.svg" "$BG/yggdrasil-login.svg"

TH=$B/usr/share/desktop-base/yggdrasil-theme
png wallpaper-1920x1080.svg 1920 1080 "$TH/wallpaper/contents/images/1920x1080.png"
png wallpaper-2560x1440.svg 2560 1440 "$TH/wallpaper/contents/images/2560x1440.png"
png wallpaper-1920x1200.svg 1920 1200 "$TH/wallpaper/contents/images/1920x1200.png"
install -d "$TH/login" "$TH/lockscreen/contents/images"
cp "$SVG/login.svg" "$TH/login/background.svg"
png login.svg 1920 1080 "$TH/lockscreen/contents/images/1920x1080.png"
png grub.svg 1920 1080 "$TH/grub/grub-16x9.png"
png grub-4x3.svg 1024 768 "$TH/grub/grub-4x3.png"

for size in 16 22 24 32 48 64 128 256 512; do
    png icon.svg "$size" "$size" "$B/usr/share/icons/hicolor/${size}x${size}/apps/yggdrasil.png"
done
install -d "$B/usr/share/icons/hicolor/scalable/apps" "$B/usr/share/pixmaps"
cp "$SVG/icon-qt.svg" "$B/usr/share/icons/hicolor/scalable/apps/yggdrasil.svg"
cp "$SVG/icon-qt.svg" "$B/usr/share/pixmaps/yggdrasil.svg"
cp "$SVG/icon-alerte.svg" "$B/usr/share/icons/hicolor/scalable/apps/yggdrasil-alerte.svg"
png icon.svg 256 256 "$B/usr/share/pixmaps/yggdrasil.png"

install -d "$B/usr/share/yggdrasil/arbre" "$B/usr/share/doc/yggdrasil"
echo "$VERSION" > "$B/usr/share/yggdrasil/version"
cp "$REPO/docs/index.html" "$B/usr/share/doc/yggdrasil/index.html"
cp "$SVG/emblem.svg" "$B/usr/share/doc/yggdrasil/logo.svg"
# L'arbre-monde du terminal : le grand (ASCII fourni) et le petit, au format
# fastfetch ($1 $2 $3), et en séquences ANSI pour la console et le message d'accueil.
A=$B/usr/share/yggdrasil/arbre
cp "$REPO/assets/arbre-grand.txt" "$A/grand.txt"
python3 "$REPO/assets/arbre_ascii.py" compact > "$A/compact.txt"
for size in grand compact; do
    python3 "$REPO/assets/arbre_ascii.py" ansi "$A/$size.txt" > "$A/$size.ansi"
done

# Le catalogue français de GRUB laisse le menu en anglais (« Advanced options for… ») : un
# catalogue fr_FR complet, le sien plus assets/grub-fr.po, que gettext et GRUB préfèrent à fr
GRUB_MO=/usr/share/locale/fr/LC_MESSAGES/grub.mo
[ -f "$GRUB_MO" ] || die "catalogue français de GRUB absent : $GRUB_MO (paquet grub-common)"
L=$B/usr/share/locale
install -d "$L/fr_FR/LC_MESSAGES"
python3 "$REPO/scripts/catalogue-grub.py" fusionner "$GRUB_MO" "$REPO/assets/grub-fr.po" "$L/fr_FR/LC_MESSAGES/grub.mo"
for variante in fr_BE fr_CA fr_CH fr_LU; do
    install -d "$L/$variante/LC_MESSAGES"
    ln -s ../../fr_FR/LC_MESSAGES/grub.mo "$L/$variante/LC_MESSAGES/grub.mo"
done

# --------------------------------------------------------------------------
log "yggdrasil-tools"
stage yggdrasil-tools
T=$WORK/pkg/yggdrasil-tools
install -d "$T/usr/lib/python3/dist-packages" "$T/usr/share/yggdrasil" "$T/usr/bin"
cp -a "$REPO/src/yggdrasil" "$T/usr/lib/python3/dist-packages/"
find "$T/usr/lib/python3/dist-packages" -name __pycache__ -type d -prune -exec rm -rf {} +
for d in realms bifrost brokkr; do
    cp -a "$REPO/data/$d" "$T/usr/share/yggdrasil/"
done
for tool in "${TOOLS[@]}"; do
    cat > "$T/usr/bin/$tool" <<EOF
#!/usr/bin/python3
# $tool — outil Yggdrasil (paquet yggdrasil-tools)
import sys

from yggdrasil.$tool import main

sys.exit(main())
EOF
done
for tool in "${TOOLS[@]}"; do
    [ "$tool" = "ygg" ] || ln -sf ygg "$T/usr/share/bash-completion/completions/$tool"
done

# --------------------------------------------------------------------------
log "yggdrasil-desktop"
stage yggdrasil-desktop
D=$WORK/pkg/yggdrasil-desktop
install -d "$D/usr/bin"
cat > "$D/usr/bin/yggdrasil-welcome" <<'EOF'
#!/usr/bin/python3
# Centre de bienvenue d'Yggdrasil (paquet yggdrasil-desktop)
import sys

from yggdrasil.welcome import main

sys.exit(main())
EOF

# L'arbre vivant : le fond dont les feuilles des royaumes installés s'allument (ygg realm arbre)
install -D -m 644 "$SVG/arbre-vivant.svg" "$D/usr/share/yggdrasil/arbre-vivant.svg"

# Raccourcis globaux de Mímir : Plasma les lit dans share/kglobalaccel
install -d "$D/usr/share/kglobalaccel"
for app in mimir mimir-selection; do
    ln -sf "../applications/$app.desktop" "$D/usr/share/kglobalaccel/$app.desktop"
done

# Fonds d'écran (paquet de fonds Plasma : Plasma choisit la taille la plus proche)
WP=$D/usr/share/wallpapers/Yggdrasil/contents
for file in "$SVG"/wallpaper-*.svg; do
    size=${file##*/wallpaper-}
    size=${size%.svg}
    png "wallpaper-$size.svg" "${size%x*}" "${size#*x}" "$WP/images/$size.png"
done
png wallpaper-1920x1080.svg 400 225 "$WP/screenshot.png"

# Apparence globale : animation de l'écran de session, aperçus
LNF=$D/usr/share/plasma/look-and-feel/org.yggdrasil.desktop/contents
for ((i = 0; i < FRAMES; i++)); do
    png "arbre/arbre-$i.svg" 512 512 "$LNF/splash/images/arbre-$i.png"
done
png title.svg 560 - "$LNF/splash/images/title.png"
png preview.svg 640 360 "$LNF/previews/preview.png"
png preview.svg 1280 720 "$WORK/fullpreview.png"
convert "$WORK/fullpreview.png" -quality 90 "$LNF/previews/fullscreenpreview.jpg"

# Écran de connexion SDDM
SD=$D/usr/share/sddm/themes/yggdrasil
png login.svg 1920 1080 "$SD/background.png"
png emblem.svg 512 512 "$SD/logo.png"
png preview.svg 640 360 "$SD/preview.png"

# Couleurs par défaut : le jeu « Yggdrasil » recopié dans kdeglobals (seul
# endroit où Plasma lit les couleurs par défaut), sauf [General] et [KDE].
awk '/^\[/{keep = ($0 !~ /^\[(General|KDE)\]/)} keep' \
    "$D/usr/share/color-schemes/Yggdrasil.colors" >> "$D/etc/xdg/yggdrasil/kdeglobals"

# Thème d'icônes : Papirus sombre, dossiers dorés (variante « paleorange »,
# la plus proche de l'or du logo), comme le ferait papirus-folders.
IT=$D/usr/share/icons/Yggdrasil
install -d "$IT"
dirs=()
for sizedir in "$PAPIRUS"/*/places; do
    size=$(basename "$(dirname "$sizedir")")
    found=0
    for icon in "$sizedir"/*-paleorange*.svg; do
        [ -e "$icon" ] || continue
        name=$(basename "$icon")
        target=${name/-paleorange/}
        install -d "$IT/$size/places"
        ln -sf "/usr/share/icons/Papirus/$size/places/$name" "$IT/$size/places/$target"
        found=1
    done
    if [ "$found" = 1 ]; then dirs+=("$size/places"); fi
done
[ "${#dirs[@]}" -gt 0 ] || die "aucune icône de dossier « paleorange » dans Papirus"
{
    echo "[Icon Theme]"
    echo "Name=Yggdrasil"
    echo "Comment=Papirus sombre aux dossiers dorés"
    echo "Inherits=Papirus-Dark,breeze-dark,hicolor"
    echo "Example=folder"
    echo "FollowsColorScheme=true"
    (IFS=,; echo "Directories=${dirs[*]}")
    for d in "${dirs[@]}"; do
        size=${d%%/*}
        echo
        echo "[$d]"
        echo "Context=Places"
        if [ "$size" = "symbolic" ]; then
            echo "Size=16"
            echo "MinSize=16"
            echo "MaxSize=512"
            echo "Type=Scalable"
        else
            n=${size%%x*}
            n=${n%@*}
            echo "Size=$n"
            case "$size" in *@2x) echo "Scale=2" ;; esac
            echo "Type=Fixed"
        fi
    done
} > "$IT/index.theme"

# --------------------------------------------------------------------------
log "yggdrasil-archive-keyring"
stage yggdrasil-archive-keyring
K=$WORK/pkg/yggdrasil-archive-keyring
bash "$REPO/scripts/cle-depot.sh" exporter "$K/usr/share/keyrings/yggdrasil-archive-keyring.gpg"
DEPOT_URL=$(sed -n 's/^DEPOT_URL=//p' "$REPO/depot.conf" 2>/dev/null | tr -d ' \r"')
if [ -n "$DEPOT_URL" ]; then DEPOT_ACTIF=yes; else DEPOT_URL=https://depot.yggdrasil.invalid/; DEPOT_ACTIF=no; fi
sed -i -e "s|@DEPOT_URL@|$DEPOT_URL|" -e "s|@DEPOT_ACTIF@|$DEPOT_ACTIF|" "$K/etc/apt/sources.list.d/yggdrasil.sources"
echo "  dépôt : $DEPOT_URL ($([ "$DEPOT_ACTIF" = yes ] && echo actif || echo "désactivé : depot.conf"))"

# --------------------------------------------------------------------------
log "yggdrasil-serveur"
stage yggdrasil-serveur
# L'arbre-monde à la console, avant la connexion (agetty), avec l'adresse de la machine
python3 "$REPO/assets/arbre_ascii.py" issue "$A/compact.txt" \
    > "$WORK/pkg/yggdrasil-serveur/etc/issue.d/yggdrasil-arbre.issue"

# --------------------------------------------------------------------------
log "yggdrasil-calamares"
stage yggdrasil-calamares
C=$WORK/pkg/yggdrasil-calamares/etc/calamares/branding/yggdrasil
png icon.svg 256 256 "$C/logo.png"
png calamares-welcome.svg 600 300 "$C/welcome.png"

# --------------------------------------------------------------------------
mkdir -p "$OUT"
for pkg in "${PACKAGES[@]}"; do
    dir=$WORK/pkg/$pkg
    # Substitution des versions dans les fichiers texte
    { grep -rlI '@VERSION' "$dir" || true; } | while read -r f; do
        sed -i -e "s/@VERSION_SHORT@/$VERSION_SHORT/g" -e "s/@VERSION@/$VERSION/g" "$f"
    done
    # Fins de ligne Unix partout (au cas où un éditeur Windows serait passé par là)
    { grep -rlI $'\r' "$dir" || true; } | while read -r f; do sed -i 's/\r$//' "$f"; done
    # Permissions normalisées (indispensable : le dépôt peut venir de Windows)
    find "$dir" -type d -exec chmod 0755 {} +
    find "$dir" -type f -exec chmod 0644 {} +
    for script in preinst postinst prerm postrm; do
        if [ -f "$dir/DEBIAN/$script" ]; then chmod 0755 "$dir/DEBIAN/$script"; fi
    done
    if [ -d "$dir/usr/bin" ]; then chmod 0755 "$dir"/usr/bin/*; fi
    if [ -d "$dir/usr/libexec/yggdrasil" ]; then chmod 0755 "$dir"/usr/libexec/yggdrasil/*; fi
    if [ -d "$dir/etc/update-motd.d" ]; then chmod 0755 "$dir"/etc/update-motd.d/*; fi
    if [ -d "$dir/etc/grub.d" ]; then chmod 0755 "$dir"/etc/grub.d/*; fi
    if [ -d "$dir/etc/NetworkManager/dispatcher.d" ]; then chmod 0755 "$dir"/etc/NetworkManager/dispatcher.d/*; fi
    # Fichiers de configuration (conffiles) = tout /etc
    if [ -d "$dir/etc" ]; then
        (cd "$dir" && find etc -type f | sort | sed 's|^|/|') > "$dir/DEBIAN/conffiles"
    fi
    # Sommes de contrôle et taille installée
    (cd "$dir" && find . -path ./DEBIAN -prune -o -type f -printf '%P\0' | sort -z | xargs -0 -r md5sum) > "$dir/DEBIAN/md5sums"
    size=$(du -sk --exclude=DEBIAN "$dir" | cut -f1)
    sed -i "/^Installed-Size:/d" "$dir/DEBIAN/control"
    sed -i "/^Architecture:/a Installed-Size: $size" "$dir/DEBIAN/control"
    dpkg-deb --root-owner-group -Zxz --build "$dir" "$OUT/${pkg}_${VERSION}_all.deb" >/dev/null
    printf '  ✔ %s_%s_all.deb (%s Ko installés)\n' "$pkg" "$VERSION" "$size"
done
log "Paquets prêts dans $OUT"
