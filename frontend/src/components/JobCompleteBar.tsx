import { jobAssetUrl, JobProgress } from "../api";

interface Props {
  progress: JobProgress;
  onNewJob: () => void;
  onViewFull: () => void;
  viewMode: "live" | "full";
}

export default function JobCompleteBar({
  progress,
  onNewJob,
  onViewFull,
  viewMode,
}: Props) {
  const isComplete = progress.status === "complete";
  const isFailed = progress.status === "failed";
  const jobId = progress.job_id;

  if (!isComplete && !isFailed) return null;

  const download = (artifact: string, _label: string) => {
    const a = document.createElement("a");
    a.href = `/api/mosaic/jobs/${jobId}/download/${artifact}`;
    a.download = "";
    a.click();
  };

  return (
    <div
      className={`px-4 py-3 border-t shrink-0 flex flex-wrap items-center gap-3 ${
        isFailed ? "bg-red-950/50 border-red-900" : "bg-green-950/30 border-green-900/50"
      }`}
    >
      <div className="flex-1 min-w-[200px]">
        <p className={`text-sm font-medium ${isFailed ? "text-red-200" : "text-green-200"}`}>
          {isComplete ? "Mosaic complete" : "Job failed"}
        </p>
        <p className="text-xs text-neutral-400 mt-0.5">
          {isComplete
            ? `${progress.tiles_total} tiles · ${progress.elapsed_s.toFixed(0)}s · ~$${progress.est_cost_usd.toFixed(2)}`
            : progress.error}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {isComplete && (
          <>
            <button
              type="button"
              onClick={onViewFull}
              className="px-3 py-1.5 text-sm rounded bg-accent hover:bg-blue-600 text-white"
            >
              {viewMode === "full" ? "Live view" : "View full mosaic"}
            </button>
            <button
              type="button"
              onClick={() => download("feather", "mosaic.png")}
              className="px-3 py-1.5 text-sm rounded border border-neutral-600 hover:bg-neutral-800"
            >
              Save PNG
            </button>
            <button
              type="button"
              onClick={() => download("bigtiff", "master.tiff")}
              className="px-3 py-1.5 text-sm rounded border border-neutral-600 hover:bg-neutral-800"
            >
              Save BigTIFF
            </button>
            <a
              href={`/api/mosaic/jobs/${jobId}/export`}
              className="px-3 py-1.5 text-sm rounded border border-neutral-600 hover:bg-neutral-800 inline-block"
            >
              Export ZIP
            </a>
            {progress.outputs.mosaic_feather_blend && (
              <a
                href={jobAssetUrl(jobId, progress.outputs.mosaic_feather_blend as string) ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 text-sm rounded border border-neutral-600 hover:bg-neutral-800"
              >
                Open in tab
              </a>
            )}
          </>
        )}
        <button
          type="button"
          onClick={onNewJob}
          className="px-3 py-1.5 text-sm rounded border border-neutral-500 hover:bg-neutral-800 text-neutral-200"
        >
          New job
        </button>
      </div>
    </div>
  );
}
