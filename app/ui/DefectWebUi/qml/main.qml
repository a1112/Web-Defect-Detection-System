import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Controls.Material

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

    property url apiBaseUrl: "http://192.168.1.10:8000"
    property url placeholderUrl: "https://dummyimage.com/960x540/1a2138/ffffff.png&text=Defect+Preview"
    property url imageUrl: apiBaseUrl + "/api/images/mosaic?surface=top&seq_no=1&view=2D&limit=256&stride=4&width=1280"
    property date lastRefresh: new Date()

    header: PanelHeader {
        id: mainHeader
        subtitle: qsTr("WASM ready build - minimal inspection shell")
    }

    Item {
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
                                            loadFromField()
                                        }
                                    }

                                    Button {
                                        text: qsTr("Use Placeholder")
                                        Layout.preferredWidth: 160
                                        onClicked: {
                                            imageUrl = placeholderUrl
                                            urlField.text = imageUrl.toString()
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

                Item {
                    id: tileDemoPage
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    property string lastTileMessage: qsTr("尚未选中瓦片")

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 16

                        TileViewport {
                            id: tileViewport
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            baseUrl: apiBaseUrl
                            surface: surfaceSelector.currentText
                            seqNo: seqField.value
                            view: viewField.currentText
                            level: levelField.value
                            tileSize: tileSizeField.value
                            columns: columnField.value
                            rows: rowField.value
                            showGrid: gridSwitch.checked
                            onTileTapped: function(tileX, tileY) {
                                tileDemoPage.lastTileMessage = qsTr("Tile (%1, %2) @ level %3").arg(tileX).arg(tileY).arg(level)
                            }
                        }

                        Pane {
                            Layout.fillWidth: true

                            contentItem: ColumnLayout {
                                spacing: 12

                                Flow {
                                    width: parent.width
                                    spacing: 12

                                    ComboBox {
                                        id: surfaceSelector
                                        width: 140
                                        model: ["top", "bottom"]
                                        currentIndex: 0
                                        editable: false
                                        delegate: ItemDelegate {
                                            required property string modelData
                                            text: modelData
                                        }
                                    }

                                    ComboBox {
                                        id: viewField
                                        width: 160
                                        model: ["2D", "3D", "IR"]
                                        currentIndex: 0
                                        delegate: ItemDelegate {
                                            required property string modelData
                                            text: modelData
                                        }
                                    }

                                    SpinBox {
                                        id: seqField
                                        width: 120
                                        from: 1
                                        to: 999999
                                        value: 1
                                        stepSize: 1
                                    }

                                    SpinBox {
                                        id: levelField
                                        width: 120
                                        from: 0
                                        to: 8
                                        value: 0
                                        stepSize: 1
                                        textFromValue: function(value, locale) {
                                            return qsTr("Level %1").arg(value)
                                        }
                                    }

                                    SpinBox {
                                        id: tileSizeField
                                        width: 130
                                        from: 64
                                        to: 1024
                                        stepSize: 64
                                        value: 512
                                    }

                                    SpinBox {
                                        id: columnField
                                        width: 120
                                        from: 1
                                        to: 12
                                        value: 6
                                    }

                                    SpinBox {
                                        id: rowField
                                        width: 120
                                        from: 1
                                        to: 12
                                        value: 3
                                    }

                                    Switch {
                                        id: gridSwitch
                                        text: qsTr("显示网格")
                                        checked: true
                                    }
                                }

                                RowLayout {
                                    width: parent.width
                                    spacing: 12

                                    Button {
                                        text: qsTr("刷新瓦片")
                                        onClicked: tileViewport.reloadTiles()
                                    }

                                    Button {
                                        text: qsTr("重置视图")
                                        onClicked: tileViewport.resetView()
                                    }

                                    Item { Layout.fillWidth: true }

                                    Label {
                                        text: tileDemoPage.lastTileMessage
                                        color: "#b0b7c3"
                                        elide: Text.ElideRight
                                        horizontalAlignment: Text.AlignRight
                                    }
                                }
                            }
                        }
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

    function loadFromField() {
        var candidate = urlField.text.trim()
        if (candidate.length === 0) {
            return
        }
        if (!candidate.startsWith("http://") && !candidate.startsWith("https://")) {
            candidate = "http://" + candidate
        }
        imageUrl = candidate
        urlField.text = imageUrl.toString()
        refreshFrame()
    }

    Component.onCompleted: {
        urlField.text = imageUrl.toString()
        refreshFrame()
    }
}
