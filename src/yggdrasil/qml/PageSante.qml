// Santé : le diagnostic de « ygg doctor », point par point.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    title: "Santé"

    actions: [
        Kirigami.Action {
            text: "Réparer"
            icon.name: "tools-wizard"
            onTriggered: ygg.lancer("ygg reparer", "Réparation")
        },
        Kirigami.Action {
            text: "Expliquer avec Mímir"
            icon.name: "yggdrasil"
            onTriggered: ygg.lancer("mimir doctor", "Mímir")
        },
        Kirigami.Action {
            text: "Réexaminer"
            icon.name: "view-refresh"
            onTriggered: ygg.actualiser()
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            text: "Chaque ligne vient de « ygg doctor ». Les points en orange méritent un coup d'œil, "
                  + "ceux en rouge une action."
            wrapMode: Text.WordWrap
            opacity: 0.8
            Layout.fillWidth: true
        }

        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Carte {
                icone: "tools-wizard"
                titre: "Réparer"
                texte: "Paquets à moitié installés, dépendances cassées, Flatpak ; ou le bureau, le son, le réseau."
                QQC2.Button { text: "Système"; onClicked: ygg.lancer("ygg reparer systeme", "Réparation") }
                QQC2.Button { text: "Son"; onClicked: ygg.lancer("ygg reparer son", "Réparation") }
            }
            Carte {
                icone: "edit-undo"
                titre: "Défaire la dernière action"
                texte: "Une installation, un service activé… La saga sait comment revenir en arrière."
                QQC2.Button { text: "Annuler"; onClicked: ygg.lancer("ygg annuler", "Annuler") }
            }
            Carte {
                icone: "edit-clear-all"
                titre: "Níðhöggr, le grand ménage"
                texte: "Le dragon ronge les racines mortes : caches, vieux noyaux, journaux anciens."
                QQC2.Button { text: "Nettoyer"; onClicked: ygg.lancer("ygg nettoyer", "Níðhöggr") }
            }
            Carte {
                icone: "document-export"
                titre: "Draupnir, la graine"
                texte: "Ta machine dans un fichier chiffré : royaumes, logiciels, réglages, gardiens et services, "
                       + "à replanter ailleurs ou après une réinstallation (draupnir planter)."
                QQC2.Button { text: "Forger la graine"; onClicked: ygg.lancer("draupnir graine --chiffrer", "Draupnir") }
                QQC2.Button { text: "Ce qu'elle emporte"; onClicked: ygg.lancer("draupnir", "Draupnir") }
            }
            Carte {
                icone: "drive-removable-media-usb"
                titre: "Skíðblaðnir, Yggdrasil dans la poche"
                texte: "Une clé USB qui démarre Yggdrasil et garde tes fichiers d'un démarrage à l'autre "
                       + "(skidbladnir ecrire sdX ; tout ce que contient la clé est effacé)."
                QQC2.Button { text: "Voir les clés"; onClicked: ygg.lancer("skidbladnir", "Skíðblaðnir") }
            }
            Carte {
                icone: "preferences-system"
                titre: "Pilotes manquants"
                texte: "Carte NVIDIA, Wi-Fi, micrologiciels : ce qui manque à ton matériel."
                QQC2.Button { text: "Chercher"; onClicked: ygg.lancer("ygg pilotes installer", "Pilotes") }
            }
            Carte {
                icone: "computer"
                titre: "Matériel et températures"
                texte: "Disques et leur santé, températures, usure de la batterie, durée du démarrage."
                QQC2.Button { text: "Matériel"; onClicked: ygg.lancer("ygg materiel", "Matériel") }
                QQC2.Button { text: "Démarrage"; onClicked: ygg.lancer("ygg demarrage", "Démarrage") }
            }
            Carte {
                icone: "document-export"
                titre: "Demander de l'aide"
                texte: "Un rapport anonymisé (sans adresses ni noms) à joindre sur un forum."
                QQC2.Button { text: "Rapport"; onClicked: ygg.lancer("ygg rapport", "Rapport") }
            }
        }

        Kirigami.Heading { text: "Le diagnostic"; level: 3; color: fenetre.or }

        Kirigami.PlaceholderMessage {
            visible: ygg.sante.length === 0
            text: "Examen en cours…"
            icon.name: "utilities-system-monitor"
            Layout.fillWidth: true
        }

        Repeater {
            model: ygg.sante
            delegate: Kirigami.AbstractCard {
                Layout.fillWidth: true
                contentItem: RowLayout {
                    spacing: Kirigami.Units.largeSpacing
                    Kirigami.Icon {
                        source: modelData.statut === "ok" ? "emblem-success"
                              : modelData.statut === "warn" ? "emblem-warning"
                              : modelData.statut === "fail" ? "emblem-error" : "emblem-information"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        QQC2.Label {
                            text: modelData.libelle
                            font.bold: true
                        }
                        QQC2.Label {
                            text: modelData.message
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                            color: modelData.statut === "fail" ? Kirigami.Theme.negativeTextColor
                                 : modelData.statut === "warn" ? Kirigami.Theme.neutralTextColor
                                 : Kirigami.Theme.textColor
                        }
                        QQC2.Label {
                            text: modelData.conseil
                            visible: text !== ""
                            wrapMode: Text.WordWrap
                            opacity: 0.7
                            Layout.fillWidth: true
                        }
                    }
                    // Un conseil qui est une commande de l'arbre : un clic la lance dans un terminal
                    QQC2.Button {
                        visible: modelData.statut !== "ok" && /^(ygg|norns|heimdall|mimir) [a-z][a-z -]*$/.test(modelData.conseil)
                        text: "Faire"
                        icon.name: "system-run"
                        onClicked: ygg.lancer(modelData.conseil, modelData.libelle)
                    }
                }
            }
        }
    }
}
