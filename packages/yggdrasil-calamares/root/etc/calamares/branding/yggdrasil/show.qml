/* Diaporama de l'installation d'Yggdrasil (Calamares, API 2) : nuit, or et sauge. */

import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    readonly property color night: "#091C30"
    readonly property color gold: "#E8CC8C"
    readonly property color parchment: "#F2EAD7"
    readonly property color mist: "#9DB3AA"

    function onActivate() { }
    function onLeave() { }

    Timer {
        interval: 15000
        running: true
        repeat: true
        onTriggered: presentation.goToNextSlide()
    }

    Rectangle {
        anchors.fill: parent
        color: presentation.night
        z: -1
    }

    // Une diapositive : titre gravé en or, texte sur la nuit
    component Page: Slide {
        id: page
        property string heading
        property string body
        property bool showLogo: false

        Image {
            id: logo
            visible: page.showLogo
            source: "logo.png"
            width: page.showLogo ? 150 : 0
            height: width
            fillMode: Image.PreserveAspectFit
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: page.showLogo ? 24 : 0
        }
        Text {
            id: title
            anchors.top: logo.bottom
            anchors.topMargin: page.showLogo ? 18 : parent.height * 0.22
            anchors.horizontalCenter: parent.horizontalCenter
            text: page.heading
            color: presentation.gold
            font.family: "EB Garamond"
            font.pixelSize: 32
        }
        Rectangle {
            id: rule
            anchors.top: title.bottom
            anchors.topMargin: 10
            anchors.horizontalCenter: parent.horizontalCenter
            width: 120
            height: 1
            color: presentation.gold
            opacity: 0.5
        }
        Text {
            anchors.top: rule.bottom
            anchors.topMargin: 18
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width * 0.78
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            textFormat: Text.StyledText
            color: presentation.parchment
            font.pixelSize: 17
            lineHeight: 1.25
            text: page.body
        }
    }

    Page {
        showLogo: true
        heading: "Bienvenue dans Yggdrasil"
        body: "L'arbre-monde prend racine sur ton disque : une base Debian 13 solide, " +
              "un bureau KDE Plasma aux couleurs de la nuit, de l'or et de la sauge, " +
              "et des outils qui ne font jamais rien sans ton accord."
    }

    Page {
        heading: "Les royaumes"
        body: "Les neuf mondes de l'arbre : Muspelheim pour le jeu, Alfheim pour la création, " +
              "Nidavellir pour le code, Vanaheim pour l'IA, Jötunheim pour les serveurs…<br/>" +
              "Au premier démarrage, dis quel voyageur tu es : ils seront pré-cochés.<br/><br/>" +
              "<font color='#E8CC8C'><tt>ygg realm list</tt></font>"
    }

    Page {
        heading: "Mímir, l'oracle"
        body: "Une IA qui vit entièrement sur ta machine. Elle explique, lit tes journaux " +
              "et propose des commandes que tu valides toujours.<br/><br/>" +
              "<font color='#E8CC8C'><tt>mimir install</tt></font> puis " +
              "<font color='#E8CC8C'><tt>mimir chat</tt></font>"
    }

    Page {
        heading: "Heimdall veille, les Nornes se souviennent"
        body: "Le pare-feu est actif dès le premier démarrage.<br/>" +
              "Avec <font color='#E8CC8C'><tt>norns setup</tt></font>, chaque mise à jour " +
              "est précédée d'un instantané : tu peux toujours revenir en arrière."
    }

    Page {
        heading: "Bifröst et Brokkr"
        body: "Un serveur Minecraft en une commande : " +
              "<font color='#E8CC8C'><tt>bifrost up minecraft-paper</tt></font><br/><br/>" +
              "Un bot Discord prêt à coder : " +
              "<font color='#E8CC8C'><tt>brokkr new discord-bot MonBot</tt></font>"
    }
}
