import { useCallback, useEffect, useRef, useState } from "react";
import { jobAssetUrl, TileState } from "../api";

const STATUS_BORDER: Record<string, string> = {
  queued: "border-neutral-700",
  cloud_generating: "border-blue-400 animate-pulse",
  cloud_done: "border-blue-300",
  local_queued: "border-yellow-500",
  local_processing: "border-orange-400 animate-pulse",
  composited: "border-green-500",
  error: "border-red-500",
};

interface Props {
  jobId: string;
  tiles: TileState[];
  rows: number;
  cols: number;
  cacheBust: number;
  onSelectTile?: (tile: TileState) => void;
  selectedTile?: TileState | null;
}

const MIN_W = 160;
const MIN_H = 100;
const MAX_W = 640;
const MAX_H = 500;
const DEFAULT_W = 300;

export default function MosaicNavigator({
  jobId,
  tiles,
  rows,
  cols,
  cacheBust,
  onSelectTile,
  selectedTile,
}: Props) {
  const aspect = cols / Math.max(1, rows);

  const [size, setSize] = useState<{ w: number; h: number }>(() => {
    const w = DEFAULT_W;
    const h = Math.round(w / aspect);
    return { w, h: Math.min(h, 400) };
  });

  useEffect(() => {
    setSize((prev) => {
      const h = Math.round(prev.w / aspect);
      return { w: prev.w, h: Math.min(Math.max(h, MIN_H), MAX_H) };
    });
  }, [aspect]);

  const dragRef = useRef<{
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  } | null>(null);

  const onGripPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startW: size.w,
        startH: size.h,
      };
    },
    [size],
  );

  const onGripPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      const newW = Math.min(MAX_W, Math.max(MIN_W, dragRef.current.startW + dx));
      const newH = Math.min(MAX_H, Math.max(MIN_H, dragRef.current.startH + dy));
      setSize({ w: newW, h: newH });
    },
    [],
  );

  const onGripPointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const grid: (TileState | undefined)[][] = Array.from({ length: rows }, () =>
    Array(cols).fill(undefined),
  );
  for (const tile of tiles) {
    if (tile.row < rows && tile.col < cols) {
      grid[tile.row][tile.col] = tile;
    }
  }

  const activeCount = tiles.filter(
    (t) => t.status === "cloud_generating" || t.status === "local_processing",
  ).length;

  return (
    <div
      className="bg-black/75 backdrop-blur-sm rounded-lg border border-neutral-700 shadow-2xl overflow-hidden select-none"
      style={{ width: size.w }}
    >
      {/* header */}
      <div className="px-2 py-1.5 flex items-center justify-between border-b border-neutral-800">
        <span className="text-[10px] text-neutral-400 uppercase tracking-widest font-semibold">
          Mosaic navigator
        </span>
        <span className="text-[10px] text-neutral-500">
          {rows}×{cols}
          {activeCount > 0 && (
            <span className="ml-1.5 text-blue-400 animate-pulse">
              {activeCount} active
            </span>
          )}
        </span>
      </div>

      {/* tile grid */}
      <div
        className="grid gap-px bg-neutral-800"
        style={{
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          height: size.h,
        }}
      >
        {grid.flatMap((rowArr, r) =>
          rowArr.map((tile, c) => {
            const thumbUrl =
              tile?.tile_path &&
              tile.status !== "queued" &&
              tile.status !== "cloud_generating"
                ? `${jobAssetUrl(jobId, tile.tile_path)}?v=${cacheBust}`
                : null;
            const isSelected = selectedTile?.row === r && selectedTile?.col === c;

            return (
              <button
                key={`${r}-${c}`}
                type="button"
                disabled={!tile}
                onClick={() => tile && onSelectTile?.(tile)}
                title={
                  tile
                    ? `r${r}c${c} · ${tile.status}${tile.seq ? ` · #${tile.seq}` : ""}`
                    : "empty"
                }
                className={[
                  "relative overflow-hidden border transition-[border-color]",
                  tile ? STATUS_BORDER[tile.status] : "border-neutral-800",
                  isSelected ? "ring-2 ring-accent ring-offset-1 ring-offset-black" : "",
                  "bg-neutral-900 min-w-0 min-h-0",
                ].join(" ")}
              >
                {thumbUrl ? (
                  <img
                    src={thumbUrl}
                    alt={`tile r${r}c${c}`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div
                    className={`w-full h-full ${
                      tile?.status === "cloud_generating"
                        ? "bg-blue-900/50"
                        : tile?.status === "local_processing"
                          ? "bg-orange-900/40"
                          : tile?.status === "queued"
                            ? "bg-neutral-800"
                            : "bg-neutral-900"
                    }`}
                  />
                )}
                {(tile?.status === "cloud_generating" || tile?.status === "local_processing") && (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div
                      className={`w-2 h-2 rounded-full animate-ping ${
                        tile.status === "cloud_generating" ? "bg-blue-400" : "bg-orange-400"
                      }`}
                    />
                  </div>
                )}
                {isSelected && (
                  <div className="absolute inset-0 ring-2 ring-inset ring-accent pointer-events-none" />
                )}
              </button>
            );
          }),
        )}
      </div>

      {/* resize grip */}
      <div
        className="h-3 flex items-center justify-center cursor-se-resize bg-neutral-900/60 hover:bg-neutral-800/80 transition-colors border-t border-neutral-800"
        onPointerDown={onGripPointerDown}
        onPointerMove={onGripPointerMove}
        onPointerUp={onGripPointerUp}
        onPointerLeave={onGripPointerUp}
        title="Drag to resize"
      >
        <svg width="16" height="6" viewBox="0 0 16 6" className="text-neutral-600" fill="currentColor">
          <rect x="0" y="0" width="16" height="1.5" rx="1" />
          <rect x="0" y="4" width="16" height="1.5" rx="1" />
        </svg>
      </div>
    </div>
  );
}
