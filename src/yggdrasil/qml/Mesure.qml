// Une mesure du trône : un chiffre (ou un mot), son libellé, et une couleur d'état.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.AbstractCard {
    id: mesure

    property string valeur
    property string libelle
    property string detail
    property color couleur: Kirigami.Theme.textColor

    Layout.fillWidth: true
    Layout.preferredWidth: Kirigami.Units.gridUnit * 9

    contentItem: ColumnLayout {
        spacing: 0
        Kirigami.Heading {
            text: mesure.valeur
            level: 1
            color: mesure.couleur
            font.family: "EB Garamond"
            font.features: { "lnum": 1 }
            Layout.alignment: Qt.AlignHCenter
        }
        QQC2.Label {
            text: mesure.libelle
            Layout.alignment: Qt.AlignHCenter
        }
        QQC2.Label {
            text: mesure.detail
            visible: text !== ""
            opacity: 0.7
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            Layout.alignment: Qt.AlignHCenter
        }
    }
}
