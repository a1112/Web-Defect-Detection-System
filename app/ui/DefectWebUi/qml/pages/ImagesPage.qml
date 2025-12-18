import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../store" as Store
import "../components"

Item {
    id: root

    property string surfaceFilter: "all"
    property string orientation: "vertical"
    property int level: 0
    property real zoom: 0.8

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Label {
                text: qsTr("长带图像 / 瓦片视图")
                color: "#f7f7f7"
                font.bold: true
            }
            Item { Layout.fillWidth: true }

            RowLayout {
                spacing: 6
                Label { text: qsTr("Surface"); color: "#b0b7c3"; font.pixelSize: 12 }
                ToolButton {
                    text: "all"
                    checkable: true
                    checked: root.surfaceFilter === "all"
                    onClicked: { root.surfaceFilter = "all" }
                }
                ToolButton {
                    text: "top"
                    checkable: true
                    checked: root.surfaceFilter === "top"
                    onClicked: { root.surfaceFilter = "top" }
                }
                ToolButton {
                    text: "bottom"
                    checkable: true
                    checked: root.surfaceFilter === "bottom"
                    onClicked: { root.surfaceFilter = "bottom" }
                }
            }

            RowLayout {
                spacing: 6
                Label { text: qsTr("Orientation"); color: "#b0b7c3"; font.pixelSize: 12 }
                ToolButton {
                    text: "vertical"
                    checkable: true
                    checked: root.orientation === "vertical"
                    onClicked: { root.orientation = "vertical" }
                }
                ToolButton {
                    text: "horizontal"
                    checkable: true
                    checked: root.orientation === "horizontal"
                    onClicked: { root.orientation = "horizontal" }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: Qt.rgba(1, 1, 1, 0.02)
            border.color: Qt.rgba(1, 1, 1, 0.06)

            TileViewer {
                id: viewer
                anchors.fill: parent
                anchors.margins: 8
                seqNo: Store.AppStore.selectedSeqNo
                surfaceImageInfo: Store.AppStore.surfaceImages
                surfaceFilter: root.surfaceFilter
                orientation: root.orientation
                level: root.level
                zoom: root.zoom
            }

            Rectangle {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 14
                radius: 10
                color: Qt.rgba(0, 0, 0, 0.55)
                border.color: Qt.rgba(1, 1, 1, 0.12)

                RowLayout {
                    anchors.fill: parent
                    spacing: 10

                    Label {
                        text: qsTr("Level %1").arg(root.level)
                        color: "#f2f4ff"
                        font.pixelSize: 12
                    }
                    ToolButton {
                        text: "-"
                        enabled: root.level > 0
                        onClicked: root.level = Math.max(0, root.level - 1)
                    }
                    ToolButton {
                        text: "+"
                        enabled: root.level < Store.AppStore.maxTileLevel
                        onClicked: root.level = Math.min(Store.AppStore.maxTileLevel, root.level + 1)
                    }

                    Label {
                        text: qsTr("Zoom %1x").arg(root.zoom.toFixed(2))
                        color: "#f2f4ff"
                        font.pixelSize: 12
                    }
                    ToolButton {
                        text: "-"
                        enabled: root.zoom > 0.21
                        onClicked: root.zoom = Math.max(0.2, root.zoom / 1.15)
                    }
                    ToolButton {
                        text: "+"
                        enabled: root.zoom < 3.99
                        onClicked: root.zoom = Math.min(4.0, root.zoom * 1.15)
                    }
                }
            }
        }
    }
}
