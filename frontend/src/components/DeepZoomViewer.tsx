import { useCallback, useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    OpenSeadragon?: {
      (options: Record<string, unknown>): { destroy: () => void; viewport: { goHome: (b: boolean) => void } };
    };
  }
}

interface Props {
  dziUrl?: string | null;
  fallbackUrl: string;
  cacheBust: number;
}

export default function DeepZoomViewer({ dziUrl, fallbackUrl, cacheBust }: Props) {
  const osdHostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<{ destroy: () => void } | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const useOsd = Boolean(dziUrl && window.OpenSeadragon);

  useEffect(() => {
    if (!useOsd || !osdHostRef.current || !window.OpenSeadragon || !dziUrl) return;

    const viewer = window.OpenSeadragon({
      element: osdHostRef.current,
      prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",
      tileSources: `${dziUrl}?v=${cacheBust}`,
      showNavigationControl: true,
      animationTime: 0.4,
      blendTime: 0.1,
      constrainDuringPan: true,
      maxZoomPixelRatio: 3,
      visibilityRatio: 0.5,
      minZoomImageRatio: 0.5,
      defaultZoomLevel: 0,
    });
    viewerRef.current = viewer;

    return () => {
      viewer.destroy();
      viewerRef.current = null;
    };
  }, [useOsd, dziUrl, cacheBust]);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale((s) => Math.min(8, Math.max(0.2, s - e.deltaY * 0.001)));
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
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

  if (useOsd) {
    return (
      <div className="w-full h-full relative bg-neutral-950 rounded overflow-hidden">
        <div ref={osdHostRef} className="w-full h-full" />
        <p className="absolute bottom-2 left-2 text-[10px] text-neutral-500 pointer-events-none">
          OpenSeadragon deep zoom · scroll/pinch to explore
        </p>
      </div>
    );
  }

  return (
    <div
      className="w-full h-full overflow-hidden cursor-grab active:cursor-grabbing bg-neutral-950 rounded relative"
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <button
          type="button"
          className="text-xs px-2 py-1 bg-neutral-800 rounded border border-neutral-600"
          onClick={() => setScale((s) => Math.min(8, s * 1.25))}
        >
          +
        </button>
        <button
          type="button"
          className="text-xs px-2 py-1 bg-neutral-800 rounded border border-neutral-600"
          onClick={() => setScale((s) => Math.max(0.2, s / 1.25))}
        >
          −
        </button>
        <button
          type="button"
          className="text-xs px-2 py-1 bg-neutral-800 rounded border border-neutral-600"
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
          src={`${fallbackUrl}?v=${cacheBust}`}
          alt="Full mosaic"
          className="max-w-none select-none"
          draggable={false}
          style={{ maxHeight: "90vh", maxWidth: "90vw" }}
        />
      </div>
      <p className="absolute bottom-2 left-2 text-[10px] text-neutral-500">
        Scroll to zoom · drag to pan · {Math.round(scale * 100)}%
        {!dziUrl ? " · DZI pyramid pending" : ""}
      </p>
    </div>
  );
}
