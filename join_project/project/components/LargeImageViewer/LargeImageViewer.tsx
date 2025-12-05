import React, { useEffect, useRef, useState, useCallback } from 'react';
import { clamp, getVisibleTiles, Size, Point, Tile } from './utils';

interface LargeImageViewerProps {
  imageWidth: number;
  imageHeight: number;
  tileSize?: number;
  minTileWidth?: number; // For the "min dimension" constraint if needed
  className?: string;
  /**
   * Custom renderer for a tile.
   * If not provided, renders a debug grid with coordinates.
   */
  renderTile?: (
    ctx: CanvasRenderingContext2D,
    tile: Tile,
    tileSize: number,
    scale: number
  ) => void;
}

export const LargeImageViewer: React.FC<LargeImageViewerProps> = ({
  imageWidth,
  imageHeight,
  tileSize = 256,
  className,
  renderTile,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  // State stored in refs for high-performance animation loop without re-renders
  const transform = useRef({ x: 0, y: 0, scale: 1 });
  const isDragging = useRef(false);
  const lastMousePosition = useRef<Point>({ x: 0, y: 0 });
  
  // Container size state
  const [containerSize, setContainerSize] = useState<Size>({ width: 0, height: 0 });
  
  // Force render for UI overlays (like zoom level text)
  const [, setTick] = useState(0);

  // Constants
  const MIN_SIDE_LENGTH_ON_SCREEN = 50; // Minimum pixels a side should take up
  
  // Calculate constraints
  const getConstraints = useCallback(() => {
    const cw = containerSize.width;
    const ch = containerSize.height;
    
    // Min scale: Fit entire image OR min dimension constraint
    // "最小为完整显示出图像或者单边宽度达到了最小值"
    const fitScale = Math.min(cw / imageWidth, ch / imageHeight);
    
    // If we want a hard minimum where at least 'MIN_SIDE_LENGTH_ON_SCREEN' pixels are shown
    // const minSideScale = MIN_SIDE_LENGTH_ON_SCREEN / Math.min(imageWidth, imageHeight);
    // const minScale = Math.max(fitScale, minSideScale);
    
    // For this implementation, let's stick to "Fit entire image" as the floor, 
    // unless the image is insanely huge and fitting it makes it invisible. 
    // But 160000px wide fitting into 1000px is scale 0.006. 
    const minScale = fitScale; 
    
    const maxScale = 1.0; // "缩放的最大为原生图像大小"

    return { minScale, maxScale };
  }, [containerSize, imageWidth, imageHeight]);

  // Main Draw Function
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || containerSize.width === 0) return;

    // Clear
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Background
    ctx.fillStyle = '#e5e5e5';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const { x, y, scale } = transform.current;

    // Calculate visible area in virtual coordinates
    // Screen: 0 to width -> Virtual: -x/scale to (-x+width)/scale
    const visibleRect = {
      x: -x / scale,
      y: -y / scale,
      width: containerSize.width / scale,
      height: containerSize.height / scale
    };

    // Optimization: Don't draw if nothing is visible (shouldn't happen with constraints)
    
    // Draw Image Placeholder (The "Canvas")
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);

    // Draw whole image boundary
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 2 / scale; // keep line width constant in screen pixels
    ctx.strokeRect(0, 0, imageWidth, imageHeight);
    
    // Draw Tiles
    const tiles = getVisibleTiles(
      visibleRect, 
      tileSize, 
      { width: imageWidth, height: imageHeight },
      scale
    );
    
    tiles.forEach(tile => {
      if (renderTile) {
        renderTile(ctx, tile, tileSize, scale);
      } else {
        // Default Debug Tile
        ctx.fillStyle = 'white';
        ctx.fillRect(tile.x, tile.y, tile.width, tile.height);
        
        // Border (0 margin)
        ctx.strokeStyle = '#ccc';
        ctx.lineWidth = 1 / scale;
        ctx.strokeRect(tile.x, tile.y, tile.width, tile.height);
        
        // Text
        ctx.fillStyle = '#000';
        // Scale text so it remains readable? Or stick to virtual size?
        // If we stick to virtual size, it disappears when zoomed out.
        // Let's make text constant screen size.
        
        ctx.save();
        ctx.translate(tile.x, tile.y);
        // Inverse scale for text rendering to keep it constant size on screen
        const textScale = 1 / scale;
        ctx.scale(textScale, textScale);
        ctx.font = '12px sans-serif';
        ctx.fillText(`L${tile.level} [${tile.col},${tile.row}]`, 8, 20);
        ctx.restore();
      }
    });

    ctx.restore();
    
  }, [containerSize, imageWidth, imageHeight, tileSize, renderTile]);

  // Animation Loop
  useEffect(() => {
    let animationFrameId: number;
    const renderLoop = () => {
      draw();
      animationFrameId = requestAnimationFrame(renderLoop);
    };
    renderLoop();
    return () => cancelAnimationFrame(animationFrameId);
  }, [draw]);

  // Initial centering
  useEffect(() => {
    if (containerSize.width > 0 && transform.current.scale === 1) { // Only on first meaningful load
       const { minScale } = getConstraints();
       transform.current = {
         scale: minScale,
         x: (containerSize.width - imageWidth * minScale) / 2,
         y: (containerSize.height - imageHeight * minScale) / 2
       };
       setTick(t => t + 1);
    }
  }, [containerSize, imageWidth, imageHeight, getConstraints]);

  // Resize Observer
  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
        // Update canvas resolution
        if (canvasRef.current) {
          canvasRef.current.width = entry.contentRect.width;
          canvasRef.current.height = entry.contentRect.height;
        }
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  // Interactions
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault(); // Prevent page scroll
    
    const { minScale, maxScale } = getConstraints();
    const current = transform.current;
    
    // Zoom factor
    const zoomSensitivity = 0.001;
    const delta = -e.deltaY * zoomSensitivity;
    const factor = Math.exp(delta); 
    
    let newScale = clamp(current.scale * factor, minScale, maxScale);
    
    // Calculate mouse position in virtual space
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    const mouseVirtualX = (mouseX - current.x) / current.scale;
    const mouseVirtualY = (mouseY - current.y) / current.scale;
    
    // Update position to keep mouse over same virtual point
    let newX = mouseX - mouseVirtualX * newScale;
    let newY = mouseY - mouseVirtualY * newScale;

    // Constraint: Don't let image fly off screen completely?
    // usually map viewers allow some panning, but let's keep it simple.
    
    transform.current = { x: newX, y: newY, scale: newScale };
    setTick(t => t + 1);
  }, [getConstraints]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    lastMousePosition.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging.current) return;
    
    const dx = e.clientX - lastMousePosition.current.x;
    const dy = e.clientY - lastMousePosition.current.y;
    
    lastMousePosition.current = { x: e.clientX, y: e.clientY };
    
    transform.current.x += dx;
    transform.current.y += dy;
    // No need to setTick here if using requestAnimationFrame loop, 
    // but if we want to debug coordinate UI, we might need it.
    // drawing is handled by loop.
  }, []);

  const handleMouseUp = useCallback(() => {
    isDragging.current = false;
  }, []);

  const lastTouchDistance = useRef<number | null>(null);
  const lastTouchCenter = useRef<Point | null>(null);

  const getTouchDistance = (touches: React.TouchList) => {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  };

  const getTouchCenter = (touches: React.TouchList) => {
    return {
      x: (touches[0].clientX + touches[1].clientX) / 2,
      y: (touches[0].clientY + touches[1].clientY) / 2,
    };
  };

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      isDragging.current = true;
      lastMousePosition.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    } else if (e.touches.length === 2) {
      isDragging.current = false;
      lastTouchDistance.current = getTouchDistance(e.touches);
      const rect = canvasRef.current?.getBoundingClientRect();
      if(rect) {
         const center = getTouchCenter(e.touches);
         lastTouchCenter.current = { x: center.x - rect.left, y: center.y - rect.top };
      }
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    // Prevent scrolling
    // Note: might need e.preventDefault() in a non-React listener for this to work reliably on some browsers
    // but in React 18+ passive events are default so e.preventDefault might fail. 
    // We will trust the style "touch-none" to handle most browser scroll prevention.
    
    if (e.touches.length === 1 && isDragging.current) {
      const dx = e.touches[0].clientX - lastMousePosition.current.x;
      const dy = e.touches[0].clientY - lastMousePosition.current.y;
      lastMousePosition.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      transform.current.x += dx;
      transform.current.y += dy;
    } else if (e.touches.length === 2) {
      const dist = getTouchDistance(e.touches);
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect || lastTouchDistance.current === null || !lastTouchCenter.current) return;
      
      const { minScale, maxScale } = getConstraints();
      const current = transform.current;
      
      // Calculate Zoom Factor
      const factor = dist / lastTouchDistance.current;
      let newScale = clamp(current.scale * factor, minScale, maxScale);
      
      // Calculate Center in Virtual Space
      // We use the INITIAL center of the pinch as the anchor, or the current center?
      // Usually map apps use the moving center.
      const centerScreen = getTouchCenter(e.touches);
      const centerX = centerScreen.x - rect.left;
      const centerY = centerScreen.y - rect.top;

      // To simplify: Zoom towards the midpoint of fingers
      const mouseVirtualX = (centerX - current.x) / current.scale;
      const mouseVirtualY = (centerY - current.y) / current.scale;

      let newX = centerX - mouseVirtualX * newScale;
      let newY = centerY - mouseVirtualY * newScale;
      
      // Adjust for pan (fingers moving together)
      // actually the above formula handles both zoom and pan relative to the center point!
      
      transform.current = { x: newX, y: newY, scale: newScale };
      lastTouchDistance.current = dist;
      // Update center for next frame? 
      // Ideally we don't update center anchor if we want "zoom to point", 
      // but if we want to allow panning while zooming, we update.
      lastTouchCenter.current = { x: centerX, y: centerY };
      
      setTick(t => t + 1);
    }
  }, [getConstraints]);

  const handleTouchEnd = useCallback(() => {
    isDragging.current = false;
    lastTouchDistance.current = null;
    lastTouchCenter.current = null;
  }, []);

  return (
    <div 
      ref={containerRef} 
      className={`relative overflow-hidden bg-gray-100 w-full h-full ${className}`}
    >
      <canvas
        ref={canvasRef}
        className="block touch-none cursor-move"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      />
      
      {/* Overlay UI */}
      <div className="absolute bottom-4 left-4 bg-black/75 text-white text-xs p-2 rounded pointer-events-none">
        <div>Scale: {(transform.current.scale * 100).toFixed(3)}% (1:{(1/transform.current.scale).toFixed(1)})</div>
        <div>Pos: {transform.current.x.toFixed(0)}, {transform.current.y.toFixed(0)}</div>
        <div>Visible Tiles: {getVisibleTiles({
             x: -transform.current.x / transform.current.scale,
             y: -transform.current.y / transform.current.scale,
             width: containerSize.width / transform.current.scale,
             height: containerSize.height / transform.current.scale
        }, tileSize, { width: imageWidth, height: imageHeight }, transform.current.scale).length}</div>
      </div>
    </div>
  );
};
