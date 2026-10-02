#!/bin/bash
# Tests automatiques d'Yggdrasil, dans le conteneur de construction (docker/Dockerfile).
#   scripts/test.sh            (le conteneur doit être --privileged pour le test nftables)
# Les captures d'écran éventuelles sont déposées dans /out si ce dossier existe.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
OUT=${OUT:-/out}

step() { printf '\n\033[1;33m» %s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }

rsync -a --exclude out/ --exclude build/ --exclude .git/ --exclude __pycache__/ "$REPO/" "$WORK/src/"
cd "$WORK/src"
find . -type f \( -name '*.sh' -o -name '*.chroot' -o -name '*.binary' -o -path '*/DEBIAN/*' \) -exec sed -i 's/\r$//' {} +
export PYTHONPATH=$PWD/src YGG_DATA_DIR=$PWD/data YGG_ETC_DIR=$WORK/etc NO_COLOR=1
# Une clé de dépôt jetable : les tests ne touchent pas à la vraie (out/cles)
export YGG_CLES=$WORK/cles

step "1. Tests unitaires Python"
python3 -m pytest -q tests
ok "pytest"

step "2. Analyse des scripts shell (shellcheck)"
mapfile -t SCRIPTS < <(ls scripts/*.sh build.sh live/hooks/live/* packages/*/DEBIAN/*inst packages/*/DEBIAN/*rm \
    packages/yggdrasil-base/root/etc/update-motd.d/* packages/yggdrasil-base/root/etc/grub.d/* live/includes.chroot/usr/lib/live/config/* \
    packages/yggdrasil-tools/root/etc/NetworkManager/dispatcher.d/* 2>/dev/null)
shellcheck -x "${SCRIPTS[@]}"
shellcheck -s sh packages/yggdrasil-desktop/root/etc/xdg/plasma-workspace/env/yggdrasil.sh \
    packages/yggdrasil-base/root/etc/default/grub.d/10-yggdrasil.cfg \
    packages/yggdrasil-desktop/root/usr/libexec/yggdrasil/session-setup \
    packages/yggdrasil-base/root/usr/bin/yggdrasil-fetch
shellcheck -s bash -e SC2034 packages/yggdrasil-base/root/etc/yggdrasil/bashrc \
    packages/yggdrasil-tools/root/usr/share/bash-completion/completions/ygg
ok "${#SCRIPTS[@]} scripts + configuration bash"

step "3. Règles nftables générées, vérifiées par nft"
for profile in desktop server strict; do
    python3 - "$profile" > "$WORK/rules-$profile.nft" <<'EOF'
import sys
from yggdrasil import heimdall
cfg = heimdall.Config(enabled=True, profile=sys.argv[1], log_drops=True, rules=[
    heimdall.Rule("25565", "tcp", "lan", "minecraft"),
    heimdall.Rule("1714-1764", "both", "any", "kdeconnect"),
    heimdall.Rule("8096", "tcp", "192.168.1.0/24", "jellyfin"),
    heimdall.Rule("51820", "udp", "fd00::/8", "wireguard"),
])
sys.stdout.write(heimdall.render_ruleset(cfg))
EOF
    nft -c -f "$WORK/rules-$profile.nft"
    ok "profil $profile accepté par nft"
done
# Chargement réel puis retrait, dans l'espace réseau du conteneur
nft -f "$WORK/rules-desktop.nft"
loaded=$(nft list table inet heimdall)
[[ "$loaded" == *"policy drop"* && "$loaded" == *"@lan4 tcp dport 25565"* ]]
nft delete table inet heimdall
ok "chargement et retrait de la table inet heimdall"

step "4. Validation des données"
python3 - <<'EOF'
from yggdrasil import bifrost, brokkr, realms
r, s, t = realms.load_realms(), bifrost.load_stacks(), brokkr.load_templates()
assert len([x for x in r.values() if not x.perso]) == 9, "les neuf mondes"
v = realms.load_voyageurs()
print(f"  {len(r)} royaumes ({' '.join(x.rune for x in r.values())}), {len(v)} voyageurs, {len(s)} services Bifröst, {len(t)} modèles Brokkr")
EOF
ok "royaumes, services et modèles valides"

step "5. Paquets .deb"
bash scripts/build-packages.sh "$PWD" "$WORK/debs"
for deb in "$WORK"/debs/*.deb; do
    dpkg-deb --info "$deb" > /dev/null
done
check_file() { # check_file <paquet> <chemin> [mode]
    local line
    line=$(dpkg-deb -c "$WORK/debs/$1"_*.deb | awk -v p="./$2" '$6 == p {print}')
    [ -n "$line" ] || { echo "absent de $1 : $2" >&2; exit 1; }
    if [ -n "${3:-}" ]; then
        case "$line" in "$3"*) ;; *) echo "mauvais droits pour $2 : $line" >&2; exit 1 ;; esac
    fi
}
check_file yggdrasil-tools usr/bin/ygg -rwxr-xr-x
check_file yggdrasil-tools usr/lib/python3/dist-packages/yggdrasil/mimir.py -rw-r--r--
check_file yggdrasil-tools usr/share/yggdrasil/brokkr/templates/discord-bot/files/bot.py
check_file yggdrasil-tools usr/lib/python3/dist-packages/yggdrasil/draupnir.py
check_file yggdrasil-tools usr/bin/skidbladnir -rwxr-xr-x
check_file yggdrasil-tools usr/lib/systemd/system/yggdrasil-instantanes-grub.timer
check_file yggdrasil-base etc/grub.d/41_yggdrasil-instantanes -rwxr-xr-x
check_file yggdrasil-base etc/initramfs-tools/conf.d/yggdrasil-clavier
check_file yggdrasil-base usr/share/locale/fr_FR/LC_MESSAGES/grub.mo -rw-r--r--
check_file yggdrasil-base usr/lib/systemd/system/yggdrasil-police-console.service -rw-r--r--
check_file yggdrasil-calamares etc/calamares/branding/yggdrasil/stylesheet.qss
check_file yggdrasil-serveur etc/issue.d/yggdrasil-arbre.issue
check_file yggdrasil-calamares etc/calamares/modules/partition.conf
check_file yggdrasil-tools usr/lib/systemd/system/heimdall.service
check_file yggdrasil-tools usr/lib/systemd/system/gjallarhorn.timer
check_file yggdrasil-tools etc/NetworkManager/dispatcher.d/50-heimdall-zone -rwxr-xr-x
check_file yggdrasil-base usr/lib/os-release
check_file yggdrasil-base usr/share/yggdrasil/issue
check_file yggdrasil-base usr/share/plymouth/themes/yggdrasil/arbre-47.png
check_file yggdrasil-base usr/share/yggdrasil/arbre/grand.txt
check_file yggdrasil-base usr/share/yggdrasil/arbre/compact.ansi
check_file yggdrasil-base usr/bin/yggdrasil-fetch -rwxr-xr-x
check_file yggdrasil-base usr/share/grub/themes/yggdrasil/dejavu_sans_16.pf2
check_file yggdrasil-base etc/update-motd.d/05-yggdrasil -rwxr-xr-x
check_file yggdrasil-desktop usr/bin/yggdrasil-welcome -rwxr-xr-x
check_file yggdrasil-desktop usr/libexec/yggdrasil/session-setup -rwxr-xr-x
check_file yggdrasil-desktop usr/share/plasma/look-and-feel/org.yggdrasil.desktop/contents/splash/Splash.qml
check_file yggdrasil-desktop usr/share/yggdrasil/arbre-vivant.svg
check_file yggdrasil-base usr/share/icons/hicolor/scalable/apps/yggdrasil-alerte.svg
check_file yggdrasil-desktop usr/lib/systemd/user/yggdrasil-theme.timer
check_file yggdrasil-desktop usr/share/plasma/look-and-feel/org.yggdrasil.desktop/contents/splash/images/arbre-47.png
check_file yggdrasil-desktop usr/share/color-schemes/Yggdrasil.colors
check_file yggdrasil-desktop usr/share/aurorae/themes/Yggdrasil/decoration.svg
check_file yggdrasil-desktop usr/share/sddm/themes/yggdrasil/Main.qml
check_file yggdrasil-desktop usr/share/sddm/themes/yggdrasil/logo.png
check_file yggdrasil-desktop usr/share/wallpapers/Yggdrasil/contents/images/1920x1080.png
check_file yggdrasil-desktop usr/share/icons/Yggdrasil/index.theme
check_file yggdrasil-desktop etc/xdg/yggdrasil/kdeglobals
check_file yggdrasil-calamares etc/calamares/branding/yggdrasil/show.qml
dpkg-deb -I "$WORK"/debs/yggdrasil-base_*.deb conffiles | grep -q /etc/default/grub.d/10-yggdrasil.cfg
# Les couleurs du jeu « Yggdrasil » sont recopiées dans les réglages par défaut
mkdir -p "$WORK/desktop" && dpkg-deb -x "$WORK"/debs/yggdrasil-desktop_*.deb "$WORK/desktop"
grep -q '^\[Colors:Window\]' "$WORK/desktop/etc/xdg/yggdrasil/kdeglobals"
grep -q '^LookAndFeelPackage=org.yggdrasil.desktop' "$WORK/desktop/etc/xdg/yggdrasil/kdeglobals"
[ -L "$WORK/desktop/usr/share/icons/Yggdrasil/48x48/places/folder.svg" ]
dpkg-deb -f "$WORK"/debs/yggdrasil-base_*.deb Version | grep -qx "$(tr -d ' \r\n' < VERSION)"
ok "$(find "$WORK/debs" -name '*.deb' | wc -l) paquets construits et vérifiés"

check_file yggdrasil-archive-keyring usr/share/keyrings/yggdrasil-archive-keyring.gpg
dpkg-deb -x "$WORK"/debs/yggdrasil-archive-keyring_*.deb "$WORK/cle"
grep -qx "Enabled: no" "$WORK/cle/etc/apt/sources.list.d/yggdrasil.sources"  # depot.conf vide

step "6. Dépôt APT signé"
bash scripts/build-repo.sh "$WORK/debs" "$WORK/depot" | tail -2
python3 -m http.server 8765 --bind 127.0.0.1 --directory "$WORK/depot" >/dev/null 2>&1 &
SERVEUR=$!
# APT avec ses propres sources et listes : celles du conteneur ne sont pas touchées
APT_ISOLE=(-o Dir::Etc::SourceList=/dev/null -o Dir::Etc::SourceParts="$WORK/sources"
           -o Dir::State::Lists="$WORK/listes" -o Dir::Cache="$WORK/cache-apt" -o Debug::NoLocking=1
           -o APT::Sandbox::User=root)
mkdir -p "$WORK/sources" "$WORK/listes/partial" "$WORK/cache-apt/archives/partial"
# La source livrée par le paquet, pointée sur le dépôt local et sur la clé extraite
sed -e "s|^URIs:.*|URIs: http://127.0.0.1:8765/|" -e "s|^Enabled:.*|Enabled: yes|" \
    -e "s|/usr/share/keyrings/|$WORK/cle/usr/share/keyrings/|" \
    "$WORK/cle/etc/apt/sources.list.d/yggdrasil.sources" > "$WORK/sources/yggdrasil.sources"
sleep 1
apt-get -q "${APT_ISOLE[@]}" update > "$WORK/apt.log" 2>&1 || { cat "$WORK/apt.log"; exit 1; }
if grep -q "^W:\|^E:" "$WORK/apt.log"; then cat "$WORK/apt.log"; exit 1; fi
apt-cache "${APT_ISOLE[@]}" policy yggdrasil-tools > "$WORK/politique.txt"
grep -q "127.0.0.1:8765 trixie/main" "$WORK/politique.txt" || { echo "yggdrasil-tools absent du dépôt" >&2; exit 1; }
# Signé par une autre clé : APT doit refuser le dépôt
YGG_CLES=$WORK/autre-cle bash scripts/cle-depot.sh signer "$WORK/depot/dists/trixie/Release" 2>/dev/null
rm -rf "$WORK/listes" && mkdir -p "$WORK/listes/partial"
apt-get -q "${APT_ISOLE[@]}" update > "$WORK/apt-faux.log" 2>&1 || true
grep -q "NO_PUBKEY\|Missing key\|is not signed" "$WORK/apt-faux.log" || { cat "$WORK/apt-faux.log"; echo "dépôt mal signé accepté" >&2; exit 1; }
kill "$SERVEUR"
ok "APT accepte le dépôt signé par la clé d'Yggdrasil, et refuse celui d'une autre clé"

step "7. Les instantanés btrfs au menu de démarrage"
# Une racine btrfs comme celle de Calamares (@, @home) et deux instantanés Timeshift
[ -e /dev/loop-control ] || mknod /dev/loop-control c 10 237
for i in $(seq 0 15); do [ -e "/dev/loop$i" ] || mknod "/dev/loop$i" b 7 "$i"; done
truncate -s 300M "$WORK/btrfs.img"
mkfs.btrfs -q "$WORK/btrfs.img"
DISQUE=$(losetup -f --show "$WORK/btrfs.img")
mkdir -p "$WORK/top"
mount "$DISQUE" "$WORK/top"
btrfs -q subvolume create "$WORK/top/@"
btrfs -q subvolume create "$WORK/top/@home"
mkdir -p "$WORK/top/timeshift-btrfs/snapshots"
for NOM in 2026-09-30_08-00-00 2026-10-02_10-15-01; do
    mkdir -p "$WORK/top/timeshift-btrfs/snapshots/$NOM"
    btrfs -q subvolume create "$WORK/top/timeshift-btrfs/snapshots/$NOM/@"
    mkdir -p "$WORK/top/timeshift-btrfs/snapshots/$NOM/@/boot"
    touch "$WORK/top/timeshift-btrfs/snapshots/$NOM/@/boot/vmlinuz-6.12.48+deb13-amd64" \
          "$WORK/top/timeshift-btrfs/snapshots/$NOM/@/boot/initrd.img-6.12.48+deb13-amd64"
done
printf '{\n  "comments" : "avant ygg realm add muspelheim",\n  "tags" : "O"\n}\n' \
    > "$WORK/top/timeshift-btrfs/snapshots/2026-10-02_10-15-01/info.json"
mkdir -p "$WORK/top/timeshift-btrfs/snapshots/piege';reboot;'"  # un nom piégé est ignoré
# Installation chiffrée : /boot à part, l'instantané n'a que les modules de son noyau
mkdir -p "$WORK/top/timeshift-btrfs/snapshots/2026-10-02_12-30-00"
btrfs -q subvolume create "$WORK/top/timeshift-btrfs/snapshots/2026-10-02_12-30-00/@"
mkdir -p "$WORK/top/timeshift-btrfs/snapshots/2026-10-02_12-30-00/@/usr/lib/modules/6.12.48+deb13-amd64"
umount "$WORK/top"
YGG_RACINE_SOURCE="${DISQUE}[/@]" YGG_RACINE_FSTYPE=btrfs YGG_RACINE_OPTIONS="rw,noatime,subvolid=256,subvol=/@" \
    YGG_BOOT_SOURCE="" sh packages/yggdrasil-base/root/etc/grub.d/41_yggdrasil-instantanes > "$WORK/menu.cfg" 2>/dev/null
grep -q "^submenu 'Yggdrasil — revenir à un instantané'" "$WORK/menu.cfg"
grep -q "menuentry '2026-10-02 à 10:15 — avant ygg realm add muspelheim'" "$WORK/menu.cfg"
grep -q "linux /timeshift-btrfs/snapshots/2026-09-30_08-00-00/@/boot/vmlinuz-6.12.48+deb13-amd64 root=UUID=.* rw rootflags=subvol=timeshift-btrfs/snapshots/2026-09-30_08-00-00/@" "$WORK/menu.cfg"
if grep -q "piege\|reboot" "$WORK/menu.cfg"; then echo "nom piégé dans le menu" >&2; exit 1; fi
[ "$(grep -c menuentry "$WORK/menu.cfg")" -eq 2 ]  # sans /boot à part, l'instantané sans noyau est laissé
# Avec un /boot à part (ext4) : le noyau de /boot dont l'instantané a les modules
truncate -s 64M "$WORK/boot.img"
mkfs.ext4 -q "$WORK/boot.img"
DISQUE_BOOT=$(losetup -f --show "$WORK/boot.img")
mkdir -p "$WORK/boot"
mount "$DISQUE_BOOT" "$WORK/boot"
touch "$WORK/boot/vmlinuz-6.12.48+deb13-amd64" "$WORK/boot/initrd.img-6.12.48+deb13-amd64" \
      "$WORK/boot/vmlinuz-6.12.99+deb13-amd64" "$WORK/boot/initrd.img-6.12.99+deb13-amd64"
YGG_RACINE_SOURCE="${DISQUE}[/@]" YGG_RACINE_FSTYPE=btrfs YGG_RACINE_OPTIONS="rw,subvol=/@" \
    YGG_BOOT_SOURCE="$DISQUE_BOOT" YGG_BOOT_DIR="$WORK/boot" \
    sh packages/yggdrasil-base/root/etc/grub.d/41_yggdrasil-instantanes > "$WORK/menu-boot.cfg" 2>/dev/null
umount "$WORK/boot"
losetup -d "$DISQUE_BOOT"
losetup -d "$DISQUE"
[ "$(grep -c menuentry "$WORK/menu-boot.cfg")" -eq 3 ]
# 6.12.99 est plus récent mais l'instantané n'en a pas les modules : c'est 6.12.48, à la racine de /boot
grep -q "linux /vmlinuz-6.12.48+deb13-amd64 root=UUID=.* rw rootflags=subvol=timeshift-btrfs/snapshots/2026-10-02_12-30-00/@" "$WORK/menu-boot.cfg"
grep -q "initrd /initrd.img-6.12.48+deb13-amd64" "$WORK/menu-boot.cfg"
# GRUB cherche chaque volume par son UUID : la racine btrfs, ou le /boot à part
grep -q "search --no-floppy --fs-uuid --set=root $(blkid -s UUID -o value "$WORK/boot.img")" "$WORK/menu-boot.cfg"
grep -q "search --no-floppy --fs-uuid --set=root $(blkid -s UUID -o value "$WORK/btrfs.img")" "$WORK/menu.cfg"
# Sur une racine ext4, rien
[ -z "$(YGG_RACINE_FSTYPE=ext4 sh packages/yggdrasil-base/root/etc/grub.d/41_yggdrasil-instantanes)" ]
ok "instantanés au menu (le plus récent d'abord, avec son commentaire), noyau de l'instantané ou de /boot à part, nom piégé ignoré, rien sur ext4"

step "8. Le menu de démarrage en français"
# Chaque traduction répond à une chaîne des scripts de GRUB installés ici (grub-common), et il n'en manque aucune
python3 scripts/catalogue-grub.py verifier /usr/share/locale/fr/LC_MESSAGES/grub.mo assets/grub-fr.po \
    /etc/grub.d/* /usr/sbin/grub-mkconfig /usr/share/grub/grub-mkconfig_lib > "$WORK/grub-anglais.txt"
[ ! -s "$WORK/grub-anglais.txt" ] || { cat "$WORK/grub-anglais.txt"; echo "chaînes de GRUB sans traduction" >&2; exit 1; }
mkdir -p "$WORK/base" && dpkg-deb -x "$WORK"/debs/yggdrasil-base_*.deb "$WORK/base"
python3 - "$WORK/base/usr/share/locale" <<'EOF'
import gettext, sys
def catalogue(chemin): return gettext.GNUTranslations(open(chemin, "rb"))
fr = catalogue(f"{sys.argv[1]}/fr_FR/LC_MESSAGES/grub.mo")
amont = catalogue("/usr/share/locale/fr/LC_MESSAGES/grub.mo")
assert fr.gettext("Advanced options for %s") == "Options avancées pour %s"
assert fr.gettext("%s, with Linux %s (%s)") % ("Yggdrasil GNU/Linux", "6.12", fr.gettext("recovery mode")) \
    == "Yggdrasil GNU/Linux, avec Linux 6.12 (mode de dépannage)"
# GRUB ne lit que fr_FR.mo quand il existe : tout le catalogue d'origine doit y être
assert all(fr._catalog.get(cle) == valeur for cle, valeur in amont._catalog.items())
assert catalogue(f"{sys.argv[1]}/fr_CA/LC_MESSAGES/grub.mo")._catalog == fr._catalog
EOF
# Calamares lance grub-mkconfig avec LC_ALL=C : les réglages d'Yggdrasil reprennent la langue
# du système installé (grub-mkconfig les lit sous set -e : un fichier cassé ne l'arrête pas)
# shellcheck disable=SC2016  # développé par le sh lancé, pas ici
reglages_grub() { env -i "$@" sh -ec '. packages/yggdrasil-base/root/etc/default/grub.d/10-yggdrasil.cfg; echo "${LC_ALL-aucun} ${LANG-aucune}"'; }
printf 'LANG=fr_FR.UTF-8\nLC_TIME=fr_FR.UTF-8\n' > "$WORK/locale"
printf 'if then\n' > "$WORK/locale-cassee"
[ "$(reglages_grub LC_ALL=C LANG=en_US.UTF-8 YGG_LOCALE="$WORK/locale")" = "aucun fr_FR.UTF-8" ]
[ "$(reglages_grub LANG=en_US.UTF-8 YGG_LOCALE="$WORK/locale")" = "aucun en_US.UTF-8" ]
[ "$(reglages_grub LC_ALL=C YGG_LOCALE="$WORK/locale-cassee")" = "aucun C" ]
ok "catalogue fr_FR de GRUB : celui de grub-common, plus les $(($(grep -c '^msgid ' assets/grub-fr.po) - 1)) chaînes du menu et de update-grub ; langue du système reprise sous Calamares (LC_ALL=C)"

step "9. Hliðskjálf, le Centre (Qt Quick + Kirigami, hors écran)"
# Rendu avec le style de Plasma, les icônes et les réglages par défaut des paquets
dpkg-deb -x "$WORK"/debs/yggdrasil-base_*.deb "$WORK/desktop"
python3 scripts/rendu-centre.py "$WORK/centre" "$WORK/desktop"
if [ -d "$OUT" ] && [ -w "$OUT" ]; then
    mkdir -p "$OUT/rendus/centre" && cp "$WORK"/centre/*.png "$OUT/rendus/centre/"
fi
ok "les $(find "$WORK/centre" -name '*.png' | wc -l) écrans du Centre et de l'assistant se chargent sans erreur QML"

step "Tous les tests sont passés"
