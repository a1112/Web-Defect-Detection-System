import React, { useCallback } from 'react';
import { LargeImageViewer } from './components/LargeImageViewer/LargeImageViewer';
import { Tile } from './components/LargeImageViewer/utils';

export default function App() {
  // Image Dimensions: 160,000 x 16,000 as requested
  const IMAGE_WIDTH = 160000;
  const IMAGE_HEIGHT = 16000;
  const TILE_SIZE = 512;

  // Custom Tile Renderer
  const renderTile = useCallback((
    ctx: CanvasRenderingContext2D,
    tile: Tile,
    tileSize: number,
    scale: number
  ) => {
    // The tile passed here has width/height corresponding to its Virtual Size (in original image coords)
    // tile.width = tileSize * 2^level
    
    // 1. Draw Tile Background
    // Use different shades for different levels to visualize LOD
    // Level 0 = Light, Level 5 = Darker
    const hue = (tile.level * 30) % 360;
    const isEven = (tile.row + tile.col) % 2 === 0;
    
    ctx.fillStyle = `hsla(${hue}, 50%, ${isEven ? 90 : 85}%, 1)`;
    ctx.fillRect(tile.x, tile.y, tile.width, tile.height);

    // 2. Draw Border
    ctx.strokeStyle = `hsla(${hue}, 50%, 40%, 0.5)`;
    ctx.lineWidth = 1 / scale; // 1px on screen
    ctx.strokeRect(tile.x, tile.y, tile.width, tile.height);
    
    // Edge case highlighting: if width/height is different from standard, it's an edge tile
    if (tile.width !== tile.height || (tile.width !== tileSize * Math.pow(2, tile.level) && tile.level === 0)) {
         // Just checking if it's non-square is a quick heuristic, 
         // but strictly speaking edge tiles can be square if remainder matches.
         // Better: check against standard size
         const standardSize = tileSize * Math.pow(2, tile.level);
         if (tile.width < standardSize || tile.height < standardSize) {
             ctx.fillStyle = 'rgba(255, 0, 0, 0.1)';
             ctx.fillRect(tile.x, tile.y, tile.width, tile.height);
             ctx.strokeStyle = 'red';
             ctx.strokeRect(tile.x, tile.y, tile.width, tile.height);
         }
    }

    // 3. Draw Text
    // We only want to draw text if it fits comfortably
    // Screen size of this tile is roughly 'tileSize' (e.g. 512px) mostly, 
    // but can vary between 0.5*tileSize and 1.0*tileSize depending on exact zoom.
    
    ctx.save();
    ctx.translate(tile.x, tile.y);
    const textScale = 1 / scale;
    ctx.scale(textScale, textScale);
    
    ctx.fillStyle = '#333';
    ctx.font = 'bold 14px Inter, sans-serif';
    ctx.fillText(`LOD ${tile.level}`, 10, 24);
    
    ctx.font = '12px Inter, sans-serif';
    ctx.fillStyle = '#555';
    ctx.fillText(`Row: ${tile.row}, Col: ${tile.col}`, 10, 42);
    ctx.fillText(`${tile.width}x${tile.height}px (Virtual)`, 10, 58);
    
    ctx.restore();
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col bg-white font-sans text-slate-900">
      <header className="h-14 border-b px-4 flex items-center justify-between shrink-0 z-10 bg-white/80 backdrop-blur">
        <div className="flex items-center gap-2">
          <div className="size-6 rounded bg-blue-600"></div>
          <h1 className="font-semibold text-sm">GigaPixel Viewer</h1>
        </div>
        <div className="text-xs text-slate-500">
          {IMAGE_WIDTH.toLocaleString()} x {IMAGE_HEIGHT.toLocaleString()} px
        </div>
      </header>
      
      <main className="flex-1 relative overflow-hidden">
        <LargeImageViewer
          imageWidth={IMAGE_WIDTH}
          imageHeight={IMAGE_HEIGHT}
          tileSize={TILE_SIZE}
          renderTile={renderTile}
          className="bg-slate-50"
        />
        
        {/* Floating Instructions */}
        <div className="absolute top-4 right-4 w-64 bg-white/90 backdrop-blur shadow-lg rounded-lg p-4 border text-sm pointer-events-none">
          <h3 className="font-medium mb-2">Controls</h3>
          <ul className="space-y-1 text-slate-600 list-disc pl-4">
            <li>Scroll / Pinch to Zoom</li>
            <li>Drag to Pan</li>
            <li><b>LOD Enabled</b>: Tile size changes with zoom</li>
          </ul>
        </div>
      </main>
    </div>
  );
}
