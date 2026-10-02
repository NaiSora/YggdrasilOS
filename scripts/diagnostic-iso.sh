#!/bin/bash
# Diagnostic de l'image live dans QEMU, photographié depuis la console texte 2
# (la session live y est ouverte automatiquement).
#
#   scripts/diagnostic-iso.sh [dossier de l'ISO] [attente en secondes] [session|deconnexion]
#
#   session      la session graphique ne s'affiche pas : journaux de SDDM et erreurs
#   deconnexion  on ferme la session Plasma, puis on regarde ce que devient l'écran
#                de connexion (journal de SDDM et de son écran d'accueil)
set -euo pipefail

DIR=${1:-/out}
ATTENTE=${2:-420}
MODE=${3:-session}
HERE=$(cd "$(dirname "$0")" && pwd)
ISO=$(find "$DIR" -maxdepth 1 -name 'yggdrasil-*.iso' | sort | tail -n 1)
SHOTS=$DIR/diagnostic
rm -rf "$SHOTS"
mkdir -p "$SHOTS"

DEBUT="wait:40,key:ret,wait:$ATTENTE,shot:diag-1-ecran"
SERIE=()
case $MODE in
    session)
        SCENARIO="$DEBUT,key:ctrl+alt+f2,wait:20,shot:diag-2-console,\
type:systemctl status sddm --no-pager -l,key:ret,wait:15,shot:diag-3-sddm,\
type:clear,key:ret,type:sudo journalctl -b -u sddm -n 45 --no-pager -o cat,key:ret,wait:20,shot:diag-4-journal-sddm,\
type:clear,key:ret,type:loginctl list-sessions --no-pager,key:ret,wait:10,shot:diag-5-sessions,\
type:clear,key:ret,type:sudo journalctl -b --no-pager -p err -n 45 -o cat,key:ret,wait:20,shot:diag-6-erreurs"
        ;;
    deconnexion)
        # Après la déconnexion, l'écran et le clavier ne répondent plus : on démarre donc
        # depuis la ligne de commande de GRUB avec la console sur le port série, où le
        # journal du système est recopié (fichier serie.log).
        xorriso -osirrox on -indev "$ISO" -extract /boot/grub/grub.cfg "$SHOTS/grub.cfg" >/dev/null 2>&1
        LINUX=$(grep -m1 -P '^\tlinux\t' "$SHOTS/grub.cfg" | sed -E 's/^\tlinux\t//; s/ quiet| splash| findiso=\S+//g')
        INITRD=$(grep -m1 -P '^\tinitrd\t' "$SHOTS/grub.cfg" | sed -E 's/^\tinitrd\t//')
        SCENARIO="wait:30,key:c,wait:3,\
type-us:linux $LINUX console=tty0 console=ttyS0\\,115200 systemd.journald.forward_to_console=1,key:ret,wait:2,\
type-us:initrd $INITRD,key:ret,wait:2,type-us:boot,key:ret,\
wait:$ATTENTE,shot:diag-1-ecran,key:ctrl+alt+t,wait:60,\
type:qdbus6 org.kde.Shutdown /Shutdown logout,key:ret,wait:150,shot:diag-2-apres-150-s,\
wait:150,shot:diag-3-apres-300-s,wait:200,shot:diag-4-apres-500-s"
        SERIE=(--serie "$SHOTS/serie.log")
        ;;
    *) echo "mode inconnu : $MODE (session, deconnexion)" >&2; exit 1 ;;
esac

python3 "$HERE/qemu-shots.py" "$ISO" "$SHOTS" --uefi --memory 6144 "${SERIE[@]}" --script "$SCENARIO"
ls -1 "$SHOTS"
