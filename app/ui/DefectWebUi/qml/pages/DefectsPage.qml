import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../store" as Store
import "../components"
import "../js/api.js" as Api

Item {
    id: root

    property string selectedDefectId: ""
    property string viewMode: "full" // "full" | "single"
    property string surfaceFilter: "top" // "top" | "bottom" | "all"
    property string defectTypeFilter: ""
    property int level: 0
    property real zoom: 0.8
    property string orientation: "horizontal"

    ListModel { id: filteredDefects }

    function _refreshDefects() {
        filteredDefects.clear()
        const typeFilter = defectTypeFilter
        const surface = surfaceFilter
        for (let i = 0; i < Store.AppStore.defectsModel.count; i += 1) {
            const item = Store.AppStore.defectsModel.get(i)
            if (surface !== "all" && item.surface !== surface) {
                continue
            }
            if (typeFilter && typeFilter.length > 0 && ("" + item.defectType).indexOf(typeFilter) < 0) {
                continue
            }
            filteredDefects.append(item)
        }
        if (selectedDefectId.length === 0 && filteredDefects.count > 0) {
            selectedDefectId = filteredDefects.get(0).defectId
        }
    }

    Connections {
        target: Store.AppStore.defectsModel
        function onCountChanged() { root._refreshDefects() }
    }

    onSurfaceFilterChanged: _refreshDefects()
    onDefectTypeFilterChanged: _refreshDefects()

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Label {
                text: Store.AppStore.selectedSeqNo > 0
                    ? qsTr("钢板 %1 (SEQ %2)").arg(Store.AppStore.selectedSteelNo).arg(Store.AppStore.selectedSeqNo)
                    : qsTr("请选择钢板")
                color: "#f7f7f7"
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            RowLayout {
                spacing: 6
                Label { text: qsTr("Surface"); color: "#b0b7c3"; font.pixelSize: 12 }
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
                ToolButton {
                    text: "all"
                    checkable: true
                    checked: root.surfaceFilter === "all"
                    onClicked: { root.surfaceFilter = "all" }
                }
            }

            RowLayout {
                spacing: 6

                Rectangle {
                    id: typeField
                    Layout.preferredWidth: 220
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.02)
                    border.color: Qt.rgba(1, 1, 1, 0.08)
                    border.width: 1
                    height: 36

                    TextInput {
                        id: typeInput
                        anchors.fill: parent
                        anchors.margins: 10
                        color: "#f0f0f0"
                        text: root.defectTypeFilter
                        clip: true
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        text: qsTr("缺陷类型过滤(可选)")
                        color: "#7f8aa3"
                        visible: typeInput.text.length === 0 && !typeInput.activeFocus
                    }
                }

                ToolButton {
                    text: qsTr("应用")
                    onClicked: {
                        root.defectTypeFilter = typeInput.text.trim()
                        root._refreshDefects()
                    }
                }

                ToolButton {
                    text: qsTr("清空")
                    enabled: root.defectTypeFilter.length > 0 || typeInput.text.length > 0
                    onClicked: {
                        typeInput.text = ""
                        root.defectTypeFilter = ""
                        root._refreshDefects()
                    }
                }
            }

            ToolButton {
                text: root.viewMode === "full" ? qsTr("大图") : qsTr("单缺陷")
                onClicked: { root.viewMode = root.viewMode === "full" ? "single" : "full" }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            Item {
                SplitView.fillWidth: true
                SplitView.preferredWidth: 820

                Rectangle {
                    anchors.fill: parent
                    radius: 12
                    color: Qt.rgba(1, 1, 1, 0.02)
                    border.color: Qt.rgba(1, 1, 1, 0.06)

                    Loader {
                        anchors.fill: parent
                        anchors.margins: 8
                        active: true
                        sourceComponent: root.viewMode === "full" ? fullView : singleView
                    }
                }
            }

            Item {
                SplitView.preferredWidth: 420
                SplitView.maximumWidth: 560
                SplitView.minimumWidth: 320
                SplitView.fillHeight: true

                Rectangle {
                    anchors.fill: parent
                    radius: 12
                    color: Qt.rgba(1, 1, 1, 0.02)
                    border.color: Qt.rgba(1, 1, 1, 0.06)

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                text: qsTr("缺陷列表")
                                color: "#b0b7c3"
                                font.pixelSize: 12
                            }
                            Item { Layout.fillWidth: true }
                            ToolButton {
                                icon.name: "refresh"
                                onClicked: Store.AppStore.reloadDefects(root.surfaceFilter === "all" ? "" : root.surfaceFilter)
                            }
                        }

                        DefectListPanel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            model: filteredDefects
                            selectedDefectId: root.selectedDefectId
                            onDefectSelected: function (defectId, surface) {
                                root.selectedDefectId = defectId
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: fullView
        Item {
            anchors.fill: parent

            TileViewer {
                anchors.fill: parent
                seqNo: Store.AppStore.selectedSeqNo
                surfaceImageInfo: Store.AppStore.surfaceImages
                surfaceFilter: root.surfaceFilter
                level: root.level
                zoom: root.zoom
                orientation: root.orientation
                selectedDefectId: root.selectedDefectId
                defectsModel: filteredDefects
                onDefectSelected: function (defectId) {
                    root.selectedDefectId = defectId
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 10
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

    Component {
        id: singleView
        Item {
            anchors.fill: parent

            ImagePreview {
                anchors.fill: parent
                label: qsTr("缺陷裁剪")
                sourceUrl: {
                    if (root.selectedDefectId.length === 0) {
                        return ""
                    }
                    let surface = "top"
                    for (let i = 0; i < filteredDefects.count; i += 1) {
                        const item = filteredDefects.get(i)
                        if (item.defectId === root.selectedDefectId) {
                            surface = item.surface
                            break
                        }
                    }
                    return Api.defectCropUrl(
                        Store.AppStore.apiBaseUrl,
                        root.selectedDefectId,
                        surface,
                        32,
                        960,
                        540,
                        "JPEG"
                    )
                }
            }
        }
    }

    Component.onCompleted: _refreshDefects()
}
