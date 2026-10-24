/** API client for the litegm admin API. */

export type TaskPreview = {
  url: string;
  kind: string;
  width: number | null;
  height: number | null;
} | null;

export type TaskSummary = {
  id: string;
  task_type: string;
  status: string;
  stage: string | null;
  progress: number;
  model_alias: string;
  backend_id: string;
  prompt: string;
  created_at: number;
  finished_at: number | null;
  error_code: string | null;
  artifact_count: number;
  suspicious: boolean;
  /** Thumbnail of the first artifact, when the backend provides one. */
  preview?: TaskPreview;
  /** Thumbnail of the first uploaded input image, when present. */
  input_preview?: TaskPreview;
};

export type Artifact = {
  id: string;
  kind: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  suspicious: boolean;
  meta: Record<string, unknown>;
  url: string;
  signed_url: string;
};

export type InputImage = {
  index: number;
  role: string | null;
  filename: string;
  mime_type: string | null;
  size_bytes: number;
  width: number | null;
  height: number | null;
  url: string;
};

export type TaskEvent = { ts: number; kind: string; data: Record<string, unknown> | null };

export type TaskDetail = TaskSummary & {
  request: Record<string, unknown>;
  workflow: Record<string, unknown> | null;
  comfy_prompt_id: string | null;
  started_at: number | null;
  error: Record<string, unknown> | null;
  attempts: Array<Record<string, unknown>>;
  cancel_requested: boolean;
  input_images: InputImage[];
  artifacts: Artifact[];
  events: TaskEvent[];
  /** Wall-clock execution time in seconds, when known. */
  duration_s?: number | null;
};

export type BackendHealth = {
  healthy?: boolean;
  error?: string;
  comfyui_version?: string;
  os?: string;
  ram_free?: number;
  ram_total?: number;
  devices?: Array<Record<string, unknown>>;
  queue?: { running: number | null; pending: number | null };
};

export type QueueStats = { running: number; waiting: number; concurrency: number; queue_max: number };

export type HealthResponse = {
  version: string;
  uptime_s: number;
  tasks: Record<string, number>;
  active: number;
  queues?: Record<string, QueueStats>;
  backends: Record<string, BackendHealth>;
};

export type ModelConstraints = {
  size_policy?: string;
  size_step?: number;
  min_edge?: number;
  max_edge?: number;
  default_size?: string | null;
  n_max?: number;
  output_formats?: string[];
  backgrounds?: string[];
  quality_map?: Record<string, Record<string, number>>;
  duration_min?: number | null;
  duration_max?: number | null;
  duration_default?: number | null;
  duration_step?: number | null;
};

export type TaskModel = {
  alias: string;
  backend: string;
  template: string;
  fallbacks?: string[];
  mask_policy?: string;
  constraints: ModelConstraints;
};

export type ConfigView = {
  server: Record<string, unknown>;
  backends: Array<Record<string, unknown>>;
  routing?: {
    unified_image_models: Array<{ alias: string; generate_task: string; edit_task: string }>;
    video_families?: Array<Record<string, unknown>>;
  };
  tasks: Record<string, { models: TaskModel[] }>;
};

export type StorageStats = {
  usage: { artifacts_bytes: number; uploads_bytes: number; total_bytes: number };
  limits: {
    max_bytes: number | null;
    artifact_ttl_days: number;
    failed_retention_days: number | null;
    sweep_interval_s: number;
  };
};

export type ModelInfo = {
  id: string;
  capabilities: Record<string, unknown>;
};

/** Discovery documents served by the gateway (no auth required). */
export const API_DOCS_URL = "/swagger-ui";
export const LLMS_TXT_URL = "/llms.txt";

/** Absolute URL for a same-origin path, so links can be handed to an agent. */
export function absoluteUrl(path: string): string {
  return `${window.location.origin}${path.startsWith("/") ? path : `/${path}`}`;
}

export type TaskQuery = {
  limit?: number;
  offset?: number;
  status?: string;
  task_type?: string;
  model_alias?: string;
  backend_id?: string;
  since?: number;
  until?: number;
  search?: string;
};

const ADMIN = "/admin/api";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(ADMIN + path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      /* non-JSON error */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function queryString(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  });
  return qs.toString();
}

export const api = {
  me: () => request<{ authenticated: boolean; username?: string; auth_enabled?: boolean }>("/me"),
  login: async (username: string, masterKey: string) => {
    const res = await fetch(ADMIN + "/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: "Basic " + btoa(`${username}:${masterKey}`) },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body?.error?.message ?? "登录失败");
    }
    return res.json();
  },
  logout: () => request("/logout", { method: "POST" }),
  tasks: (params: TaskQuery) =>
    request<{ total: number; items: TaskSummary[] }>(`/tasks?${queryString(params)}`),
  task: (id: string) => request<TaskDetail>(`/tasks/${id}`),
  cancel: (id: string) => request(`/tasks/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => request<{ task_id: string }>(`/tasks/${id}/retry`, { method: "POST" }),
  remove: (id: string) => request<{ freed_bytes: number }>(`/tasks/${id}`, { method: "DELETE" }),
  health: () => request<HealthResponse>("/health"),
  config: () => request<ConfigView>("/config"),
  reloadConfig: () =>
    request<{ ok: boolean; restart_required: string[] }>("/config/reload", { method: "POST" }),
  storage: () => request<StorageStats>("/storage"),
  sweep: () =>
    request<{ removed: Record<string, number>; usage: StorageStats["usage"] }>("/storage/sweep", {
      method: "POST",
    }),
  exportUrl: (format: "json" | "csv", params: TaskQuery = {}) =>
    `${ADMIN}/tasks/export?${queryString({ format, ...params })}`,
  /** Thumbnail URL for an artifact. Falls back to the full file if unsupported. */
  artifactThumb: (id: string, size = 384) => `${ADMIN}/artifacts/${id}/thumb?size=${size}`,
  inputThumb: (taskId: string, index: number, size = 384) =>
    `${ADMIN}/tasks/${taskId}/inputs/${index}/thumb?size=${size}`,
};

/** Models available for Studio submissions, taken from the public API. */
export async function listModels(apiKey: string): Promise<ModelInfo[]> {
  const res = await fetch("/v1/models", { headers: { Authorization: `Bearer ${apiKey}` } });
  if (!res.ok) throw new Error(`模型列表获取失败: HTTP ${res.status}`);
  const body = await res.json();
  return body.data as ModelInfo[];
}
