# Réglages par défaut du bureau Plasma d'Yggdrasil (sourcé par startplasma).
# /etc/xdg/yggdrasil passe en tête des dossiers de configuration : ses valeurs
# priment sur celles de Debian, et tes propres réglages (~/.config) sur les deux.
case ":${XDG_CONFIG_DIRS:-}:" in
    *:/etc/xdg/yggdrasil:*) ;;
    *) XDG_CONFIG_DIRS="/etc/xdg/yggdrasil:${XDG_CONFIG_DIRS:-/etc/xdg:/usr/share/desktop-base/kf5-settings}" ;;
esac
export XDG_CONFIG_DIRS
