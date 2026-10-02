// Un des neuf mondes : sa rune, son nom, ce qu'il apporte, et ses logiciels à cocher.
// Dans le Centre, « Installer la sélection » ouvre un terminal ; dans l'assistant de
// premier démarrage (modeChoix), on coche le royaume entier et on règle sa carte.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.AbstractCard {
    id: carte

    property var royaume: ({})
    property bool modeChoix: false
    property bool retenu: false
    property bool enAvant: false
    property bool deplie: false
    property var coches: ({})

    highlighted: enAvant || (modeChoix && retenu)

    function selection() {
        var ids = []
        for (var i = 0; i < (royaume.logiciels || []).length; ++i) {
            var x = royaume.logiciels[i]
            if (coches[x.id])
                ids.push(x.id)
        }
        return ids
    }

    function nombreCoches() {
        return selection().length
    }

    Component.onCompleted: {
        var etat = {}
        for (var i = 0; i < (royaume.logiciels || []).length; ++i) {
            var x = royaume.logiciels[i]
            etat[x.id] = x.defaut || x.installe
        }
        coches = etat
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Layout.fillWidth: true

            QQC2.Label {
                text: carte.royaume.rune || "✦"
                font.family: "Noto Sans Runic"
                font.pixelSize: Kirigami.Units.gridUnit * 2.4
                color: fenetre.or
                horizontalAlignment: Text.AlignHCenter
                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.6
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Kirigami.Heading {
                    level: 3
                    text: carte.royaume.titre + (carte.royaume.surnom ? " — " + carte.royaume.surnom : "")
                    font.family: "EB Garamond"
                    color: fenetre.or
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                QQC2.Label {
                    text: carte.royaume.perso ? "Royaume personnel" : (carte.royaume.theme || "")
                    opacity: 0.7
                }
            }
            QQC2.Label {
                visible: !carte.modeChoix && carte.royaume.etat !== "—"
                text: carte.royaume.etat || ""
                color: fenetre.sauge
                font.bold: true
            }
            QQC2.Switch {
                visible: carte.modeChoix
                checked: carte.retenu
                onToggled: carte.retenu = checked
            }
        }

        QQC2.Label {
            text: carte.royaume.description || ""
            wrapMode: Text.WordWrap
            opacity: 0.85
            Layout.fillWidth: true
        }
        QQC2.Label {
            visible: !!carte.royaume.runeNom
            text: "Rune " + carte.royaume.runeNom + " : " + carte.royaume.runeSens + "."
            font.italic: true
            color: fenetre.or
            opacity: 0.75
        }

        RowLayout {
            Layout.fillWidth: true
            QQC2.ToolButton {
                text: (carte.deplie ? "Masquer les logiciels" : "Choisir les logiciels")
                      + " (" + carte.nombreCoches() + "/" + (carte.royaume.logiciels || []).length + ")"
                icon.name: carte.deplie ? "arrow-up" : "arrow-down"
                onClicked: carte.deplie = !carte.deplie
            }
            Item { Layout.fillWidth: true }
            QQC2.Button {
                visible: !carte.modeChoix
                text: "Installer la sélection"
                icon.name: "run-install"
                enabled: carte.nombreCoches() > 0
                onClicked: ygg.lancer("ygg realm add " + carte.royaume.nom + " --seulement "
                                      + carte.selection().join(","), carte.royaume.titre)
            }
        }

        Repeater {
            model: carte.deplie ? carte.royaume.logiciels : []
            delegate: RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.gridUnit * 3
                QQC2.CheckBox {
                    text: modelData.nom
                    checked: !!carte.coches[modelData.id]
                    enabled: !modelData.installe
                    onToggled: {
                        var etat = Object.assign({}, carte.coches)
                        etat[modelData.id] = checked
                        carte.coches = etat
                    }
                }
                QQC2.Label {
                    text: modelData.installe ? "déjà installé" : modelData.description
                    opacity: 0.65
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }
}
