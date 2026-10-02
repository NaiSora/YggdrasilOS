// Une carte d'action : icône, titre, texte, état, et ses boutons à droite.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.AbstractCard {
    id: carte

    property string titre
    property string texte
    property string icone
    property string etiquette
    property color couleurEtiquette: Kirigami.Theme.positiveTextColor
    default property alias boutons: rangee.data

    contentItem: RowLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Icon {
            source: carte.icone
            visible: carte.icone !== ""
            Layout.preferredWidth: Kirigami.Units.iconSizes.large
            Layout.preferredHeight: Kirigami.Units.iconSizes.large
            Layout.alignment: Qt.AlignTop
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Heading {
                level: 4
                text: carte.titre
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            QQC2.Label {
                text: carte.texte
                visible: text !== ""
                wrapMode: Text.WordWrap
                opacity: 0.8
                Layout.fillWidth: true
            }
            QQC2.Label {
                text: carte.etiquette
                visible: text !== ""
                color: carte.couleurEtiquette
                font.bold: true
            }
        }

        RowLayout {
            id: rangee
            spacing: Kirigami.Units.smallSpacing
            Layout.alignment: Qt.AlignVCenter
        }
    }
}
