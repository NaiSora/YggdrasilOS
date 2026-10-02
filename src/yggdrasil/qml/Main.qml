/*
    Hliðskjálf — le Centre d'Yggdrasil.
    Le trône d'Odin d'où l'on voit les neuf mondes : l'état de la machine d'un
    coup d'œil, et chaque action en un clic (toujours dans un terminal visible).
*/

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: fenetre

    title: "Hliðskjálf — Centre Yggdrasil"
    width: Kirigami.Units.gridUnit * 62
    height: Kirigami.Units.gridUnit * 42
    minimumWidth: Kirigami.Units.gridUnit * 40
    minimumHeight: Kirigami.Units.gridUnit * 28

    // Couleurs du logo, pour les touches d'or et de sauge
    readonly property color or: "#E8CC8C"
    readonly property color etoile: "#FBE39B"
    readonly property color sauge: "#79AC99"
    property string pageCourante: ""

    function ouvrir(nom) {
        if (nom === pageCourante)
            return
        pageCourante = nom
        var fichier = "Page" + nom.charAt(0).toUpperCase() + nom.slice(1) + ".qml"
        pageStack.clear()
        pageStack.push(Qt.resolvedUrl(fichier))
    }

    Connections {
        target: ygg
        function onMessage(texte) { fenetre.showPassiveNotification(texte, "long") }
    }

    globalDrawer: Kirigami.GlobalDrawer {
        modal: false
        collapsible: false
        width: Kirigami.Units.gridUnit * 13

        header: ColumnLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: "yggdrasil"
                Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
            }
            Kirigami.Heading {
                text: "Hliðskjálf"
                level: 2
                color: fenetre.or
                font.family: "EB Garamond"
                Layout.alignment: Qt.AlignHCenter
            }
            QQC2.Label {
                text: "Yggdrasil " + ygg.version
                opacity: 0.7
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: ygg.occupe ? 0 : Kirigami.Units.largeSpacing
            }
            // Les corbeaux sont partis aux nouvelles : un indicateur discret, sans bande réservée
            RowLayout {
                visible: ygg.occupe
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
                QQC2.BusyIndicator {
                    running: ygg.occupe
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }
                QQC2.Label { text: "Les corbeaux rapportent des nouvelles…"; opacity: 0.7 }
            }
        }

        actions: [
            Entree { nomPage: "trone"; text: "Le trône"; icon.name: "go-home" },
            Entree { nomPage: "sante"; text: "Santé"; icon.name: "utilities-system-monitor" },
            Entree { nomPage: "logiciels"; text: "Logiciels et royaumes"; icon.name: "plasmadiscover" },
            Entree { nomPage: "gardiens"; text: "Gardiens"; icon.name: "security-high" },
            Entree { nomPage: "bifrost"; text: "Bifröst"; icon.name: "network-server" },
            Entree { nomPage: "forge"; text: "La forge"; icon.name: "applications-development" },
            Entree { nomPage: "oracle"; text: "Mímir, l'oracle"; icon.name: "yggdrasil" },
            Entree { nomPage: "reglages"; text: "Réglages"; icon.name: "configure" }
        ]
    }

    component Entree: Kirigami.Action {
        property string nomPage
        checkable: true
        checked: fenetre.pageCourante === nomPage
        onTriggered: fenetre.ouvrir(nomPage)
    }

    Component.onCompleted: ouvrir(ygg.pageInitiale)
}
