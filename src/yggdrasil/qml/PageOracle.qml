// Mímir, l'oracle : l'IA qui vit sur ta machine, son puits, son ton, ce qu'il sait de toi.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    title: "Mímir, l'oracle"

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            spacing: Kirigami.Units.largeSpacing * 2
            Layout.fillWidth: true
            Kirigami.Icon {
                source: "yggdrasil"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                Layout.preferredHeight: Kirigami.Units.gridUnit * 5
            }
            ColumnLayout {
                Layout.fillWidth: true
                QQC2.Label {
                    text: "« Le puits est profond, voyageur. Que viens-tu y puiser ? »"
                    font.italic: true
                    color: fenetre.or
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                QQC2.Label {
                    text: !ygg.oracle.ollama ? "Ollama n'est pas encore installé : l'oracle dort."
                        : ygg.oracle.eveille ? "Éveillé. Modèles : " + ygg.oracle.modeles
                                             : "Ollama est installé mais ne répond pas."
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                QQC2.Label {
                    text: "Le puits : " + (ygg.oracle.puits || "…")
                    opacity: 0.7
                }
            }
        }

        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Carte {
                icone: "download"
                titre: "Éveiller l'oracle"
                texte: "Installe Ollama et le modèle adapté à ta mémoire (" + (ygg.oracle.recommande || "…") + ")."
                visible: !ygg.oracle.eveille
                QQC2.Button { text: "Installer"; highlighted: true; onClicked: ygg.lancer("mimir install", "Mímir") }
            }
            Carte {
                icone: "dialog-messages"
                titre: "Consulter le puits"
                texte: "Une conversation, enregistrée en Markdown. Raccourci : Meta+M."
                QQC2.Button { text: "Consulter"; onClicked: ygg.lancer("mimir chat", "Mímir") }
            }
            Carte {
                icone: "help-about"
                titre: "Pourquoi ça a échoué ?"
                texte: "La dernière commande qui a échoué dans ton terminal, expliquée."
                QQC2.Button { text: "Comprendre"; onClicked: ygg.lancer("mimir pourquoi", "Mímir") }
            }
            Carte {
                icone: "story-editor"
                titre: "Lire les runes"
                texte: "Les erreurs du jour dans les journaux du système, interprétées."
                QQC2.Button { text: "Lire"; onClicked: ygg.lancer("mimir runes", "Mímir") }
            }
            Carte {
                icone: "tools-wizard"
                titre: "Résoudre un problème pas à pas"
                texte: "Décris-le dans le terminal : chaque commande proposée attend ton accord."
                QQC2.Button {
                    text: "Commencer"
                    onClicked: ygg.lancer("read -rp 'Décris ton problème : ' probleme && mimir guide \"$probleme\"",
                                          "Mímir")
                }
            }
            Carte {
                icone: "folder-documents"
                titre: "Remplir le puits"
                texte: "Que Mímir puisse consulter la documentation d'Yggdrasil (et ton coffre de notes, "
                       + "si tu l'ajoutes dans les réglages) et citer ses sources."
                QQC2.Button { text: "Remplir"; onClicked: ygg.lancer("mimir puits remplir", "Mímir") }
            }
        }

        Kirigami.Heading { text: "Ce que Mímir sait de toi"; level: 3; color: fenetre.or }
        Kirigami.FormLayout {
            Layout.fillWidth: true
            QQC2.TextField {
                id: prenom
                Kirigami.FormData.label: "Ton prénom :"
                text: ygg.oracle.prenom || ""
                placeholderText: "vide : il t'appelle « voyageur »"
                onAccepted: ygg.regler("prenom", text)
            }
            QQC2.Button {
                text: "Enregistrer"
                onClicked: ygg.regler("prenom", prenom.text)
            }
            QQC2.ComboBox {
                Kirigami.FormData.label: "Ton de Mímir :"
                model: ["oracle", "skalde", "sobre"]
                currentIndex: Math.max(0, model.indexOf(ygg.reglages.tonMimir || "oracle"))
                onActivated: ygg.regler("tonMimir", currentText)
            }
        }
    }
}
