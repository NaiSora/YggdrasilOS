#!/bin/bash
# Installe les paquets Yggdrasil dans un Debian 13 vierge, exerce les outils,
# puis les désinstalle : vérifie les scripts de maintenance (diversions, alternatives…).
#
#   docker run --rm -v <debs>:/debs:ro -v <dépôt>:/src:ro debian:trixie bash /src/scripts/test-packages.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive NO_COLOR=1

step() { printf '\n» %s\n' "$*"; }
ok() { printf '  ✔ %s\n' "$*"; }
fail() { printf '  ✘ %s\n' "$*" >&2; exit 1; }

step "Installation"
apt-get update -qq
apt-get install -y -qq --no-install-recommends desktop-base plymouth timeshift fastfetch ncurses-bin >/dev/null
apt-get install -y -qq --no-install-recommends /debs/yggdrasil-base_*.deb /debs/yggdrasil-tools_*.deb /debs/yggdrasil-desktop_*.deb >/dev/null
ok "yggdrasil-base, yggdrasil-tools, yggdrasil-desktop installés"

step "Identité du système"
grep -q '^ID=yggdrasil' /etc/os-release || fail "os-release"
grep -q '^ID=debian' /usr/lib/os-release.debian || fail "os-release Debian non conservé"
grep -q Yggdrasil /etc/issue || fail "issue"
[ "$(dpkg-divert --list | grep -c yggdrasil)" -eq 1 ] || fail "diversions"
grep -q "^Debian" /var/lib/yggdrasil-base/issue.debian || fail "sauvegarde de /etc/issue"
[ "$(readlink -f /usr/share/desktop-base/active-theme)" = /usr/share/desktop-base/yggdrasil-theme ] || fail "thème desktop-base"
[ "$(readlink -f /usr/share/images/desktop-base/login-background.svg)" = /usr/share/desktop-base/yggdrasil-theme/login/background.svg ] || fail "fond de connexion"
[ "$(plymouth-set-default-theme)" = yggdrasil ] || fail "thème plymouth"
[ "$(readlink -f /usr/share/images/desktop-base/desktop-background)" = /usr/share/desktop-base/yggdrasil-theme/wallpaper/contents/images/1920x1080.png ] || fail "fond desktop-base"
ok "os-release, issue, diversion, thèmes desktop-base et Plymouth"

step "Menu de démarrage en français"
apt-get install -y -qq --no-install-recommends grub-common locales >/dev/null
sed -i 's/^# *\(fr_FR.UTF-8 UTF-8\)/\1/' /etc/locale.gen
locale-gen >/dev/null
grub_fr() { LANG=fr_FR.UTF-8 TEXTDOMAIN=grub TEXTDOMAINDIR=/usr/share/locale gettext "$1"; }
[ "$(grub_fr "Advanced options for %s")" = "Options avancées pour %s" ] || fail "menu de GRUB en anglais"
[ "$(grub_fr "(on %s)")" = "(sur %s)" ] || fail "entrées d'os-prober en anglais"
# Le reste vient toujours du catalogue de grub-common (seul, avec LANGUAGE=fr)
aide="Use the %C and %C keys to select which entry is highlighted."
amont=$(LANGUAGE=fr LANG=fr_FR.UTF-8 TEXTDOMAIN=grub TEXTDOMAINDIR=/usr/share/locale gettext "$aide")
if [ "$amont" = "$aide" ] || [ "$(grub_fr "$aide")" != "$amont" ]; then fail "catalogue de GRUB tronqué"; fi
ok "gettext prend le catalogue fr_FR d'Yggdrasil avant celui de grub-common, qui y est entier"

step "Bureau Plasma"
grep -q '^LookAndFeelPackage=org.yggdrasil.desktop' /etc/xdg/yggdrasil/kdeglobals || fail "apparence globale"
grep -q '^\[Colors:Window\]' /etc/xdg/yggdrasil/kdeglobals || fail "couleurs par défaut"
unset XDG_CONFIG_DIRS
# shellcheck disable=SC1091
. /etc/xdg/plasma-workspace/env/yggdrasil.sh
[ "$XDG_CONFIG_DIRS" = /etc/xdg/yggdrasil:/etc/xdg:/usr/share/desktop-base/kf5-settings ] \
    || fail "XDG_CONFIG_DIRS : $XDG_CONFIG_DIRS"
# Sourcé deux fois (session relancée) : pas de doublon
# shellcheck disable=SC1091
. /etc/xdg/plasma-workspace/env/yggdrasil.sh
[ "$XDG_CONFIG_DIRS" = /etc/xdg/yggdrasil:/etc/xdg:/usr/share/desktop-base/kf5-settings ] || fail "doublon"
grep -q '^Current=yggdrasil' /etc/sddm.conf.d/99-yggdrasil.conf || fail "thème SDDM"
grep -qx 'InputMethod=' /etc/sddm.conf.d/99-yggdrasil.conf || fail "clavier virtuel de SDDM non désactivé"
[ -f "$(readlink -f /usr/share/icons/Yggdrasil/48x48/places/folder.svg)" ] || fail "dossiers dorés"
[ -f /usr/share/plasma/look-and-feel/org.yggdrasil.desktop/contents/splash/images/arbre-0.png ] || fail "écran de session"
ok "apparence globale, couleurs, écran de connexion, icônes, écran de session"

step "Services"
[ -L /etc/systemd/system/sysinit.target.wants/heimdall.service ] || fail "heimdall.service non activé"
[ -L /etc/systemd/user/timers.target.wants/ratatoskr.timer ] || fail "ratatoskr.timer non activé"
[ -L /etc/systemd/system/multi-user.target.wants/ratatoskr-refresh.service ] || fail "ratatoskr-refresh non activé"
grep -q '"enabled": true' /etc/heimdall/heimdall.json || fail "configuration heimdall"
[ -L /etc/systemd/system/multi-user.target.wants/yggdrasil-police-console.service ] || fail "police de la console non activée"
ok "heimdall, ratatoskr (minuteur et rafraîchissement au démarrage), police de la console activés, pare-feu configuré"

step "Commandes"
# has <texte attendu> <commande…> : la sortie complète (stdout+stderr) doit contenir le texte
has() {
    local expected=$1 out
    shift
    out=$("$@" 2>&1) || true
    [[ "$out" == *"$expected"* ]] || { printf '%s\n' "$out" >&2; fail "« $expected » absent de : $*"; }
}
has "Yggdrasil $(tr -d ' \r\n' < /src/VERSION)" ygg version
has "Yggdrasil" ygg info
has "Muspelheim" ygg realm list
has "ᛈ" ygg realm list
has "org.prismlauncher.PrismLauncher" ygg realm show muspelheim
has "simulation" ygg realm add jotunheim --seulement btop -n -y
has "L'arbre vivant" ygg realm arbre
has "Pare-feu Heimdall" ygg doctor
# (ygg doctor sort en code 1 ou 2 quand il trouve des avertissements : c'est voulu)
{ ygg doctor --json || true; } | python3 -c 'import json,sys; assert len(json.load(sys.stdin)) > 5'
has "htop" ygg search --limit 3 htop
has "table inet heimdall" heimdall render
has "simulation" heimdall allow minecraft --from lan -n
has "minecraft" heimdall services
has "Serveurs de jeu" bifrost list
has "--type" bifrost info minecraft
has "TYPE=FABRIC" bifrost up minecraft --nom essai --type fabric --version 1.21.4 --mods lithium --local -n
has "discord-bot" brokkr list
for tpl in discord-bot discord-bot-js python-app site-web ia-locale qt-app jeu minecraft-pack script-bash; do
    brokkr new "$tpl" "Essai-$tpl" --dir /tmp/projets --no-git > /dev/null
done
[ -x /tmp/projets/essai-script-bash/essai-script-bash.sh ] || fail "brokkr script-bash"
python3 -m py_compile /tmp/projets/essai-discord-bot/bot.py /tmp/projets/essai-discord-bot/cogs/moderation.py
has "Ollama installé" mimir status
has "ne répond pas" mimir ask "test"
has "Norns" norns status
# Mímir l'oracle : présage (calculé par le programme, sans modèle), profil, voix
has "Présage du jour" mimir presage
has "État du système" mimir presage --ton sobre
has "Astrid" mimir profil --prenom Astrid
has "Je veille" heimdall status
# « mimir pourquoi » : l'invite bash note la dernière commande échouée
mkdir -p /tmp/maison
printf 'commande-inexistante --aide\nexit\n' \
    | HOME=/tmp/maison YGG_NO_FETCH=1 YGG_NO_PRESAGE=1 bash --rcfile /etc/yggdrasil/bashrc -i >/dev/null 2>&1 || true
grep -q '^commande-inexistante --aide$' /tmp/maison/.cache/yggdrasil/derniere-erreur || fail "dernière erreur non notée"
has "commande-inexistante" env HOME=/tmp/maison mimir pourquoi
# Le présage : au premier terminal du jour seulement, et jamais si le Centre l'a coupé
presage_bash() { echo exit | HOME=$1 YGG_NO_FETCH=1 bash --rcfile /etc/yggdrasil/bashrc -i 2>/dev/null; }
mkdir -p /tmp/oracle1 /tmp/oracle2/.config/yggdrasil && touch /tmp/oracle2/.config/yggdrasil/presage-desactive
[ -n "$(presage_bash /tmp/oracle1)" ] || fail "pas de présage au premier terminal"
[ -z "$(presage_bash /tmp/oracle1)" ] || fail "présage répété dans la journée"
[ -z "$(presage_bash /tmp/oracle2)" ] || fail "présage affiché malgré presage-desactive"
# Démarré sur un instantané (menu de GRUB) : le terminal le dit, avec de quoi le garder
# (hors instantané, rien : le terminal de /tmp/oracle2 est resté muet juste au-dessus)
printf '26 1 0:25 /timeshift-btrfs/snapshots/2026-10-02_06-00-02/@ / rw - btrfs /dev/vda3 rw\n' > /tmp/mountinfo
instantane_bash() { echo exit | HOME=/tmp/oracle2 YGG_NO_FETCH=1 YGG_MOUNTINFO=/tmp/mountinfo bash --rcfile /etc/yggdrasil/bashrc -i 2>/dev/null; }
has "Démarré sur l'instantané du 02/10/2026 à 06:00" instantane_bash
has "norns restore 2026-10-02_06-00-02" instantane_bash
ratatoskr check --print > /dev/null
has "autostart" yggdrasil-welcome --help
# L'arbre-monde du terminal : le grand (ASCII fourni) et le petit
has "MM@@@@" env TERM=xterm-256color yggdrasil-fetch --grand --pipe true
has "_.-''" env TERM=xterm-256color yggdrasil-fetch --compact --pipe true
has "Yggdrasil" env TERM=xterm-256color yggdrasil-fetch --sans-arbre --pipe true
# Un tube fermé tôt (« | head ») ne doit pas être une erreur
ygg realm list | head -n 1 > /dev/null
ok "ygg, heimdall, bifrost, brokkr, mimir, norns, ratatoskr, yggdrasil-welcome, yggdrasil-fetch"

step "Gestionnaire système (les actions sont simulées : -n)"
has "usage" ygg
has "Processeur" ygg materiel
has "Pilotes et micrologiciels" ygg pilotes
has "Noyaux Linux" ygg noyaux
has "Le réveil de l'arbre" ygg demarrage
has "Níðhöggr" ygg nettoyer --analyse
has "Ce qui peut être défait" ygg annuler --liste
has "Les habitants de Midgard" ygg comptes
has "mode : nuit" ygg theme
has "Accès à distance" ygg distance
has "chaque jour à 21:00" ygg taches ajouter essai "echo bonjour" --quand 21:00 -n
mkdir -p /tmp/Partage
has "net usershare add Partage /tmp/Partage" ygg partage ajouter /tmp/Partage -n -y
has "# Rapport Yggdrasil" ygg rapport -o -
ygg rapport -o - | grep -q "$(hostname)" && fail "le rapport contient le nom de la machine"
ok "matériel, pilotes, noyaux, démarrage, Níðhöggr, annulation, comptes, thème, accès à distance, tâches, partage, rapport"

step "Les gardiens (lot 5)"
has "zone maison" heimdall zone
has "simulation" heimdall fete terraria --heures 1 -n
has "Qui est sur ton réseau" heimdall voisins
has "Gjallarhorn" heimdall gjallarhorn
has "Le bilan de Ratatoskr" ratatoskr bilan
has "Téléphone" ratatoskr status
has "Urd, ce qui a été" urd
has "Skuld, ce qui doit être" skuld
has "processeur" huginn --une-fois
has '"machine"' huginn --une-fois --json
has "Muninn" muninn
has "Gleipnir" gleipnir
has "disque de sauvegarde" norns versions /etc/hostname
[ -x /usr/bin/verdandi ] || fail "verdandi"
[ -f /usr/lib/udev/rules.d/90-yggdrasil-norns.rules ] || fail "règle udev des Nornes"
[ -x /etc/NetworkManager/dispatcher.d/50-heimdall-zone ] || fail "zone réseau de Heimdall"
[ -f /usr/share/kio/servicemenus/yggdrasil-versions.desktop ] || fail "Versions précédentes (Dolphin)"
ok "zones, LAN party, voisins, Gjallarhorn, bilan, Urd, Skuld, Huginn, Muninn, Gleipnir, versions précédentes"

step "Draupnir, Skíðblaðnir, dépôt APT, édition serveur (lot 7)"
apt-get install -y -qq --no-install-recommends gnupg >/dev/null
has "ce que ta graine emporterait" draupnir
mkdir -p /root/.config/yggdrasil && printf '[mimir]\nprenom = "Astrid"\n' > /root/.config/yggdrasil/config.toml
printf 'graine-de-frene' > /tmp/phrase
has "graine forgée" draupnir graine /tmp/ma-graine --chiffrer --mot-de-passe /tmp/phrase
[ -f /tmp/ma-graine.gpg ] || fail "graine chiffrée absente"
has "Réglages de la maison" draupnir lire /tmp/ma-graine.gpg --mot-de-passe /tmp/phrase
has "Ce que Draupnir va planter" draupnir planter /tmp/ma-graine.gpg --mot-de-passe /tmp/phrase -n -y
if draupnir lire /tmp/ma-graine.gpg </dev/null >/dev/null 2>&1; then fail "graine chiffrée lue sans mot de passe"; fi
has "les clés à bord" skidbladnir
has "aucun disque" skidbladnir ecrire sdz /etc/hostname -y
apt-get install -y -qq --no-install-recommends /debs/yggdrasil-archive-keyring_*.deb >/dev/null
SOURCE=/etc/apt/sources.list.d/yggdrasil.sources
DEPOT_URL=$(sed -n 's/^DEPOT_URL=//p' /src/depot.conf | tr -d ' \r"')
if [ -n "$DEPOT_URL" ]; then
    grep -qx "Enabled: yes" "$SOURCE" || fail "dépôt Yggdrasil désactivé malgré son adresse"
    grep -qx "URIs: $DEPOT_URL" "$SOURCE" || fail "adresse du dépôt Yggdrasil"
    # Une fois le site publié (YGG_DEPOT_EN_LIGNE=1) : APT lit le vrai dépôt et vérifie sa signature
    if [ "${YGG_DEPOT_EN_LIGNE:-0}" = 1 ]; then
        apt-get update -q > /tmp/apt-depot.log 2>&1 || { cat /tmp/apt-depot.log >&2; fail "apt update sur le dépôt en ligne"; }
        apt-cache policy yggdrasil-tools | grep -q "${DEPOT_URL#https://}" || fail "yggdrasil-tools absent du dépôt en ligne"
    fi
else
    grep -qx "Enabled: no" "$SOURCE" || fail "dépôt Yggdrasil actif sans adresse"
    apt-get update -q 2>&1 | grep -q "yggdrasil" && fail "apt update touche un dépôt désactivé"
fi
apt-get install -y -qq /debs/yggdrasil-serveur_*.deb >/dev/null
grep -q '"profile": "server"' /etc/heimdall/heimdall.json || fail "Heimdall pas en profil serveur"
grep -q "édition serveur" /etc/issue.d/yggdrasil-arbre.issue || fail "arbre de la console"
grep -q 'adresse \\4' /etc/issue.d/yggdrasil-arbre.issue || fail "adresse de la machine à la console"
ok "graine chiffrée forgée, lue et replantée (simulation), clés listées, source APT d'Yggdrasil$([ "${YGG_DEPOT_EN_LIGNE:-0}" = 1 ] && echo " lue en ligne"), édition serveur"

step "Réglages de session"
mkdir -p /tmp/home-test
cp /etc/skel/.face /tmp/home-test/.face            # avatar Debian par défaut
HOME=/tmp/home-test /usr/libexec/yggdrasil/session-setup
cmp -s /tmp/home-test/.face /usr/share/pixmaps/yggdrasil.png || fail "avatar Yggdrasil non appliqué"
cp /usr/share/pixmaps/yggdrasil.svg /tmp/home-test/.face  # avatar choisi par l'utilisateur
HOME=/tmp/home-test /usr/libexec/yggdrasil/session-setup
cmp -s /tmp/home-test/.face /usr/share/pixmaps/yggdrasil.svg || fail "avatar personnel écrasé"
ok "avatar par défaut remplacé, avatar personnel respecté"

step "Complétion bash"
# shellcheck disable=SC1091
source /usr/share/bash-completion/completions/ygg
COMP_WORDS=(ygg realm add mu); COMP_CWORD=3; _ygg_complete
[[ " ${COMPREPLY[*]} " == *" muspelheim "* ]] || fail "complétion des royaumes"
COMP_WORDS=(bifrost up mine); COMP_CWORD=2; _ygg_complete
[[ " ${COMPREPLY[*]} " == *" minecraft "* ]] || fail "complétion bifrost"
ok "complétion des royaumes et des services"

step "Désinstallation"
apt-get purge -y -qq yggdrasil-serveur yggdrasil-archive-keyring yggdrasil-desktop yggdrasil-tools yggdrasil-base >/dev/null
[ ! -e /etc/apt/sources.list.d/yggdrasil.sources ] || fail "source APT d'Yggdrasil restante"
grep -q '^ID=debian' /etc/os-release || fail "os-release Debian non restauré"
grep -q '^Debian' /etc/issue || fail "/etc/issue Debian non restauré"
[ "$(dpkg-divert --list | grep -c yggdrasil || true)" -eq 0 ] || fail "diversions restantes"
[ "$(readlink -f /usr/share/desktop-base/active-theme)" != /usr/share/desktop-base/yggdrasil-theme ] || fail "thème encore actif"
[ ! -e /etc/heimdall ] || fail "/etc/heimdall non purgé"
[ ! -e /etc/systemd/system/multi-user.target.wants/yggdrasil-police-console.service ] || fail "police de la console encore activée"
ok "système Debian d'origine restauré"

printf '\nTous les tests de paquets sont passés.\n'
