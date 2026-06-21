import { WorkerStatus } from "../api";

interface Props {
  workers: WorkerStatus;
  apiCalls: number;
  estCost: number;
  stage?: string;
}

function isActive(flag: boolean, label: string, busyHints: string[]) {
  if (flag) return true;
  const lower = label.toLowerCase();
  if (lower.includes("idle")) return false;
  return busyHints.some((hint) => lower.includes(hint));
}

function Monitor({
  label,
  active,
  detail,
  color,
}: {
  label: string;
  active: boolean;
  detail: string;
  color: string;
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[140px] ${
        active ? `${color} border-current/30` : "border-neutral-700 text-neutral-500"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            active ? "animate-pulse bg-current" : "bg-neutral-600"
          }`}
        />
        <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
      </div>
      <p className="text-[11px] mt-1 truncate" title={detail}>
        {detail}
      </p>
    </div>
  );
}

export default function WorkerMonitors({ workers, apiCalls, estCost, stage }: Props) {
  const xaiActive = isActive(workers.xai_active, workers.xai_label, [
    "xai",
    "blueprint",
    "tile",
    "generating",
    "fetching",
  ]);
  const cpuActive = isActive(workers.cpu_active, workers.cpu_label, [
    "crop",
    "seam",
    "stitch",
    "composit",
    "lanczos",
    "dzi",
    "wrap",
    "repair",
    "refiner",
  ]);
  const gpuActive = isActive(workers.gpu_active, workers.gpu_label, [
    "esrgan",
    "cuda",
    "real-",
    "upscale",
    "blend",
  ]);

  return (
    <div className="flex flex-wrap gap-2 items-stretch">
      <Monitor
        label="xAI Cloud"
        active={xaiActive || stage === "blueprint"}
        detail={workers.xai_label}
        color="text-blue-400 bg-blue-950/40"
      />
      <Monitor
        label="Local CPU"
        active={cpuActive || stage === "compositing" || stage === "local_refinery" || stage === "closing_pass"}
        detail={workers.cpu_label}
        color="text-amber-400 bg-amber-950/40"
      />
      <Monitor
        label="Local GPU"
        active={gpuActive}
        detail={workers.gpu_label}
        color="text-emerald-400 bg-emerald-950/40"
      />
      <div className="rounded-lg border border-neutral-700 px-3 py-2 min-w-[100px] text-neutral-400">
        <div className="text-xs font-semibold uppercase tracking-wide">API</div>
        <p className="text-[11px] mt-1">
          {apiCalls} calls · ~${estCost.toFixed(2)}
        </p>
      </div>
    </div>
  );
}
