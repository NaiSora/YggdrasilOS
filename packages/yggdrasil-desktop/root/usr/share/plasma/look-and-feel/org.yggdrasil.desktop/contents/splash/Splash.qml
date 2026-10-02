/*
    Écran de démarrage de session d'Yggdrasil : l'arbre-monde pousse
    (l'anneau se trace, les racines et la ramure grandissent, l'étoile
    s'allume), puis le nom apparaît. Les images sont celles de Plymouth.
*/

import QtQuick

Rectangle {
    id: root
    color: "#091C30"

    property int stage
    property int frame: 0
    readonly property int frames: 48

    // Démarre dès l'affichage : la session prend parfois moins de 3 s
    Component.onCompleted: growth.start()

    NumberAnimation {
        id: growth
        target: root
        property: "frame"
        from: 0
        to: root.frames - 1
        duration: 2600
    }

    Image {
        id: tree
        readonly property real side: Math.min(root.width, root.height) * 0.42
        width: side
        height: side
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -root.height * 0.05
        source: "images/arbre-" + root.frame + ".png"
        sourceSize.width: 512
        sourceSize.height: 512
        smooth: true
        cache: true
    }

    Image {
        id: title
        source: "images/title.png"
        width: tree.width * 0.6
        fillMode: Image.PreserveAspectFit
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: tree.bottom
        anchors.topMargin: tree.height * 0.04
        opacity: Math.max(0, (root.frame - root.frames * 0.6) / (root.frames * 0.4))
        smooth: true
    }
}
