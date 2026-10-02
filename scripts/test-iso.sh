#!/bin/bash
# Démarre les ISO Yggdrasil dans QEMU et enregistre des captures d'écran dans
# <dossier>/captures. Sans KVM (Docker Desktop), l'émulation est lente : compter une
# vingtaine de minutes par démarrage, une heure ou plus par installation.
#
#   scripts/test-iso.sh [dossier] [scénario…]
#
# Scénarios : live (défaut : l'édition bureau en session live), serveur-live,
# serveur-install (installateur texte automatique, puis le système installé),
# bureau-install (Calamares : btrfs chiffré, puis le système installé et un instantané),
# cle (Skíðblaðnir : une clé persistante garde un fichier d'un démarrage à l'autre).
set -euo pipefail

DIR=${1:-/out}
shift || true
SCENARIOS=("$@")
[ ${#SCENARIOS[@]} -gt 0 ] || SCENARIOS=(live)
HERE=${YGG_SRC:+$YGG_SRC/scripts}  # YGG_SRC : le dépôt, quand ce script tourne depuis une copie
HERE=${HERE:-$(cd "$(dirname "$0")" && pwd)}
ISO_BUREAU=$(find "$DIR" -maxdepth 1 -name 'yggdrasil-[0-9]*-amd64.iso' | sort | tail -n 1)
ISO_SERVEUR=$(find "$DIR" -maxdepth 1 -name 'yggdrasil-serveur-*-amd64.iso' | sort | tail -n 1)
SHOTS=$DIR/captures
DISQUES=$(mktemp -d)
mkdir -p "$SHOTS"
SERVEUR_HTTP=""
trap 'if [ -n "$SERVEUR_HTTP" ]; then kill "$SERVEUR_HTTP" 2>/dev/null || true; fi; rm -rf "$DISQUES"' EXIT
shots() { python3 "$HERE/qemu-shots.py" "$@"; }
exiger() { [ -n "$1" ] || { echo "ISO absente de $DIR : $2" >&2; exit 1; }; }
# La machine démarre sur une copie privée de l'ISO : une construction peut remplacer celle
# de $DIR pendant ce temps (une installation sans KVM dure des heures)
prive() { # prive NOM_DE_VARIABLE
    local chemin=${!1}
    case "$chemin" in ""|"$DISQUES"/*) return 0 ;; esac
    cp "$chemin" "$DISQUES/"
    printf -v "$1" '%s' "$DISQUES/$(basename "$chemin")"
}

live() {
    exiger "$ISO_BUREAU" "./build.sh"
    prive ISO_BUREAU
    rm -f "$SHOTS"/bios-* "$SHOTS"/uefi-*
    echo "» BIOS : menu de démarrage isolinux"
    shots "$ISO_BUREAU" "$SHOTS" --script "wait:25,shot:bios-1-menu"

    # UEFI : menu GRUB, l'arbre qui pousse (Plymouth), session live Plasma et le Centre,
    # puis un terminal : l'arbre-monde en ASCII, ygg doctor, heimdall, un vrai royaume
    # installé (Helheim, avec TestDisk) qui allume sa feuille sur le fond d'écran, Gleipnir,
    # l'assistant « Bienvenue, voyageur » ; 6 minutes sans toucher à rien (pas de
    # verrouillage attendu), enfin déconnexion propre, comme depuis le menu de Plasma,
    # pour voir l'écran de connexion SDDM. (Un « loginctl terminate-user » tue
    # sddm-helper : SDDM y voit une erreur d'authentification et ne relance pas
    # l'écran de connexion.)
    echo "» UEFI : démarrage complet jusqu'au bureau Plasma"
    shots "$ISO_BUREAU" "$SHOTS" --uefi --memory 6144 --script "wait:40,shot:uefi-01-grub,key:ret,wait:20,shot:uefi-02-plymouth,wait:25,shot:uefi-03-plymouth,wait:150,shot:uefi-04-session,wait:120,shot:uefi-05-bureau,wait:60,shot:uefi-06-centre,key:ctrl+alt+t,wait:75,shot:uefi-07-terminal,type:ygg doctor,key:ret,wait:90,shot:uefi-08-ygg-doctor,type:clear,key:ret,type:heimdall status,key:ret,wait:40,shot:uefi-09-heimdall,type:clear,key:ret,type:ygg realm list,key:ret,wait:45,shot:uefi-10-royaumes,type:clear,key:ret,type:ygg realm add helheim --seulement testdisk -y,key:ret,wait:300,shot:uefi-11-helheim,key:meta_l+d,wait:20,shot:uefi-12-arbre-vivant,key:meta_l+d,wait:10,type:clear,key:ret,type:gleipnir,key:ret,wait:40,shot:uefi-13-gleipnir,type:clear,key:ret,type:yggdrasil-welcome --accueil &,key:ret,wait:90,shot:uefi-14-accueil,key:alt+f4,wait:10,type:clear,key:ret,type:hostnamectl,key:ret,wait:20,shot:uefi-15-identite,wait:360,shot:uefi-16-apres-6-min,type:clear,key:ret,type:qdbus6 org.kde.Shutdown /Shutdown logout,key:ret,wait:150,shot:uefi-17-connexion,wait:120,shot:uefi-18-connexion"
}

serveur_live() {
    exiger "$ISO_SERVEUR" "./build.sh serveur"
    prive ISO_SERVEUR
    rm -f "$SHOTS"/serveur-live-*
    # La console : l'arbre-monde avant la connexion (agetty), puis la session ouverte
    # d'elle-même ; Heimdall en profil serveur, Docker prêt pour Bifröst.
    echo "» Édition serveur : session live (UEFI)"
    shots "$ISO_SERVEUR" "$SHOTS" --uefi --memory 4096 --script "wait:40,shot:serveur-live-01-grub,key:ret,wait:240,shot:serveur-live-02-console,type:heimdall status,key:ret,wait:30,shot:serveur-live-03-heimdall,type:clear,key:ret,type:sudo docker info 2>/dev/null | grep 'Server Version',key:ret,wait:40,type:bifrost list,key:ret,wait:40,shot:serveur-live-04-bifrost,type:clear,key:ret,type:cat /etc/issue.d/yggdrasil-arbre.issue | head -4,key:ret,wait:10,shot:serveur-live-05-issue"
}

serveur_install() {
    exiger "$ISO_SERVEUR" "./build.sh serveur"
    prive ISO_SERVEUR
    rm -f "$SHOTS"/serveur-install-* "$SHOTS"/serveur-installe-*
    # Réponses complètes pour une installation sans question, servies à la machine
    # virtuelle (QEMU joint l'hôte en 10.0.2.2)
    mkdir -p "$DISQUES/http"
    cat > "$DISQUES/http/auto.cfg" <<'EOF'
d-i debian-installer/locale string fr_FR.UTF-8
d-i keyboard-configuration/xkb-keymap select fr(latin9)
d-i netcfg/get_hostname string yggdrasil
d-i netcfg/get_domain string
d-i partman-auto/disk string /dev/vda
d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
d-i partman-efi/non_efi_system boolean true
d-i passwd/root-login boolean false
d-i passwd/user-fullname string Voyageur
d-i passwd/username string ygg
d-i passwd/user-password password graine
d-i passwd/user-password-again password graine
d-i user-setup/allow-password-weak boolean true
d-i pkgsel/run_tasksel boolean false
d-i pkgsel/upgrade select none
d-i pkgsel/update-policy select none
d-i grub-installer/only_debian boolean true
d-i grub-installer/bootdev string default
d-i finish-install/reboot_in_progress note
EOF
    python3 -m http.server 8000 --bind 0.0.0.0 --directory "$DISQUES/http" >/dev/null 2>&1 &
    SERVEUR_HTTP=$!
    # Le disque est gardé dans $DIR/vm (comme celui du bureau), pour l'examiner ensuite
    mkdir -p "$DIR/vm"
    rm -f "$DIR/vm/serveur.qcow2" "$DIR/vm/serveur-vars.fd"
    qemu-img create -q -f qcow2 "$DIR/vm/serveur.qcow2" 20G
    # GRUB, ligne de commande (c) : le noyau de l'installateur avec l'adresse des réponses
    echo "» Édition serveur : installation automatique (Debian Installer, mode texte)"
    shots "$ISO_SERVEUR" "$SHOTS" --uefi --memory 4096 --disque "$DIR/vm/serveur.qcow2" \
        --efivars "$DIR/vm/serveur-vars.fd" --serie "$SHOTS/serveur-install.serie.log" --script \
        "wait:40,shot:serveur-install-01-grub,key:c,wait:3,type-us:linux /install/vmlinuz auto=true priority=critical url=http://10.0.2.2:8000/auto.cfg --- quiet,wait:3,key:ret,wait:3,type-us:initrd /install/initrd.gz,wait:3,key:ret,wait:3,shot:serveur-install-01b-commandes,type-us:boot,wait:2,key:ret,wait:300,shot:serveur-install-02-installateur,wait:900,shot:serveur-install-03-installation,wait:1200,shot:serveur-install-04-installation,wait:1200,shot:serveur-install-05-installation,wait:1200,shot:serveur-install-06-installation,fin:14400"
    kill "$SERVEUR_HTTP" 2>/dev/null || true

    echo "» Édition serveur : le système installé"
    shots - "$SHOTS" --uefi --memory 4096 --disque "$DIR/vm/serveur.qcow2" --efivars "$DIR/vm/serveur-vars.fd" \
        --script "wait:30,shot:serveur-installe-01-grub,wait:180,shot:serveur-installe-02-console,type:ygg,key:ret,wait:3,type:graine,key:ret,wait:60,shot:serveur-installe-03-session,type:clear,key:ret,type:systemctl is-active ssh docker heimdall yggdrasil-police-console; dpkg -s live-boot 2>&1 | head -1; groups; heimdall status | head -4,key:ret,wait:40,shot:serveur-installe-04-services,type:clear,key:ret,type:sudo apt-get update -q 2>&1 | tail -3 ; apt-cache policy yggdrasil-tools | head -6,key:ret,wait:5,type:graine,key:ret,wait:90,shot:serveur-installe-05-depot"
}

bureau_install() {
    exiger "$ISO_BUREAU" "./build.sh"
    prive ISO_BUREAU
    rm -f "$SHOTS"/bureau-install-* "$SHOTS"/bureau-installe-*
    # Le disque est gardé dans $DIR/vm : « YGG_PILOTE_ISO=- ./build.sh boot pilote » le reprend
    mkdir -p "$DIR/vm"
    rm -f "$DIR/vm/disque.qcow2" "$DIR/vm/vars.fd"
    qemu-img create -q -f qcow2 "$DIR/vm/disque.qcow2" 40G
    # Session live, puis Calamares (lancé du terminal, comme le fait le Centre) : effacer le disque,
    # btrfs, chiffrer le système. Un guetteur prévient sur le port série quand Calamares a
    # démonté le système installé (fin de l'installation, qui dure des heures sans KVM) ;
    # setsid : il survit à la fermeture du terminal.
    echo "» Édition bureau : installation avec Calamares (btrfs chiffré)"
    shots "$ISO_BUREAU" "$SHOTS" "${VM_BUREAU[@]}" --clavier-virtio --serie "$SHOTS/bureau-install.serie.log" --script \
        "wait:45,key:ret,wait:420,shot:bureau-install-01-bureau,key:ctrl+alt+t,wait:75,type:sudo setsid sh -c 'until findmnt -rn | grep -q calamares-root; do sleep 5; done; while findmnt -rn | grep -q calamares-root; do sleep 10; done; echo CALAMARES-FINI > /dev/ttyS0' > /dev/null 2>&1 &,key:ret,wait:5,type:setsid calamares-install-debian > /dev/null 2>&1 &,key:ret,wait:5,key:alt+f4,wait:150,shot:bureau-install-02-bienvenue,key:alt+s,wait:20,key:alt+s,wait:20,key:alt+s,wait:40,clic:645:293,wait:20,clic:645:673,wait:10,clic:890:673,wait:2,type:$PHRASE,wait:3,clic:1118:673,wait:2,type:$PHRASE,wait:3,wait:8,shot:bureau-install-03-partitions,clic:1349:865,wait:30,clic:741:272,wait:2,type:Voyageur,wait:3,clic:741:335,wait:2,key:ctrl+q,type:ygg,wait:3,clic:741:397,wait:2,key:ctrl+q,type:yggdrasil,wait:3,clic:741:460,wait:2,type:$PHRASE,wait:3,clic:956:460,wait:2,type:$PHRASE,wait:3,wait:5,shot:bureau-install-04-utilisateurs,clic:1349:865,wait:30,shot:bureau-install-05-resume,key:alt+i,wait:120,shot:bureau-install-06-installation,serie:CALAMARES-FINI:21600,wait:30,shot:bureau-install-07-termine"
    bureau_installe
}

# « a », « m » et « - » ne sont pas au même endroit en AZERTY et en QWERTY : si l'initramfs
# lisait la phrase avec le mauvais clavier, le disque ne s'ouvrirait pas
PHRASE=arbre-monde
VM_BUREAU=(--uefi --memory 6144 --disque "$DIR/vm/disque.qcow2" --efivars "$DIR/vm/vars.fd" --frappe 0.3)

# Le système déjà installé par bureau_install (disque gardé dans $DIR/vm)
bureau_installe() {
    [ -e "$DIR/vm/disque.qcow2" ] || { echo "pas de système installé : scénario bureau-install" >&2; exit 1; }
    local VM=("${VM_BUREAU[@]}")
    # Le système installé : la phrase secrète (demandée par l'initramfs, clavier français),
    # l'écran de connexion, le bureau et l'assistant du premier démarrage ; puis Norns
    # prend un instantané, qui rejoint le menu de démarrage.
    echo "» Édition bureau : le système installé"
    shots - "$SHOTS" "${VM[@]}" --script "wait:30,shot:bureau-installe-01-grub,wait:90,shot:bureau-installe-02-phrase,type:$PHRASE,key:ret,wait:240,shot:bureau-installe-03-connexion,type:$PHRASE,key:ret,veille:300,shot:bureau-installe-04-accueil,key:alt+f4,wait:15,shot:bureau-installe-05-bureau,key:ctrl+alt+t,wait:75,type:findmnt -no SOURCE\,FSTYPE\,OPTIONS / ; lsblk -o NAME\,FSTYPE\,SIZE\,MOUNTPOINTS,key:ret,wait:15,shot:bureau-installe-06-disques,type:clear,key:ret,type:sudo norns setup -y,key:ret,wait:5,type:$PHRASE,key:ret,veille:400,type:sudo grep -A4 submenu /boot/grub/grub.cfg,key:ret,wait:10,shot:bureau-installe-07-instantane,type:echo GRUB_TIMEOUT=-1 | sudo tee /etc/default/grub.d/z-test.cfg && sudo update-grub && sudo poweroff,key:ret,fin:900"

    # Le menu de démarrage (sans délai pour le test : z-test.cfg, lu en dernier) propose l'instantané : on y retourne (« revenir à un
    # instantané », après Yggdrasil, ses options avancées et les réglages UEFI)
    echo "» Édition bureau : démarrer sur l'instantané"
    shots - "$SHOTS" "${VM[@]}" --script "wait:45,shot:bureau-installe-08-menu,key:down,wait:1,key:down,wait:1,key:down,wait:2,shot:bureau-installe-08b-menu-instantanes,key:ret,wait:3,shot:bureau-installe-09-instantanes,key:ret,wait:90,type:$PHRASE,key:ret,wait:240,type:$PHRASE,key:ret,veille:300,key:alt+f4,wait:10,key:ctrl+alt+t,wait:75,type:findmnt -no OPTIONS / ; norns status,key:ret,wait:20,shot:bureau-installe-10-sur-l-instantane"
}

cle() {
    exiger "$ISO_BUREAU" "./build.sh"
    prive ISO_BUREAU
    rm -f "$SHOTS"/cle-*
    # Skíðblaðnir écrit l'ISO sur une « clé » de 6 Go (dont ~3 Go persistants, en clair)
    [ -e /dev/loop-control ] || mknod /dev/loop-control c 10 237
    for i in $(seq 0 15); do [ -e "/dev/loop$i" ] || mknod "/dev/loop$i" b 7 "$i"; done
    truncate -s 6G "$DISQUES/cle.img"
    LOOP=$(losetup -f --show "$DISQUES/cle.img")
    PYTHONPATH="$HERE/../src" YGG_DATA_DIR="$HERE/../data" NO_COLOR=1 \
        python3 -m yggdrasil.skidbladnir ecrire "${LOOP#/dev/}" "$ISO_BUREAU" --loop -y >/dev/null
    losetup -d "$LOOP"
    # Premier démarrage « clé persistante » : un fichier écrit, puis extinction. Le Centre,
    # ouvert à la connexion, est fermé d'abord (Alt+F4) : il passerait sinon devant le terminal
    echo "» Skíðblaðnir : premier démarrage sur la clé persistante"
    shots - "$SHOTS" --uefi --memory 6144 --cle "$DISQUES/cle.img" --script \
        "wait:40,key:down,wait:2,shot:cle-01-grub,key:ret,wait:420,shot:cle-02-bureau,key:alt+f4,wait:10,key:ctrl+alt+t,wait:120,type:echo graine-persistante > \$HOME/graine.txt && sudo touch /etc/preuve-persistance && sync && echo ECRIT,key:ret,wait:60,shot:cle-03-ecrit,type:sudo poweroff,key:ret,fin:600"
    echo "» Skíðblaðnir : second démarrage, le fichier est-il resté ?"
    shots - "$SHOTS" --uefi --memory 6144 --cle "$DISQUES/cle.img" --script \
        "wait:40,key:down,wait:2,key:ret,wait:420,key:alt+f4,wait:10,key:ctrl+alt+t,wait:120,type:cat \$HOME/graine.txt; ls -l /etc/preuve-persistance; ls /run/live/persistence,key:ret,wait:40,shot:cle-04-souvenir"
}

# Mise au point : la machine démarre (ISO bureau et un disque vierge de 40 Go, gardé dans
# $DIR/vm), puis exécute chaque ligne ajoutée à $DIR/pilote.txt (« stop » pour finir).
# YGG_PILOTE_ISO=- démarre sur le disque déjà installé.
pilote() {
    mkdir -p "$DIR/vm"
    [ -e "$DIR/vm/disque.qcow2" ] || qemu-img create -q -f qcow2 "$DIR/vm/disque.qcow2" 40G
    : > "$DIR/pilote.txt"
    shots "${YGG_PILOTE_ISO:-$ISO_BUREAU}" "$SHOTS" --uefi --memory 6144 --disque "$DIR/vm/disque.qcow2" \
        --efivars "$DIR/vm/vars.fd" --script "pilote:$DIR/pilote.txt"
}

for s in "${SCENARIOS[@]}"; do
    case "$s" in
        live) live ;;
        serveur-live) serveur_live ;;
        serveur-install) serveur_install ;;
        bureau-install) bureau_install ;;
        bureau-installe) bureau_installe ;;
        cle) cle ;;
        pilote) pilote ;;
        *) echo "scénario inconnu : $s (live, serveur-live, serveur-install, bureau-install, bureau-installe, cle, pilote)" >&2; exit 1 ;;
    esac
done

echo "Captures dans $SHOTS :"
ls -1 "$SHOTS"
