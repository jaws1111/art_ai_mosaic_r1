import { TileState } from "../api";

const STATUS_COLOR: Record<string, string> = {
  queued: "bg-neutral-700",
  cloud_generating: "bg-blue-500 animate-pulse",
  cloud_done: "bg-blue-300",
  local_queued: "bg-yellow-600",
  local_processing: "bg-orange-500 animate-pulse",
  composited: "bg-green-500",
  error: "bg-red-500",
};

interface Props {
  tiles: TileState[];
  rows: number;
  cols: number;
}

export default function TileMatrix({ tiles, rows, cols }: Props) {
  const grid: (TileState | undefined)[][] = Array.from({ length: rows }, () =>
    Array(cols).fill(undefined),
  );
  for (const tile of tiles) {
    grid[tile.row][tile.col] = tile;
  }

  return (
    <div
      className="grid gap-0.5 p-2 bg-black/40 rounded border border-neutral-700"
      style={{ gridTemplateColumns: `repeat(${cols}, 1fr)`, width: 200, height: 200 }}
    >
      {grid.flatMap((row, r) =>
        row.map((tile, c) => (
          <div
            key={`${r}-${c}`}
            title={tile ? `${tile.status} (seq ${tile.seq})` : "empty"}
            className={`rounded-sm ${STATUS_COLOR[tile?.status ?? "queued"]}`}
          />
        )),
      )}
    </div>
  );
}
