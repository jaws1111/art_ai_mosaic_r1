import { useEffect, useRef, useState } from "react";
import { ActivityEvent } from "../api";

const CATEGORY_STYLE: Record<string, string> = {
  system: "text-neutral-300",
  xai: "text-blue-400",
  cpu: "text-amber-400",
  gpu: "text-emerald-400",
  network: "text-violet-400",
};

interface Props {
  events: ActivityEvent[];
  defaultCollapsed?: boolean;
  /** When true, always expanded and fills available height (Activity tab). */
  fullHeight?: boolean;
}

export default function ActivityFeed({ events, defaultCollapsed = false, fullHeight = false }: Props) {
  const [collapsed, setCollapsed] = useState(fullHeight ? false : defaultCollapsed);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!collapsed) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events.length, collapsed]);

  return (
    <div className="flex flex-col h-full min-h-0 bg-neutral-950/80">
      {!fullHeight && (
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="px-3 py-2 text-xs font-semibold text-neutral-400 uppercase tracking-wide border-b border-neutral-800 flex items-center justify-between hover:bg-neutral-900/80 w-full text-left"
        >
          <span>Activity log ({events.length})</span>
          <span className="text-neutral-500 normal-case">{collapsed ? "Show" : "Hide"}</span>
        </button>
      )}
      {fullHeight && (
        <div className="px-3 py-2 text-xs font-semibold text-neutral-400 uppercase tracking-wide border-b border-neutral-800 flex items-center gap-2">
          <span>Activity log</span>
          <span className="text-neutral-600 font-normal">{events.length} events</span>
        </div>
      )}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[11px] space-y-1 min-h-0">
          {events.length === 0 && (
            <p className="text-neutral-600">Waiting for pipeline events…</p>
          )}
          {events.map((ev, i) => (
            <div key={`${ev.ts}-${i}`} className="leading-relaxed">
              <span className="text-neutral-600">[{ev.ts.toFixed(1)}s]</span>{" "}
              <span className={CATEGORY_STYLE[ev.category] ?? "text-neutral-400"}>
                [{ev.category}]
              </span>{" "}
              <span className="text-neutral-200">{ev.message}</span>
              {ev.detail && (
                <span className="text-neutral-500 block pl-4 truncate" title={ev.detail}>
                  {ev.detail}
                </span>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
