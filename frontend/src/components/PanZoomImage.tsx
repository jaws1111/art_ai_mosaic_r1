import { useCallback, useRef, useState } from "react";

interface Props {
  url: string;
  cacheBust?: number;
  alt?: string;
  className?: string;
}

/** Lightweight pan/zoom for blueprint and preview images while jobs run. */
export default function PanZoomImage({ url, cacheBust = 0, alt = "Preview", className = "" }: Props) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const src = `${url}${url.includes("?") ? "&" : "?"}v=${cacheBust}`;

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale((s) => Math.min(12, Math.max(0.25, s - e.deltaY * 0.001)));
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    setOffset({
      x: dragRef.current.ox + (e.clientX - dragRef.current.x),
      y: dragRef.current.oy + (e.clientY - dragRef.current.y),
    });
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  return (
    <div
      className={`w-full h-full overflow-hidden cursor-grab active:cursor-grabbing relative ${className}`}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <button
          type="button"
          className="text-xs px-2 py-1 bg-neutral-800/90 rounded border border-neutral-600"
          onClick={() => setScale((s) => Math.min(12, s * 1.2))}
        >
          +
        </button>
        <button
          type="button"
          className="text-xs px-2 py-1 bg-neutral-800/90 rounded border border-neutral-600"
          onClick={() => setScale((s) => Math.max(0.25, s / 1.2))}
        >
          −
        </button>
        <button
          type="button"
          className="text-xs px-2 py-1 bg-neutral-800/90 rounded border border-neutral-600"
          onClick={() => {
            setScale(1);
            setOffset({ x: 0, y: 0 });
          }}
        >
          Reset
        </button>
      </div>
      <div
        className="w-full h-full flex items-center justify-center"
        style={{
          transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          transformOrigin: "center center",
        }}
      >
        <img
          src={src}
          alt={alt}
          className="max-w-none select-none shadow-2xl rounded"
          draggable={false}
          style={{ maxHeight: "85vh", maxWidth: "85vw" }}
        />
      </div>
      <p className="absolute bottom-2 left-2 text-[10px] text-neutral-500 pointer-events-none">
        Scroll to zoom · drag to pan · {Math.round(scale * 100)}%
      </p>
    </div>
  );
}
