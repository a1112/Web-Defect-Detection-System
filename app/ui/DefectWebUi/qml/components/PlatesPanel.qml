import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "../store" as Store

Pane {
    id: root

    property alias searchText: searchField.text
    signal plateSelected(int seqNo, string steelNo)

    padding: 12

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label {
                text: qsTr("钢板列表")
                font.bold: true
                color: "#f7f7f7"
            }

            Item { Layout.fillWidth: true }

            ToolButton {
                icon.name: "refresh"
                enabled: !Store.AppStore.loadingSteels
                onClicked: { Store.AppStore.reloadSteels() }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 8
            color: Qt.rgba(1, 1, 1, 0.02)
            border.color: Qt.rgba(1, 1, 1, 0.08)
            border.width: 1
            height: 36

            TextInput {
                id: searchField
                anchors.fill: parent
                anchors.margins: 10
                color: "#f0f0f0"
                clip: true
                focus: true
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 10
                text: qsTr("搜索：钢板号 / 流水号")
                color: "#7f8aa3"
                visible: searchField.text.length === 0 && !searchField.activeFocus
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 10
            color: Qt.rgba(1, 1, 1, 0.02)
            border.color: Qt.rgba(1, 1, 1, 0.06)

            ListView {
                id: listView
                anchors.fill: parent
                anchors.margins: 6
                clip: true
                model: Store.AppStore.steelsModel

                delegate: ItemDelegate {
                    required property int seqNo
                    required property string steelNo
                    required property string level
                    required property int defectCount

                    width: ListView.view.width
                    highlighted: Store.AppStore.selectedSeqNo === seqNo
                    visible: {
                        const q = root.searchText.trim()
                        if (q.length === 0) {
                            return true
                        }
                        return steelNo.indexOf(q) >= 0 || ("" + seqNo).indexOf(q) >= 0
                    }
                    height: visible ? implicitHeight : 0

                    text: qsTr("%1  (SEQ %2)").arg(steelNo).arg(seqNo)
                    onClicked: { root.plateSelected(seqNo, steelNo) }

                    contentItem: RowLayout {
                        spacing: 10
                        Label {
                            Layout.fillWidth: true
                            text: parent.parent.text
                            color: "#f0f0f0"
                            elide: Text.ElideRight
                        }
                        Label {
                            text: qsTr("L%1").arg(level)
                            color: "#9cb3ff"
                            font.bold: true
                        }
                        Label {
                            text: defectCount > 0 ? qsTr("%1").arg(defectCount) : qsTr("-")
                            color: defectCount > 0 ? "#ffb200" : "#808aa0"
                            horizontalAlignment: Text.AlignRight
                            Layout.minimumWidth: 28
                        }
                    }
                }
            }
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
