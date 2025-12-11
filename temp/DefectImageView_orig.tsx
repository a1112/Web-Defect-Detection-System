import { useState, useEffect, useMemo } from "react";
import { AlertCircle } from "lucide-react";
import { env } from "../src/config/env";
import type { SteelPlate, Defect } from "../types/app.types";
import type {
  SurfaceImageInfo,
  Surface,
} from "../src/api/types";
import { getTileImageUrl } from "../src/api/client";
import { LargeImageViewer } from "./LargeImageViewer/LargeImageViewer";
import type { Tile } from "./LargeImageViewer/utils";

// 瓦片图像缓存
const tileImageCache = new Map<string, HTMLImageElement>();
const tileImageLoading = new Set<string>();

export interface ViewportInfo {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface DefectImageViewProps {
  selectedPlate: SteelPlate | undefined;
  defects: Defect[];
  surface: "all" | "top" | "bottom";
  imageViewMode: "full" | "single";
  selectedDefectId: string | null;
  onDefectSelect: (id: string | null) => void;
  surfaceImageInfo?: SurfaceImageInfo[] | null;
  onViewportChange?: (info: ViewportInfo | null) => void;
}

export function DefectImageView({
  selectedPlate,
  defects,
  surface,
  imageViewMode,
  selectedDefectId,
  onDefectSelect,
  surfaceImageInfo,
  onViewportChange,
}: DefectImageViewProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [isLoadingImage, setIsLoadingImage] = useState(false);

  const actualSurface: Surface = useMemo(
    () => (surface === "all" ? "top" : surface) as Surface,
    [surface],
  );

  const surfaceMeta: SurfaceImageInfo | undefined = useMemo(
    () =>
      surfaceImageInfo?.find(
        (info) => info.surface === actualSurface,
      ),
    [surfaceImageInfo, actualSurface],
  );

  const seqNo = useMemo(
    () =>
      selectedPlate
        ? parseInt(selectedPlate.serialNumber, 10)
        : null,
    [selectedPlate],
  );

  // 获取当前选中的缺陷
  const selectedDefect = selectedDefectId
    ? defects.find((d) => d.id === selectedDefectId)
    : null;

  // 计算聚焦目标区域
  const focusTarget = useMemo(() => {
    if (!selectedDefect || !surfaceMeta || imageViewMode !== "full") {
      return null;
    }

    // 只聚焦到当前表面的缺陷
    if (selectedDefect.surface !== actualSurface) {
      return null;
    }

    // 确保缺陷有 imageIndex
    if (typeof selectedDefect.imageIndex !== "number") {
      return null;
    }

    const frameHeight = surfaceMeta.image_height;
    const defectY = selectedDefect.imageIndex * frameHeight + selectedDefect.y;
    const defectX = selectedDefect.x;

    // 放大区域，让缺陷周围也可见
    const padding = Math.max(selectedDefect.width, selectedDefect.height) * 2;
    
    return {
      x: Math.max(0, defectX - padding / 2),
      y: Math.max(0, defectY - padding / 2),
      width: selectedDefect.width + padding,
      height: selectedDefect.height + padding,
    };
  }, [selectedDefect, surfaceMeta, actualSurface, imageViewMode]);

  // 当显示单缺陷模式时，如果没有选中，自动选中第一个
  useEffect(() => {
    if (
      imageViewMode === "single" &&
      !selectedDefectId &&
      defects.length > 0
    ) {
      onDefectSelect(defects[0].id);
    }
  }, [
    imageViewMode,
    selectedDefectId,
    defects,
    onDefectSelect,
  ]);

  // 加载图像（单缺陷模式使用裁剪接口）
  useEffect(() => {
    if (!selectedPlate) {
      setImageUrl(null);
      return;
    }

    if (imageViewMode === "full") {
      // 大图模式使用 LargeImageViewer，不需要加载单帧图像
      setImageUrl(null);
      setIsLoadingImage(false);
      return;
    }

    const loadImage = async () => {
      setIsLoadingImage(true);
      setImageError(null);

      try {
        const baseUrl = env.getApiBaseUrl();

        // 单缺陷模式：使用缺陷裁剪接口
        if (imageViewMode === "single" && selectedDefect) {
          const url = `${baseUrl}/images/defect/${selectedDefect.id}?surface=${selectedDefect.surface}`;
          console.log(`🖼️ 加载单缺陷图像: ${url}`);
          setImageUrl(url);
          return;
        }
      } catch (error) {
        console.error("❌ 加载图像失败:", error);
        setImageError(
          error instanceof Error ? error.message : "加载失败",
        );
      } finally {
        setIsLoadingImage(false);
      }
    };

    loadImage();
  }, [
    selectedPlate,
    imageViewMode,
    selectedDefect,
    actualSurface,
    seqNo,
  ]);

  if (isLoadingImage) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 text-muted-foreground">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
        <p className="text-sm">加载图像中...</p>
      </div>
    );
  }

  if (imageError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 text-destructive">
        <AlertCircle className="w-16 h-16 opacity-50" />
        <p className="text-sm">图像加载失败: {imageError}</p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      {imageViewMode === "full" ? (
        // 大图模式：使用 LargeImageViewer（与图像界面一致）
        <>
          {surfaceImageInfo && seqNo != null ? (
            (() => {
              const tileSize = 512;
              
              // 获取上下表面的元数据
              const topMeta = surfaceImageInfo?.find((info) => info.surface === "top");
              const bottomMeta = surfaceImageInfo?.find((info) => info.surface === "bottom");

              // 根据选中缺陷决定显示哪个表面
              const showTop = actualSurface === "top";
              const showBottom = actualSurface === "bottom";

              // 瓦片渲染函数
              const createRenderTile = (surfaceType: Surface) => {
                const metaForSurface = surfaceType === "top" ? topMeta : bottomMeta;
                if (!metaForSurface) return undefined;

                return (
                  ctx: CanvasRenderingContext2D,
                  tile: Tile,
                  tileSizeParam: number,
                  scale: number
                ) => {
                  const tileX = Math.floor(tile.x / tileSizeParam);
                  const tileY = Math.floor(tile.y / tileSizeParam);

                  const url = getTileImageUrl({
                    surface: surfaceType,
                    seqNo,
                    level: tile.level,
                    tileX,
                    tileY,
                    tileSize: tileSizeParam,
                    fmt: "JPEG",
                  });

                  const cacheKey = `${surfaceType}-${seqNo}-${tile.level}-${tileX}-${tileY}-${tileSizeParam}`;
                  const cached = tileImageCache.get(cacheKey);

                  if (cached && cached.complete) {
                    // 绘制瓦片图像
                    ctx.drawImage(cached, tile.x, tile.y, tile.width, tile.height);

                    // 调试：瓦片边框
                    ctx.strokeStyle = "rgba(0,0,0,0.2)";
                    ctx.lineWidth = 1 / scale;
                    ctx.strokeRect(tile.x, tile.y, tile.width, tile.height);

                    // 开发模式：显示瓦片信息
                    if (env.isDevelopment()) {
                      ctx.save();
                      ctx.translate(tile.x + 5, tile.y + 5);
                      const textScale = 1 / scale;
                      ctx.scale(textScale, textScale);
                      ctx.font = "11px 'Consolas', monospace";
                      
                      // 半透明背景
                      ctx.fillStyle = "rgba(0, 0, 0, 0.75)";
                      ctx.fillRect(-2, -2, 140, 90);

                      // 瓦片基本信息
                      ctx.fillStyle = "#00ff40";
                      ctx.fillText(`L${tile.level} [${tileX},${tileY}]`, 2, 10);
                      ctx.fillStyle = "#ffaa00";
                      ctx.fillText(`Pos: ${Math.round(tile.x)},${Math.round(tile.y)}`, 2, 24);
                      ctx.fillStyle = "#00aaff";
                      ctx.fillText(`${Math.round(tile.width)}×${Math.round(tile.height)}`, 2, 38);
                      
                      // Surface 和状态
                      ctx.fillStyle = "#ff6600";
                      ctx.fillText(`Surface: ${surfaceType}`, 2, 52);
                      ctx.fillStyle = "#00ff00";
                      ctx.fillText(`✓ LOADED`, 2, 66);
                      
                      // 序列号
                      ctx.fillStyle = "#aaa";
                      ctx.font = "9px 'Consolas', monospace";
                      ctx.fillText(`seq:${seqNo}`, 2, 80);

                      ctx.restore();
                    }

                    // 绘制该瓦片范围内的缺陷
                    const defectsForSurface = defects.filter(
                      (d) => d.surface === surfaceType && typeof d.imageIndex === "number"
                    );

                    if (defectsForSurface.length > 0 && metaForSurface) {
                      const frameHeight = metaForSurface.image_height;

                      // 过滤出当前瓦片范围内的缺陷
                      const visibleDefects = defectsForSurface.filter((d) => {
                        const defectY = d.imageIndex * frameHeight + d.y;
                        const defectX = d.x;

                        // 判断是否与当前瓦片相交
                        return !(
                          defectX + d.width < tile.x ||
                          defectX > tile.x + tile.width ||
                          defectY + d.height < tile.y ||
                          defectY > tile.y + tile.height
                        );
                      });

                      // 绘制缺陷矩形框
                      visibleDefects.forEach((d) => {
                        const defectY = d.imageIndex * frameHeight + d.y;
                        const defectX = d.x;

                        // 根据严重程度选择颜色
                        let strokeColor = "#ffff00";
                        if (d.severity === "high") {
                          strokeColor = "#ff0000";
                        } else if (d.severity === "medium") {
                          strokeColor = "#ff8800";
                        }

                        // 如果是选中的缺陷，使用更亮的颜色
                        if (d.id === selectedDefectId) {
                          strokeColor = "#00ff00"; // 亮绿色
                          ctx.lineWidth = 3 / scale;
                        } else {
                          ctx.lineWidth = 2 / scale;
                        }

                        ctx.strokeStyle = strokeColor;
                        ctx.strokeRect(defectX, defectY, d.width, d.height);

                        // 绘制缺陷类型标签
                        if (scale > 0.3) {
                          ctx.save();
                          ctx.translate(defectX + 2, defectY + 2);
                          const labelScale = 1 / scale;
                          ctx.scale(labelScale, labelScale);
                          ctx.font = "10px sans-serif";
                          ctx.fillStyle = strokeColor;
                          ctx.fillText(d.type, 0, 10);
                          ctx.restore();
                        }
                      });
                    }

                    return;
                  }

                  // 开始加载瓦片
                  if (!tileImageLoading.has(cacheKey)) {
                    tileImageLoading.add(cacheKey);
                    const img = new Image();
                    img.src = url;
                    img.onload = () => {
                      tileImageCache.set(cacheKey, img);
                      tileImageLoading.delete(cacheKey);
                    };
                    img.onerror = () => {
                      tileImageLoading.delete(cacheKey);
                    };
                  }

                  // 绘制占位网格
                  ctx.fillStyle = "#f8f8f8";
                  ctx.fillRect(tile.x, tile.y, tile.width, tile.height);

                  ctx.strokeStyle = "#ccc";
                  ctx.lineWidth = 1 / scale;
                  ctx.strokeRect(tile.x, tile.y, tile.width, tile.height);

                  // 开发模式：显示加载中的瓦片信息
                  if (env.isDevelopment()) {
                    ctx.save();
                    ctx.translate(tile.x + 5, tile.y + 5);
                    const loadingScale = 1 / scale;
                    ctx.scale(loadingScale, loadingScale);
                    ctx.font = "11px 'Consolas', monospace";

                    // 半透明背景
                    ctx.fillStyle = "rgba(200, 200, 200, 0.8)";
                    ctx.fillRect(-2, -2, 140, 90);

                    // 瓦片信息
                    ctx.fillStyle = "#666";
                    ctx.fillText(`L${tile.level} [${tileX},${tileY}]`, 2, 10);
                    ctx.fillStyle = "#888";
                    ctx.fillText(`Pos: ${Math.round(tile.x)},${Math.round(tile.y)}`, 2, 24);
                    ctx.fillStyle = "#aaa";
                    ctx.fillText(`${Math.round(tile.width)}×${Math.round(tile.height)}`, 2, 38);

                    // Surface 和 Status
                    ctx.fillStyle = "#ff6600";
                    ctx.fillText(`Surface: ${surfaceType}`, 2, 52);
                    ctx.fillStyle = "#ff0000";
                    ctx.fillText(`⏳ LOADING...`, 2, 66);

                    // URL 信息
                    ctx.fillStyle = "#999";
                    ctx.font = "9px 'Consolas', monospace";
                    ctx.fillText(`seq:${seqNo}`, 2, 80);

                    ctx.restore();
                  }
                };
              };

              return (
                <div className="relative w-full h-full">
                  {/* 上表面画布 */}
                  {showTop && topMeta && (
                    <div className="absolute inset-0">
                      <LargeImageViewer
                        imageWidth={topMeta.image_width}
                        imageHeight={topMeta.frame_count * topMeta.image_height}
                        tileSize={tileSize}
                        className="bg-black"
                        renderTile={createRenderTile("top")}
                        focusTarget={focusTarget}
                      />
                    </div>
                  )}

                  {/* 下表面画布 */}
                  {showBottom && bottomMeta && (
                    <div className="absolute inset-0">
                      <LargeImageViewer
                        imageWidth={bottomMeta.image_width}
                        imageHeight={bottomMeta.frame_count * bottomMeta.image_height}
                        tileSize={tileSize}
                        className="bg-black"
                        renderTile={createRenderTile("bottom")}
                        focusTarget={focusTarget}
                      />
                    </div>
                  )}
                </div>
              );
            })()
          ) : (
            <div className="flex flex-col items-center justify-center gap-4 text-muted-foreground h-full">
              <AlertCircle className="w-16 h-16 opacity-50" />
              <p className="text-sm">无可用大图</p>
            </div>
          )}
        </>
      ) : (
        // 单缺陷模式显示裁剪后的缺陷图像
        <div className="relative w-full h-full flex flex-col items-center justify-center gap-4 p-4">
          {imageUrl ? (
            <>
              <img
                src={imageUrl}
                alt={`缺陷: ${selectedDefect?.type}`}
                className="max-w-full max-h-full object-contain border-2 border-primary/50 rounded"
                onError={() => setImageError("图像加载失败")}
              />
              {selectedDefect && (
                <div className="absolute bottom-4 left-4 right-4 bg-black/80 backdrop-blur-sm p-3 rounded border border-border">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-bold text-white">
                          {selectedDefect.type}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-bold ${
                            selectedDefect.severity === "high"
                              ? "bg-red-500 text-white"
                              : selectedDefect.severity === "medium"
                                ? "bg-yellow-500 text-black"
                                : "bg-green-500 text-white"
                          }`}
                        >
                          {selectedDefect.severity.toUpperCase()}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        位置: ({selectedDefect.x.toFixed(1)},{" "}
                        {selectedDefect.y.toFixed(1)}) | 尺寸:{" "}
                        {selectedDefect.width.toFixed(1)} ×{" "}
                        {selectedDefect.height.toFixed(1)} | 置信度:{" "}
                        {(selectedDefect.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center gap-4 text-muted-foreground">
              <AlertCircle className="w-16 h-16 opacity-50" />
              <p className="text-sm">请选择一个缺陷</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}