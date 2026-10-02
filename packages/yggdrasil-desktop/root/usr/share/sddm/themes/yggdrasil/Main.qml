/*
    Écran de connexion d'Yggdrasil (SDDM, Qt 6).
    Ciel nuit, l'arbre-monde, l'heure en lettres gravées, les comptes dans des
    anneaux d'or, le mot de passe, puis la session et l'alimentation en bas.
*/

import QtQuick
import QtQuick.Controls
import QtQuick.Effects

Rectangle {
    id: root
    width: 1920
    height: 1080
    color: night

    readonly property color night: "#091C30"
    readonly property color nightLight: "#0F2742"
    readonly property color line: "#3A5570"
    readonly property color gold: "#E8CC8C"
    readonly property color star: "#FBE39B"
    readonly property color sage: "#5B8B7B"
    readonly property color parchment: "#F2EAD7"
    readonly property color mist: "#9DB3AA"
    readonly property color danger: "#E07A6E"
    readonly property string titleFont: "EB Garamond"
    readonly property string textFont: "Noto Sans"
    readonly property real unit: Math.max(0.75, height / 1080)

    function now() {
        return new Date()
    }

    function login() {
        message.text = ""
        var user = users.currentItem ? users.currentItem.userName : userModel.lastUser
        sddm.login(user, password.text, session.currentIndex)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            message.text = "Mot de passe incorrect"
            password.text = ""
            password.forceActiveFocus()
            shake.start()
        }
        function onInformationMessage(text) {
            message.text = text
        }
    }

    Image {
        anchors.fill: parent
        source: config.background
        fillMode: Image.PreserveAspectCrop
    }

    Image {
        id: logo
        source: config.logo
        width: Math.min(root.height * 0.3, 360 * root.unit)
        height: width
        sourceSize.width: 512
        sourceSize.height: 512
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height * 0.07
        smooth: true
    }

    Column {
        id: clockBox
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: logo.bottom
        anchors.topMargin: 6 * root.unit
        spacing: 0

        Text {
            id: clock
            anchors.horizontalCenter: parent.horizontalCenter
            font.family: root.titleFont
            font.pixelSize: 68 * root.unit
            font.features: { "lnum": 1 }  // chiffres alignés (Garamond a des chiffres elzéviriens)
            color: root.gold
            text: Qt.formatTime(root.now(), "HH:mm")
        }
        Text {
            id: day
            anchors.horizontalCenter: parent.horizontalCenter
            font.family: root.textFont
            font.pixelSize: 17 * root.unit
            color: root.mist
            text: root.now().toLocaleDateString(Qt.locale(), "dddd d MMMM")
        }
        Timer {
            interval: 1000
            running: true
            repeat: true
            onTriggered: {
                clock.text = Qt.formatTime(root.now(), "HH:mm")
                day.text = root.now().toLocaleDateString(Qt.locale(), "dddd d MMMM")
            }
        }
    }

    ListView {
        id: users
        model: userModel
        orientation: ListView.Horizontal
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: clockBox.bottom
        anchors.topMargin: 34 * root.unit
        width: Math.max(1, Math.min(count, 5)) * 150 * root.unit
        height: 150 * root.unit
        interactive: count > 5
        clip: true
        currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0
        keyNavigationEnabled: true

        delegate: Item {
            id: account
            width: 150 * root.unit
            height: 150 * root.unit
            property string userName: model.name
            readonly property bool selected: ListView.isCurrentItem

            Rectangle {
                id: ring
                width: 98 * root.unit
                height: width
                radius: width / 2
                anchors.horizontalCenter: parent.horizontalCenter
                color: root.nightLight
                border.color: account.selected ? root.gold : root.line
                border.width: (account.selected ? 2 : 1.5) * root.unit

                Image {
                    id: face
                    anchors.fill: parent
                    anchors.margins: 7 * root.unit
                    source: model.icon
                    sourceSize.width: 256
                    sourceSize.height: 256
                    fillMode: Image.PreserveAspectCrop
                    visible: false
                }
                Rectangle {
                    id: faceMask
                    anchors.fill: face
                    radius: width / 2
                    visible: false
                    layer.enabled: true
                }
                MultiEffect {
                    anchors.fill: face
                    source: face
                    maskEnabled: true
                    maskSource: faceMask
                }
            }
            Text {
                anchors.top: ring.bottom
                anchors.topMargin: 8 * root.unit
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: model.realName || model.name
                color: account.selected ? root.parchment : root.mist
                font.family: root.textFont
                font.pixelSize: 16 * root.unit
            }
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    users.currentIndex = index
                    password.forceActiveFocus()
                }
            }
        }
    }

    TextField {
        id: password
        width: 330 * root.unit
        height: 46 * root.unit
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: users.bottom
        anchors.topMargin: 6 * root.unit
        echoMode: TextInput.Password
        passwordCharacter: "•"
        placeholderText: "Mot de passe"
        placeholderTextColor: root.mist
        color: root.parchment
        selectionColor: root.sage
        selectedTextColor: root.parchment
        font.family: root.textFont
        font.pixelSize: 16 * root.unit
        horizontalAlignment: TextInput.AlignHCenter
        verticalAlignment: TextInput.AlignVCenter
        focus: true
        background: Rectangle {
            radius: height / 2
            color: root.nightLight
            border.color: password.activeFocus ? root.gold : root.line
            border.width: 1.5 * root.unit
        }
        Keys.onReturnPressed: root.login()
        Keys.onEnterPressed: root.login()
    }

    Rectangle {
        id: go
        width: 46 * root.unit
        height: width
        radius: width / 2
        anchors.left: password.right
        anchors.leftMargin: 10 * root.unit
        anchors.verticalCenter: password.verticalCenter
        color: goArea.containsMouse ? root.gold : "transparent"
        border.color: root.gold
        border.width: 1.5 * root.unit
        Text {
            anchors.centerIn: parent
            text: "→"
            color: goArea.containsMouse ? root.night : root.gold
            font.family: root.textFont
            font.pixelSize: 22 * root.unit
        }
        MouseArea {
            id: goArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.login()
        }
    }

    SequentialAnimation {
        id: shake
        loops: 2
        NumberAnimation { target: password; property: "anchors.horizontalCenterOffset"; to: -10; duration: 45 }
        NumberAnimation { target: password; property: "anchors.horizontalCenterOffset"; to: 10; duration: 90 }
        NumberAnimation { target: password; property: "anchors.horizontalCenterOffset"; to: 0; duration: 45 }
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: password.bottom
        anchors.topMargin: 14 * root.unit
        spacing: 6 * root.unit
        Text {
            id: message
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.danger
            font.family: root.textFont
            font.pixelSize: 15 * root.unit
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: keyboard.capsLock
            text: "Verrouillage des majuscules activé"
            color: root.star
            font.family: root.textFont
            font.pixelSize: 14 * root.unit
        }
    }

    Row {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 26 * root.unit
        spacing: 10 * root.unit

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Session"
            color: root.mist
            font.family: root.textFont
            font.pixelSize: 14 * root.unit
        }
        ComboBox {
            id: session
            model: sessionModel
            textRole: "name"
            currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
            width: 250 * root.unit
            height: 38 * root.unit
            font.family: root.textFont
            font.pixelSize: 14 * root.unit

            contentItem: Text {
                leftPadding: 14 * root.unit
                rightPadding: 28 * root.unit
                text: session.displayText
                color: root.parchment
                font: session.font
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            indicator: Text {
                anchors.right: parent.right
                anchors.rightMargin: 12 * root.unit
                anchors.verticalCenter: parent.verticalCenter
                text: "▾"
                color: root.gold
                font.pixelSize: 14 * root.unit
            }
            background: Rectangle {
                radius: height / 2
                color: root.nightLight
                border.color: session.activeFocus ? root.gold : root.line
                border.width: 1.5 * root.unit
            }
            delegate: ItemDelegate {
                id: choice
                width: session.width
                highlighted: session.highlightedIndex === index
                contentItem: Text {
                    text: model.name
                    color: root.parchment
                    font: session.font
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: choice.highlighted ? root.sage : root.nightLight
                }
            }
            popup: Popup {
                y: -implicitHeight - 6 * root.unit
                width: session.width
                implicitHeight: contentItem.implicitHeight + 2
                padding: 1
                contentItem: ListView {
                    clip: true
                    implicitHeight: contentHeight
                    model: session.popup.visible ? session.delegateModel : null
                    currentIndex: session.highlightedIndex
                }
                background: Rectangle {
                    color: root.nightLight
                    border.color: root.gold
                    radius: 8 * root.unit
                }
            }
        }
    }

    component PowerButton: Item {
        id: power
        property string icon
        property string label
        signal activated()
        width: 64 * root.unit
        height: 64 * root.unit
        Image {
            id: glyph
            anchors.horizontalCenter: parent.horizontalCenter
            width: 36 * root.unit
            height: width
            sourceSize.width: 72
            sourceSize.height: 72
            source: power.icon + (powerArea.containsMouse ? "-survol.svg" : ".svg")
        }
        Text {
            anchors.top: glyph.bottom
            anchors.topMargin: 4 * root.unit
            anchors.horizontalCenter: parent.horizontalCenter
            text: power.label
            color: powerArea.containsMouse ? root.parchment : root.mist
            font.family: root.textFont
            font.pixelSize: 12 * root.unit
        }
        MouseArea {
            id: powerArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: power.activated()
        }
    }

    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 22 * root.unit
        spacing: 12 * root.unit
        PowerButton { icon: "veille"; label: "Veille"; visible: sddm.canSuspend; onActivated: sddm.suspend() }
        PowerButton { icon: "redemarrer"; label: "Redémarrer"; visible: sddm.canReboot; onActivated: sddm.reboot() }
        PowerButton { icon: "eteindre"; label: "Éteindre"; visible: sddm.canPowerOff; onActivated: sddm.powerOff() }
    }

    Component.onCompleted: password.forceActiveFocus()
}
