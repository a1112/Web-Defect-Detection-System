import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Controls.Material

import "components"
import "pages"
import "store" as Store

ApplicationWindow {
    id: window
    width: 1280
    height: 720
    visible: true
    title: qsTr("Defect Detection Console")
    color: "#05060a"
    Material.theme: Material.Dark
    Material.accent: Material.LightBlue

    header: PanelHeader {
        title: qsTr("Web Defect Detection")
        subtitle: qsTr("QML/WASM client - API compatible")
    }

    Item {
        anchors.fill: parent

        RowLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 24

            NavRail {
                Layout.preferredWidth: 200
                Layout.fillHeight: true
                onRouteSelected: mainStack.currentIndex = index
            }

            PlatesPanel {
                Layout.preferredWidth: 340
                Layout.fillHeight: true
                onPlateSelected: function (seqNo, steelNo) {
                    Store.AppStore.selectSteel(seqNo, steelNo)
                }
            }

            StackLayout {
                id: mainStack
                Layout.fillWidth: true
                Layout.fillHeight: true

                DefectsPage { }
                ImagesPage { }
                SettingsPage { }
            }
        }
    }

    Component.onCompleted: {
        if (typeof DEFECT_API_BASE_URL !== "undefined" && DEFECT_API_BASE_URL) {
            Store.AppStore.apiBaseUrl = DEFECT_API_BASE_URL
        }
        Store.AppStore.reloadMeta()
        Store.AppStore.reloadSteels()
    }
}
