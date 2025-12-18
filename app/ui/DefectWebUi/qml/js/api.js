.pragma library
.import "http.js" as Http

function apiUrl(baseUrl, path, params) {
    return Http.resolveUrl(baseUrl, path, params)
}

function steelsUrl(baseUrl, limit, defectOnly, startSeq, order) {
    return apiUrl(baseUrl, "/api/steels", {
        limit: limit || 50,
        defect_only: defectOnly ? "true" : "",
        start_seq: startSeq || "",
        order: order || "desc"
    })
}

function defectsUrl(baseUrl, seqNo, surface) {
    return apiUrl(baseUrl, "/api/defects/" + seqNo, {
        surface: surface || ""
    })
}

function metaUrl(baseUrl) {
    return apiUrl(baseUrl, "/api/meta")
}

function steelMetaUrl(baseUrl, seqNo) {
    return apiUrl(baseUrl, "/api/steel-meta/" + seqNo)
}

function tileImageUrl(baseUrl, surface, seqNo, level, tileX, tileY, view, fmt, orientation) {
    return apiUrl(baseUrl, "/api/images/tile", {
        surface: surface,
        seq_no: seqNo,
        level: level || 0,
        tile_x: tileX,
        tile_y: tileY,
        view: view || "",
        fmt: fmt || "JPEG",
        orientation: orientation || "vertical"
    })
}

function mosaicImageUrl(baseUrl, surface, seqNo, view, limit, skip, stride, width, height, fmt) {
    return apiUrl(baseUrl, "/api/images/mosaic", {
        surface: surface,
        seq_no: seqNo,
        view: view || "",
        limit: limit || "",
        skip: skip || "",
        stride: stride || "",
        width: width || "",
        height: height || "",
        fmt: fmt || "JPEG"
    })
}

function defectCropUrl(baseUrl, defectId, surface, expand, width, height, fmt) {
    return apiUrl(baseUrl, "/api/images/defect/" + defectId, {
        surface: surface,
        expand: expand === undefined ? 32 : expand,
        width: width || "",
        height: height || "",
        fmt: fmt || "JPEG"
    })
}
