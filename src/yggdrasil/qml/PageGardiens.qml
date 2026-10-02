// Les gardiens : Heimdall (le pare-feu), les Nornes (instantanés et
// sauvegardes) et Ratatoskr (les nouvelles).

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    title: "Gardiens"

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Heading { text: "Heimdall, le guetteur"; level: 2; color: fenetre.or }
        QQC2.Label {
            text: ygg.etat.parefeu === "actif" ? "« Je veille. Nul ne franchit le pont sans y être invité. »"
                                               : "Le pont est sans garde : le pare-feu est " + ygg.etat.parefeu + "."
            font.italic: true
            color: ygg.etat.parefeu === "actif" ? fenetre.or : Kirigami.Theme.negativeTextColor
        }
        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Carte {
                icone: "security-high"
                titre: "État du pare-feu"
                texte: "Profil, ouvertures et règles chargées."
                QQC2.Button { text: "Voir"; onClicked: ygg.lancer("heimdall status", "Heimdall") }
            }
            Carte {
                icone: "network-connect"
                titre: "Ce qui écoute sur le réseau"
                texte: "Chaque port ouvert, et s'il est joignable depuis le réseau local ou Internet."
                QQC2.Button { text: "Examiner"; onClicked: ygg.lancer("heimdall ports", "Heimdall") }
            }
            Carte {
                icone: "network-wireless"
                titre: "Le réseau du moment"
                texte: "Chez toi, tes ouvertures s'appliquent ; sur un Wi-Fi public inconnu, rien n'entre. "
                       + "Heimdall suit le réseau tout seul."
                QQC2.Button { text: "Maison"; onClicked: ygg.lancer("heimdall zone maison", "Heimdall") }
                QQC2.Button { text: "Public"; onClicked: ygg.lancer("heimdall zone public", "Heimdall") }
            }
            Carte {
                icone: "applications-games"
                titre: "LAN party"
                texte: "Les ports de jeu ouverts au réseau local pour quatre heures, puis tout se referme seul."
                QQC2.Button { text: "Ouvrir"; onClicked: ygg.lancer("heimdall fete", "LAN party") }
            }
            Carte {
                icone: "network-workgroup"
                titre: "Qui est sur mon réseau ?"
                texte: "Les appareils du réseau local, leur nom et leur fabricant. Gjallarhorn sonne quand un inconnu arrive."
                QQC2.Button { text: "Voir"; onClicked: ygg.lancer("heimdall voisins --scan", "Voisins") }
            }
            Carte {
                icone: "security-medium"
                titre: "Réveiller Heimdall"
                texte: "Réactive le pare-feu (profil poste de travail)."
                visible: ygg.etat.parefeu !== "actif"
                QQC2.Button { text: "Activer"; onClicked: ygg.lancer("heimdall enable", "Heimdall") }
            }
        }

        Kirigami.Heading { text: "Les Nornes, fileuses du destin"; level: 2; color: fenetre.or }
        QQC2.Label {
            text: "Urd garde le passé, Verdandi tisse le présent, Skuld prépare l'avenir : "
                  + "instantanés du système et sauvegardes de ton dossier personnel."
            wrapMode: Text.WordWrap
            opacity: 0.8
            Layout.fillWidth: true
        }
        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Carte {
                icone: "document-save"
                titre: "Verdandi, le présent"
                texte: "Maintenant : un instantané du système, la sauvegarde de ton dossier et la copie distante."
                QQC2.Button { text: "Tisser"; onClicked: ygg.lancer("verdandi", "Verdandi") }
            }
            Carte {
                icone: "view-history"
                titre: "Urd, le passé"
                texte: "La frise de tes sauvegardes. Clic droit sur un fichier dans Dolphin : « Versions précédentes »."
                QQC2.Button { text: "Voir"; onClicked: ygg.lancer("urd", "Urd") }
            }
            Carte {
                icone: "chronometer"
                titre: "Skuld, l'avenir"
                texte: "Ce qui est planifié : sauvegardes, copie distante chiffrée, relecture mensuelle."
                QQC2.Button { text: "Chaque jour"; onClicked: ygg.lancer("skuld sauvegarde quotidien; skuld verification mensuel; skuld", "Skuld") }
            }
            Carte {
                icone: "drive-removable-media-usb"
                titre: "Sauvegarder au branchement"
                texte: "Dès que ton disque de sauvegarde est branché, les Nornes s'en occupent (une fois par jour)."
                QQC2.Button { text: "Activer"; onClicked: ygg.lancer("norns disque", "Nornes") }
            }
            Carte {
                icone: "view-history"
                titre: "Instantanés existants"
                texte: "La liste, et la restauration si un jour il faut remonter le fil."
                QQC2.Button { text: "Voir"; onClicked: ygg.lancer("norns list", "Nornes") }
            }
            Carte {
                icone: "configure"
                titre: "Configurer les instantanés"
                texte: "Un instantané avant chaque mise à jour, et d'autres chaque jour."
                QQC2.Button { text: "Configurer"; onClicked: ygg.lancer("norns setup", "Nornes") }
            }
            Carte {
                icone: "drive-removable-media"
                titre: "Sauvegarder mon dossier"
                texte: "Copie incrémentale de ton dossier personnel sur un disque externe."
                QQC2.Button { text: "Sauvegarder"; onClicked: ygg.lancer("norns backup", "Nornes") }
            }
        }

        Kirigami.Heading { text: "Les portes de la maison"; level: 2; color: fenetre.or }
        QQC2.Label {
            text: "Partager des dossiers avec les autres ordinateurs (Windows compris), "
                  + "ou rejoindre cette machine de loin. Heimdall n'ouvre que ce qui est nécessaire."
            wrapMode: Text.WordWrap
            opacity: 0.8
            Layout.fillWidth: true
        }
        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Carte {
                icone: "folder-network"
                titre: "Dossiers partagés"
                texte: "Visibles dans « Réseau » sous Windows, et depuis Linux ou macOS, protégés par mot de passe."
                QQC2.Button { text: "Partager ~/Public"; onClicked: ygg.lancer("ygg partage ajouter ~/Public", "Partage") }
                QQC2.Button { text: "Voir"; onClicked: ygg.lancer("ygg partage", "Partage") }
            }
            Carte {
                icone: "network-vpn"
                titre: "Accès à distance"
                texte: "SSH sur le réseau local, ou un tunnel WireGuard pour venir de partout (QR code pour le téléphone)."
                QQC2.Button { text: "Voir"; onClicked: ygg.lancer("ygg distance", "Accès à distance") }
            }
        }

        Kirigami.Heading { text: "Ratatoskr, le messager"; level: 2; color: fenetre.or }
        Carte {
            Layout.fillWidth: true
            icone: "preferences-desktop-notification"
            titre: "Les nouvelles, tout de suite"
            texte: "Ratatoskr passe à l'ouverture de session, puis toutes les six heures. "
                   + "Tu peux aussi l'envoyer courir maintenant."
            QQC2.Button { text: "Demander"; onClicked: ygg.lancer("ratatoskr check --print", "Ratatoskr") }
            QQC2.Button { text: "Sur mon téléphone"; onClicked: ygg.lancer("ratatoskr telephone ntfy", "Ratatoskr") }
        }

        Kirigami.Heading { text: "Les corbeaux et le lien"; level: 2; color: fenetre.or }
        Kirigami.CardsLayout {
            maximumColumnWidth: Kirigami.Units.gridUnit * 30
            Layout.fillWidth: true
            Carte {
                icone: "utilities-system-monitor"
                titre: "Huginn, la pensée"
                texte: "Tes machines en direct : processeur, mémoire, disque, réseau, chaleur, services."
                QQC2.Button { text: "Observer"; onClicked: ygg.lancer("huginn", "Huginn") }
            }
            Carte {
                icone: "view-calendar-day"
                titre: "Muninn, la mémoire"
                texte: "Ce qui a changé depuis hier : paquets, services, ports, noyau, disque."
                QQC2.Button { text: "Se souvenir"; onClicked: ygg.lancer("muninn", "Muninn") }
            }
            Carte {
                icone: "dialog-password"
                titre: "Gleipnir, qui a accès à quoi"
                texte: "Comptes et pouvoirs, connexions à distance, portes ouvertes, partages, applications trop libres."
                QQC2.Button { text: "Vérifier"; onClicked: ygg.lancer("gleipnir", "Gleipnir") }
            }
        }
    }
}
