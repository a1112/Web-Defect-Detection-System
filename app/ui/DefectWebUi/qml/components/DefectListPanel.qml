import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ListView {
    id: root

    property string selectedDefectId: ""
    signal defectSelected(string defectId, string surface)

    clip: true
    spacing: 2

    delegate: ItemDelegate {
        required property string defectId
        required property string defectType
        required property string severity
        required property string surface
        required property int bboxX
        required property int bboxY
        required property int bboxWidth
        required property int bboxHeight
        required property int imageIndex

        width: ListView.view.width
        highlighted: root.selectedDefectId === defectId
        onClicked: { root.defectSelected(defectId, surface) }

        contentItem: ColumnLayout {
            spacing: 4
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Rectangle {
                    width: 8
                    height: 8
                    radius: 2
                    color: severity === "high" ? "#ff5d73"
                                               : severity === "medium" ? "#ffb200"
                                                                       : "#3ed598"
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("%1  ·  %2").arg(defectType).arg(surface)
                    color: "#f0f0f0"
                    elide: Text.ElideRight
                    font.bold: true
                }

                Label {
                    text: qsTr("#%1").arg(defectId)
                    color: "#9aa3b2"
                    font.pixelSize: 11
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: qsTr("idx %1").arg(imageIndex)
                    color: "#7f8aa3"
                    font.pixelSize: 11
                }
                Item { Layout.fillWidth: true }
                Label {
                    text: qsTr("(%1,%2) %3×%4").arg(bboxX).arg(bboxY).arg(bboxWidth).arg(bboxHeight)
                    color: "#7f8aa3"
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignRight
                }
            }
        }
    }
}
