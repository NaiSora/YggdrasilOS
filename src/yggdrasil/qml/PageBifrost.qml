// Bifröst, le pont arc-en-ciel : des services prêts à lancer en conteneurs, par domaine.
// Rien n'est installé d'avance : un clic installe et lance, dans un terminal.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    title: "Bifröst"

    readonly property var domaines: {
        var vus = []
        for (var i = 0; i < ygg.services.length; ++i)
            if (vus.indexOf(ygg.services[i].domaine) < 0)
                vus.push(ygg.services[i].domaine)
        return vus
    }

    actions: [
        Kirigami.Action {
            text: "Le portail"
            icon.name: "internet-services"
            onTriggered: ygg.lancer("bifrost portail", "Bifröst")
        },
        Kirigami.Action {
            text: "Tout voir"
            icon.name: "view-list-details"
            onTriggered: ygg.lancer("bifrost list", "Bifröst")
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            text: "Chaque service tourne dans un conteneur Docker, n'écoute que sur ta machine par défaut, "
                  + "et ne s'ouvre au réseau local que si tu le demandes. Plusieurs serveurs Minecraft peuvent "
                  + "tourner côte à côte : donne un nom à chacun."
            wrapMode: Text.WordWrap
            opacity: 0.8
            Layout.fillWidth: true
        }

        Repeater {
            model: page.domaines
            delegate: ColumnLayout {
                id: domaine
                required property string modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading {
                    text: domaine.modelData
                    level: 3
                    color: fenetre.or
                    Layout.topMargin: Kirigami.Units.largeSpacing
                }
                Kirigami.CardsLayout {
                    maximumColumnWidth: Kirigami.Units.gridUnit * 30
                    Layout.fillWidth: true
                    Repeater {
                        model: ygg.services.filter(s => s.domaine === domaine.modelData)
                        delegate: Carte {
                            titre: modelData.titre
                            texte: modelData.description
                            etiquette: modelData.deployes.length
                                       ? (modelData.instances ? "déployés : " : "déployé")
                                         + (modelData.instances ? modelData.deployes.join(", ") : "")
                                       : ""
                            couleurEtiquette: fenetre.sauge
                            icone: modelData.icone
                            QQC2.TextField {
                                id: exemplaire
                                visible: modelData.instances
                                placeholderText: "nom (ex. survie)"
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                            }
                            QQC2.Button {
                                text: modelData.deployes.length && !modelData.instances ? "Relancer" : "Installer"
                                onClicked: ygg.lancer("bifrost up " + modelData.nom
                                                      + (exemplaire.text ? " --nom " + exemplaire.text : ""),
                                                      modelData.titre)
                            }
                            QQC2.Button {
                                text: "Ouvrir"
                                visible: modelData.url !== "" && modelData.deployes.length > 0
                                onClicked: ygg.ouvrirAdresse(modelData.url)
                            }
                        }
                    }
                }
            }
        }
    }
}
