import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property alias currentIndex: listView.currentIndex
    signal routeSelected(int index)

    color: Qt.rgba(1, 1, 1, 0.03)
    radius: 16
    width: 200

    ListModel {
        id: railModel
        ListElement { label: qsTr("Live Monitor"); iconName: "view-media" }
        ListElement { label: qsTr("Detections"); iconName: "chart-xy" }
        ListElement { label: qsTr("History"); iconName: "time" }
        ListElement { label: qsTr("Tile Demo"); iconName: "map" }
    }

    ListView {
        id: listView
        anchors.fill: parent
        model: railModel
        clip: true
        delegate: ItemDelegate {
            width: ListView.view.width
            text: model.label
            icon.name: model.iconName
            checked: ListView.isCurrentItem
            onClicked: {
                ListView.view.currentIndex = index
                root.routeSelected(index)
            }
        }
    }
}
