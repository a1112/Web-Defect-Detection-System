import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ToolBar {
    id: root
    property alias title: titleLabel.text
    property string subtitle: ""
    property url logo: ""

    RowLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            id: titleLabel
            text: qsTr("Defect Web UI")
            font.pixelSize: 20
            font.bold: true
            color: "#f7f7f7"
        }

        Label {
            text: root.subtitle
            color: "#b0b7c3"
            font.pixelSize: 12
            Layout.alignment: Qt.AlignVCenter
        }

        Item { Layout.fillWidth: true }

        RoundButton {
            icon.name: "refresh"
            text: qsTr("Refresh")
            visible: false
        }
    }
}
