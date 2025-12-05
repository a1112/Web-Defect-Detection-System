export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
export type Rect = { x: number; y: number; width: number; height: number };

export interface Tile {
  level: number;
  row: number;
  col: number;
  x: number;      // Virtual X coordinate (Original Image)
  y: number;      // Virtual Y coordinate (Original Image)
  width: number;  // Virtual Width (Original Image)
  height: number; // Virtual Height (Original Image)
}

export const clamp = (val: number, min: number, max: number) => Math.min(Math.max(val, min), max);

export const getVisibleTiles = (
  viewRect: Rect, // The visible area in VIRTUAL coordinates
  tileSize: number, // The base tile size (e.g. 256)
  imageSize: Size,
  currentScale: number
): Tile[] => {
  
  let level = Math.floor(Math.log2(1 / currentScale));
  level = Math.max(0, level);
  
  const virtualTileSize = tileSize * Math.pow(2, level);

  const startCol = Math.floor(Math.max(0, viewRect.x) / virtualTileSize);
  const startRow = Math.floor(Math.max(0, viewRect.y) / virtualTileSize);
  
  // Calculate the maximum number of columns and rows for this level
  // Use ceil to ensure the last partial tile is included
  const maxCols = Math.ceil(imageSize.width / virtualTileSize);
  const maxRows = Math.ceil(imageSize.height / virtualTileSize);

  // Determine the end column/row based on the view rectangle, but clamp to the image boundaries
  // Note: The original logic for endCol was slightly flawed for edge cases. 
  // We want to iterate up to the tile that *intersects* the view end.
  const viewEndCol = Math.floor((viewRect.x + viewRect.width) / virtualTileSize);
  const viewEndRow = Math.floor((viewRect.y + viewRect.height) / virtualTileSize);

  const endCol = Math.min(maxCols - 1, viewEndCol);
  const endRow = Math.min(maxRows - 1, viewEndRow);

  const tiles: Tile[] = [];
  for (let row = startRow; row <= endRow; row++) {
    for (let col = startCol; col <= endCol; col++) {
      // Calculate standard tile position
      const x = col * virtualTileSize;
      const y = row * virtualTileSize;
      
      // Handle Edge Tiles: If this is the last column or row, it might be smaller (rectangular)
      // "适配好边部（基本整除）" - means the edge tiles should fit exactly to the image size
      // If x + virtualTileSize > imageSize.width, width = imageSize.width - x
      const width = (col === maxCols - 1) 
        ? imageSize.width - x 
        : virtualTileSize;
        
      const height = (row === maxRows - 1) 
        ? imageSize.height - y 
        : virtualTileSize;

      tiles.push({ 
        level, 
        row, 
        col, 
        x, 
        y,
        width,
        height
      });
    }
  }
  return tiles;
};
