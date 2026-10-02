// Le trône : le présage du jour, l'état de la machine, les gestes essentiels.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    title: "Le trône"

    actions: [
        Kirigami.Action {
            text: "Actualiser"
            icon.name: "view-refresh"
            onTriggered: ygg.actualiser()
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing * 2

        RowLayout {
            spacing: Kirigami.Units.largeSpacing * 2
            Layout.fillWidth: true

            Kirigami.Icon {
                source: "yggdrasil"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                Layout.preferredHeight: Kirigami.Units.gridUnit * 7
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Heading {
                    text: "Yggdrasil"
                    level: 1
                    color: fenetre.or
                    font.family: "EB Garamond"
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2.6
                }
                QQC2.Label {
                    text: "D'ici, on voit les neuf mondes. Chaque action s'ouvre dans un terminal : "
                          + "tu vois ce qui se passe, et rien ne se fait sans ton accord."
                    wrapMode: Text.WordWrap
                    opacity: 0.8
                    Layout.fillWidth: true
                }
                QQC2.Label {
                    text: ygg.etat.presage ? "✦ " + ygg.etat.presage : "✦ Les corbeaux sont partis aux nouvelles…"
                    color: fenetre.or
                    font.italic: true
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.smallSpacing
                }
            }
        }

        Carte {
            visible: ygg.live
            Layout.fillWidth: true
            icone: "system-software-install"
            titre: "Installer Yggdrasil sur cet ordinateur"
            texte: (ygg.persistante
                    ? "Tu es sur une clé persistante : ce que tu installes et enregistres y reste. "
                    : "Tu es en session live : rien n'est conservé à l'extinction. ")
                   + "L'installateur te guide en quelques minutes (chiffrement et instantanés possibles), "
                   + "puis l'assistant du premier démarrage te fait choisir tes royaumes."
            QQC2.Button {
                text: "Installer"
                icon.name: "system-software-install"
                highlighted: true
                onClicked: ygg.installerSysteme()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Mesure {
                valeur: ygg.etat.majs < 0 ? "?" : ygg.etat.majs
                libelle: "mises à jour"
                detail: ygg.etat.securite > 0 ? ygg.etat.securite + " de sécurité" : ""
                couleur: ygg.etat.securite > 0 ? Kirigami.Theme.negativeTextColor
                       : ygg.etat.majs > 0 ? Kirigami.Theme.neutralTextColor : fenetre.sauge
            }
            Mesure {
                valeur: ygg.etat.disque < 0 ? "?" : ygg.etat.disque + " %"
                libelle: "disque occupé"
                couleur: ygg.etat.disque >= 90 ? Kirigami.Theme.negativeTextColor
                       : ygg.etat.disque >= 80 ? Kirigami.Theme.neutralTextColor : fenetre.sauge
            }
            Mesure {
                valeur: ygg.etat.parefeu === "actif" ? "veille" : ygg.etat.parefeu
                libelle: "Heimdall (pare-feu)"
                couleur: ygg.etat.parefeu === "actif" ? fenetre.sauge : Kirigami.Theme.negativeTextColor
            }
            Mesure {
                valeur: ygg.etat.echecs < 0 ? "?" : ygg.etat.echecs
                libelle: "services en échec"
                couleur: ygg.etat.echecs > 0 ? Kirigami.Theme.negativeTextColor : fenetre.sauge
            }
        }

        Kirigami.Heading {
            text: "Gestes essentiels"
            level: 3
            color: fenetre.or
        }

        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true

            Carte {
                icone: "system-software-update"
                titre: "Mettre à jour"
                texte: "Debian et Flatpak, après un instantané : on peut toujours revenir en arrière."
                QQC2.Button { text: "Mettre à jour"; onClicked: ygg.lancer("ygg update", "Mises à jour") }
            }
            Carte {
                icone: "utilities-system-monitor"
                titre: "Diagnostic"
                texte: "Disque, mémoire, services, mises à jour, pare-feu, instantanés, horloge."
                QQC2.Button { text: "Examiner"; onClicked: ygg.lancer("ygg doctor", "Diagnostic") }
            }
            Carte {
                icone: "yggdrasil"
                titre: "Consulter Mímir"
                texte: "L'oracle local : il explique, lit les journaux, guide pas à pas."
                QQC2.Button { text: "Consulter"; onClicked: ygg.lancer("mimir chat", "Mímir") }
            }
            Carte {
                icone: "help-contents"
                titre: "Le guide d'Yggdrasil"
                texte: "Toute la documentation, hors ligne."
                QQC2.Button { text: "Lire"; onClicked: ygg.ouvrirGuide() }
            }
            Carte {
                icone: "view-history"
                titre: "La saga"
                texte: "Tout ce que les outils d'Yggdrasil ont fait sur cette machine, et quand."
                QQC2.Button { text: "Relire"; onClicked: ygg.lancer("ygg saga", "La saga") }
            }
            Carte {
                icone: "edit-clear-all"
                titre: "Faire le ménage"
                texte: "Caches, paquets orphelins, vieux journaux : la place est rendue au disque."
                QQC2.Button { text: "Nettoyer"; onClicked: ygg.lancer("ygg clean", "Nettoyage") }
            }
        }
    }
}
