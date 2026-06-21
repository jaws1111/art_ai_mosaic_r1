import { useEffect, useState } from "react";
import { cancelJob, getJob, jobAssetUrl, JobProgress, TileState } from "../api";
import ActivityFeed from "./ActivityFeed";
import DeepZoomViewer from "./DeepZoomViewer";
import JobCompleteBar from "./JobCompleteBar";
import JobNameEditor from "./JobNameEditor";
import MosaicNavigator from "./MosaicNavigator";
import PanZoomImage from "./PanZoomImage";
import QualityReviewPanel from "./QualityReviewPanel";
import WorkerMonitors from "./WorkerMonitors";

export type ViewMode = "live" | "full" | "tile";
type Tab = "monitor" | "activity" | "quality";

interface Props {
  progress: JobProgress;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  onNewJob: () => void;
  onProgressUpdate?: (p: JobProgress) => void;
}

export default function MissionControl({
  progress,
  viewMode,
  onViewModeChange,
  onNewJob,
  onProgressUpdate,
}: Props) {
  const jobId = progress.job_id;
  const rows = progress.grid_rows || 3;
  const cols = progress.grid_cols || 3;
  const [selectedTile, setSelectedTile] = useState<TileState | null>(null);
  const [displayName, setDisplayName] = useState(progress.display_name || "");
  const [activeTab, setActiveTab] = useState<Tab>("monitor");
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    setDisplayName(progress.display_name || "");
  }, [progress.display_name]);

  const blueprintUrl = jobAssetUrl(jobId, progress.outputs.blueprint as string);
  const mosaicUrl =
    jobAssetUrl(jobId, progress.outputs.mosaic_feather_blend as string) ??
    jobAssetUrl(jobId, progress.outputs.mosaic_hard_paste as string);
  const dziUrl = jobAssetUrl(jobId, progress.outputs.dzi as string);

  const isComplete = progress.status === "complete";
  const isFailed = progress.status === "failed";
  const cacheBust = progress.api_calls + progress.tiles_complete;

  const hasQuality = !!(
    (progress.outputs.quality_report as Record<string, unknown> | null)?.metrics ||
    isComplete
  );

  const selectedTileUrl = selectedTile?.tile_path
    ? jobAssetUrl(jobId, selectedTile.tile_path)
    : null;

  function handleViewFull() {
    if (isComplete && mosaicUrl) {
      onViewModeChange(viewMode === "full" ? "live" : "full");
    }
  }

  function handleSelectTile(tile: TileState) {
    setSelectedTile(tile);
    if (tile.tile_path) onViewModeChange("tile");
  }

  async function refreshProgress() {
    const updated = await getJob(jobId);
    onProgressUpdate?.(updated);
  }

  async function handleCancel() {
    if (!confirm("Stop this job? Tiles generated so far will be kept.")) return;
    setCancelling(true);
    try {
      await cancelJob(jobId);
    } catch (err) {
      alert(String(err));
      setCancelling(false);
    }
  }

  // ── ETA calculation ──────────────────────────────────────────────────────
  const tilesTotal = progress.tiles_total || 1;
  const tilesDone = progress.tiles_complete;
  const elapsedS = progress.elapsed_s;
  const pct = tilesTotal > 0 ? Math.round((tilesDone / tilesTotal) * 100) : 0;
  const etaS = tilesDone > 0 ? Math.round((elapsedS / tilesDone) * (tilesTotal - tilesDone)) : null;
  const fmtTime = (s: number) => s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
  const isRunning = !isComplete && !isFailed;

  const TAB_BTN =
    "px-3 py-1.5 text-xs font-medium rounded-t border-b-2 transition-colors";
  const TAB_ACTIVE = "border-accent text-white bg-neutral-900";
  const TAB_IDLE = "border-transparent text-neutral-500 hover:text-neutral-300 hover:bg-neutral-900/50";

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0">
      {/* ── header: job name + stats + workers ── */}
      <div className="px-4 pt-3 pb-2 border-b border-neutral-800 space-y-2 shrink-0 bg-neutral-950/80">
        {/* row 1: name + stop button */}
        <div className="flex items-center gap-2 min-w-0">
          <JobNameEditor
            jobId={jobId}
            displayName={displayName}
            fallbackId={jobId}
            onRenamed={setDisplayName}
          />
          <div className="text-sm text-neutral-500 truncate flex-1 min-w-0" title={progress.message}>
            {progress.message}
          </div>
          {isRunning && (
            <button
              type="button"
              disabled={cancelling}
              onClick={handleCancel}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded border border-red-800 text-red-400 hover:bg-red-950/60 hover:text-red-200 disabled:opacity-40 transition-colors"
            >
              <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
              {cancelling ? "Stopping…" : "Stop"}
            </button>
          )}
        </div>

        {/* row 2: ETA progress bar */}
        {isRunning && tilesTotal > 0 && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[10px] text-neutral-500">
              <span>
                Tiles {tilesDone}/{tilesTotal} · Stage: <span className="text-neutral-300">{progress.stage}</span> · {rows}×{cols} grid
              </span>
              <span className="font-mono">
                {fmtTime(Math.round(elapsedS))} elapsed
                {etaS !== null && <> · <span className="text-blue-400">~{fmtTime(etaS)} left</span></>}
              </span>
            </div>
            <div className="relative h-1.5 rounded-full bg-neutral-800 overflow-hidden">
              {/* animated shimmer while running */}
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-blue-600 to-accent transition-all duration-700"
                style={{ width: `${Math.max(2, pct)}%` }}
              />
              <div
                className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent animate-[shimmer_2s_infinite]"
                style={{ backgroundSize: "200% 100%" }}
              />
            </div>
            <div className="flex items-center gap-3 text-[10px]">
              <span className="text-neutral-500">{pct}%</span>
              <span className="text-blue-400 animate-pulse">Building mosaic…</span>
            </div>
          </div>
        )}

        {isComplete && (
          <div className="flex items-center gap-2 text-[10px] text-neutral-400">
            <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
            Complete · {tilesDone} tiles · {fmtTime(Math.round(elapsedS))} · ~${progress.est_cost_usd.toFixed(2)}
            · Grid {rows}×{cols}
          </div>
        )}

        {/* row 3: workers */}
        <WorkerMonitors
          workers={progress.workers}
          apiCalls={progress.api_calls}
          estCost={progress.est_cost_usd}
          stage={progress.stage}
        />
      </div>

      {/* ── tab bar ── */}
      <div className="flex gap-1 px-4 border-b border-neutral-800 bg-neutral-950 shrink-0">
        {(
          [
            ["monitor", "Monitor"],
            ["activity", "Activity"],
            ["quality", "Quality"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            className={`${TAB_BTN} ${activeTab === id ? TAB_ACTIVE : TAB_IDLE}${
              id === "quality" && !isComplete ? " opacity-40 pointer-events-none" : ""
            }`}
          >
            {label}
            {id === "quality" && hasQuality && isComplete && (
              <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-accent inline-block align-middle" />
            )}
          </button>
        ))}
      </div>

      {/* ── tab content ── */}
      <div className="flex-1 min-h-0 flex flex-col">

        {/* MONITOR TAB */}
        {activeTab === "monitor" && (
          <div className="flex-1 relative bg-neutral-900 flex flex-col min-w-0 min-h-0">
            {/* view label */}
            <div className="absolute top-3 left-3 z-10 flex gap-2">
              {viewMode === "full" && (
                <span className="text-xs bg-accent/80 px-2 py-1 rounded text-white">Deep zoom</span>
              )}
              {viewMode === "tile" && selectedTile && (
                <span className="text-xs bg-neutral-800 px-2 py-1 rounded text-neutral-300">
                  Tile r{selectedTile.row}c{selectedTile.col}
                </span>
              )}
              {viewMode === "live" && blueprintUrl && !isComplete && (
                <span className="text-xs bg-black/60 px-2 py-1 rounded text-neutral-300">
                  Blueprint — pan/zoom
                </span>
              )}
              {viewMode === "live" && isComplete && (
                <span className="text-xs bg-black/60 px-2 py-1 rounded text-neutral-300">
                  Final mosaic
                </span>
              )}
            </div>

            {/* back button */}
            {viewMode !== "live" && (
              <button
                type="button"
                onClick={() => onViewModeChange("live")}
                className="absolute top-3 right-3 z-10 text-xs px-2 py-1 rounded bg-neutral-800 hover:bg-neutral-700 border border-neutral-600"
              >
                Back to live
              </button>
            )}

            {/* main canvas */}
            <div className="flex-1 flex items-center justify-center p-4 overflow-hidden min-h-0">
              {viewMode === "full" && mosaicUrl ? (
                <DeepZoomViewer dziUrl={dziUrl} fallbackUrl={mosaicUrl} cacheBust={cacheBust} />
              ) : viewMode === "tile" && selectedTileUrl ? (
                <PanZoomImage url={selectedTileUrl} cacheBust={cacheBust} alt="Tile preview" />
              ) : isComplete && mosaicUrl ? (
                <img
                  src={`${mosaicUrl}?v=${cacheBust}`}
                  alt="Final mosaic"
                  className="max-w-full max-h-full object-contain shadow-2xl rounded cursor-zoom-in"
                  onClick={() => onViewModeChange("full")}
                  title="Click for deep zoom"
                />
              ) : blueprintUrl ? (
                <PanZoomImage url={blueprintUrl} cacheBust={cacheBust} alt="Master blueprint" />
              ) : (
                <div className="text-center text-neutral-500 space-y-2">
                  <div className="w-8 h-8 border-2 border-neutral-600 border-t-accent rounded-full animate-spin mx-auto" />
                  <p>Generating master blueprint via xAI…</p>
                </div>
              )}
            </div>

            {/* resizable navigator overlay */}
            <div className="absolute bottom-4 left-4 z-10">
              <MosaicNavigator
                jobId={jobId}
                tiles={progress.tiles}
                rows={rows}
                cols={cols}
                cacheBust={cacheBust}
                onSelectTile={handleSelectTile}
                selectedTile={selectedTile}
              />
            </div>
          </div>
        )}

        {/* ACTIVITY TAB */}
        {activeTab === "activity" && (
          <div className="flex-1 min-h-0 flex flex-col bg-neutral-950">
            <ActivityFeed events={progress.activity} defaultCollapsed={false} fullHeight />
          </div>
        )}

        {/* QUALITY TAB */}
        {activeTab === "quality" && (
          <div className="flex-1 min-h-0 flex flex-col bg-neutral-950">
            <QualityReviewPanel
              progress={progress}
              onRefresh={() => void refreshProgress()}
              fullHeight
            />
          </div>
        )}
      </div>

      {/* ── job complete / failed bar ── */}
      <JobCompleteBar
        progress={progress}
        onNewJob={onNewJob}
        onViewFull={handleViewFull}
        viewMode={viewMode === "full" ? "full" : "live"}
      />

      {isFailed && progress.error && (
        <div className="p-3 bg-red-950 text-red-200 text-sm border-t border-red-900 shrink-0">
          {progress.error}
        </div>
      )}
    </div>
  );
}
