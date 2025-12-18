.pragma library

const SURFACE_ORDER = ["top", "bottom"]

function buildOrientationLayout(params) {
    const orientation = params.orientation || "vertical"
    const surfaceFilter = params.surfaceFilter || "all"
    const topMeta = params.topMeta
    const bottomMeta = params.bottomMeta
    const surfaceGap = params.surfaceGap || 0

    const metaMap = { top: topMeta, bottom: bottomMeta }
    const shouldIncludeSurface = function (surface) {
        return surfaceFilter === "all" || surfaceFilter === surface
    }

    const surfaces = []
    for (const surface of SURFACE_ORDER) {
        if (!shouldIncludeSurface(surface)) {
            continue
        }
        const meta = metaMap[surface]
        if (!meta) {
            continue
        }
        const mosaicWidth = meta.image_width || 0
        const mosaicHeight = (meta.frame_count || 0) * (meta.image_height || 0)
        if (mosaicWidth <= 0 || mosaicHeight <= 0) {
            continue
        }
        surfaces.push({
            surface: surface,
            meta: meta,
            mosaicWidth: mosaicWidth,
            mosaicHeight: mosaicHeight,
            worldWidth: orientation === "horizontal" ? mosaicHeight : mosaicWidth,
            worldHeight: orientation === "horizontal" ? mosaicWidth : mosaicHeight,
            offsetX: 0,
            offsetY: 0
        })
    }

    if (surfaces.length === 0) {
        return { surfaces: [], worldWidth: 0, worldHeight: 0 }
    }

    if (orientation === "horizontal") {
        let offsetY = 0
        surfaces.forEach(function (surfaceLayout, index) {
            surfaceLayout.offsetX = 0
            surfaceLayout.offsetY = offsetY
            offsetY += surfaceLayout.worldHeight
            if (index < surfaces.length - 1) {
                offsetY += surfaceGap
            }
        })
        return {
            surfaces: surfaces,
            worldWidth: Math.max.apply(null, surfaces.map(function (s) { return s.worldWidth })),
            worldHeight: offsetY
        }
    }

    let offsetX = 0
    surfaces.forEach(function (surfaceLayout, index) {
        surfaceLayout.offsetX = offsetX
        surfaceLayout.offsetY = 0
        offsetX += surfaceLayout.worldWidth
        if (index < surfaces.length - 1) {
            offsetX += surfaceGap
        }
    })
    return {
        surfaces: surfaces,
        worldWidth: offsetX,
        worldHeight: Math.max.apply(null, surfaces.map(function (s) { return s.worldHeight }))
    }
}

function computeTileRequestInfo(params) {
    const surface = params.surface
    const tile = params.tile
    const orientation = params.orientation || "vertical"
    const virtualTileSize = params.virtualTileSize
    const tileSize = params.tileSize

    const alignedOffsetX = orientation === "vertical" && surface.surface === "bottom"
        ? Math.ceil(surface.offsetX / tileSize) * tileSize
        : surface.offsetX
    const localX = tile.x - alignedOffsetX
    const localY = tile.y - surface.offsetY
    const intersects = (localX + tile.width > 0) && (localY + tile.height > 0)
        && (localX < surface.worldWidth) && (localY < surface.worldHeight)
    if (!intersects) {
        return null
    }

    const sourceX = orientation === "horizontal" ? localY : localX
    const sourceY = orientation === "horizontal" ? localX : localY

    const tileX = Math.floor(sourceX / virtualTileSize)
    const tileY = Math.floor(sourceY / virtualTileSize)
    if (tileX < 0 || tileY < 0) {
        return null
    }

    const maxTileX = Math.ceil(surface.mosaicWidth / virtualTileSize)
    const maxTileY = Math.ceil(surface.mosaicHeight / virtualTileSize)
    if (tileX >= maxTileX || tileY >= maxTileY) {
        return null
    }

    return { tileX: tileX, tileY: tileY }
}

function convertDefectToWorldRect(params) {
    const surface = params.surface
    const defect = params.defect
    const orientation = params.orientation || "vertical"

    if (defect.surface !== surface.surface) {
        return null
    }
    const frameHeight = surface.meta.image_height || 0
    const mosaicX = defect.bboxX
    const frameIndex = defect.imageIndex && defect.imageIndex > 0 ? defect.imageIndex - 1 : 0
    const mosaicY = frameIndex * frameHeight + defect.bboxY

    if (orientation === "horizontal") {
        return {
            x: surface.offsetX + mosaicY,
            y: surface.offsetY + mosaicX,
            width: defect.bboxHeight,
            height: defect.bboxWidth
        }
    }
    return {
        x: surface.offsetX + mosaicX,
        y: surface.offsetY + mosaicY,
        width: defect.bboxWidth,
        height: defect.bboxHeight
    }
}
