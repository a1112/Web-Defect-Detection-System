pragma Singleton

import QtQuick

import "../js/http.js" as Http
import "../js/api.js" as Api

QtObject {
    id: store

    property string apiBaseUrl: ""
    property int steelsLimit: 50

    property bool loadingMeta: false
    property bool loadingSteels: false
    property bool loadingDefects: false
    property bool loadingSteelMeta: false

    property string lastError: ""

    property var globalMeta: ({})
    property int defaultTileSize: 1024
    property int maxTileLevel: 2
    property int frameWidth: 0
    property int frameHeight: 0

    property int selectedSeqNo: -1
    property string selectedSteelNo: ""

    property var surfaceImages: []

    property ListModel steelsModel: ListModel { }
    property ListModel defectsModel: ListModel { }

    function _setError(message) {
        lastError = message || ""
    }

    function reloadMeta() {
        loadingMeta = true
        _setError("")
        Http.getJson(
            Api.metaUrl(apiBaseUrl),
            function (data) {
                globalMeta = data || ({})
                if (data && data.tile) {
                    defaultTileSize = data.tile.default_tile_size || defaultTileSize
                    maxTileLevel = data.tile.max_level || maxTileLevel
                }
                if (data && data.image) {
                    frameWidth = data.image.frame_width || 0
                    frameHeight = data.image.frame_height || 0
                }
                loadingMeta = false
            },
            function (message) {
                _setError(message)
                loadingMeta = false
            }
        )
    }

    function reloadSteels() {
        loadingSteels = true
        _setError("")
        Http.getJson(
            Api.steelsUrl(apiBaseUrl, steelsLimit, false, "", "desc"),
            function (data) {
                steelsModel.clear()
                const steels = data && data.steels ? data.steels : []
                for (let i = 0; i < steels.length; i += 1) {
                    const item = steels[i]
                    steelsModel.append({
                        seqNo: item.seq_no,
                        steelNo: item.steel_no,
                        steelType: item.steel_type || "",
                        length: item.length || 0,
                        width: item.width || 0,
                        thickness: item.thickness || 0,
                        timestamp: item.timestamp || "",
                        level: item.level || "D",
                        defectCount: item.defect_count || 0
                    })
                }
                loadingSteels = false
            },
            function (message) {
                _setError(message)
                loadingSteels = false
            }
        )
    }

    function selectSteel(seqNo, steelNo) {
        selectedSeqNo = seqNo
        selectedSteelNo = steelNo || ""
        reloadDefects()
        reloadSteelMeta()
    }

    function reloadDefects(surfaceFilter) {
        if (selectedSeqNo <= 0) {
            defectsModel.clear()
            return
        }
        loadingDefects = true
        _setError("")
        Http.getJson(
            Api.defectsUrl(apiBaseUrl, selectedSeqNo, surfaceFilter || ""),
            function (data) {
                defectsModel.clear()
                const defects = data && data.defects ? data.defects : []
                for (let i = 0; i < defects.length; i += 1) {
                    const item = defects[i]
                    defectsModel.append({
                        defectId: item.defect_id,
                        defectType: item.defect_type,
                        severity: item.severity,
                        bboxX: item.x,
                        bboxY: item.y,
                        bboxWidth: item.width,
                        bboxHeight: item.height,
                        confidence: item.confidence,
                        surface: item.surface,
                        imageIndex: item.image_index
                    })
                }
                loadingDefects = false
            },
            function (message) {
                _setError(message)
                loadingDefects = false
            }
        )
    }

    function reloadSteelMeta() {
        if (selectedSeqNo <= 0) {
            surfaceImages = []
            return
        }
        loadingSteelMeta = true
        _setError("")
        Http.getJson(
            Api.steelMetaUrl(apiBaseUrl, selectedSeqNo),
            function (data) {
                surfaceImages = data && data.surface_images ? data.surface_images : []
                loadingSteelMeta = false
            },
            function (message) {
                _setError(message)
                loadingSteelMeta = false
            }
        )
    }
}
