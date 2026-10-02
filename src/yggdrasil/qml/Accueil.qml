/*
    « Bienvenue, voyageur » — l'assistant de la première session d'Yggdrasil.
    Cinq étapes : ton prénom, quel voyageur tu es, tes mondes, tes gardiens, puis
    l'arbre est planté dans un terminal visible (chaque commande s'y affiche).
*/

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: fenetre

    title: "Bienvenue sur Yggdrasil"
    width: Kirigami.Units.gridUnit * 56
    height: Kirigami.Units.gridUnit * 40
    minimumWidth: Kirigami.Units.gridUnit * 40
    minimumHeight: Kirigami.Units.gridUnit * 30

    readonly property color or: "#E8CC8C"
    readonly property color etoile: "#FBE39B"
    readonly property color sauge: "#79AC99"
    readonly property var titres: ["Bienvenue", "Voyageur", "Les mondes", "Les gardiens", "Planter l'arbre"]
    property int etape: 0
    property var voyageursChoisis: []
    property var commandes: []

    function royaumesPourVoyageurs() {
        for (var i = 0; i < cartes.count; ++i) {
            var carte = cartes.itemAt(i)
            if (!carte)
                continue
            var lui = (carte.royaume.voyageurs || [])
            carte.retenu = lui.some(v => voyageursChoisis.indexOf(v) >= 0)
        }
    }

    function choix() {
        var royaumes = {}
        for (var i = 0; i < cartes.count; ++i) {
            var carte = cartes.itemAt(i)
            if (carte && carte.retenu)
                royaumes[carte.royaume.nom] = carte.selection()
        }
        return {
            "prenom": prenom.text,
            "royaumes": royaumes,
            "theme": theme.currentValue,
            "instantanes": instantanes.checked,
            "ratatoskr": ratatoskr.checked,
            "arbre": arbreVivant.checked,
            "centre": centre.checked
        }
    }

    onEtapeChanged: {
        if (etape === 2)
            royaumesPourVoyageurs()
        if (etape === 4)
            commandes = ygg.apercu(choix())
    }

    Connections {
        target: ygg
        function onMessage(texte) { fenetre.showPassiveNotification(texte, "long") }
    }

    pageStack.initialPage: Kirigami.Page {
        id: page
        title: "Bienvenue, voyageur — " + (etape + 1) + " sur 5 : " + fenetre.titres[etape]
        padding: 0

        actions: [
            Kirigami.Action {
                text: "Passer"
                icon.name: "go-next-skip"
                onTriggered: { ygg.passerAccueil(); Qt.quit() }
            }
        ]

        footer: QQC2.ToolBar {
            contentItem: RowLayout {
                Repeater {
                    model: 5
                    delegate: Rectangle {
                        width: Kirigami.Units.smallSpacing * 2
                        height: width
                        radius: width / 2
                        color: index <= fenetre.etape ? fenetre.or : Kirigami.Theme.disabledTextColor
                    }
                }
                Item { Layout.fillWidth: true }
                QQC2.Button {
                    text: "Précédent"
                    icon.name: "go-previous"
                    enabled: fenetre.etape > 0
                    onClicked: fenetre.etape -= 1
                }
                QQC2.Button {
                    visible: fenetre.etape < 4
                    text: "Suivant"
                    icon.name: "go-next"
                    highlighted: true
                    onClicked: fenetre.etape += 1
                }
                QQC2.Button {
                    visible: fenetre.etape === 4
                    text: "Planter l'arbre"
                    icon.name: "yggdrasil"
                    highlighted: true
                    onClicked: { ygg.planter(fenetre.choix()); Qt.quit() }
                }
            }
        }

        Item {
            anchors.fill: parent

            // 1. Bienvenue
            ColumnLayout {
                anchors.fill: parent
                visible: fenetre.etape === 0
                spacing: Kirigami.Units.largeSpacing * 2
                Item { Layout.fillHeight: true }
                Kirigami.Icon {
                    source: "yggdrasil"
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 10
                    Layout.alignment: Qt.AlignHCenter
                }
                Kirigami.Heading {
                    text: "Bienvenue, voyageur"
                    font.family: "EB Garamond"
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 3
                    color: fenetre.or
                    Layout.alignment: Qt.AlignHCenter
                }
                QQC2.Label {
                    text: "L'arbre-monde relie les neuf mondes. En quelques questions, choisis ceux qui "
                          + "pousseront sur ta machine. Rien ne s'installe sans ton accord, et tout se change ensuite "
                          + "depuis le Centre."
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    opacity: 0.85
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 34
                    Layout.alignment: Qt.AlignHCenter
                }
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    QQC2.Label { text: "Comment Mímir doit-il t'appeler ?" }
                    QQC2.TextField {
                        id: prenom
                        placeholderText: "ton prénom (sinon : voyageur)"
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                    }
                }
                Item { Layout.fillHeight: true }
            }

            // 2. Quel voyageur es-tu ?
            ColumnLayout {
                anchors.fill: parent
                visible: fenetre.etape === 1
                spacing: Kirigami.Units.largeSpacing
                Kirigami.Heading {
                    text: "Quel voyageur es-tu ?"
                    font.family: "EB Garamond"
                    color: fenetre.or
                    Layout.margins: Kirigami.Units.largeSpacing * 2
                }
                QQC2.Label {
                    text: "Choisis-en un ou plusieurs : les mondes qui te correspondent seront cochés à l'étape suivante."
                    wrapMode: Text.WordWrap
                    opacity: 0.8
                    Layout.leftMargin: Kirigami.Units.largeSpacing * 2
                    Layout.fillWidth: true
                }
                Kirigami.CardsLayout {
                    maximumColumnWidth: Kirigami.Units.gridUnit * 24
                    Layout.fillHeight: false
                    Layout.alignment: Qt.AlignHCenter | Qt.AlignTop
                    Layout.margins: Kirigami.Units.largeSpacing * 2
                    Layout.fillWidth: true
                    Repeater {
                        model: ygg.voyageurs
                        delegate: Kirigami.AbstractCard {
                            id: carteVoyageur
                            readonly property bool choisi: fenetre.voyageursChoisis.indexOf(modelData.id) >= 0
                            highlighted: choisi
                            showClickFeedback: true
                            onClicked: {
                                var liste = fenetre.voyageursChoisis.filter(v => v !== modelData.id)
                                if (!choisi)
                                    liste.push(modelData.id)
                                fenetre.voyageursChoisis = liste
                            }
                            contentItem: RowLayout {
                                spacing: Kirigami.Units.largeSpacing
                                Kirigami.Icon {
                                    source: modelData.icone
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.large
                                    Layout.preferredHeight: Kirigami.Units.iconSizes.large
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Kirigami.Heading { level: 3; text: modelData.nom }
                                    QQC2.Label {
                                        text: modelData.description
                                        wrapMode: Text.WordWrap
                                        opacity: 0.8
                                        Layout.fillWidth: true
                                    }
                                }
                                QQC2.CheckBox {
                                    checked: carteVoyageur.choisi
                                    onToggled: carteVoyageur.clicked()
                                }
                            }
                        }
                    }
                }
                Item { Layout.fillHeight: true }
            }

            // 3. Les neuf mondes
            QQC2.ScrollView {
                anchors.fill: parent
                visible: fenetre.etape === 2
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: Kirigami.Units.largeSpacing
                    Kirigami.Heading {
                        text: "Les mondes de ton arbre"
                        font.family: "EB Garamond"
                        color: fenetre.or
                        Layout.margins: Kirigami.Units.largeSpacing * 2
                        Layout.bottomMargin: 0
                    }
                    QQC2.Label {
                        text: "Active les mondes qui te tentent, et règle leur contenu avec « Choisir les logiciels ». "
                              + "Chaque monde planté allumera une feuille d'or sur ton fond d'écran."
                        wrapMode: Text.WordWrap
                        opacity: 0.8
                        Layout.leftMargin: Kirigami.Units.largeSpacing * 2
                        Layout.rightMargin: Kirigami.Units.largeSpacing * 2
                        Layout.fillWidth: true
                    }
                    Kirigami.CardsLayout {
                        maximumColumnWidth: Kirigami.Units.gridUnit * 30
                        Layout.margins: Kirigami.Units.largeSpacing * 2
                        Layout.fillWidth: true
                        Repeater {
                            id: cartes
                            model: ygg.royaumes
                            delegate: CarteRoyaume {
                                royaume: modelData
                                modeChoix: true
                            }
                        }
                    }
                }
            }

            // 4. Les gardiens
            ColumnLayout {
                anchors.fill: parent
                visible: fenetre.etape === 3
                spacing: Kirigami.Units.largeSpacing
                Kirigami.Heading {
                    text: "Les gardiens de ta machine"
                    font.family: "EB Garamond"
                    color: fenetre.or
                    Layout.margins: Kirigami.Units.largeSpacing * 2
                }
                Kirigami.FormLayout {
                    Layout.fillWidth: true
                    QQC2.ComboBox {
                        id: theme
                        Kirigami.FormData.label: "Thème :"
                        textRole: "texte"
                        valueRole: "valeur"
                        model: [
                            { "valeur": "nuit", "texte": "Nuit — le bleu du logo" },
                            { "valeur": "aube", "texte": "Aube — parchemin clair" },
                            { "valeur": "auto", "texte": "Les deux, selon l'heure" }
                        ]
                    }
                    QQC2.Switch {
                        id: instantanes
                        visible: !ygg.live
                        checked: true
                        Kirigami.FormData.label: "Les Nornes :"
                        text: "un instantané du système avant chaque mise à jour"
                    }
                    QQC2.Switch {
                        id: ratatoskr
                        checked: true
                        Kirigami.FormData.label: "Ratatoskr :"
                        text: "me prévenir des mises à jour et des soucis"
                    }
                    QQC2.Switch {
                        id: arbreVivant
                        checked: true
                        Kirigami.FormData.label: "L'arbre vivant :"
                        text: "une feuille d'or par monde planté, sur le fond d'écran"
                    }
                    QQC2.Switch {
                        id: centre
                        checked: true
                        Kirigami.FormData.label: "Hliðskjálf :"
                        text: "ouvrir le Centre à chaque session"
                    }
                }
                QQC2.Label {
                    text: "Heimdall, le pare-feu, veille déjà : rien n'entre sans y être invité."
                    font.italic: true
                    color: fenetre.or
                    Layout.leftMargin: Kirigami.Units.largeSpacing * 2
                }
                Item { Layout.fillHeight: true }
            }

            // 5. Planter l'arbre
            ColumnLayout {
                anchors.fill: parent
                visible: fenetre.etape === 4
                spacing: Kirigami.Units.largeSpacing
                Kirigami.Heading {
                    text: "Planter l'arbre"
                    font.family: "EB Garamond"
                    color: fenetre.or
                    Layout.margins: Kirigami.Units.largeSpacing * 2
                    Layout.bottomMargin: 0
                }
                QQC2.Label {
                    text: "Un terminal va s'ouvrir et lancer ces commandes, une à une : tu y verras tout, "
                          + "et ton mot de passe te sera demandé une fois."
                    wrapMode: Text.WordWrap
                    opacity: 0.8
                    Layout.leftMargin: Kirigami.Units.largeSpacing * 2
                    Layout.rightMargin: Kirigami.Units.largeSpacing * 2
                    Layout.fillWidth: true
                }
                QQC2.Frame {
                    Layout.margins: Kirigami.Units.largeSpacing * 2
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    QQC2.ScrollView {
                        anchors.fill: parent
                        ColumnLayout {
                            Repeater {
                                model: fenetre.commandes
                                delegate: QQC2.Label {
                                    text: "$ " + modelData
                                    font.family: "JetBrains Mono"
                                    color: index % 2 ? Kirigami.Theme.textColor : fenetre.sauge
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
