// La forge de Brokkr : des projets prêts à coder, tests et Docker compris.
// Chaque modèle se règle ici (forme, modules) ; la forge s'ouvre dans un terminal.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    title: "La forge"

    actions: [
        Kirigami.Action {
            text: "L'assistant"
            icon.name: "tools-wizard"
            onTriggered: ygg.lancer("brokkr assistant", "Brokkr")
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            text: "« Le métal est chaud. » Donne un nom à ton projet, Brokkr forge le reste dans ~/Projets. "
                  + "Ensuite : brokkr deploy pour l'héberger, brokkr package pour en faire un .deb."
            font.italic: true
            color: fenetre.or
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Repeater {
                model: ygg.modeles
                delegate: Kirigami.AbstractCard {
                    id: carte
                    property var coches: {
                        var c = {}
                        for (var i = 0; i < modelData.modules.length; ++i)
                            c[modelData.modules[i].id] = modelData.modules[i].defaut
                        return c
                    }
                    function modulesChoisis() {
                        return modelData.modules.filter(m => carte.coches[m.id]).map(m => m.id).join(",")
                    }
                    contentItem: ColumnLayout {
                        spacing: Kirigami.Units.smallSpacing
                        RowLayout {
                            Kirigami.Icon {
                                source: "applications-development"
                                Layout.preferredWidth: Kirigami.Units.iconSizes.large
                                Layout.preferredHeight: Kirigami.Units.iconSizes.large
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Kirigami.Heading { level: 4; text: modelData.titre }
                                QQC2.Label { text: modelData.langage; color: fenetre.sauge }
                            }
                        }
                        QQC2.Label {
                            text: modelData.description
                            wrapMode: Text.WordWrap
                            opacity: 0.8
                            Layout.fillWidth: true
                        }
                        QQC2.ComboBox {
                            id: variante
                            visible: modelData.variantes.length > 0
                            model: modelData.variantes
                            textRole: "nom"
                            valueRole: "id"
                            Layout.fillWidth: true
                        }
                        Flow {
                            visible: modelData.modules.length > 0
                            spacing: Kirigami.Units.smallSpacing
                            Layout.fillWidth: true
                            Repeater {
                                model: modelData.modules
                                delegate: QQC2.CheckBox {
                                    text: modelData.nom
                                    checked: !!carte.coches[modelData.id]
                                    onToggled: {
                                        var c = Object.assign({}, carte.coches)
                                        c[modelData.id] = checked
                                        carte.coches = c
                                    }
                                }
                            }
                        }
                        RowLayout {
                            QQC2.TextField {
                                id: nom
                                placeholderText: "Nom du projet"
                                Layout.fillWidth: true
                                onAccepted: forge.clicked()
                            }
                            QQC2.Button {
                                id: forge
                                text: "Forger"
                                icon.name: "run-build"
                                onClicked: ygg.forger(modelData.nom, nom.text,
                                                      modelData.variantes.length ? variante.currentValue : "",
                                                      carte.modulesChoisis())
                            }
                        }
                    }
                }
            }
        }
    }
}
