import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../store" as Store

Item {
    id: root

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        Label {
            text: qsTr("设置")
            color: "#f7f7f7"
            font.bold: true
            font.pixelSize: 18
        }

        GroupBox {
            title: qsTr("API 连接")
            Layout.fillWidth: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 10

                Label {
                    text: qsTr("API Base URL（留空表示同源，例如 WASM 由后端 /ui 提供）")
                    color: "#b0b7c3"
                    wrapMode: Text.Wrap
                }

                Rectangle {
                    Layout.fillWidth: true
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.02)
                    border.color: Qt.rgba(1, 1, 1, 0.08)
                    border.width: 1
                    height: 36

                    TextInput {
                        id: baseUrlInput
                        anchors.fill: parent
                        anchors.margins: 10
                        color: "#f0f0f0"
                        text: Store.AppStore.apiBaseUrl
                        clip: true
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        text: qsTr("例如：http://127.0.0.1:8120")
                        color: "#7f8aa3"
                        visible: baseUrlInput.text.length === 0 && !baseUrlInput.activeFocus
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    ToolButton {
                        text: qsTr("应用")
                        onClicked: { Store.AppStore.apiBaseUrl = baseUrlInput.text.trim() }
                    }

                    ToolButton {
                        text: qsTr("刷新 Meta")
                        enabled: !Store.AppStore.loadingMeta
                        onClicked: { Store.AppStore.reloadMeta() }
                    }
                    ToolButton {
                        text: qsTr("刷新钢板列表")
                        enabled: !Store.AppStore.loadingSteels
                        onClicked: { Store.AppStore.reloadSteels() }
                    }
                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    visible: Store.AppStore.lastError.length > 0
                    text: Store.AppStore.lastError
                    color: "#ff5d73"
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                }
            }
        }

        GroupBox {
            title: qsTr("运行信息")
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 8
                Label { text: qsTr("默认瓦片大小: %1").arg(Store.AppStore.defaultTileSize); color: "#b0b7c3" }
                Label { text: qsTr("最大瓦片等级: %1").arg(Store.AppStore.maxTileLevel); color: "#b0b7c3" }
                Label { text: qsTr("Frame: %1×%2").arg(Store.AppStore.frameWidth).arg(Store.AppStore.frameHeight); color: "#b0b7c3" }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
