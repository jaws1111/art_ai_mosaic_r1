import { useMemo, useState } from "react";
import { jobAssetUrl, JobProgress, QualityReport, runQualityReview } from "../api";
import PanZoomImage from "./PanZoomImage";

type CompareMode =
  | "side_by_side"
  | "overlay"
  | "blueprint"
  | "mosaic"
  | "difference"
  | "outline"
  | "multiply";

interface Props {
  progress: JobProgress;
  onRefresh?: () => void;
  /** When true, fills available height (Quality tab). Omit for compact inline variant. */
  fullHeight?: boolean;
}

export default function QualityReviewPanel({ progress, onRefresh, fullHeight = false }: Props) {
  const report = (progress.outputs.quality_report || null) as (QualityReport & { ai_scale?: string }) | null;
  const [mode, setMode] = useState<CompareMode>("side_by_side");
  const [overlay, setOverlay] = useState(0.5);
  const [busy, setBusy] = useState(false);

  const jobId = progress.job_id;
  const blueprintUrl = jobAssetUrl(jobId, progress.outputs.blueprint as string);
  const mosaicUrl =
    jobAssetUrl(jobId, progress.outputs.mosaic_feather_blend as string) ??
    jobAssetUrl(jobId, progress.outputs.mosaic_hard_paste as string);

  const artifactUrl = useMemo(() => {
    if (!report?.artifacts) return null;
    const key =
      mode === "side_by_side"
        ? "side_by_side"
        : mode === "difference"
          ? "difference"
          : mode === "outline"
            ? "outline"
            : mode === "multiply"
              ? "multiply"
              : mode === "overlay"
                ? "overlay_50"
                : null;
    if (!key) return null;
    return jobAssetUrl(jobId, report.artifacts[key]);
  }, [report, mode, jobId]);

  async function runManual(ai: boolean) {
    setBusy(true);
    try {
      await runQualityReview(jobId, ai);
      onRefresh?.();
    } catch (err) {
      alert(String(err));
    } finally {
      setBusy(false);
    }
  }

  const running = report?.status === "running";
  const metrics = report?.metrics;

  const scoreColor = !metrics
    ? "text-neutral-400"
    : metrics.passed
      ? "text-green-300"
      : metrics.overall_score >= 70
        ? "text-amber-300"
        : "text-red-300";

  const scoreBg = !metrics
    ? "bg-neutral-900 border-neutral-700"
    : metrics.passed
      ? "bg-green-950/60 border-green-800/60"
      : metrics.overall_score >= 70
        ? "bg-amber-950/60 border-amber-800/60"
        : "bg-red-950/60 border-red-800/60";

  return (
    <div
      className={[
        "flex flex-col min-h-0",
        fullHeight
          ? "flex-1"
          : "border-t border-neutral-800 bg-neutral-950/90 shrink-0 max-h-[45vh]",
      ].join(" ")}
    >
      {/* ── toolbar ── */}
      <div className="px-3 py-2 flex flex-wrap items-center gap-2 border-b border-neutral-800 bg-neutral-900/60 shrink-0">
        <span className="text-xs font-semibold text-neutral-300 uppercase tracking-wide">
          Quality review
        </span>

        {metrics && (
          <span className={`text-xs px-2 py-0.5 rounded border font-mono ${scoreBg} ${scoreColor}`}>
            {metrics.overall_score}/100
          </span>
        )}
        {metrics && (
          <span className="text-[10px] text-neutral-500">
            SSIM {metrics.ssim.toFixed(3)} · edges {metrics.edge_overlap.toFixed(3)} · detail ×{metrics.detail_ratio.toFixed(2)}
          </span>
        )}
        {report?.ai_scale && report.ai_scale !== "match" && (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-medium bg-red-950 text-red-300">
            scale: {report.ai_scale}
          </span>
        )}
        {metrics && (
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
              metrics.passed ? "bg-green-950 text-green-300" : "bg-red-950 text-red-300"
            }`}
          >
            {metrics.passed ? "PASS" : "FAIL"}
          </span>
        )}

        {running && <span className="text-xs text-blue-400 animate-pulse">{report?.message}</span>}

        <div className="ml-auto flex gap-1">
          <button
            type="button"
            disabled={busy || running}
            onClick={() => void runManual(false)}
            className="text-[10px] px-2 py-1 rounded border border-neutral-600 hover:bg-neutral-800 disabled:opacity-40"
          >
            Run metrics
          </button>
          <button
            type="button"
            disabled={busy || running}
            onClick={() => void runManual(true)}
            className="text-[10px] px-2 py-1 rounded border border-neutral-600 hover:bg-neutral-800 disabled:opacity-40"
          >
            + AI critique
          </button>
        </div>
      </div>

      {/* ── compare mode buttons ── */}
      <div className="px-3 py-1.5 flex flex-wrap gap-1 border-b border-neutral-800/60 shrink-0">
        {(
          [
            ["side_by_side", "Side by side"],
            ["overlay", "Live overlay"],
            ["difference", "Difference"],
            ["outline", "Outline"],
            ["multiply", "Multiply"],
            ["blueprint", "Blueprint"],
            ["mosaic", "Mosaic"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setMode(id)}
            className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
              mode === id
                ? "bg-accent text-white"
                : "bg-neutral-800 text-neutral-400 hover:bg-neutral-700"
            }`}
          >
            {label}
          </button>
        ))}

        {mode === "overlay" && blueprintUrl && mosaicUrl && (
          <label className="text-[10px] text-neutral-500 flex items-center gap-2 ml-2">
            Blueprint opacity
            <input
              type="range"
              min={0}
              max={100}
              value={overlay * 100}
              onChange={(e) => setOverlay(Number(e.target.value) / 100)}
              className="w-24"
            />
            {Math.round(overlay * 100)}%
          </label>
        )}
      </div>

      {/* ── main image area ── */}
      <div className="flex-1 min-h-0 relative mx-3 my-2 rounded border border-neutral-800 overflow-hidden bg-neutral-900">
        {mode === "overlay" && blueprintUrl && mosaicUrl ? (
          <div className="relative w-full h-full">
            <img src={mosaicUrl} alt="Mosaic" className="absolute inset-0 w-full h-full object-contain" />
            <img
              src={blueprintUrl}
              alt="Blueprint overlay"
              className="absolute inset-0 w-full h-full object-contain pointer-events-none"
              style={{ opacity: overlay }}
            />
          </div>
        ) : artifactUrl ? (
          <PanZoomImage url={artifactUrl} alt="Quality comparison" />
        ) : mode === "blueprint" && blueprintUrl ? (
          <PanZoomImage url={blueprintUrl} alt="Blueprint" />
        ) : mode === "mosaic" && mosaicUrl ? (
          <PanZoomImage url={mosaicUrl} alt="Mosaic" />
        ) : (
          <div className="flex items-center justify-center h-full text-xs text-neutral-500 p-4 text-center">
            {running
              ? report?.message ?? "Running quality checks…"
              : "Enable quality review before generate, or click Run metrics after completion."}
          </div>
        )}
      </div>

      {/* ── metric notes ── */}
      {metrics?.notes && metrics.notes.length > 0 && (
        <ul className="px-3 pb-1 text-[10px] list-disc pl-6 space-y-0.5 shrink-0">
          {metrics.notes.map((n) => (
            <li
              key={n}
              className={
                n.toLowerCase().includes("fail") || n.toLowerCase().includes("weak") || n.toLowerCase().includes("drift")
                  ? "text-red-400"
                  : n.toLowerCase().includes("pass") || n.toLowerCase().includes("strong")
                    ? "text-green-400"
                    : "text-neutral-500"
              }
            >
              {n}
            </li>
          ))}
        </ul>
      )}

      {/* ── AI critique ── */}
      {report?.ai_critique && (
        <div className="mx-3 mb-3 shrink-0">
          <p className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1 font-semibold">
            AI critique
          </p>
          <pre className="p-3 text-[11px] text-neutral-200 bg-neutral-900 rounded border border-neutral-800 whitespace-pre-wrap overflow-y-auto leading-relaxed"
               style={{ maxHeight: fullHeight ? "none" : "8rem" }}>
            {report.ai_critique}
          </pre>
        </div>
      )}
    </div>
  );
}
