# Environnement de construction d'Yggdrasil : Debian 13 + live-build et outils de test.
FROM debian:trixie

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        live-build debootstrap debian-archive-keyring apt-utils \
        dpkg-dev librsvg2-bin grub-common fonts-dejavu-core fonts-ebgaramond papirus-icon-theme \
        xorriso squashfs-tools mtools dosfstools e2fsprogs cryptsetup-bin fdisk gnupg xz-utils btrfs-progs \
        python3 python3-pytest python3-gi gir1.2-gtk-3.0 \
        shellcheck nftables rsync ca-certificates curl \
        qemu-system-x86 qemu-utils ovmf netpbm xvfb xauth imagemagick \
        python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtqml python3-pyside6.qtquick \
        python3-pyside6.qtwidgets qml6-module-org-kde-kirigami qml6-module-org-kde-kirigamiaddons-formcard \
        qml6-module-qtquick-controls qml6-module-qtquick-layouts qml6-module-qtquick-templates \
        qml6-module-qtquick-window qml6-module-qtqml-workerscript qml6-module-qtquick-effects \
        qml6-module-org-kde-desktop qt6-svg-plugins fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
