/** Studio (Playground): constraint-driven generation composer.
 *
 * Modes, models, size presets, durations, formats and n limits all come from the
 * live catalog (`/v1/models`) plus the per-model constraints in `api.config()`.
 * Submission semantics are unchanged: `/v1/images/generations`,
 * `/v1/images/edits` (multipart, `image` fields), `/v1/videos` (multipart) and
 * `/v1/audio/generations`. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  listModels,
  type Artifact,
  type ConfigView,
  type ModelConstraints,
  type ModelInfo,
  type TaskDetail,
  type TaskModel,
} from "./api";
import { ArtifactGallery, StatusPill } from "./components";
import { fmtDuration, fmtSize, shortId, statusMeta, truncate } from "./format";
import {
  IconAlert,
  IconArrowUpRight,
  IconAudio,
  IconCheck,
  IconClose,
  IconDice,
  IconEdit,
  IconGrip,
  IconImage,
  IconInfo,
  IconPlus,
  IconRefresh,
  IconSeed,
  IconSpark,
  IconStop,
  IconUpload,
  IconVideo,
} from "./icons";
import { EmptyState, ErrorBanner, IconButton, ProgressBar, Skeleton, Tooltip, useToast } from "./ui";

type Props = {
  apiKey: string;
  onOpenTask: (id: string) => void;
  onSubmitted: () => void;
};

type Mode = "image.generate" | "image.edit" | "video.generate" | "audio.generate";

type ModeDef = {
  id: Mode;
  label: string;
  short: string;
  hint: string;
  icon: (p: { size?: number }) => React.ReactNode;
};

const MODES: ModeDef[] = [
  { id: "image.generate", label: "文生图", short: "T2I", hint: "由提示词直接生成图片，可选尺寸、数量与输出格式。", icon: IconImage },
  { id: "image.edit", label: "图生图", short: "I2I", hint: "上传编辑目标与参考图，按提示词改写画面。", icon: IconEdit },
  { id: "video.generate", label: "视频", short: "VIDEO", hint: "文生视频 / 图生视频 / 参考生视频，时长受模型约束。", icon: IconVideo },
  { id: "audio.generate", label: "音频", short: "AUDIO", hint: "由描述与歌词生成音乐片段。", icon: IconAudio },
];

type RefFile = {
  id: string;
  file: File;
  url: string;
  role: "target" | "reference" | "first_frame";
};

const PRESETS: Record<Mode, Array<{ label: string; text: string }>> = {
  "image.generate": [
    { label: "电影感静物", text: "cinematic still life, soft window light, shallow depth of field, muted warm palette, 35mm film grain" },
    { label: "产品棚拍", text: "studio product shot on a seamless dark backdrop, three-point lighting, crisp reflections, ultra sharp" },
    { label: "概念场景", text: "concept art of a quiet harbor at dawn, low fog, long exposure, volumetric light, muted teal and amber" },
    { label: "人像", text: "editorial portrait, natural skin texture, rim light from behind, calm expression, neutral grey background" },
  ],
  "image.edit": [
    { label: "换背景", text: "把背景替换为雨夜的霓虹街道，保持主体身份与姿态不变" },
    { label: "风格化", text: "重绘为水墨风格，保留构图与光影关系" },
    { label: "服装修改", text: "把外套换成深色皮质风衣，保持面部与发型不变" },
    { label: "画质提升", text: "提升细节与锐度，修复噪点，不改动内容与构图" },
  ],
  "video.generate": [
    { label: "缓慢推进", text: "a slow camera push across a calm harbor at sunrise, gentle waves, film grain" },
    { label: "环绕镜头", text: "slow orbital camera move around a lone lighthouse, dusk, volumetric fog" },
    { label: "延时", text: "time-lapse of clouds rolling over a mountain ridge, golden hour, ultra detailed" },
    { label: "微距", text: "macro shot of dew drops sliding off a leaf, shallow depth of field, soft bokeh" },
  ],
  "audio.generate": [
    { label: "氛围电子", text: "ambient electronic, warm pads, slow 78 BPM, no vocals, cinematic" },
    { label: "爵士三重奏", text: "lofi jazz trio, upright bass, brushed drums, mellow piano, 92 BPM" },
    { label: "电影配乐", text: "orchestral cinematic score, building tension, strings and low brass, 110 BPM" },
    { label: "民谣", text: "acoustic folk, fingerpicked guitar, intimate vocal, 84 BPM" },
  ],
};

/* ------------------------------------------------------------- constraints */

type CatalogModel = {
  id: string;
  capabilities: Record<string, unknown>;
  config: TaskModel | null;
};

function tasksOf(m: ModelInfo): string[] {
  const task = m.capabilities?.task;
  if (Array.isArray(task)) return task.map(String);
  if (typeof task === "string") return [task];
  return [];
}

function modelsForMode(catalog: CatalogModel[], mode: Mode): CatalogModel[] {
  return catalog.filter((m) => {
    const tasks = tasksOf(m);
    if (mode === "video.generate") return tasks.includes("video.generate") || Boolean(m.capabilities?.video_family);
    return tasks.includes(mode);
  });
}

function acceptsImages(m: CatalogModel, mode: Mode): boolean {
  if (mode === "image.edit") return true;
  const caps = m.capabilities ?? {};
  if (caps.accepts_images === true) return true;
  if (typeof caps.max_images === "number" && caps.max_images > 0) return true;
  return Boolean(caps.unified);
}

/** Merge catalog capabilities with config constraints (config wins when present). */
function mergedConstraints(m: CatalogModel | null, mode: Mode): ModelConstraints | null {
  if (!m) return null;
  const caps = m.capabilities ?? {};
  const cfg = m.config?.constraints ?? null;
  const num = (k: string): number | null => (typeof caps[k] === "number" ? (caps[k] as number) : null);
  const out: ModelConstraints = {
    size_policy: cfg?.size_policy ?? (typeof caps.size_policy === "string" ? caps.size_policy : undefined),
    size_step: cfg?.size_step ?? num("size_step") ?? undefined,
    min_edge: cfg?.min_edge ?? num("min_edge") ?? undefined,
    max_edge: cfg?.max_edge ?? num("max_edge") ?? undefined,
    default_size: cfg?.default_size ?? (typeof caps.default_size === "string" ? caps.default_size : null),
    n_max: cfg?.n_max ?? num("n_max") ?? undefined,
    output_formats: cfg?.output_formats ?? (Array.isArray(caps.output_formats) ? (caps.output_formats as string[]) : undefined),
    backgrounds: cfg?.backgrounds ?? (Array.isArray(caps.backgrounds) ? (caps.backgrounds as string[]) : undefined),
    quality_map: cfg?.quality_map,
    duration_min: cfg?.duration_min ?? null,
    duration_max: cfg?.duration_max ?? null,
    duration_default: cfg?.duration_default ?? null,
    duration_step: cfg?.duration_step ?? null,
  };
  return out;
}

/** Aspect-ratio presets derived from the model's edge bounds. */
function sizePresets(c: ModelConstraints | null): Array<{ label: string; size: string | null; ratio: string }> {
  if (!c) return [];
  const max = c.max_edge ?? 1024;
  const step = c.size_step ?? 32;
  const snap = (v: number) => Math.max(c.min_edge ?? 256, Math.min(max, Math.round(v / step) * step));
  const base = Math.min(max, Math.max(c.min_edge ?? 256, 1024));
  // Keep the longer edge at ``base`` so every preset stays within max_edge and
  // honours size_step; the shorter edge follows the requested aspect ratio.
  const pair = (ratioW: number, ratioH: number) => {
    const long = base;
    const w = ratioW >= ratioH ? long : Math.round((long * ratioW) / ratioH);
    const h = ratioW >= ratioH ? Math.round((long * ratioH) / ratioW) : long;
    return `${snap(w)}x${snap(h)}`;
  };
  const presets = [
    { label: "自动", size: null, ratio: "1:1" },
    { label: "1:1", size: pair(1, 1), ratio: "1:1" },
    { label: "3:4", size: pair(3, 4), ratio: "3:4" },
    { label: "4:3", size: pair(4, 3), ratio: "4:3" },
    { label: "9:16", size: pair(9, 16), ratio: "9:16" },
    { label: "16:9", size: pair(16, 9), ratio: "16:9" },
    { label: "2:3", size: pair(2, 3), ratio: "2:3" },
    { label: "3:2", size: pair(3, 2), ratio: "3:2" },
  ];
  return presets.filter((p, i) => p.size === null || presets.findIndex((q) => q.size === p.size) === i);
}

function durationRange(c: ModelConstraints | null): { min: number; max: number; step: number; def: number } | null {
  if (!c || c.duration_min == null || c.duration_max == null) return null;
  const step = c.duration_step && c.duration_step > 0 ? c.duration_step : 0.5;
  const min = c.duration_min;
  const max = c.duration_max;
  const def = Math.min(max, Math.max(min, c.duration_default ?? min));
  return { min, max, step, def };
}

function snapDuration(value: number, range: { min: number; max: number; step: number }): number {
  const snapped = range.min + Math.round((value - range.min) / range.step) * range.step;
  return Math.min(range.max, Math.max(range.min, Number(snapped.toFixed(2))));
}

/* ----------------------------------------------------------------- submit */

async function readError(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return (body?.error?.message as string | undefined) ?? `HTTP ${res.status}`;
}

async function submitImage(
  mode: "image.generate" | "image.edit",
  apiKey: string,
  fields: Record<string, string>,
  files: File[],
): Promise<{ id: string }> {
  const common: Record<string, string> = {
    model: fields.model,
    prompt: fields.prompt,
    size: fields.size || "auto",
    n: fields.n || "1",
    quality: fields.quality || "auto",
    output_format: fields.output_format || "png",
    seed: fields.seed || "",
  };
  let res: Response;
  if (mode === "image.generate") {
    const body: Record<string, unknown> = { ...common };
    if (body.seed === "") delete body.seed;
    res = await fetch("/v1/images/generations", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } else {
    const form = new FormData();
    for (const [k, v] of Object.entries(common)) if (v !== "") form.append(k, v);
    files.forEach((f) => form.append("image", f));
    res = await fetch("/v1/images/edits", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
      body: form,
    });
  }
  if (!res.ok) throw new Error(await readError(res));
  const body = await res.json().catch(() => ({}));
  const taskId = res.headers.get("x-litegm-task-id") ?? body?.task_id ?? body?.id;
  if (!taskId) throw new Error("服务端未返回任务 ID");
  return { id: String(taskId) };
}

async function submitVideo(apiKey: string, fields: Record<string, string>, files: File[]): Promise<{ id: string }> {
  const form = new FormData();
  form.append("prompt", fields.prompt);
  form.append("model", fields.model);
  if (fields.size) form.append("size", fields.size);
  if (fields.seconds) form.append("seconds", fields.seconds);
  if (fields.inputMode === "image" && files[0]) form.append("input_reference", files[0]);
  if (fields.inputMode === "reference") files.forEach((f) => form.append("reference_images", f));
  const res = await fetch("/v1/videos", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}` },
    body: form,
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = await res.json().catch(() => ({}));
  const id = body.id ?? body.task_id;
  if (!id) throw new Error("服务端未返回任务 ID");
  return { id: String(id) };
}

async function submitAudio(apiKey: string, fields: Record<string, string>): Promise<{ id: string }> {
  const body: Record<string, unknown> = {
    model: fields.model,
    input: fields.prompt,
    lyrics: fields.lyrics || "",
  };
  if (fields.seconds) body.seconds = Number(fields.seconds);
  if (fields.seed) body.seed = Number(fields.seed);
  const res = await fetch("/v1/audio/generations", {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json().catch(() => ({}));
  const id = data.id ?? data.task_id;
  if (!id) throw new Error("服务端未返回任务 ID");
  return { id: String(id) };
}

/* ------------------------------------------------------------------- page */

export default function Playground({ apiKey, onOpenTask, onSubmitted }: Props) {
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("image.generate");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [config, setConfig] = useState<ConfigView | null>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [fields, setFields] = useState<Record<string, string>>({
    prompt: "",
    size: "",
    n: "1",
    quality: "auto",
    output_format: "",
    seed: "",
    seconds: "",
    lyrics: "",
    inputMode: "text",
  });
  const [files, setFiles] = useState<RefFile[]>([]);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [polled, setPolled] = useState<TaskDetail | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const alive = useRef(true);

  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true);
    try {
      const [list, cfg] = await Promise.all([listModels(apiKey), api.config().catch(() => null)]);
      if (!alive.current) return;
      setModels(list);
      setConfig(cfg);
      setModelsError(null);
    } catch (err) {
      if (!alive.current) return;
      setModelsError((err as Error).message);
    } finally {
      if (alive.current) setLoadingCatalog(false);
    }
  }, [apiKey]);

  useEffect(() => {
    alive.current = true;
    void loadCatalog();
    return () => {
      alive.current = false;
    };
  }, [loadCatalog]);

  const catalog = useMemo<CatalogModel[]>(() => {
    return models.map((m) => {
      const task = tasksOf(m)[0];
      const cfgModels = config && task ? config.tasks[task]?.models ?? [] : [];
      const cfg = cfgModels.find((c) => c.alias === m.id) ?? null;
      return { id: m.id, capabilities: m.capabilities ?? {}, config: cfg };
    });
  }, [models, config]);

  const modeModels = useMemo(() => modelsForMode(catalog, mode), [catalog, mode]);
  const selectedModel = useMemo(
    () => modeModels.find((m) => m.id === fields.model) ?? modeModels[0] ?? null,
    [modeModels, fields.model],
  );
  const constraints = useMemo(() => mergedConstraints(selectedModel, mode), [selectedModel, mode]);
  const presets = useMemo(() => sizePresets(constraints), [constraints]);
  const durations = useMemo(() => durationRange(constraints), [constraints]);
  const isVideo = mode === "video.generate";
  const isAudio = mode === "audio.generate";
  const isImage = mode === "image.generate" || mode === "image.edit";
  const needsImages = mode === "image.edit" || (isVideo && fields.inputMode !== "text");
  const maxImages =
    mode === "image.edit"
      ? Math.max(1, Math.min(16, Number(selectedModel?.capabilities?.max_images) || 16))
      : isVideo
        ? fields.inputMode === "reference"
          ? Math.max(1, Number(selectedModel?.capabilities?.max_images) || 8)
          : 1
        : 0;

  // Keep the selected model valid for the current mode.
  useEffect(() => {
    setFields((f) => {
      if (modeModels.length && !modeModels.some((m) => m.id === f.model)) return { ...f, model: modeModels[0].id };
      return f;
    });
  }, [modeModels]);

  // Clamp n / format / duration to the selected model's real constraints.
  useEffect(() => {
    if (!constraints) return;
    setFields((f) => {
      const next = { ...f };
      let changed = false;
      const nMax = constraints.n_max ?? 4;
      const n = Number(f.n) || 1;
      if (n < 1 || n > nMax) {
        next.n = String(Math.min(nMax, Math.max(1, n)));
        changed = true;
      }
      if (constraints.output_formats?.length && !constraints.output_formats.includes(f.output_format)) {
        next.output_format = constraints.output_formats[0];
        changed = true;
      }
      if (durations) {
        const current = Number(f.seconds) || durations.def;
        const snapped = snapDuration(current, durations);
        if (f.seconds !== String(snapped)) {
          next.seconds = String(snapped);
          changed = true;
        }
      }
      return changed ? next : f;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [constraints, durations]);

  // Poll the submitted task until it settles.
  useEffect(() => {
    if (!taskId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const d = await api.task(taskId);
        if (stopped || !alive.current) return;
        setPolled(d);
        if (!["queued", "submitting", "running"].includes(d.status)) {
          window.clearInterval(timer);
          onSubmitted();
        }
      } catch {
        /* transient */
      }
    };
    void tick();
    const timer = window.setInterval(tick, 2500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [taskId, onSubmitted]);

  const set = (k: string, v: string) => setFields((f) => ({ ...f, [k]: v }));

  const addFiles = (list: FileList | File[]) => {
    const incoming = Array.from(list).filter((f) => f.type.startsWith("image/"));
    if (!incoming.length) return;
    setFiles((prev) => {
      const room = Math.max(0, maxImages - prev.length);
      if (room <= 0) {
        toast.push("info", "已达图片数量上限", `该模型最多 ${maxImages} 张`);
        return prev;
      }
      const next = incoming.slice(0, room).map((file, i) => ({
        id: `${Date.now()}-${i}-${file.name}`,
        file,
        url: URL.createObjectURL(file),
        role: (prev.length === 0 && i === 0 && mode === "image.edit"
          ? "target"
          : mode === "video.generate"
            ? "first_frame"
            : "reference") as RefFile["role"],
      }));
      return [...prev, ...next];
    });
  };

  const removeFile = (id: string) => {
    setFiles((prev) => {
      const removed = prev.find((f) => f.id === id);
      if (removed) URL.revokeObjectURL(removed.url);
      return prev
        .filter((f) => f.id !== id)
        .map((f, i) => ({ ...f, role: mode === "image.edit" && i === 0 ? "target" : mode === "image.edit" ? "reference" : f.role }));
    });
  };

  const moveFile = (from: number, to: number) => {
    setFiles((prev) => {
      const next = [...prev];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next.map((f, i) => ({ ...f, role: mode === "image.edit" && i === 0 ? "target" : mode === "image.edit" ? "reference" : f.role }));
    });
  };

  const setRole = (id: string, role: RefFile["role"]) => {
    setFiles((prev) =>
      role === "target"
        ? prev.map((f) => ({ ...f, role: f.id === id ? "target" : "reference" }))
        : prev.map((f) => (f.id === id ? { ...f, role } : f)),
    );
  };

  const clearAll = () => {
    files.forEach((f) => URL.revokeObjectURL(f.url));
    setFiles([]);
    setFields((f) => ({ ...f, prompt: "", lyrics: "", seed: "" }));
    setTaskId(null);
    setPolled(null);
    setError(null);
  };

  const submit = async () => {
    setError(null);
    if (!selectedModel) {
      setError("当前模式没有可用模型");
      return;
    }
    if (!fields.prompt?.trim()) {
      setError(isAudio ? "请填写音乐描述" : "请填写提示词");
      return;
    }
    if (mode === "image.edit" && files.length === 0) {
      setError("图生图需要至少一张图片（第一张作为编辑目标）");
      return;
    }
    if (isVideo && fields.inputMode !== "text" && files.length === 0) {
      setError(fields.inputMode === "reference" ? "参考生视频需要至少一张参考图" : "图生视频需要首帧图");
      return;
    }
    setSubmitting(true);
    setTaskId(null);
    setPolled(null);
    try {
      // The tray order is authoritative: first image = edit target / first frame.
      const ordered = files.map((f) => f.file);
      let res: { id: string };
      if (mode === "image.generate") {
        res = await submitImage(mode, apiKey, { ...fields, model: selectedModel.id }, []);
      } else if (mode === "image.edit") {
        res = await submitImage(mode, apiKey, { ...fields, model: selectedModel.id }, ordered);
      } else if (isVideo) {
        res = await submitVideo(apiKey, { ...fields, model: selectedModel.id }, ordered);
      } else {
        res = await submitAudio(apiKey, { ...fields, model: selectedModel.id });
      }
      setTaskId(res.id);
      toast.push("success", "任务已提交", `${selectedModel.id} · ${shortId(res.id)}`);
      onSubmitted();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const reuse = () => {
    if (!polled) return;
    const req = polled.request ?? {};
    setMode(polled.task_type as Mode);
    setFields((f) => ({
      ...f,
      model: polled.model_alias,
      prompt: String(req.prompt ?? polled.prompt ?? f.prompt),
      size: req.size ? String(req.size) : "",
      n: String(req.n ?? 1),
      quality: req.quality ? String(req.quality) : "auto",
      output_format: req.output_format ? String(req.output_format) : f.output_format,
      seed: req.seed != null ? String(req.seed) : "",
      seconds: req.seconds != null ? String(req.seconds) : f.seconds,
    }));
    toast.push("info", "已载入上次参数", "调整后可直接再次提交");
  };

  const promptLen = fields.prompt?.length ?? 0;
  const activeDef = MODES.find((m) => m.id === mode) ?? MODES[0];
  const artifacts: Artifact[] = polled?.artifacts ?? [];
  const running = polled ? ["queued", "submitting", "running"].includes(polled.status) : false;
  const nMax = constraints?.n_max ?? 4;
  // Manual size entry must respect the model's step and edge bounds; the presets
  // already satisfy this, so the hint only fires for hand-typed values.
  const sizeInvalid = (() => {
    const raw = (fields.size ?? "").trim();
    if (!raw) return false;
    const m = /^(\d+)\s*[x×]\s*(\d+)$/i.exec(raw);
    if (!m) return true;
    const w = Number(m[1]);
    const h = Number(m[2]);
    if (!w || !h) return true;
    const step = constraints?.size_step;
    const minEdge = constraints?.min_edge;
    const maxEdge = constraints?.max_edge;
    if (step && (w % step !== 0 || h % step !== 0)) return true;
    if (minEdge && (w < minEdge || h < minEdge)) return true;
    if (maxEdge && (w > maxEdge || h > maxEdge)) return true;
    return false;
  })();

  return (
    <div className="space-y-5 animate-fade-up">
      {/* --------------------------------------------------------- header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">创作台</div>
          <h1 className="display mt-1.5 text-[1.65rem] leading-tight">直接提交生成任务</h1>
          <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-fg-500">
            模型、尺寸、时长与格式全部来自线上目录与配置约束；提交后可在此实时观察进度与产物。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary h-8" onClick={() => void loadCatalog()}>
            <IconRefresh size={14} className={loadingCatalog ? "animate-spin-slow" : ""} />
            刷新目录
          </button>
          <span className="flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1.5 text-2xs text-fg-500">
            <span className="h-1.5 w-1.5 rounded-full bg-jade-400" />
            {catalog.length} 个模型可用
          </span>
        </div>
      </div>

      {modelsError && <ErrorBanner message={`模型目录获取失败：${modelsError}`} onRetry={() => void loadCatalog()} />}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(340px,420px)]">
        {/* -------------------------------------------------- composer */}
        <section className="flex flex-col gap-4">
          <div className="surface p-1.5">
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4" role="tablist" aria-label="生成模式">
              {MODES.map((m) => {
                const Icon = m.icon;
                const active = mode === m.id;
                const available = modelsForMode(catalog, m.id).length > 0;
                return (
                  <button
                    key={m.id}
                    role="tab"
                    aria-selected={active}
                    className={`group relative flex flex-col items-start gap-1.5 rounded-xl border px-3 py-2.5 text-left transition-all ${
                      active
                        ? "border-amber-400/35 bg-amber-400/[0.10] text-fg-100"
                        : "border-transparent text-fg-400 hover:bg-white/[0.04] hover:text-fg-200"
                    }`}
                    onClick={() => {
                      setMode(m.id);
                      setFiles([]);
                      setTaskId(null);
                      setPolled(null);
                      setError(null);
                      setFields((f) => ({ ...f, inputMode: "text", model: "" }));
                    }}
                    disabled={loadingCatalog}
                  >
                    <span className={`flex items-center gap-2 ${active ? "text-amber-300" : ""}`}>
                      <Icon size={16} />
                      <span className="text-[0.8125rem] font-medium">{m.label}</span>
                    </span>
                    <span className="text-2xs text-fg-500">
                      {m.short} · {available ? "可用" : "无模型"}
                    </span>
                    {active && <span className="absolute inset-x-3 bottom-0 h-px bg-gradient-to-r from-transparent via-amber-400/60 to-transparent" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* prompt composer */}
          <div className="surface overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.07] px-3 py-2">
              <span className="eyebrow flex items-center gap-1.5">
                <IconSpark size={12} className="text-amber-400" />
                {isAudio ? "音乐描述" : "提示词"}
              </span>
              <div className="ml-auto flex items-center gap-1.5 text-2xs text-fg-500">
                <span className="font-mono">{promptLen}</span>
                <span>字符</span>
              </div>
            </div>
            <div className="p-3">
              <textarea
                className="field min-h-[132px] resize-y bg-transparent px-1 py-1 text-[0.875rem] leading-relaxed focus:ring-0"
                value={fields.prompt ?? ""}
                onChange={(e) => set("prompt", e.target.value)}
                placeholder={activeDef.hint}
                aria-label={isAudio ? "音乐描述" : "提示词"}
              />
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="text-2xs text-fg-600">预设</span>
                {PRESETS[mode].map((p) => (
                  <button
                    key={p.label}
                    className="rounded-lg border border-white/[0.08] bg-white/[0.02] px-2 py-1 text-2xs text-fg-400 transition-colors hover:border-white/20 hover:text-fg-100"
                    onClick={() => set("prompt", p.text)}
                    title={p.text}
                  >
                    {p.label}
                  </button>
                ))}
                <Tooltip text="清空提示词">
                  <IconButton label="清空提示词" className="ml-auto h-7 w-7" onClick={() => set("prompt", "")}>
                    <IconClose size={13} />
                  </IconButton>
                </Tooltip>
              </div>
            </div>
          </div>

          {/* model + parameters */}
          <div className="surface overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/[0.07] px-3 py-2">
              <span className="eyebrow">模型与参数</span>
              <span className="text-2xs text-fg-500">{modeModels.length} 个模型支持此模式</span>
            </div>
            <div className="space-y-4 p-3">
              <div>
                <div className="label">模型</div>
                {loadingCatalog ? (
                  <Skeleton className="h-9 w-full" />
                ) : modeModels.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-white/10 px-3 py-2.5 text-xs text-fg-500">此模式暂无可用模型</div>
                ) : (
                  <div className="space-y-2.5">
                    {[
                      { key: "media", label: "可带图 / 多图", test: (m: CatalogModel) => acceptsImages(m, mode) },
                      { key: "plain", label: "纯提示词", test: (m: CatalogModel) => !acceptsImages(m, mode) },
                    ]
                      .map((g) => ({ ...g, models: modeModels.filter(g.test) }))
                      .filter((g) => g.models.length > 0)
                      .map((g) => (
                        <div key={g.key}>
                          <div className="mb-1.5 flex items-center gap-1.5 text-2xs uppercase tracking-[0.12em] text-fg-600">
                            <span className="h-px flex-1 bg-white/[0.06]" />
                            {g.label}
                            <span className="h-px flex-1 bg-white/[0.06]" />
                          </div>
                          <div className="grid gap-1.5 sm:grid-cols-2">
                            {g.models.map((m) => {
                              const active = selectedModel?.id === m.id;
                              const c = mergedConstraints(m, mode);
                              return (
                                <button
                                  key={m.id}
                                  className={`rounded-xl border px-2.5 py-2 text-left transition-all ${
                                    active
                                      ? "border-amber-400/60 bg-amber-400/[0.10] shadow-[inset_0_0_24px_-12px_rgba(240,176,74,0.9)]"
                                      : "border-white/[0.08] bg-white/[0.02] hover:border-white/20"
                                  }`}
                                  onClick={() => set("model", m.id)}
                                  aria-pressed={active}
                                >
                                  <div className="flex items-center gap-1.5">
                                    <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-amber-400" : "bg-fg-600"}`} />
                                    <span className={`truncate font-mono text-xs ${active ? "text-amber-100" : "text-fg-100"}`}>{m.id}</span>
                                    {active && <IconCheck size={12} className="ml-auto text-amber-300" />}
                                  </div>
                                  <div className="mt-1 flex flex-wrap gap-1 text-2xs text-fg-500">
                                    {c?.size_policy && <span className="rounded border border-white/10 px-1">{c.size_policy}</span>}
                                    {c?.n_max ? <span className="rounded border border-white/10 px-1">n≤{c.n_max}</span> : null}
                                    {c?.default_size && <span className="rounded border border-white/10 px-1">{c.default_size}</span>}
                                    {c?.duration_max ? <span className="rounded border border-white/10 px-1">≤{c.duration_max}s</span> : null}
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                  </div>
                )}
              </div>

              {selectedModel && constraints && (
                <div className="rounded-xl border border-white/[0.06] bg-ink-900/50 p-2.5">
                  <div className="flex flex-wrap items-center gap-1.5 text-2xs text-fg-500">
                    <IconInfo size={11} />
                    约束来自配置：步进 <span className="font-mono text-fg-300">{constraints.size_step ?? "—"}</span> · 边缘{" "}
                    <span className="font-mono text-fg-300">
                      {constraints.min_edge ?? "—"}–{constraints.max_edge ?? "—"}
                    </span>{" "}
                    px · 上限 n <span className="font-mono text-fg-300">{constraints.n_max ?? "—"}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(constraints.output_formats ?? []).map((f) => (
                      <span key={f} className="rounded border border-white/10 px-1 py-px font-mono text-2xs text-fg-400">
                        {f}
                      </span>
                    ))}
                    {selectedModel.config?.backend && (
                      <span className="rounded border border-jade-500/25 px-1 py-px font-mono text-2xs text-jade-300">{selectedModel.config.backend}</span>
                    )}
                  </div>
                </div>
              )}

              {isImage && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <div className="label">尺寸</div>
                    <div className="flex flex-wrap gap-1.5">
                      {presets.map((p) => {
                        const active = (fields.size || "") === (p.size ?? "");
                        return (
                          <button
                            key={p.label}
                            className={`rounded-lg border px-2.5 py-1.5 text-2xs transition-colors ${
                              active
                                ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-200"
                                : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20 hover:text-fg-200"
                            }`}
                            onClick={() => set("size", p.size ?? "")}
                            aria-pressed={active}
                          >
                            <span className="mr-1.5 inline-block h-3 w-3 rounded-[2px] border border-current align-middle" style={{ aspectRatio: p.ratio }} />
                            {p.label}
                            {p.size && <span className="ml-1.5 font-mono text-fg-500">{fmtSize(p.size)}</span>}
                          </button>
                        );
                      })}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-2xs text-fg-600">自定义</span>
                      <input
                        className={`field-mono h-8 w-32 ${
                          sizeInvalid ? "border-coral-500/60 focus:border-coral-500" : ""
                        }`}
                        value={fields.size ?? ""}
                        onChange={(e) => set("size", e.target.value)}
                        placeholder={constraints?.default_size ?? "WxH"}
                        aria-label="自定义尺寸"
                        aria-invalid={sizeInvalid}
                      />
                      {constraints?.size_step ? (
                        <span className={`text-2xs ${sizeInvalid ? "text-coral-300" : "text-fg-600"}`}>
                          {sizeInvalid ? `宽高需为 ${constraints.size_step} 的倍数且在允许范围内` : `需为 ${constraints.size_step} 的倍数`}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div>
                    <div className="label">数量 n</div>
                    <div className="flex items-center gap-1.5">
                      <button
                        className="btn btn-secondary h-8 w-8 p-0"
                        onClick={() => set("n", String(Math.max(1, Number(fields.n || 1) - 1)))}
                        aria-label="减少数量"
                      >
                        <IconPlus size={13} className="rotate-45" />
                      </button>
                      <span className="w-8 text-center font-mono text-sm text-fg-100">{fields.n || "1"}</span>
                      <button
                        className="btn btn-secondary h-8 w-8 p-0"
                        onClick={() => set("n", String(Math.min(nMax, Number(fields.n || 1) + 1)))}
                        aria-label="增加数量"
                      >
                        <IconPlus size={13} />
                      </button>
                      <span className="ml-1 text-2xs text-fg-500">上限 {nMax}</span>
                    </div>
                  </div>
                  <div>
                    <div className="label">输出格式</div>
                    <div className="flex flex-wrap gap-1.5">
                      {(constraints?.output_formats ?? []).map((f) => (
                        <button
                          key={f}
                          className={`rounded-lg border px-2 py-1 font-mono text-2xs transition-colors ${
                            fields.output_format === f
                              ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-200"
                              : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20"
                          }`}
                          onClick={() => set("output_format", f)}
                          aria-pressed={fields.output_format === f}
                        >
                          {f}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="label">质量</div>
                    <div className="flex flex-wrap gap-1.5">
                      {(Object.keys(constraints?.quality_map ?? {}).length ? Object.keys(constraints?.quality_map ?? {}) : ["auto"]).map((q) => (
                        <button
                          key={q}
                          className={`rounded-lg border px-2 py-1 font-mono text-2xs transition-colors ${
                            fields.quality === q
                              ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-200"
                              : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20"
                          }`}
                          onClick={() => set("quality", q)}
                          aria-pressed={fields.quality === q}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="sm:col-span-2">
                    <div className="label">seed（可空）</div>
                    <div className="flex items-center gap-1.5">
                      <input
                        className="field-mono"
                        value={fields.seed ?? ""}
                        onChange={(e) => set("seed", e.target.value.replace(/[^\d]/g, ""))}
                        placeholder="留空则随机"
                        aria-label="seed"
                      />
                      <Tooltip text="随机生成一个 seed">
                        <IconButton label="随机 seed" onClick={() => set("seed", String(Math.floor(Math.random() * 2 ** 31)))}>
                          <IconDice size={15} />
                        </IconButton>
                      </Tooltip>
                    </div>
                  </div>
                </div>
              )}

              {isVideo && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <div className="label">输入方式</div>
                    <div className="seg w-full">
                      {[
                        { id: "text", label: "文生视频" },
                        { id: "image", label: "图生视频" },
                        { id: "reference", label: "参考生视频" },
                      ].map((o) => (
                        <button
                          key={o.id}
                          className={`seg-item flex-1 justify-center ${fields.inputMode === o.id ? "seg-item-active" : ""}`}
                          onClick={() => {
                            set("inputMode", o.id);
                            setFiles([]);
                          }}
                          aria-pressed={fields.inputMode === o.id}
                        >
                          {o.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="label">尺寸</div>
                    <div className="flex flex-wrap gap-1.5">
                      {presets.map((p) => {
                        const active = (fields.size || "") === (p.size ?? "");
                        return (
                          <button
                            key={p.label}
                            className={`rounded-lg border px-2 py-1 text-2xs transition-colors ${
                              active
                                ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-200"
                                : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20"
                            }`}
                            onClick={() => set("size", p.size ?? "")}
                            aria-pressed={active}
                          >
                            {p.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <div className="label">输出格式</div>
                    <div className="flex flex-wrap gap-1.5">
                      {(constraints?.output_formats ?? []).map((f) => (
                        <button
                          key={f}
                          className={`rounded-lg border px-2 py-1 font-mono text-2xs transition-colors ${
                            fields.output_format === f
                              ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-200"
                              : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20"
                          }`}
                          onClick={() => set("output_format", f)}
                          aria-pressed={fields.output_format === f}
                        >
                          {f}
                        </button>
                      ))}
                    </div>
                  </div>
                  {durations && (
                    <div className="sm:col-span-2">
                      <div className="label">
                        时长
                        <span className="ml-auto font-mono text-fg-300">{Number(fields.seconds || durations.def).toFixed(2)}s</span>
                      </div>
                      <input
                        type="range"
                        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-white/[0.08] accent-amber-400"
                        min={durations.min}
                        max={durations.max}
                        step={durations.step}
                        value={Number(fields.seconds || durations.def)}
                        onChange={(e) => set("seconds", String(snapDuration(Number(e.target.value), durations)))}
                        aria-label="时长"
                      />
                      <div className="mt-1 flex items-center justify-between text-2xs text-fg-600">
                        <span className="font-mono">{durations.min}s</span>
                        <span>
                          步进 {durations.step.toFixed(2)}s · 上限 {durations.max}s
                        </span>
                        <span className="font-mono">{durations.max}s</span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {isAudio && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {durations && (
                    <div className="sm:col-span-2">
                      <div className="label">
                        时长
                        <span className="ml-auto font-mono text-fg-300">{Number(fields.seconds || durations.def).toFixed(0)}s</span>
                      </div>
                      <input
                        type="range"
                        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-white/[0.08] accent-amber-400"
                        min={durations.min}
                        max={durations.max}
                        step={durations.step}
                        value={Number(fields.seconds || durations.def)}
                        onChange={(e) => set("seconds", String(snapDuration(Number(e.target.value), durations)))}
                        aria-label="时长"
                      />
                      <div className="mt-1 flex items-center justify-between text-2xs text-fg-600">
                        <span className="font-mono">{durations.min}s</span>
                        <span>上限 {durations.max}s</span>
                        <span className="font-mono">{durations.max}s</span>
                      </div>
                    </div>
                  )}
                  <div className="sm:col-span-2">
                    <div className="label">歌词（可选，支持 [Verse] 等段落标签）</div>
                    <textarea
                      className="field min-h-[88px] resize-y"
                      value={fields.lyrics ?? ""}
                      onChange={(e) => set("lyrics", e.target.value)}
                      placeholder="[Verse] ..."
                      aria-label="歌词"
                    />
                  </div>
                  <div>
                    <div className="label">seed（可空）</div>
                    <input
                      className="field-mono"
                      value={fields.seed ?? ""}
                      onChange={(e) => set("seed", e.target.value.replace(/[^\d]/g, ""))}
                      aria-label="seed"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* reference tray */}
          {needsImages && (
            <div
              className={`surface overflow-hidden transition-colors ${dragOver ? "border-amber-400/40 bg-amber-400/[0.04]" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                addFiles(e.dataTransfer.files);
              }}
            >
              <div className="flex items-center gap-2 border-b border-white/[0.07] px-3 py-2">
                <span className="eyebrow">参考托盘</span>
                <span className="text-2xs text-fg-500">
                  {mode === "image.edit" ? "第一张为编辑目标，其余为参考图" : fields.inputMode === "reference" ? "参考图（可多张）" : "首帧图"}
                </span>
                <span className="ml-auto font-mono text-2xs text-fg-500">
                  {files.length}/{maxImages}
                </span>
                <button className="btn btn-secondary h-7 px-2 text-2xs" onClick={() => fileInput.current?.click()}>
                  <IconUpload size={12} />
                  添加
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  multiple={maxImages > 1}
                  className="hidden"
                  onChange={(e) => {
                    addFiles(e.target.files ?? []);
                    e.target.value = "";
                  }}
                />
              </div>
              <div className="p-3">
                {files.length === 0 ? (
                  <button
                    type="button"
                    className="flex w-full flex-col items-center gap-2 rounded-xl border border-dashed border-white/10 bg-white/[0.015] px-4 py-8 text-center transition-colors hover:border-white/25"
                    onClick={() => fileInput.current?.click()}
                  >
                    <span className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 bg-ink-850 text-fg-500">
                      <IconUpload size={18} />
                    </span>
                    <span className="text-xs text-fg-300">拖拽图片到这里，或点击选择</span>
                    <span className="text-2xs text-fg-600">支持 PNG / JPG / WEBP，最多 {maxImages} 张</span>
                  </button>
                ) : (
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                    {files.map((f, i) => (
                      <div
                        key={f.id}
                        draggable
                        onDragStart={() => setDragIndex(i)}
                        onDragEnd={() => setDragIndex(null)}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={() => {
                          if (dragIndex !== null && dragIndex !== i) moveFile(dragIndex, i);
                          setDragIndex(null);
                        }}
                        className={`group relative overflow-hidden rounded-lg border bg-ink-950 ${
                          f.role === "target" ? "border-amber-400/45" : "border-white/[0.08]"
                        } ${dragIndex === i ? "opacity-60" : ""}`}
                      >
                        <div className="checker relative aspect-square overflow-hidden">
                          <img src={f.url} alt={f.file.name} className="h-full w-full object-cover" />
                          <span className="absolute left-1 top-1 flex items-center gap-1 rounded border border-white/15 bg-black/55 px-1 py-px text-2xs text-white/85 backdrop-blur">
                            <IconGrip size={9} />
                            {f.role === "target" ? "目标" : f.role === "first_frame" ? "首帧" : `参考 ${i + 1}`}
                          </span>
                          <button
                            className="absolute right-1 top-1 grid h-5 w-5 place-items-center rounded border border-white/20 bg-black/55 text-white/85 backdrop-blur hover:bg-black/75"
                            onClick={() => removeFile(f.id)}
                            aria-label={`移除 ${f.file.name}`}
                          >
                            <IconClose size={11} />
                          </button>
                        </div>
                        <div className="space-y-1 p-1.5">
                          <div className="truncate font-mono text-2xs text-fg-400" title={f.file.name}>
                            {truncate(f.file.name, 22)}
                          </div>
                          <div className="flex gap-1">
                            {mode === "image.edit" && (
                              <button
                                className={`rounded border px-1 py-px text-2xs ${
                                  f.role === "target"
                                    ? "border-amber-400/40 bg-amber-400/[0.12] text-amber-200"
                                    : "border-white/10 text-fg-500 hover:text-fg-200"
                                }`}
                                onClick={() => setRole(f.id, "target")}
                                aria-pressed={f.role === "target"}
                              >
                                目标
                              </button>
                            )}
                            <button
                              className={`rounded border px-1 py-px text-2xs ${
                                f.role === "first_frame"
                                  ? "border-azure-500/40 bg-azure-500/[0.12] text-azure-300"
                                  : "border-white/10 text-fg-500 hover:text-fg-200"
                              }`}
                              onClick={() => setRole(f.id, "first_frame")}
                              aria-pressed={f.role === "first_frame"}
                            >
                              首帧
                            </button>
                            <button
                              className={`rounded border px-1 py-px text-2xs ${
                                f.role === "reference"
                                  ? "border-violet-500/40 bg-violet-500/[0.12] text-violet-300"
                                  : "border-white/10 text-fg-500 hover:text-fg-200"
                              }`}
                              onClick={() => setRole(f.id, "reference")}
                              aria-pressed={f.role === "reference"}
                            >
                              参考
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                    {files.length < maxImages && (
                      <button
                        className="flex min-h-[100px] flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-white/10 bg-white/[0.015] text-2xs text-fg-500 transition-colors hover:border-white/25 hover:text-fg-300"
                        onClick={() => fileInput.current?.click()}
                      >
                        <IconPlus size={16} />
                        添加图片
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {error && <ErrorBanner message={error} />}

          {/* submit — last element of the parameter column */}
          <div className="surface flex flex-wrap items-center gap-2 border-amber-400/20 bg-ink-800/95 p-3 backdrop-blur">
            <button className="btn btn-primary h-9 px-4" onClick={() => void submit()} disabled={submitting || !selectedModel}>
              <IconSpark size={15} />
              {submitting ? "提交中…" : "提交任务"}
            </button>
            <button className="btn btn-secondary h-9" onClick={clearAll}>
              清空
            </button>
            <div className="ml-auto flex flex-wrap items-center gap-2 text-2xs text-fg-500">
              {selectedModel && (
                <>
                  <span className="font-mono text-fg-300">{selectedModel.id}</span>
                  {isImage && (
                    <span>
                      {fields.size ? fmtSize(fields.size) : "自动尺寸"} · n={fields.n || 1}
                    </span>
                  )}
                  {isVideo && (
                    <span>
                      {fields.size ? fmtSize(fields.size) : "自动尺寸"} · {fields.seconds || "—"}s
                    </span>
                  )}
                  {isAudio && <span>{fields.seconds || "—"}s</span>}
                </>
              )}
            </div>
          </div>
        </section>

        {/* ----------------------------------------------------- results */}
        <aside className="space-y-4">
          <div className="surface overflow-hidden xl:sticky xl:top-[76px]">
            <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
              <div>
                <div className="eyebrow">结果</div>
                <div className="mt-0.5 text-2xs text-fg-500">{polled ? "实时进度与产物" : "提交后在此查看"}</div>
              </div>
              {polled && (
                <button className="btn btn-ghost h-7 px-2 text-2xs" onClick={() => onOpenTask(polled.id)}>
                  打开详情
                  <IconArrowUpRight size={12} />
                </button>
              )}
            </div>

            <div className="p-4">
              {!taskId && !polled ? (
                <EmptyState
                  icon={<IconSpark size={20} />}
                  title="还没有提交任务"
                  hint="在左侧填写参数后点击提交，这里会显示实时进度与生成结果。"
                />
              ) : !polled ? (
                <div className="space-y-3" aria-busy="true">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-5 w-20" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                  <Skeleton className="h-1.5 w-full" />
                  <div className="grid grid-cols-2 gap-2">
                    <Skeleton className="aspect-square" />
                    <Skeleton className="aspect-square" />
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill status={polled.status} />
                    <span className="mono-id">{shortId(polled.id)}</span>
                    {polled.stage && <span className="text-2xs text-fg-500">阶段 {polled.stage}</span>}
                    <button className="btn btn-icon ml-auto h-7 w-7" onClick={() => onOpenTask(polled.id)} aria-label="打开详情">
                      <IconArrowUpRight size={13} />
                    </button>
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between text-2xs text-fg-500">
                      <span>{statusMeta(polled.status).label}</span>
                      <span className="font-mono text-fg-300">{Math.round(polled.progress)}%</span>
                    </div>
                    <ProgressBar value={polled.progress} animated={running} tone={polled.status === "failed" ? "amber" : "azure"} />
                    {polled.started_at && (
                      <div className="mt-1 text-2xs text-fg-600">
                        {running ? "已执行" : "耗时"} {fmtDuration((polled.finished_at ?? Date.now() / 1000) - polled.started_at)}
                      </div>
                    )}
                  </div>

                  {/* developing-print stage timeline */}
                  <ol className="space-y-1.5">
                    {stageTimeline(polled).map((s, i) => (
                      <li key={i} className="flex items-center gap-2 text-2xs">
                        <span
                          className={`grid h-4 w-4 place-items-center rounded-full border ${
                            s.state === "done"
                              ? "border-jade-500/40 bg-jade-500/[0.12] text-jade-300"
                              : s.state === "active"
                                ? "animate-breathe border-azure-500/40 bg-azure-500/[0.12] text-azure-300"
                                : s.state === "failed"
                                  ? "border-coral-500/40 bg-coral-500/[0.12] text-coral-300"
                                  : "border-white/10 text-fg-600"
                          }`}
                        >
                          {s.state === "done" ? <IconCheck size={9} /> : s.state === "failed" ? <IconAlert size={9} /> : <span className="h-1 w-1 rounded-full bg-current" />}
                        </span>
                        <span className={s.state === "pending" ? "text-fg-600" : "text-fg-300"}>{s.label}</span>
                        <span className="ml-auto font-mono text-fg-600">
                          {s.at ? new Date(s.at * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "—"}
                        </span>
                      </li>
                    ))}
                  </ol>

                  {polled.error && (
                    <div className="rounded-lg border border-coral-500/25 bg-coral-500/[0.07] p-2.5">
                      <div className="font-mono text-2xs text-coral-300">{String(polled.error.code ?? "")}</div>
                      <div className="mt-0.5 break-words text-2xs leading-relaxed text-coral-200/90">{String(polled.error.message ?? "")}</div>
                    </div>
                  )}

                  {artifacts.length > 0 && (
                    <div className="space-y-2">
                      <div className="eyebrow">产物 {artifacts.length}</div>
                      <ArtifactGallery artifacts={artifacts} prompt={polled.prompt} />
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-1.5 border-t border-white/[0.06] pt-3">
                    <button className="btn btn-secondary h-8 text-xs" onClick={reuse}>
                      <IconRefresh size={13} />
                      再次生成
                    </button>
                    {artifacts[0] && (
                      <button
                        className="btn btn-ghost h-8 text-xs"
                        onClick={async () => {
                          const seed = artifacts[0].meta?.seed;
                          if (seed !== undefined) {
                            await navigator.clipboard?.writeText(String(seed));
                            toast.push("success", "已复制 seed", String(seed));
                          }
                        }}
                      >
                        <IconSeed size={13} />
                        seed
                      </button>
                    )}
                    <button
                      className="btn btn-ghost h-8 text-xs"
                      onClick={() => void api.cancel(polled.id).catch(() => undefined)}
                      disabled={!running}
                    >
                      <IconStop size={13} />
                      取消
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="surface p-4">
            <div className="eyebrow mb-2">接口</div>
            <div className="space-y-1.5 font-mono text-2xs text-fg-400">
              <div className="flex items-center gap-1.5">
                <IconImage size={11} className="text-amber-300" />
                POST /v1/images/generations
              </div>
              <div className="flex items-center gap-1.5">
                <IconEdit size={11} className="text-violet-300" />
                POST /v1/images/edits · multipart image
              </div>
              <div className="flex items-center gap-1.5">
                <IconVideo size={11} className="text-azure-300" />
                POST /v1/videos · multipart
              </div>
              <div className="flex items-center gap-1.5">
                <IconAudio size={11} className="text-jade-300" />
                POST /v1/audio/generations
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- helpers */

function stageTimeline(detail: TaskDetail): Array<{ label: string; state: "done" | "active" | "pending" | "failed"; at: number | null }> {
  const stages: Array<{ key: string; label: string }> = [
    { key: "created", label: "创建任务" },
    { key: "submitted", label: "提交到后端" },
    { key: "running", label: "执行生成" },
    { key: "artifacts", label: "产物入库" },
  ];
  const reached = new Map<string, number>();
  for (const e of detail.events) {
    if (e.kind === "created") reached.set("created", Math.min(reached.get("created") ?? e.ts, e.ts));
    if (e.kind === "submitted") reached.set("submitted", Math.min(reached.get("submitted") ?? e.ts, e.ts));
    if (e.kind === "artifacts") reached.set("artifacts", Math.min(reached.get("artifacts") ?? e.ts, e.ts));
    if (e.kind.startsWith("status:")) reached.set("running", Math.min(reached.get("running") ?? e.ts, e.ts));
  }
  const failed = detail.status === "failed" || detail.status === "timed_out";
  const activeNow = detail.status === "queued" || detail.status === "submitting" || detail.status === "running";
  return stages.map((s) => {
    const at = reached.get(s.key) ?? null;
    let state: "done" | "active" | "pending" | "failed" = "pending";
    if (at) state = "done";
    if (failed && s.key === "running") state = "failed";
    else if (activeNow && !at) {
      if (s.key === "created") state = "done";
      else if (s.key === "submitted" && detail.status !== "queued") state = "done";
      else if (s.key === "submitted") state = "active";
      else if (s.key === "running" && detail.status === "running") state = "active";
    }
    return { label: s.label, state, at };
  });
}
