// Logiciels et royaumes : une seule recherche pour Debian et Flathub, et les
// royaumes (des mondes de logiciels prêts à l'emploi).

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    title: "Logiciels et royaumes"

    property var voyageursChoisis: []

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.SearchField {
            id: recherche
            placeholderText: "Chercher un logiciel (Debian et Flathub)…"
            Layout.fillWidth: true
            onAccepted: ygg.chercher(text)
        }

        QQC2.BusyIndicator {
            visible: ygg.recherche
            running: visible
            Layout.alignment: Qt.AlignHCenter
        }

        Repeater {
            model: ygg.resultats
            delegate: Carte {
                Layout.fillWidth: true
                icone: modelData.source === "Flathub" ? "flatpak-discover" : "debian-logo"
                titre: modelData.nom
                texte: modelData.description
                etiquette: modelData.source + " · " + modelData.id
                couleurEtiquette: fenetre.sauge
                QQC2.Button {
                    text: "Installer"
                    onClicked: ygg.lancer("ygg install " + modelData.id, "Installation")
                }
            }
        }

        QQC2.Label {
            visible: recherche.text.length > 1 && !ygg.recherche && ygg.resultats.length === 0
            text: "Rien trouvé pour « " + recherche.text + " » (Entrée pour lancer la recherche)."
            opacity: 0.7
        }

        Kirigami.Heading {
            text: "Les neuf mondes"
            level: 2
            color: fenetre.or
            font.family: "EB Garamond"
            Layout.topMargin: Kirigami.Units.largeSpacing
        }
        QQC2.Label {
            text: "Chaque monde de l'arbre est un ensemble de logiciels choisis ensemble. Coche ceux que tu veux : "
                  + "un terminal te montre exactement ce qui sera installé avant de commencer."
            wrapMode: Text.WordWrap
            opacity: 0.8
            Layout.fillWidth: true
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Layout.fillWidth: true
            QQC2.Label {
                text: "Quel voyageur es-tu ?"
                color: fenetre.or
                font.italic: true
            }
            Repeater {
                model: ygg.voyageurs
                delegate: QQC2.Button {
                    text: modelData.nom
                    icon.name: modelData.icone
                    checkable: true
                    QQC2.ToolTip.text: modelData.description
                    QQC2.ToolTip.visible: hovered
                    onToggled: {
                        var liste = page.voyageursChoisis.filter(v => v !== modelData.id)
                        if (checked)
                            liste.push(modelData.id)
                        page.voyageursChoisis = liste
                    }
                }
            }
        }

        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Repeater {
                model: ygg.royaumes
                delegate: CarteRoyaume {
                    royaume: modelData
                    enAvant: (modelData.voyageurs || []).some(v => page.voyageursChoisis.indexOf(v) >= 0)
                }
            }
        }

        QQC2.Label {
            text: "Tes propres royaumes : « ygg realm creer » (ce que tu as installé), « ygg realm importer » "
                  + "(un fichier reçu). Chaque monde installé allume une feuille d'or sur ton fond d'écran."
            wrapMode: Text.WordWrap
            opacity: 0.6
            Layout.fillWidth: true
        }
    }
}
