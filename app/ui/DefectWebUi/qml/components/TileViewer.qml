import QtQuick
import QtQuick.Controls

import "../js/api.js" as Api
import "../js/orientation.js" as Orientation
import "../store" as Store

Item {
    id: root

    property int seqNo: -1
    property var surfaceImageInfo: []
    property string surfaceFilter: "top" // "top" | "bottom" | "all"
    property string orientation: "vertical" // "vertical" | "horizontal"
    property int level: 0
    property real zoom: 1.0
    property string selectedDefectId: ""
    property var defectsModel: null

    signal defectSelected(string defectId)

    readonly property int tileSize: Store.AppStore.defaultTileSize

    property var _layout: ({ surfaces: [], worldWidth: 0, worldHeight: 0 })
    property var _topMeta: null
    property var _bottomMeta: null

    ListModel { id: tileModel }
    ListModel { id: defectRectModel }

    function _rebuildLayout() {
        _topMeta = null
        _bottomMeta = null
        for (let i = 0; i < surfaceImageInfo.length; i += 1) {
            const item = surfaceImageInfo[i]
            if (item.surface === "top") {
                _topMeta = item
            } else if (item.surface === "bottom") {
                _bottomMeta = item
            }
        }
        _layout = Orientation.buildOrientationLayout({
            orientation: orientation,
            surfaceFilter: surfaceFilter,
            topMeta: _topMeta,
            bottomMeta: _bottomMeta,
            surfaceGap: 32
        })
        _scheduleTiles()
        _rebuildDefects()
    }

    function _virtualTileSize() {
        return tileSize * Math.pow(2, Math.max(0, level))
    }

    function _rebuildTilesNow() {
        tileModel.clear()
        if (seqNo <= 0 || !_layout || !_layout.surfaces || _layout.surfaces.length === 0) {
            return
        }
        const vts = _virtualTileSize()
        const scale = Math.max(0.05, scene.scale)
        const vx0 = flick.contentX / scale - 200
        const vy0 = flick.contentY / scale - 200
        const vx1 = (flick.contentX + flick.width) / scale + 200
        const vy1 = (flick.contentY + flick.height) / scale + 200

        for (let s = 0; s < _layout.surfaces.length; s += 1) {
            const surfaceLayout = _layout.surfaces[s]
            const alignedOffsetX = orientation === "vertical" && surfaceLayout.surface === "bottom"
                ? Math.ceil(surfaceLayout.offsetX / tileSize) * tileSize
                : surfaceLayout.offsetX

            const sx0 = Math.max(vx0, alignedOffsetX)
            const sy0 = Math.max(vy0, surfaceLayout.offsetY)
            const sx1 = Math.min(vx1, surfaceLayout.offsetX + surfaceLayout.worldWidth)
            const sy1 = Math.min(vy1, surfaceLayout.offsetY + surfaceLayout.worldHeight)
            if (sx1 <= sx0 || sy1 <= sy0) {
                continue
            }

            const startCol = Math.max(0, Math.floor((sx0 - alignedOffsetX) / vts))
            const endCol = Math.ceil((sx1 - alignedOffsetX) / vts)
            const startRow = Math.max(0, Math.floor((sy0 - surfaceLayout.offsetY) / vts))
            const endRow = Math.ceil((sy1 - surfaceLayout.offsetY) / vts)

            for (let col = startCol; col < endCol; col += 1) {
                for (let row = startRow; row < endRow; row += 1) {
                    const tileWorld = {
                        x: alignedOffsetX + col * vts,
                        y: surfaceLayout.offsetY + row * vts,
                        width: vts,
                        height: vts
                    }
                    const req = Orientation.computeTileRequestInfo({
                        surface: surfaceLayout,
                        tile: tileWorld,
                        orientation: orientation,
                        virtualTileSize: vts,
                        tileSize: tileSize
                    })
                    if (!req) {
                        continue
                    }
                    tileModel.append({
                        surface: surfaceLayout.surface,
                        worldX: tileWorld.x,
                        worldY: tileWorld.y,
                        size: vts,
                        tileX: req.tileX,
                        tileY: req.tileY
                    })
                }
            }
        }
    }

    function _rebuildDefects() {
        defectRectModel.clear()
        if (!defectsModel || seqNo <= 0 || !_layout || _layout.surfaces.length === 0) {
            return
        }
        for (let i = 0; i < defectsModel.count; i += 1) {
            const defect = defectsModel.get(i)
            for (let s = 0; s < _layout.surfaces.length; s += 1) {
                const surfaceLayout = _layout.surfaces[s]
                const rect = Orientation.convertDefectToWorldRect({
                    surface: surfaceLayout,
                    defect: defect,
                    orientation: orientation
                })
                if (!rect) {
                    continue
                }
                defectRectModel.append({
                    defectId: defect.defectId,
                    severity: defect.severity,
                    rectX: rect.x,
                    rectY: rect.y,
                    rectWidth: rect.width,
                    rectHeight: rect.height
                })
            }
        }
    }

    Timer {
        id: tileTimer
        interval: 30
        repeat: false
        onTriggered: root._rebuildTilesNow()
    }

    function _scheduleTiles() {
        tileTimer.restart()
    }

    Flickable {
        id: flick
        anchors.fill: parent
        clip: true
        interactive: _layout.worldWidth > 0 && _layout.worldHeight > 0

        contentWidth: scene.width * scene.scale
        contentHeight: scene.height * scene.scale

        onContentXChanged: root._scheduleTiles()
        onContentYChanged: root._scheduleTiles()

        Item {
            id: scene
            width: Math.max(1, _layout.worldWidth)
            height: Math.max(1, _layout.worldHeight)
            scale: Math.max(0.1, root.zoom)
            transformOrigin: Item.TopLeft

            Repeater {
                model: tileModel
                delegate: Item {
                    required property string surface
                    required property real worldX
                    required property real worldY
                    required property real size
                    required property int tileX
                    required property int tileY

                    x: worldX
                    y: worldY
                    width: size
                    height: size

                    Item {
                        anchors.fill: parent

                        Image {
                            id: tileImage
                            anchors.fill: parent
                            asynchronous: true
                            cache: false
                            mipmap: true
                            fillMode: Image.PreserveAspectFit
                            source: Api.tileImageUrl(
                                Store.AppStore.apiBaseUrl,
                                surface,
                                root.seqNo,
                                root.level,
                                tileX,
                                tileY,
                                "",
                                "JPEG",
                                root.orientation
                            )
                            visible: root.orientation !== "horizontal"
                        }

                        Image {
                            anchors.centerIn: parent
                            width: parent.height
                            height: parent.width
                            asynchronous: true
                            cache: false
                            mipmap: true
                            fillMode: Image.PreserveAspectFit
                            source: tileImage.source
                            visible: root.orientation === "horizontal"
                            transform: [
                                Rotation { angle: 90; origin.x: width / 2; origin.y: height / 2 },
                                Scale { xScale: 1; yScale: -1; origin.x: width / 2; origin.y: height / 2 }
                            ]
                        }
                    }
                }
            }

            Repeater {
                model: defectRectModel
                delegate: Rectangle {
                    required property string defectId
                    required property string severity
                    required property real rectX
                    required property real rectY
                    required property real rectWidth
                    required property real rectHeight

                    x: rectX
                    y: rectY
                    width: Math.max(1, rectWidth)
                    height: Math.max(1, rectHeight)
                    color: "transparent"
                    border.width: defectId === root.selectedDefectId ? 3 : 1
                    border.color: severity === "high" ? "#ff5d73"
                                                      : severity === "medium" ? "#ffb200"
                                                                              : "#3ed598"

                    TapHandler {
                        acceptedDevices: PointerDevice.AllPointingDevices
                        onTapped: root.defectSelected(defectId)
                    }
                }
            }
        }

        DragHandler {
            target: null
            property real _lastX: 0
            property real _lastY: 0
            onActiveChanged: {
                if (active) {
                    _lastX = translation.x
                    _lastY = translation.y
                } else {
                    root._scheduleTiles()
                }
            }
            onTranslationChanged: {
                const dx = translation.x - _lastX
                const dy = translation.y - _lastY
                flick.contentX -= dx
                flick.contentY -= dy
                _lastX = translation.x
                _lastY = translation.y
            }
        }

        WheelHandler {
            target: null
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: {
                const delta = wheel.angleDelta.y || wheel.pixelDelta.y
                const factor = delta > 0 ? 1.15 : 0.86
                const next = Math.max(0.2, Math.min(6.0, root.zoom * factor))
                root.zoom = next
                root._scheduleTiles()
            }
        }
    }

    onSurfaceImageInfoChanged: _rebuildLayout()
    onSurfaceFilterChanged: _rebuildLayout()
    onOrientationChanged: _rebuildLayout()
    onLevelChanged: _scheduleTiles()
    onZoomChanged: _scheduleTiles()
    onDefectsModelChanged: _rebuildDefects()

    Component.onCompleted: _rebuildLayout()
}
