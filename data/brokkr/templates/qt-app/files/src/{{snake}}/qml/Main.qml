import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    width: 480
    height: 560
    visible: true
    title: "{{name}}"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12

        RowLayout {
            Layout.fillWidth: true
            TextField {
                id: champ
                placeholderText: "Une note…"
                Layout.fillWidth: true
                onAccepted: { pont.ajouter(text); text = "" }
            }
            Button {
                text: "Ajouter"
                onClicked: { pont.ajouter(champ.text); champ.text = "" }
            }
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: pont.notes
            delegate: ItemDelegate {
                width: ListView.view.width
                text: modelData
                onDoubleClicked: pont.retirer(index)
            }
        }

        Label {
            text: "Double-clic pour effacer une note."
            opacity: 0.6
        }
    }
}
