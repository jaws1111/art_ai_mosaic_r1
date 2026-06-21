import { useCallback, useRef, useState } from "react";

export interface PromptRegion {
  id: string;
  label?: string;
  prompt: string;
  x: number;
  y: number;
  w: number;
  h: number;
  color?: string;
}

const PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#06b6d4"];

interface Props {
  width: number;
  height: number;
  regions: PromptRegion[];
  onChange: (regions: PromptRegion[]) => void;
}

export default function RegionLayoutEditor({ width, height, regions, onChange }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const dragRef = useRef<{
    mode: "create" | "move";
    id?: string;
    startX: number;
    startY: number;
    orig?: PromptRegion;
  } | null>(null);

  const aspect = width / height;

  const toNorm = useCallback((clientX: number, clientY: number) => {
    const box = boxRef.current;
    if (!box) return { x: 0, y: 0 };
    const rect = box.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (clientY - rect.top) / rect.height)),
    };
  }, []);

  function addRegion(x: number, y: number, w: number, h: number) {
    const id = `r${Date.now().toString(36)}`;
    const color = PALETTE[regions.length % PALETTE.length];
    const next: PromptRegion = {
      id,
      label: `Zone ${regions.length + 1}`,
      prompt: "",
      x,
      y,
      w,
      h,
      color,
    };
    onChange([...regions, next]);
    setSelectedId(id);
  }

  function onPointerDown(e: React.PointerEvent) {
    if ((e.target as HTMLElement).dataset.regionId) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const { x, y } = toNorm(e.clientX, e.clientY);
    dragRef.current = { mode: "create", startX: x, startY: y };
    setDraft(null);
  }

  function onRegionPointerDown(e: React.PointerEvent, region: PromptRegion) {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setSelectedId(region.id);
    dragRef.current = {
      mode: "move",
      id: region.id,
      startX: e.clientX,
      startY: e.clientY,
      orig: { ...region },
    };
  }

  function onPointerMove(e: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag) return;

    if (drag.mode === "create") {
      const { x, y } = toNorm(e.clientX, e.clientY);
      const rx = Math.min(drag.startX, x);
      const ry = Math.min(drag.startY, y);
      const rw = Math.abs(x - drag.startX);
      const rh = Math.abs(y - drag.startY);
      setDraft({ x: rx, y: ry, w: rw, h: rh });
    } else if (drag.mode === "move" && drag.orig && drag.id) {
      const box = boxRef.current;
      if (!box) return;
      const rect = box.getBoundingClientRect();
      const dx = (e.clientX - drag.startX) / rect.width;
      const dy = (e.clientY - drag.startY) / rect.height;
      onChange(
        regions.map((r) =>
          r.id === drag.id
            ? {
                ...r,
                x: Math.max(0, Math.min(1 - r.w, drag.orig!.x + dx)),
                y: Math.max(0, Math.min(1 - r.h, drag.orig!.y + dy)),
              }
            : r,
        ),
      );
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag) return;

    if (drag.mode === "create") {
      const { x, y } = toNorm(e.clientX, e.clientY);
      const rx = Math.min(drag.startX, x);
      const ry = Math.min(drag.startY, y);
      const rw = Math.abs(x - drag.startX);
      const rh = Math.abs(y - drag.startY);
      if (rw >= 0.05 && rh >= 0.05) {
        addRegion(rx, ry, rw, rh);
      }
      setDraft(null);
    }
    dragRef.current = null;
  }

  const selected = regions.find((r) => r.id === selectedId);

  function updateSelected(field: keyof PromptRegion, value: string) {
    if (!selectedId) return;
    onChange(regions.map((r) => (r.id === selectedId ? { ...r, [field]: value } : r)));
  }

  function removeSelected() {
    if (!selectedId) return;
    onChange(regions.filter((r) => r.id !== selectedId));
    setSelectedId(null);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm text-neutral-300">Regional layout</label>
        <span className="text-[10px] text-neutral-500">Drag to draw zones</span>
      </div>

      <div
        ref={boxRef}
        className="relative w-full bg-neutral-900 border border-neutral-700 rounded cursor-crosshair touch-none"
        style={{ aspectRatio: String(aspect), maxHeight: 220 }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {regions.map((r) => (
          <div
            key={r.id}
            data-region-id={r.id}
            className={`absolute border-2 rounded-sm cursor-move ${
              selectedId === r.id ? "ring-2 ring-white/50" : ""
            }`}
            style={{
              left: `${r.x * 100}%`,
              top: `${r.y * 100}%`,
              width: `${r.w * 100}%`,
              height: `${r.h * 100}%`,
              backgroundColor: `${r.color ?? "#3b82f6"}33`,
              borderColor: r.color ?? "#3b82f6",
            }}
            onPointerDown={(e) => onRegionPointerDown(e, r)}
          >
            <span className="absolute top-0 left-0 text-[9px] px-1 bg-black/60 truncate max-w-full">
              {r.label || r.id}
            </span>
          </div>
        ))}
        {draft && draft.w > 0.02 && draft.h > 0.02 && (
          <div
            className="absolute border-2 border-dashed border-blue-400/80 bg-blue-500/10 pointer-events-none"
            style={{
              left: `${draft.x * 100}%`,
              top: `${draft.y * 100}%`,
              width: `${draft.w * 100}%`,
              height: `${draft.h * 100}%`,
            }}
          />
        )}
      </div>

      {selected && (
        <div className="space-y-2 p-2 rounded border border-neutral-700 bg-neutral-900/80">
          <input
            className="w-full text-xs bg-neutral-950 border border-neutral-700 rounded px-2 py-1"
            placeholder="Zone label"
            value={selected.label}
            onChange={(e) => updateSelected("label", e.target.value)}
          />
          <textarea
            className="w-full h-16 text-xs bg-neutral-950 border border-neutral-700 rounded px-2 py-1"
            placeholder="Prompt for this zone…"
            value={selected.prompt}
            onChange={(e) => updateSelected("prompt", e.target.value)}
          />
          <button
            type="button"
            onClick={removeSelected}
            className="text-xs text-red-400 hover:text-red-300"
          >
            Remove zone
          </button>
        </div>
      )}

      {regions.length > 0 && !selected && (
        <p className="text-[10px] text-neutral-500">Click a zone to edit its prompt</p>
      )}
    </div>
  );
}
