export type TileStatus =
  | "queued"
  | "cloud_generating"
  | "cloud_done"
  | "local_queued"
  | "local_processing"
  | "composited"
  | "error";

export type ActivityCategory = "system" | "xai" | "cpu" | "gpu" | "network";

export interface ActivityEvent {
  ts: number;
  category: ActivityCategory;
  message: string;
  detail?: string | null;
}

export interface WorkerStatus {
  xai_active: boolean;
  cpu_active: boolean;
  gpu_active: boolean;
  xai_label: string;
  cpu_label: string;
  gpu_label: string;
}

export interface TileState {
  row: number;
  col: number;
  seq: number;
  status: TileStatus;
  error?: string | null;
  tile_path?: string | null;
}

export interface QualityMetrics {
  ssim: number;
  edge_overlap: number;
  mse: number;
  detail_ratio: number;
  overall_score: number;
  passed: boolean;
  notes: string[];
}

export interface QualityReport {
  status: string;
  stage?: string;
  message?: string;
  metrics?: QualityMetrics;
  artifacts?: Record<string, string>;
  ai_critique?: string | null;
  include_ai_critique?: boolean;
}

export interface JobProgress {
  job_id: string;
  display_name?: string;
  status: string;
  prompt: string;
  tiles_total: number;
  tiles_complete: number;
  grid_rows: number;
  grid_cols: number;
  generation_mode?: string;
  strategy_message?: string;
  stage: string;
  message: string;
  elapsed_s: number;
  est_cost_usd: number;
  api_calls: number;
  tiles: TileState[];
  outputs: Record<string, unknown>;
  activity: ActivityEvent[];
  workers: WorkerStatus;
  error?: string | null;
}

export interface MosaicJobCreate {
  prompt: string;
  style_anchor?: string;
  canvas: {
    width_px: number;
    height_px: number;
    mode?: "standard" | "panorama_h" | "panorama_v" | "spherical";
    aspect_label?: string;
    wraparound?: boolean;
  };
  regions?: PromptRegion[];
  display_name?: string;
  run_quality_check?: boolean;
  include_ai_critique?: boolean;
  upscale_factor?: number;
  overlap_fraction?: number;
  max_concurrency?: number;
}

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

export interface PlanPreview {
  generation_mode: string;
  strategy_message: string;
  rows: number;
  cols: number;
  tile_count: number;
  tile_effective: number;
  local_upscale_factor: number;
  est_cloud_calls: number;
  est_cost_usd: number;
  use_mosaic_stitch: boolean;
  width_px: number;
  height_px: number;
  crop_upscale_ratio: number;
  crop_quality_warning: string | null;
}

export interface PlanPreviewRequest {
  canvas: {
    width_px: number;
    height_px: number;
    mode?: "standard" | "panorama_h" | "panorama_v" | "spherical";
    aspect_label?: string;
    wraparound?: boolean;
  };
  upscale_factor?: number;
  overlap_fraction?: number;
}

const API = "/api/mosaic";

export function jobAssetUrl(jobId: string, relativePath: string | undefined | null): string | null {
  if (!relativePath || typeof relativePath !== "string") return null;
  const normalized = relativePath.replace(/\\/g, "/");
  return `${API}/jobs/${jobId}/files/${normalized}`;
}

export async function previewPlan(body: PlanPreviewRequest): Promise<PlanPreview> {
  const res = await fetch(`${API}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function renameJob(jobId: string, displayName: string): Promise<JobProgress> {
  const res = await fetch(`${API}/jobs/${jobId}/name`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function runQualityReview(jobId: string, includeAiCritique: boolean): Promise<void> {
  const res = await fetch(`${API}/jobs/${jobId}/quality`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_ai_critique: includeAiCritique }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function createJob(body: MosaicJobCreate): Promise<JobProgress> {
  const res = await fetch(`${API}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${API}/jobs/${jobId}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function getJob(jobId: string): Promise<JobProgress> {
  const res = await fetch(`${API}/jobs/${jobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function connectProgress(
  jobId: string,
  onUpdate: (p: JobProgress) => void,
): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/progress/${jobId}`);
  ws.onmessage = (event) => onUpdate(JSON.parse(event.data));
  ws.onopen = () => ws.send("ping");
  return ws;
}
