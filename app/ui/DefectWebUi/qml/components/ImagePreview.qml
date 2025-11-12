import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property url sourceUrl: ""
    property string label: qsTr("Live Frame")
    property real borderRadius: 12
    property alias status: preview.status
    signal reloadRequested()

    color: Qt.rgba(0.04, 0.05, 0.08, 0.95)
    radius: borderRadius
    border.color: Qt.rgba(1, 1, 1, 0.08)
    border.width: 1

    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.reloadRequested()
    }

    Image {
        id: preview
        anchors.fill: parent
        anchors.margins: 16
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: false
        source: root.sourceUrl
        visible: status === Image.Ready
    }

    BusyIndicator {
        anchors.centerIn: parent
        running: preview.status === Image.Loading
        visible: running
    }

    Label {
        anchors.centerIn: parent
        visible: preview.status === Image.Null
        color: "#f0f0f0"
        text: qsTr("No frame selected")
    }

    Column {
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
            margins: 18
        }
        spacing: 6

        Label {
            text: root.label
            font.pixelSize: 18
            color: "#f9f9fb"
        }
        Label {
            color: "#9cb3ff"
            font.pixelSize: 12
            wrapMode: Text.WrapAnywhere
            text: sourceUrl.toString()
            elide: Text.ElideMiddle
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        height: 46
        radius: Qt.vector4d(0, 0, borderRadius, borderRadius)
        color: Qt.rgba(1, 1, 1, 0.02)
        border.color: Qt.rgba(1, 1, 1, 0.06)

        Row {
            anchors.centerIn: parent
            spacing: 16

            Label {
                text: preview.status === Image.Loading ? qsTr("Loading ...")
                                                        : preview.status === Image.Ready ? qsTr("Ready")
                                                                                          : preview.status === Image.Error ? qsTr("Failed")
                                                                                                                            : qsTr("Idle")
                color: "#fefefe"
                font.bold: true
            }
            Rectangle {
                width: 8
                height: 8
                radius: 4
                color: preview.status === Image.Ready ? "#3ed598"
                                                       : preview.status === Image.Loading ? "#ffb200"
                                                                                           : "#ff5d73"
            }
        }
    }
}
