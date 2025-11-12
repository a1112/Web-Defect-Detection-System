import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

import "components"

ApplicationWindow {
    id: window
    width: 1280
    height: 720
    visible: true
    title: qsTr("Defect Detection Console")
    color: "#05060a"
    Material.theme: Material.Dark
    Material.accent: Material.LightBlue

    property alias imageUrl: frameBridge.sourceUrl
    property date lastRefresh: new Date()

    header: PanelHeader {
        id: mainHeader
        subtitle: qsTr("WASM ready build - minimal inspection shell")
    }

    contentItem: Item {
        anchors.fill: parent

        RowLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 24

            SideRail {
                Layout.preferredWidth: 220
                Layout.fillHeight: true
                onRouteSelected: detectionStack.currentIndex = index
            }

            StackLayout {
                id: detectionStack
                Layout.fillWidth: true
                Layout.fillHeight: true

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 16

                        ImagePreview {
                            id: livePreview
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            label: qsTr("Live Feed")
                            sourceUrl: imageUrl
                            onReloadRequested: refreshFrame()
                        }

                        Pane {
                            Layout.fillWidth: true
                            contentItem: ColumnLayout {
                                spacing: 12

                                TextField {
                                    id: urlField
                                    Layout.fillWidth: true
                                    placeholderText: qsTr("Paste HTTP(S) image URL to preview")
                                    text: imageUrl.toString()
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12

                                    Button {
                                        text: qsTr("Load URL")
                                        Layout.preferredWidth: 140
                                        onClicked: {
                                            frameBridge.loadFromString(urlField.text)
                                            refreshFrame()
                                        }
                                    }

                                    Button {
                                        text: qsTr("Use Placeholder")
                                        Layout.preferredWidth: 160
                                        onClicked: {
                                            frameBridge.useSample()
                                            urlField.text = frameBridge.sourceUrl.toString()
                                            refreshFrame()
                                        }
                                    }

                                    Item { Layout.fillWidth: true }

                                    Label {
                                        text: qsTr("Updated: %1").arg(lastRefresh.toLocaleTimeString())
                                        color: "#b0b7c3"
                                    }
                                }
                            }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 16

                        GroupBox {
                            title: qsTr("Detection Summary")
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            ListView {
                                id: detectionList
                                anchors.fill: parent
                                model: detectionModel
                                delegate: ItemDelegate {
                                    width: ListView.view.width
                                    text: model.label
                                    description: model.detail
                                }
                            }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Label {
                        anchors.centerIn: parent
                        text: qsTr("History view coming soon")
                        color: "#c0c6d4"
                        font.pixelSize: 20
                    }
                }
            }
        }
    }

    ListModel {
        id: detectionModel
        ListElement { label: qsTr("Surface scratch"); detail: qsTr("Probability 0.92") }
        ListElement { label: qsTr("Burn mark"); detail: qsTr("Probability 0.67") }
    }

    function refreshFrame() {
        lastRefresh = new Date()
    }

    Component.onCompleted: {
        frameBridge.useSample()
        refreshFrame()
    }
}
