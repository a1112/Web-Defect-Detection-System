import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property url baseUrl: "http://192.168.1.10:8000" // 使用你的 FastAPI 服务器绝对地址
    property string surface: "top"
    property int seqNo: 1
    property string view: "2D"
    property int level: 0
    property int tileSize: 512
    property int minRequestTilePixels: 256
    property int columns: 6
    property int rows: 3
    property alias zoom: content.scale
    property real minZoom: 0.5
    property real maxZoom: 6.0
    property bool showGrid: true

    signal tileTapped(int tileX, int tileY)

    color: "#05060a"
    radius: 16
    border.color: "#1f253d"
    border.width: 1
    clip: true

    readonly property int tileCount: columns * rows
    property int _reloadNonce: 0
    readonly property bool _tileRequestsEnabled: (tileSize * zoom) >= minRequestTilePixels

    function tileUrl(col, row) {
        const params = [
            "surface=" + encodeURIComponent(surface),
            "seq_no=" + seqNo,
            "view=" + encodeURIComponent(view),
            "level=" + level,
            "tile_x=" + col,
            "tile_y=" + row,
            "fmt=JPEG",
            "cache_bust=" + _reloadNonce
        ]
        return baseUrl + "/api/images/tile?" + params.join("&")
    }

    function reloadTiles() {
        _reloadNonce += 1
    }

    function resetView() {
        content.scale = 1.0
        centerContent()
    }

    function centerContent() {
        const scaledWidth = content.width * content.scale
        const scaledHeight = content.height * content.scale
        content.x = (width - scaledWidth) / 2
        content.y = (height - scaledHeight) / 2
    }

    function zoomAround(anchor, newScale) {
        const clamped = Math.min(maxZoom, Math.max(minZoom, newScale))
        if (Math.abs(clamped - content.scale) < 0.0001) {
            return
        }
        const local = content.mapFromItem(root, anchor)
        content.scale = clamped
        const mapped = content.mapToItem(root, local)
        content.x += anchor.x - mapped.x
        content.y += anchor.y - mapped.y
    }

    Item {
        id: panLayer
        anchors.fill: parent
        clip: true

        Item {
            id: content
            width: columns * tileSize
            height: rows * tileSize
            transformOrigin: Item.TopLeft

            Repeater {
                model: root.tileCount
                delegate: Rectangle {
                    required property int index
                    readonly property int col: index % root.columns
                    readonly property int row: Math.floor(index / root.columns)
                    width: root.tileSize
                    height: root.tileSize
                    x: col * root.tileSize
                    y: row * root.tileSize
                    color: "transparent"
                    border.color: root.showGrid ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                    border.width: root.showGrid ? 1 : 0

                    Image {
                        anchors.fill: parent
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: false
                        mipmap: true
                        source: root._tileRequestsEnabled ? root.tileUrl(col, row) : ""
                        smooth: true
                    }

                    TapHandler {
                        acceptedDevices: PointerDevice.AllPointingDevices
                        onTapped: root.tileTapped(col, row)
                    }
                }
            }
        }
    }

    DragHandler {
        target: content
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchScreen | PointerDevice.TouchPad
    }

    PinchHandler {
        id: pinch
        target: content
        minimumScale: root.minZoom
        maximumScale: root.maxZoom
    }

    WheelHandler {
        id: wheel
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        target: null
        onWheel: {
            const anchor = wheel.point.position
            const delta = wheel.angleDelta.y || wheel.pixelDelta.y
            const factor = delta > 0 ? 1.2 : 0.82
            root.zoomAround(anchor, content.scale * factor)
        }
    }

    Rectangle {
        id: hud
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 12
        radius: 8
        color: Qt.rgba(0, 0, 0, 0.55)
        border.color: Qt.rgba(1, 1, 1, 0.12)
        padding: 10

        Label {
            text: qsTr("Scale %1x | Level %2 | Tiles %3x%4")
                    .arg(content.scale.toFixed(2))
                    .arg(level)
                    .arg(columns)
                    .arg(rows)
            color: "#f2f4ff"
            font.pixelSize: 13
        }
    }

    Component.onCompleted: centerContent()
}
