import QtQuick
import QtQuick.Controls

Rectangle {
    id: root

    property int currentIndex: 0
    signal routeSelected(int index)

    color: Qt.rgba(1, 1, 1, 0.03)
    radius: 16

    ListModel {
        id: railModel
        ListElement { label: qsTr("缺陷"); iconName: "alert-circle" }
        ListElement { label: qsTr("图像"); iconName: "image" }
        ListElement { label: qsTr("设置"); iconName: "settings" }
    }

    ListView {
        anchors.fill: parent
        model: railModel
        clip: true
        currentIndex: root.currentIndex

        delegate: ItemDelegate {
            width: ListView.view.width
            text: model.label
            icon.name: model.iconName
            checked: ListView.isCurrentItem
            onClicked: {
                root.currentIndex = index
                root.routeSelected(index)
            }
        }
    }
}
