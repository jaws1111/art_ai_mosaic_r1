import { useEffect, useRef, useState } from "react";
import {
  createJob,
  connectProgress,
  JobProgress,
  MosaicJobCreate,
  PlanPreview,
  PromptRegion,
  previewPlan,
} from "./api";
import MissionControl, { ViewMode } from "./components/MissionControl";
import RegionLayoutEditor from "./components/RegionLayoutEditor";
import PromptLibrary from "./components/PromptLibrary";

// ── types ────────────────────────────────────────────────────────────────────
type CanvasMode = "standard" | "panorama_h" | "panorama_v" | "spherical";

interface Preset {
  label: string;
  sub: string;
  width: number;
  height: number;
  mode: CanvasMode;
}

// ── constants ─────────────────────────────────────────────────────────────────
const PRESETS: Preset[] = [
  { label: "512 test",      sub: "direct",     width: 512,   height: 512,  mode: "standard"   },
  { label: "1K tile",       sub: "1×1",        width: 1024,  height: 1024, mode: "standard"   },
  { label: "3×3 5K",        sub: "5120px",     width: 5120,  height: 5120, mode: "standard"   },
  { label: "10K sq",        sub: "square",     width: 10000, height: 10000, mode: "standard"  },
  { label: "16:9 16K",      sub: "landscape",  width: 16000, height: 9000, mode: "standard"   },
  { label: "32:9 ultra",    sub: "ultrawide",  width: 21300, height: 6000, mode: "standard"   },
  { label: "Pano 8K×2K",   sub: "h-wrap",     width: 8192,  height: 2048, mode: "panorama_h" },
  { label: "Pano 2K×8K",   sub: "v-wrap",     width: 2048,  height: 8192, mode: "panorama_v" },
];

const CANVAS_MODES: { value: CanvasMode; label: string }[] = [
  { value: "standard",   label: "Standard" },
  { value: "panorama_h", label: "360° Horizontal" },
  { value: "panorama_v", label: "360° Vertical" },
  { value: "spherical",  label: "Spherical (H+V)" },
];

const MODE_COLOR: Record<string, string> = {
  mosaic:           "text-blue-400 bg-blue-950/60 border-blue-800",
  single_enhanced:  "text-amber-400 bg-amber-950/60 border-amber-800",
  blueprint_direct: "text-emerald-400 bg-emerald-950/60 border-emerald-800",
};

// ── section wrapper ───────────────────────────────────────────────────────────
function Section({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-neutral-500">
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}

// ── field wrapper ─────────────────────────────────────────────────────────────
const inputCls =
  "w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40 transition-colors";
const selectCls =
  "w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:border-accent transition-colors appearance-none";

// ── plan preview badge ────────────────────────────────────────────────────────
function CropQualityBar({ ratio }: { ratio: number }) {
  // Sweet spot ≤ 1.30 (green), marginal ≤ 2.0 (amber), poor > 2.0 (red)
  const pct = Math.min(100, Math.round((ratio - 1) / (3 - 1) * 100));
  const color = ratio <= 1.3 ? "bg-emerald-500" : ratio <= 2.0 ? "bg-amber-500" : "bg-red-500";
  const label = ratio <= 1.3 ? "detail quality: excellent" : ratio <= 2.0 ? "detail quality: marginal" : "detail quality: poor";
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-[9px]">
        <span className={ratio <= 1.3 ? "text-emerald-400" : ratio <= 2.0 ? "text-amber-400" : "text-red-400"}>
          {label}
        </span>
        <span className="text-neutral-500">{ratio.toFixed(1)}× crop→tile</span>
      </div>
      <div className="h-1 rounded-full bg-neutral-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function PlanBadge({ plan, mode }: { plan: PlanPreview; mode: CanvasMode }) {
  const key = plan.generation_mode.replace(/_/g, " ");
  const cls = MODE_COLOR[plan.generation_mode] ?? "text-neutral-400 bg-neutral-800 border-neutral-700";
  return (
    <div className={`rounded-lg border p-3 space-y-2 ${cls}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold capitalize">{key}</span>
        <span className="text-[10px] opacity-70">
          {plan.width_px}×{plan.height_px}
        </span>
      </div>
      <p className="text-[10px] leading-snug opacity-80">{plan.strategy_message}</p>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] opacity-70">
        <span>~{plan.est_cloud_calls} API call{plan.est_cloud_calls !== 1 ? "s" : ""}</span>
        <span>est. ${plan.est_cost_usd.toFixed(2)}</span>
        {plan.use_mosaic_stitch && (
          <span>{plan.rows}×{plan.cols} grid</span>
        )}
        {!plan.use_mosaic_stitch && plan.local_upscale_factor > 1 && (
          <span>local {plan.local_upscale_factor}×</span>
        )}
        {mode !== "standard" && (
          <span className="text-amber-300">↻ wrap</span>
        )}
      </div>
      {plan.use_mosaic_stitch && (
        <CropQualityBar ratio={plan.crop_upscale_ratio ?? 1} />
      )}
      {plan.crop_quality_warning && (
        <p className="text-[9px] text-amber-400 leading-snug border-t border-amber-900/40 pt-1.5">
          ⚠ {plan.crop_quality_warning}
        </p>
      )}
    </div>
  );
}

// ── main app ─────────────────────────────────────────────────────────────────
export default function App() {
  const [prompt, setPrompt] = useState(
    "A vast alpine valley at golden hour with a winding river, pine forests, distant snow peaks.",
  );
  const [styleAnchor, setStyleAnchor] = useState("cinematic, photorealistic, 8K detail,");
  const [width, setWidth] = useState(5120);
  const [height, setHeight] = useState(5120);
  const [showLibrary, setShowLibrary] = useState(false);
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("standard");
  const [upscaleFactor, setUpscaleFactor] = useState(2);
  const [maxConcurrency, setMaxConcurrency] = useState(2);
  const [maxBlueprintCrops, setMaxBlueprintCrops] = useState(3);
  const [useRegions, setUseRegions] = useState(false);
  const [regions, setRegions] = useState<PromptRegion[]>([]);
  const [runQualityCheck, setRunQualityCheck] = useState(false);
  const [includeAiCritique, setIncludeAiCritique] = useState(false);
  const [locked, setLocked] = useState(false);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("live");
  const [planPreview, setPlanPreview] = useState<PlanPreview | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => () => { wsRef.current?.close(); }, []);

  useEffect(() => {
    if (locked) return;
    const timer = window.setTimeout(async () => {
      if (width <= 0 || height <= 0) { setPlanPreview(null); return; }
      try {
        const plan = await previewPlan({
          canvas: { width_px: width, height_px: height, mode: canvasMode, aspect_label: "custom", wraparound: canvasMode !== "standard" },
          upscale_factor: upscaleFactor,
        });
        setPlanPreview(plan);
      } catch { setPlanPreview(null); }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [width, height, canvasMode, upscaleFactor, locked]);

  function newJob() {
    wsRef.current?.close();
    wsRef.current = null;
    setProgress(null);
    setLocked(false);
    setViewMode("live");
  }

  async function startJob() {
    const activeRegions = useRegions ? regions.filter((r) => r.prompt.trim().length >= 3) : [];
    if (useRegions && activeRegions.length === 0) {
      alert("Add at least one zone with a prompt (3+ chars), or disable regional mode.");
      return;
    }
    setBusy(true);
    setLocked(true);
    setViewMode("live");
    const body: MosaicJobCreate = {
      prompt,
      style_anchor: styleAnchor.trim() || undefined,
      canvas: { width_px: width, height_px: height, mode: canvasMode, aspect_label: "custom", wraparound: canvasMode !== "standard" },
      regions: activeRegions,
      run_quality_check: runQualityCheck,
      include_ai_critique: includeAiCritique,
      upscale_factor: upscaleFactor,
      max_concurrency: maxConcurrency,
      max_blueprint_crops: maxBlueprintCrops,
    };
    try {
      const job = await createJob(body);
      setProgress(job);
      wsRef.current?.close();
      wsRef.current = connectProgress(job.job_id, setProgress);
    } catch (err) {
      alert(String(err));
      setLocked(false);
    } finally {
      setBusy(false);
    }
  }

  // ── locked sidebar (job running) ──────────────────────────────────────────
  if (locked && progress) {
    return (
      <div className="h-screen flex bg-neutral-950">
        <aside className="w-52 shrink-0 border-r border-neutral-800 flex flex-col bg-[#12141a]">
          <div className="px-4 py-4 border-b border-neutral-800">
            <p className="text-sm font-semibold text-neutral-100 truncate">
              {progress.display_name || progress.job_id.slice(0, 8)}
            </p>
            <p className="text-[10px] text-neutral-500 mt-0.5">
              {width}×{height} · {canvasMode}
            </p>
            {progress.generation_mode && (
              <p className="text-[10px] text-blue-400 mt-1 capitalize">
                {progress.generation_mode.replace(/_/g, " ")}
              </p>
            )}
          </div>

          <div className="px-4 py-3 flex-1 overflow-y-auto">
            <p className="text-[10px] text-neutral-600 uppercase tracking-wider mb-1">Style</p>
            {styleAnchor && (
              <p className="text-[11px] text-neutral-500 mb-2 line-clamp-2">{styleAnchor}</p>
            )}
            <p className="text-[10px] text-neutral-600 uppercase tracking-wider mb-1">Prompt</p>
            <p className="text-xs text-neutral-400 leading-relaxed line-clamp-6">{prompt}</p>
          </div>

          {(progress.status === "complete" || progress.status === "failed") && (
            <div className="px-4 pb-4">
              <button
                type="button"
                onClick={newJob}
                className="w-full py-2 text-sm rounded-md border border-neutral-600 hover:bg-neutral-800 text-neutral-200 transition-colors"
              >
                ← New job
              </button>
            </div>
          )}
        </aside>

        <MissionControl
          progress={progress}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          onNewJob={newJob}
          onProgressUpdate={setProgress}
        />
      </div>
    );
  }

  // ── setup sidebar ─────────────────────────────────────────────────────────
  return (
    <div className="h-screen flex bg-neutral-950">
      <aside className="w-80 shrink-0 border-r border-neutral-800 bg-[#12141a] flex flex-col min-h-0">

        {/* logo */}
        <div className="px-5 py-4 border-b border-neutral-800/70 shrink-0">
          <h1 className="text-base font-bold tracking-tight text-white">Tessera</h1>
          <p className="text-[10px] text-neutral-500 mt-0.5 tracking-wide">Multi-megapixel mosaic engine</p>
        </div>

        {/* scrollable form body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 min-h-0">

          {/* PROMPT */}
          <Section
            title="Prompt"
            action={
              <button
                type="button"
                onClick={() => setShowLibrary(true)}
                className="text-[10px] px-2 py-0.5 rounded border border-neutral-700 text-neutral-500 hover:border-accent hover:text-accent transition-colors"
              >
                Library
              </button>
            }
          >
            <textarea
              className={`${inputCls} resize-none`}
              rows={5}
              placeholder="Describe your scene in detail…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-neutral-600">Master scene description</span>
              <span className={`text-[10px] ${prompt.length > 400 ? "text-amber-400" : "text-neutral-600"}`}>
                {prompt.length} chars
              </span>
            </div>
          </Section>

          {showLibrary && (
            <PromptLibrary
              onSelect={(p) => { setPrompt(p.prompt); setStyleAnchor(p.style); setShowLibrary(false); }}
              onClose={() => setShowLibrary(false)}
            />
          )}

          {/* STYLE */}
          <Section title="Style anchor">
            <input
              type="text"
              className={inputCls}
              placeholder="e.g. cinematic, photorealistic, 8K detail,"
              value={styleAnchor}
              onChange={(e) => setStyleAnchor(e.target.value)}
            />
            <p className="text-[10px] text-neutral-600">Prepended to every tile prompt</p>
          </Section>

          {/* CANVAS */}
          <Section title="Canvas">
            {/* mode */}
            <div className="relative">
              <select
                className={selectCls}
                value={canvasMode}
                onChange={(e) => setCanvasMode(e.target.value as CanvasMode)}
              >
                {CANVAS_MODES.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-neutral-500 text-xs">▾</span>
            </div>

            {/* presets grid */}
            <div className="grid grid-cols-2 gap-1.5">
              {PRESETS.map((p) => {
                const active = width === p.width && height === p.height && canvasMode === p.mode;
                return (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => { setWidth(p.width); setHeight(p.height); setCanvasMode(p.mode); }}
                    className={[
                      "text-left px-2.5 py-2 rounded-md border text-xs transition-colors",
                      active
                        ? "bg-accent/20 border-accent text-white"
                        : "bg-neutral-900 border-neutral-700 text-neutral-400 hover:border-neutral-500 hover:text-neutral-200",
                    ].join(" ")}
                  >
                    <span className="font-medium block">{p.label}</span>
                    <span className="text-[9px] opacity-60">{p.sub}</span>
                  </button>
                );
              })}
            </div>

            {/* custom dimensions */}
            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1">
                <span className="text-[10px] text-neutral-500">Width px</span>
                <input
                  type="number"
                  className={inputCls}
                  value={width}
                  min={64}
                  onChange={(e) => setWidth(Number(e.target.value))}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] text-neutral-500">Height px</span>
                <input
                  type="number"
                  className={inputCls}
                  value={height}
                  min={64}
                  onChange={(e) => setHeight(Number(e.target.value))}
                />
              </label>
            </div>

            {/* plan preview */}
            {planPreview && <PlanBadge plan={planPreview} mode={canvasMode} />}
          </Section>

          {/* GENERATION */}
          <Section title="Generation">
            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1">
                <span className="text-[10px] text-neutral-500">Upscale factor</span>
                <select
                  className={selectCls}
                  value={upscaleFactor}
                  onChange={(e) => setUpscaleFactor(Number(e.target.value))}
                >
                  {[1, 2, 4].map((v) => (
                    <option key={v} value={v}>{v}×{v === 1 ? " (cloud native)" : ""}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-[10px] text-neutral-500">Concurrency</span>
                <select
                  className={selectCls}
                  value={maxConcurrency}
                  onChange={(e) => setMaxConcurrency(Number(e.target.value))}
                >
                  {[1, 2, 3].map((v) => (
                    <option key={v} value={v}>{v} tile{v > 1 ? "s" : ""} at once</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="space-y-1">
              <span className="text-[10px] text-neutral-500">Blueprint crops per tile</span>
              <div className="flex gap-1.5">
                {[
                  { v: 1, label: "1 — own crop only" },
                  { v: 2, label: "2 — + left context" },
                  { v: 3, label: "3 — + left + top" },
                ].map(({ v, label }) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setMaxBlueprintCrops(v)}
                    className={[
                      "flex-1 py-1.5 text-[10px] rounded border transition-colors",
                      maxBlueprintCrops === v
                        ? "bg-accent/20 border-accent text-accent"
                        : "bg-neutral-900 border-neutral-700 text-neutral-500 hover:border-neutral-500 hover:text-neutral-300",
                    ].join(" ")}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="text-[9px] text-neutral-600">
                Neighbouring blueprint crops give xAI edge-matching context (xAI limit: 3 images).
              </p>
            </label>
          </Section>

          {/* REGIONS */}
          <Section
            title="Regional prompts"
            action={
              <button
                type="button"
                onClick={() => setUseRegions((v) => !v)}
                className={[
                  "text-[10px] px-2 py-0.5 rounded border transition-colors",
                  useRegions
                    ? "bg-accent/20 border-accent text-accent"
                    : "border-neutral-700 text-neutral-500 hover:border-neutral-500",
                ].join(" ")}
              >
                {useRegions ? "on" : "off"}
              </button>
            }
          >
            {useRegions ? (
              <RegionLayoutEditor
                width={width}
                height={height}
                regions={regions}
                onChange={setRegions}
              />
            ) : (
              <p className="text-[10px] text-neutral-600">
                Enable to paint per-zone prompts over the canvas.
              </p>
            )}
          </Section>

          {/* QUALITY */}
          <Section title="After completion">
            <label className="flex items-start gap-2.5 cursor-pointer group">
              <input
                type="checkbox"
                checked={runQualityCheck}
                onChange={(e) => setRunQualityCheck(e.target.checked)}
                className="mt-0.5 accent-blue-500"
              />
              <span className="text-xs text-neutral-400 group-hover:text-neutral-200 transition-colors leading-snug">
                Blueprint fidelity check
                <span className="block text-[10px] text-neutral-600">SSIM · edges · comparison images</span>
              </span>
            </label>
            <label className={[
              "flex items-start gap-2.5 cursor-pointer group ml-5",
              !runQualityCheck ? "opacity-40 pointer-events-none" : "",
            ].join(" ")}>
              <input
                type="checkbox"
                checked={includeAiCritique}
                disabled={!runQualityCheck}
                onChange={(e) => setIncludeAiCritique(e.target.checked)}
                className="mt-0.5 accent-blue-500"
              />
              <span className="text-xs text-neutral-400 group-hover:text-neutral-200 transition-colors leading-snug">
                xAI vision critique
                <span className="block text-[10px] text-neutral-600">Strict scoring + SCALE field</span>
              </span>
            </label>
          </Section>

        </div>

        {/* generate button — sticky footer */}
        <div className="px-5 py-4 border-t border-neutral-800 bg-[#12141a] shrink-0">
          {planPreview && (
            <p className="text-[10px] text-neutral-500 mb-2 text-center">
              ~{planPreview.est_cloud_calls} API call{planPreview.est_cloud_calls !== 1 ? "s" : ""} · est. ${planPreview.est_cost_usd.toFixed(2)}
            </p>
          )}
          <button
            type="button"
            disabled={busy || prompt.trim().length < 10}
            onClick={startJob}
            className="w-full py-2.5 rounded-md font-semibold text-sm bg-accent hover:bg-blue-500 active:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors shadow-lg shadow-accent/20"
          >
            {busy ? "Starting…" : "Generate Mosaic"}
          </button>
        </div>
      </aside>

      {/* right: placeholder when no job */}
      <main className="flex-1 flex items-center justify-center bg-neutral-950 text-neutral-600 text-sm select-none">
        <div className="text-center space-y-2">
          <div className="text-4xl opacity-20">⬡</div>
          <p>Configure canvas and generate</p>
        </div>
      </main>
    </div>
  );
}
