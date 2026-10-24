/** Task detail: a print-style page with artifact gallery + lightbox, input vs
 * output comparison, structured request/execution panels, an execution
 * timeline and the compiled workflow JSON, behind a sticky action bar. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Artifact, type ConfigView, type InputImage, type TaskDetail, type TaskEvent } from "./api";
import { StatusPill, TypeIcon } from "./components";
import {
  ARTIFACT_KINDS,
  artifactPrimaryUrl,
  artifactSeed,
  artifactThumbUrl,
  aspectRatio,
  copyText,
  fmtBytes,
  fmtDuration,
  fmtRelative,
  fmtSize,
  fmtTime,
  isActive,
  shortId,
  statusMeta,
  taskTypeMeta,
  truncate,
} from "./format";
import {
  IconAlert,
  IconArrowLeft,
  IconAudio,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconClock,
  IconCode,
  IconCopy,
  IconDatabase,
  IconDownload,
  IconEdit,
  IconExpand,
  IconImage,
  IconLayers,
  IconPlay,
  IconRefresh,
  IconRetry,
  IconRoute,
  IconSeed,
  IconStop,
  IconTrash,
  IconUpload,
  IconVideo,
  IconWave,
} from "./icons";
import {
  Chip,
  ConfirmDialog,
  ErrorBanner,
  IconButton,
  JsonBlock,
  Lightbox,
  MediaThumb,
  Modal,
  ProgressBar,
  Skeleton,
  Tooltip,
  useToast,
} from "./ui";

type Props = {
  id: string;
  refreshKey: number;
  onBack: () => void;
  onChanged: () => void;
  onOpen: (id: string) => void;
  onReloadConfig: () => void;
  configVersion: number;
};

/* ------------------------------------------------------------- event meta */

type EventIcon = "upload" | "pulse" | "check" | "alert" | "stop" | "clock" | "code" | "image";

const EVENT_META: Record<string, { label: string; tone: string; icon: EventIcon }> = {
  created: { label: "创建任务", tone: "gray", icon: "clock" },
  submitted: { label: "提交到后端", tone: "blue", icon: "upload" },
  queued: { label: "进入队列", tone: "amber", icon: "clock" },
  running: { label: "开始执行", tone: "blue", icon: "pulse" },
  progress: { label: "进度更新", tone: "gray", icon: "pulse" },
  comfy_text: { label: "提示词改写", tone: "violet", icon: "code" },
  "status:succeeded": { label: "执行成功", tone: "green", icon: "check" },
  "status:failed": { label: "执行失败", tone: "red", icon: "alert" },
  "status:cancelled": { label: "已取消", tone: "gray", icon: "stop" },
  "status:timed_out": { label: "执行超时", tone: "amber", icon: "clock" },
  attempt_failed: { label: "尝试失败", tone: "red", icon: "alert" },
  artifacts: { label: "产物入库", tone: "amber", icon: "image" },
  cancel_requested: { label: "请求取消", tone: "gray", icon: "stop" },
};

function eventMeta(kind: string): { label: string; tone: string; icon: EventIcon } {
  const hit = EVENT_META[kind];
  if (hit) return hit;
  if (kind.startsWith("status:")) return { label: `状态：${kind.slice(7)}`, tone: "blue", icon: "pulse" };
  return { label: kind, tone: "gray", icon: "clock" };
}

const TONE_HEX: Record<string, string> = {
  gray: "#a3a0a0",
  blue: "#5aa8ff",
  amber: "#f0b04a",
  green: "#45d6c4",
  red: "#ff6b81",
  violet: "#a68cff",
};

const TONE_PILL: Record<string, string> = {
  gray: "pill-gray",
  blue: "pill-blue",
  amber: "pill-amber",
  green: "pill-green",
  red: "pill-red",
  violet: "pill-violet",
};

/* ------------------------------------------------------------------- page */

export default function TaskDetailView({ id, refreshKey, onBack, onChanged, onOpen, onReloadConfig, configVersion }: Props) {
  const toast = useToast();
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [config, setConfig] = useState<ConfigView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [inputLightbox, setInputLightbox] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await api.task(id);
      if (!alive.current) return;
      setDetail(d);
      setError(null);
      setNotFound(false);
    } catch (err) {
      if (!alive.current) return;
      const msg = (err as Error).message;
      if (/404/.test(msg)) setNotFound(true);
      setError(msg);
    }
  }, [id]);

  useEffect(() => {
    alive.current = true;
    setDetail(null);
    setError(null);
    setNotFound(false);
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  // Poll only while the task is in flight.
  useEffect(() => {
    if (!detail || !isActive(detail.status)) return;
    const t = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(t);
  }, [detail, load]);

  useEffect(() => {
    if (refreshKey > 0 && detail) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  useEffect(() => {
    api
      .config()
      .then((c) => {
        if (alive.current) setConfig(c);
      })
      .catch(() => undefined);
  }, [configVersion]);

  const modelInfo = useMemo(() => {
    if (!config || !detail) return null;
    const models = config.tasks[detail.task_type]?.models ?? [];
    return models.find((m) => m.alias === detail.model_alias) ?? null;
  }, [config, detail]);

  /* -------------------------------------------------------------- actions */

  const cancel = async () => {
    setBusy("cancel");
    try {
      await api.cancel(id);
      toast.push("info", "已请求取消", "后端会在当前节点结束后停止");
      onChanged();
      void load();
    } catch (err) {
      toast.push("error", "取消失败", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const retry = async () => {
    setBusy("retry");
    try {
      const res = await api.retry(id);
      toast.push("success", "已重新提交", `新任务 ${shortId(res.task_id)}`);
      onChanged();
      onOpen(res.task_id);
    } catch (err) {
      toast.push("error", "重试失败", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("delete");
    try {
      const res = await api.remove(id);
      toast.push("success", "任务已删除", `释放 ${fmtBytes(res.freed_bytes)}`);
      onChanged();
      onBack();
    } catch (err) {
      toast.push("error", "删除失败", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const copy = async (text: string, label: string) => {
    await copyText(text);
    toast.push("success", `已复制${label}`, truncate(text, 48));
  };

  const downloadAll = () => {
    if (!detail) return;
    detail.artifacts.forEach((a, i) => {
      window.setTimeout(() => {
        const link = document.createElement("a");
        link.href = artifactPrimaryUrl(a);
        link.download = a.filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
      }, i * 180);
    });
    toast.push("success", "开始下载全部产物", `${detail.artifacts.length} 个文件`);
  };

  /* ------------------------------------------------------------- loading */

  if (!detail && !error) {
    return (
      <div className="space-y-5" aria-busy="true" aria-label="正在加载任务详情">
        <Skeleton className="h-10 w-2/3" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="space-y-4">
        <button className="btn btn-secondary" onClick={onBack}>
          <IconArrowLeft size={15} />
          返回任务库
        </button>
        {notFound ? (
          <div className="surface flex flex-col items-center gap-3 px-6 py-14 text-center">
            <div className="grid h-14 w-14 place-items-center rounded-2xl border border-white/10 bg-ink-850 text-fg-500">
              <IconAlert size={22} />
            </div>
            <div className="text-sm font-medium text-fg-200">任务不存在或已被删除</div>
            <div className="mono-id">{id}</div>
            <button className="btn btn-primary mt-1 h-8 text-xs" onClick={onBack}>
              回到任务库
            </button>
          </div>
        ) : (
          <ErrorBanner message={`任务加载失败：${error}`} onRetry={() => void load()} />
        )}
      </div>
    );
  }

  const typeMeta = taskTypeMeta(detail.task_type);
  const active = isActive(detail.status);
  const failed = detail.status === "failed" || detail.status === "timed_out";
  const duration =
    detail.duration_s ??
    (detail.finished_at && detail.started_at ? Math.max(0, detail.finished_at - detail.started_at) : null);
  const media = detail.artifacts.filter((a) => a.kind === "image" || a.kind === "video" || a.kind === "audio");
  const other = detail.artifacts.filter((a) => !(a.kind === "image" || a.kind === "video" || a.kind === "audio"));
  const targetInput = detail.input_images.find((i) => i.role === "target");
  const refInputs = detail.input_images.filter((i) => i.role !== "target");
  const events = [...detail.events].sort((a, b) => b.ts - a.ts);
  const visibleEvents = timelineExpanded ? events : events.slice(0, 7);
  const hero = media[0] ?? null;

  return (
    <div className="space-y-5 pb-20 animate-fade-up">
      {/* ------------------------------------------------------- header */}
      <div className="flex flex-wrap items-start gap-3">
        <button className="btn btn-secondary h-8" onClick={onBack}>
          <IconArrowLeft size={15} />
          任务库
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="eyebrow flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: typeMeta.accent }} />
              {typeMeta.label}
            </span>
            <StatusPill status={detail.status} />
            {detail.cancel_requested && <Chip tone="gray">取消已请求</Chip>}
            {detail.suspicious && (
              <Chip tone="amber">
                <IconAlert size={11} /> 疑似空白
              </Chip>
            )}
          </div>
          <h1 className="display mt-2 max-w-4xl text-[1.55rem] leading-snug">{detail.prompt || "（无提示词）"}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-fg-500">
            <button className="group inline-flex items-center gap-1.5 font-mono text-fg-400 hover:text-fg-200" onClick={() => void copy(detail.id, "任务 ID")}>
              {detail.id}
              <IconCopy size={11} className="opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
            <span className="font-mono">{detail.model_alias}</span>
            <span className="font-mono">{detail.backend_id}</span>
            <span>{fmtTime(detail.created_at)}</span>
            <span>耗时 {fmtDuration(duration)}</span>
          </div>
        </div>
      </div>

      {active && (
        <div className="surface p-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-2 text-[0.8125rem] text-fg-200">
              <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-azure-400" />
              {statusMeta(detail.status).label}
              {detail.stage && <span className="text-fg-500">· 阶段 {detail.stage}</span>}
            </span>
            <div className="min-w-[200px] flex-1">
              <ProgressBar value={detail.progress} animated tone="azure" />
            </div>
            <span className="font-mono text-xs text-fg-300">{Math.round(detail.progress)}%</span>
            <button className="btn btn-danger h-8" onClick={() => setConfirmCancel(true)} disabled={busy === "cancel"}>
              <IconStop size={14} />
              取消任务
            </button>
          </div>
        </div>
      )}

      {failed && detail.error && (
        <div className="surface overflow-hidden border-coral-500/25">
          <div className="flex flex-wrap items-center gap-2 border-b border-coral-500/20 bg-coral-500/[0.07] px-4 py-2.5">
            <IconAlert size={15} className="text-coral-300" />
            <span className="text-[0.8125rem] font-medium text-coral-200">执行失败</span>
            <span className="rounded border border-coral-500/30 bg-coral-500/10 px-1.5 py-px font-mono text-2xs text-coral-300">
              {String(detail.error.code ?? "unknown")}
            </span>
            {detail.error.status !== undefined && <span className="text-2xs text-fg-500">HTTP {String(detail.error.status)}</span>}
            <button className="btn btn-secondary ml-auto h-7 px-2 text-2xs" onClick={() => void retry()} disabled={busy === "retry"}>
              <IconRetry size={12} />
              重试此任务
            </button>
          </div>
          <div className="px-4 py-3">
            <div className="break-words font-mono text-xs leading-relaxed text-fg-200">{String(detail.error.message ?? "")}</div>
            {Array.isArray((detail.error.details as Record<string, unknown> | null)?.problems) && (
              <ul className="mt-2 space-y-1">
                {((detail.error.details as Record<string, unknown>).problems as unknown[]).map((p, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-2xs text-fg-400">
                    <IconChevronRight size={11} className="mt-0.5 shrink-0 text-coral-400" />
                    <span className="break-all font-mono">{String(p)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------- hero / comparison */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="space-y-4">
          {hero ? (
            <div className="space-y-3">
              <div className="flex items-end justify-between">
                <div>
                  <div className="eyebrow">产物</div>
                  <div className="mt-1 text-[0.8125rem] text-fg-300">
                    {media.length} 件媒体 · {fmtBytes(media.reduce((s, a) => s + a.size_bytes, 0))}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <button className="btn btn-ghost h-7 px-2 text-2xs" onClick={downloadAll}>
                    <IconDownload size={12} />
                    下载全部
                  </button>
                  <button className="btn btn-secondary h-7 px-2 text-2xs" onClick={() => setLightbox(0)}>
                    <IconExpand size={12} />
                    {media[0]?.kind === "audio" ? "播放器视图" : "大图浏览"}
                  </button>
                </div>
              </div>
              <div className={`grid gap-3 ${media.length === 1 ? "" : "sm:grid-cols-2"}`}>
                {media.map((a, i) => (
                  <PrintTile key={a.id} artifact={a} onOpen={() => setLightbox(i)} hero={media.length === 1} />
                ))}
              </div>
            </div>
          ) : (
            <div className="print-frame checker flex min-h-[280px] flex-col items-center justify-center gap-3 text-fg-600">
              {active ? (
                <>
                  <span className="grid h-14 w-14 animate-breathe place-items-center rounded-full border border-white/10 bg-ink-900/80 text-azure-300">
                    <IconWave size={22} />
                  </span>
                  <div className="text-xs text-fg-400">正在显影… 产物会在完成后出现在这里</div>
                  <div className="w-40">
                    <ProgressBar value={detail.progress} animated tone="azure" />
                  </div>
                </>
              ) : failed ? (
                <>
                  <span className="grid h-14 w-14 place-items-center rounded-full border border-coral-500/25 bg-coral-500/[0.08] text-coral-300">
                    <IconAlert size={22} />
                  </span>
                  <div className="text-xs text-fg-400">本次请求未产出文件</div>
                </>
              ) : (
                <>
                  <span className="grid h-14 w-14 place-items-center rounded-full border border-white/10 bg-ink-900/80">
                    <IconImage size={22} />
                  </span>
                  <div className="text-xs text-fg-400">没有媒体产物</div>
                </>
              )}
            </div>
          )}

          {other.length > 0 && (
            <div className="surface p-4">
              <div className="eyebrow mb-2">其他文件</div>
              <div className="space-y-1.5">
                {other.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5">
                    <IconDatabase size={14} className="text-fg-500" />
                    <span className="truncate font-mono text-2xs text-fg-300">{a.filename}</span>
                    <span className="ml-auto text-2xs text-fg-500">{fmtBytes(a.size_bytes)}</span>
                    <a className="btn btn-ghost h-6 px-1.5 text-2xs" href={artifactPrimaryUrl(a)} download={a.filename}>
                      <IconDownload size={12} />
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ------------------------------------------- input / output */}
          <div className="surface overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
              <div>
                <div className="eyebrow">输入对照</div>
                <div className="mt-1 text-[0.8125rem] text-fg-300">编辑目标与参考图 · 与最终产物逐项比对</div>
              </div>
              {detail.input_images.length === 0 && <Chip tone="gray">纯文本任务</Chip>}
            </div>
            {detail.input_images.length === 0 ? (
              <div className="flex items-center gap-3 px-4 py-6 text-xs text-fg-400">
                <span className="grid h-9 w-9 place-items-center rounded-lg border border-white/10 bg-white/[0.03] text-fg-500">
                  <IconCode size={16} />
                </span>
                本次请求没有上传图片，直接由提示词生成。
              </div>
            ) : (
              <div className="grid gap-0 md:grid-cols-2">
                <div className="space-y-3 p-4 md:border-r md:border-white/[0.06]">
                  <div className="flex items-center gap-1.5 text-2xs text-fg-500">
                    <IconUpload size={12} />
                    输入
                  </div>
                  <div className="grid grid-cols-2 gap-2.5">
                    {detail.input_images.map((img) => (
                      <InputTile key={img.index} img={img} onOpen={() => setInputLightbox(img.index)} />
                    ))}
                  </div>
                  <div className="space-y-1">
                    {detail.input_images.map((img) => (
                      <div key={img.index} className="flex items-center gap-2 text-2xs text-fg-500">
                        <span className={`pill ${img.role === "target" ? "pill-amber" : "pill-violet"}`}>
                          {img.role === "target" ? "编辑目标 <image1>" : `参考图 <image${img.index + 1}>`}
                        </span>
                        <span className="truncate font-mono text-fg-400">{img.filename}</span>
                        <span className="ml-auto font-mono">{img.width && img.height ? `${img.width}×${img.height}` : "—"}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="space-y-3 p-4">
                  <div className="flex items-center gap-1.5 text-2xs text-fg-500">
                    <IconImage size={12} />
                    输出
                  </div>
                  {media.length === 0 ? (
                    <div className="checker grid aspect-square place-items-center rounded-lg border border-white/[0.06] text-fg-600">
                      {active ? <span className="animate-breathe text-xs text-fg-400">显影中…</span> : <IconImage size={20} />}
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2.5">
                      {media.map((a, i) =>
                        a.kind === "audio" ? (
                          // Audio tiles show a player: a placeholder thumbnail would
                          // hide the only thing the artifact is good for.
                          <div key={a.id} className="print-frame group relative block overflow-hidden bg-ink-900 p-2">
                            <div className="mb-1 flex items-center gap-1 text-2xs text-jade-300">
                              <IconAudio size={11} />
                              <span className="truncate font-mono text-fg-400" title={a.filename}>
                                {a.filename}
                              </span>
                            </div>
                            <audio src={artifactPrimaryUrl(a)} controls preload="metadata" className="w-full" />
                            <button
                              type="button"
                              onClick={() => setLightbox(i)}
                              className="mt-1 text-2xs text-amber-300 hover:underline"
                            >
                              查看详情
                            </button>
                          </div>
                        ) : (
                          <button
                            key={a.id}
                            type="button"
                            onClick={() => setLightbox(i)}
                            className="print-frame group relative block overflow-hidden"
                            aria-label={`查看 ${a.filename}`}
                          >
                            <MediaThumb src={artifactThumbUrl(a, 512)} kind={a.kind} ratio="aspect-square" alt={a.filename} />
                            <span className="pointer-events-none absolute right-1.5 top-1.5 rounded border border-white/15 bg-black/50 px-1 py-px font-mono text-2xs text-white/85 backdrop-blur">
                              {a.width && a.height ? `${a.width}×${a.height}` : ARTIFACT_KINDS[a.kind]?.label ?? a.kind}
                            </span>
                          </button>
                        ),
                      )}
                    </div>
                  )}
                  <div className="space-y-1 text-2xs text-fg-500">
                    {targetInput && media[0] && targetInput.width && targetInput.height && media[0].width && media[0].height && (
                      <div className="flex items-center gap-1.5">
                        <IconEdit size={11} />
                        画幅 {targetInput.width}×{targetInput.height} → {media[0].width}×{media[0].height}（
                        {aspectRatio(media[0].width, media[0].height)}）
                      </div>
                    )}
                    {refInputs.length > 0 && (
                      <div className="flex items-center gap-1.5">
                        <IconLayers size={11} />
                        {refInputs.length} 张参考图参与合成
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ------------------------------------------------ workflow */}
          <div className="surface overflow-hidden">
            <button className="flex w-full items-center gap-2 px-4 py-3 text-left" onClick={() => setShowWorkflow((v) => !v)} aria-expanded={showWorkflow}>
              <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-fg-300">
                <IconCode size={15} />
              </span>
              <span className="text-[0.8125rem] font-medium text-fg-100">编译后的 ComfyUI workflow</span>
              <span className="text-2xs text-fg-500">{detail.workflow ? `${Object.keys(detail.workflow).length} 个节点` : "尚未编译"}</span>
              <span className="ml-auto flex items-center gap-1.5 text-2xs text-fg-500">
                {showWorkflow ? "折叠" : "展开"}
                <IconChevronDown size={13} className={`transition-transform ${showWorkflow ? "rotate-180" : ""}`} />
              </span>
            </button>
            {showWorkflow && (
              <div className="animate-fade-in border-t border-white/[0.06] p-4">
                {detail.workflow ? (
                  <JsonBlock value={detail.workflow} collapsed maxHeight="max-h-[420px]" />
                ) : (
                  <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-xs text-fg-500">
                    {active ? "任务提交后才会生成 workflow" : "本次任务没有 workflow 快照"}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* --------------------------------------------------- sidebar */}
        <aside className="space-y-4">
          <div className="surface p-4">
            <div className="eyebrow mb-2">请求参数</div>
            <div>
              <ParamRow label="请求模型">{String(detail.request.requested_model ?? detail.model_alias)}</ParamRow>
              <ParamRow label="实际路由">{detail.model_alias}</ParamRow>
              <ParamRow label="尺寸">{fmtSize(typeof detail.request.size === "string" ? detail.request.size : null)}</ParamRow>
              <ParamRow label="数量 n">{String(detail.request.n ?? 1)}</ParamRow>
              {detail.request.seconds !== undefined && detail.request.seconds !== null && (
                <ParamRow label="时长">{String(detail.request.seconds)} 秒</ParamRow>
              )}
              {detail.request.quality !== undefined && detail.request.quality !== null && (
                <ParamRow label="质量">{String(detail.request.quality)}</ParamRow>
              )}
              {detail.request.seed !== undefined && detail.request.seed !== null && (
                <ParamRow label="seed">{String(detail.request.seed)}</ParamRow>
              )}
              <ParamRow label="输出格式">{String(detail.request.output_format ?? "—")}</ParamRow>
              {detail.request.input_mode !== undefined && detail.request.input_mode !== null && (
                <ParamRow label="输入模式">{String(detail.request.input_mode)}</ParamRow>
              )}
            </div>
            <button className="btn btn-ghost mt-2 h-7 w-full px-2 text-2xs" onClick={() => void copy(JSON.stringify(detail.request, null, 2), "请求参数")}>
              <IconCopy size={12} />
              复制完整请求
            </button>
            <div className="mt-2">
              <JsonBlock value={detail.request} collapsed maxHeight="max-h-64" />
            </div>
          </div>

          {modelInfo && (
            <div className="surface p-4">
              <div className="flex items-center justify-between">
                <span className="eyebrow">模型约束</span>
                <button className="btn btn-ghost h-6 px-1.5 text-2xs" onClick={onReloadConfig}>
                  <IconRefresh size={11} />
                  热载
                </button>
              </div>
              <div className="mt-2 space-y-1.5">
                <div className="flex flex-wrap gap-1">
                  <Chip tone="gray">{modelInfo.constraints.size_policy ?? "size 未知"}</Chip>
                  <Chip tone="gray">步进 {modelInfo.constraints.size_step ?? "—"}</Chip>
                  <Chip tone="gray">
                    {modelInfo.constraints.min_edge ?? "—"}–{modelInfo.constraints.max_edge ?? "—"} px
                  </Chip>
                  <Chip tone="gray">n ≤ {modelInfo.constraints.n_max ?? "—"}</Chip>
                </div>
                <div className="text-2xs text-fg-500">
                  默认尺寸 <span className="font-mono text-fg-300">{modelInfo.constraints.default_size ?? "自动"}</span>
                </div>
                {(modelInfo.constraints.output_formats ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {(modelInfo.constraints.output_formats ?? []).map((f) => (
                      <span key={f} className="rounded border border-white/10 px-1 py-px font-mono text-2xs text-fg-400">
                        {f}
                      </span>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-1.5 text-2xs text-fg-500">
                  <IconRoute size={11} />
                  <span className="font-mono">{modelInfo.backend}</span>
                  {modelInfo.fallbacks?.length ? <span>→ {modelInfo.fallbacks.join(" → ")}</span> : <span>无回退</span>}
                </div>
              </div>
            </div>
          )}

          <div className="surface p-4">
            <div className="eyebrow mb-2">执行</div>
            <div>
              <ParamRow label="创建">{fmtTime(detail.created_at)}</ParamRow>
              <ParamRow label="开始">{fmtTime(detail.started_at)}</ParamRow>
              <ParamRow label="完成">{fmtTime(detail.finished_at)}</ParamRow>
              <ParamRow label="耗时">{fmtDuration(duration)}</ParamRow>
              <ParamRow label="ComfyUI prompt">
                {detail.comfy_prompt_id ? (
                  <button
                    className="inline-flex min-w-0 items-center gap-1 hover:text-fg-100"
                    title={detail.comfy_prompt_id}
                    onClick={() => void copy(detail.comfy_prompt_id ?? "", "prompt id")}
                  >
                    <span className="truncate">{detail.comfy_prompt_id}</span>
                    <IconCopy size={11} className="shrink-0" />
                  </button>
                ) : (
                  "—"
                )}
              </ParamRow>
            </div>
            {detail.attempts.length > 0 && (
              <div className="mt-3 space-y-1.5">
                <div className="label">尝试记录</div>
                {detail.attempts.map((a, i) => {
                  const status = String(a.status ?? "unknown");
                  const meta = statusMeta(status);
                  const started = typeof a.started_at === "number" ? a.started_at : null;
                  const finished = typeof a.finished_at === "number" ? a.finished_at : null;
                  const err = a.error && typeof a.error === "object" ? (a.error as Record<string, unknown>) : null;
                  return (
                    <div key={i} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-2xs text-fg-300">{String(a.alias ?? "—")}</span>
                        <span className={`pill ${TONE_PILL[meta.tone]}`}>{meta.label}</span>
                        <span className="ml-auto font-mono text-2xs text-fg-500">{started && finished ? fmtDuration(finished - started) : "—"}</span>
                      </div>
                      {err && <div className="mt-1 break-all font-mono text-2xs text-coral-300">{String(err.message ?? "")}</div>}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* ----------------------------------------------------- timeline */}
      <section className="surface overflow-hidden" aria-label="执行时间线">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.07] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-fg-300">
              <IconClock size={15} />
            </span>
            <div>
              <div className="text-[0.8125rem] font-medium text-fg-100">执行时间线</div>
              <div className="text-2xs text-fg-500">{events.length} 条事件 · 倒序</div>
            </div>
          </div>
          {events.length > 7 && (
            <button className="btn btn-ghost h-7 px-2 text-2xs" onClick={() => setTimelineExpanded((v) => !v)}>
              {timelineExpanded ? "收起" : `展开全部 ${events.length} 条`}
            </button>
          )}
        </div>
        {events.length === 0 ? (
          <div className="px-4 py-8 text-xs text-fg-500">没有记录到事件</div>
        ) : (
          <ol className="relative px-4 py-3">
            <span className="pointer-events-none absolute bottom-6 left-[1.6rem] top-6 w-px bg-gradient-to-b from-white/[0.12] via-white/[0.06] to-transparent" />
            {visibleEvents.map((e, i) => (
              <TimelineRow key={`${e.kind}-${e.ts}-${i}`} event={e} prev={visibleEvents[i + 1]} first={i === 0} />
            ))}
          </ol>
        )}
      </section>

      {/* ------------------------------------------------- raw JSON */}
      <section className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="eyebrow mb-2">原始事件</div>
          <JsonBlock value={detail.events} collapsed maxHeight="max-h-72" />
        </div>
        <div>
          <div className="eyebrow mb-2">产物元数据</div>
          <JsonBlock value={detail.artifacts.map((a) => ({ id: a.id, filename: a.filename, meta: a.meta }))} collapsed maxHeight="max-h-72" />
        </div>
      </section>

      {/* ------------------------------------------------- sticky bar */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-white/[0.08] bg-ink-900/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2 px-5 py-2.5">
          <span className="flex items-center gap-2 text-2xs text-fg-500">
            <StatusPill status={detail.status} />
            <span className="mono-id hidden sm:inline">{shortId(detail.id)}</span>
            <span className="hidden md:inline">· {typeMeta.label}</span>
            <span className="hidden md:inline">· {fmtRelative(detail.created_at)}</span>
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <button className="btn btn-secondary h-8" onClick={() => void copy(detail.id, "任务 ID")}>
              <IconCopy size={14} />
              复制 ID
            </button>
            {media.length > 0 && (
              <button className="btn btn-secondary h-8" onClick={downloadAll}>
                <IconDownload size={14} />
                下载全部
              </button>
            )}
            <button className="btn btn-secondary h-8" disabled={!active || busy === "cancel"} onClick={() => setConfirmCancel(true)}>
              <IconStop size={14} />
              取消
            </button>
            <button className="btn btn-primary h-8" disabled={active || busy === "retry"} onClick={() => void retry()}>
              <IconRetry size={14} />
              重试
            </button>
            <button className="btn btn-danger h-8" disabled={busy === "delete"} onClick={() => setConfirmDelete(true)}>
              <IconTrash size={14} />
              删除
            </button>
          </div>
        </div>
      </div>

      {lightbox !== null && media.length > 0 && (
        <Lightbox
          artifacts={media}
          index={Math.min(lightbox, media.length - 1)}
          prompt={detail.prompt}
          onClose={() => setLightbox(null)}
          onIndex={setLightbox}
        />
      )}
      {inputLightbox !== null && detail.input_images[inputLightbox] && (
        <InputLightbox inputs={detail.input_images} index={inputLightbox} onClose={() => setInputLightbox(null)} onIndex={setInputLightbox} />
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="删除该任务？"
        message="将移除该任务的产物与上传文件，任务记录保留。此操作不可撤销。"
        confirmLabel="删除任务"
        onConfirm={() => void remove()}
        onClose={() => setConfirmDelete(false)}
      />
      <ConfirmDialog
        open={confirmCancel}
        title="取消该任务？"
        message="将向后端请求取消；当前正在执行的节点结束后停止，已产出的部分文件会保留。"
        danger={false}
        confirmLabel="取消任务"
        onConfirm={() => void cancel()}
        onClose={() => setConfirmCancel(false)}
      />
    </div>
  );
}

/* --------------------------------------------------------------- pieces */

function ParamRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.05] py-1.5 last:border-0">
      <span className="shrink-0 text-2xs uppercase tracking-[0.1em] text-fg-500">{label}</span>
      <span className="flex min-w-0 items-center justify-end gap-1 text-right font-mono text-xs text-fg-200">
        {children}
      </span>
    </div>
  );
}

function PrintTile({ artifact, onOpen, hero }: { artifact: Artifact; onOpen: () => void; hero: boolean }) {
  const toast = useToast();
  const seed = artifactSeed(artifact);
  const kindMeta = ARTIFACT_KINDS[artifact.kind];
  const ratio = artifact.width && artifact.height ? `${artifact.width} / ${artifact.height}` : "4 / 3";
  const isAudio = artifact.kind === "audio";
  return (
    <figure className={`print-frame group ${hero ? "mx-auto w-full max-w-[720px]" : ""}`}>
      {isAudio ? (
        // Audio has no visual frame to show: render the player inline instead of
        // the placeholder thumbnail so the artifact is playable from the page.
        <div className="flex flex-col gap-2 bg-ink-900 p-3">
          <audio
            src={artifactPrimaryUrl(artifact)}
            controls
            preload="metadata"
            className="w-full"
            aria-label={`播放 ${artifact.filename}`}
          />
          <div className="flex items-center justify-between text-2xs text-fg-500">
            <span className="truncate font-mono" title={artifact.filename}>
              {artifact.filename}
            </span>
            <button type="button" className="shrink-0 text-amber-300 hover:underline" onClick={onOpen}>
              查看详情
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={onOpen}
          className="relative block w-full overflow-hidden"
          style={{ aspectRatio: hero ? ratio : "4 / 3", maxHeight: hero ? "520px" : undefined }}
          aria-label={`大图查看 ${artifact.filename}`}
        >
          <MediaThumb src={artifactThumbUrl(artifact, 768)} kind={artifact.kind} ratio="h-full" className="!aspect-auto" alt={artifact.filename} />
          {artifact.kind === "video" && (
            <span className="pointer-events-none absolute inset-0 grid place-items-center">
              <span className="grid h-14 w-14 place-items-center rounded-full border border-white/25 bg-black/45 text-white/90 backdrop-blur-sm transition-transform duration-200 group-hover:scale-105">
                <IconPlay size={20} />
              </span>
            </span>
          )}
          <span className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950/60 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
          <span className="pointer-events-none absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-md border border-white/20 bg-black/50 text-white/90 opacity-0 backdrop-blur transition-opacity group-hover:opacity-100">
            <IconExpand size={13} />
          </span>
          {artifact.suspicious && (
            <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded border border-amber-400/40 bg-black/55 px-1.5 py-0.5 text-2xs text-amber-300 backdrop-blur">
              <IconAlert size={10} />
              疑似空白
            </span>
          )}
        </button>
      )}
      <figcaption className="flex items-center gap-2 border-t border-white/[0.06] bg-ink-900/60 px-2.5 py-1.5">
        <span className="inline-flex items-center gap-1 text-2xs text-fg-400">
          {artifact.kind === "video" ? <IconVideo size={11} /> : artifact.kind === "audio" ? <IconAudio size={11} /> : <IconImage size={11} />}
          {kindMeta?.label ?? artifact.kind}
        </span>
        <span className="truncate font-mono text-2xs text-fg-400" title={artifact.filename}>
          {artifact.filename}
        </span>
        <span className="ml-auto shrink-0 font-mono text-2xs text-fg-500">
          {artifact.width && artifact.height ? `${artifact.width}×${artifact.height}` : fmtBytes(artifact.size_bytes)}
        </span>
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          {seed && (
            <Tooltip text={`seed ${seed}`}>
              <IconButton
                label="复制 seed"
                className="h-6 w-6"
                onClick={async (e) => {
                  e.stopPropagation();
                  await copyText(seed);
                  toast.push("success", "已复制 seed", seed);
                }}
              >
                <IconSeed size={12} />
              </IconButton>
            </Tooltip>
          )}
          <a className="btn btn-icon h-6 w-6" href={artifactPrimaryUrl(artifact)} download={artifact.filename} aria-label="下载">
            <IconDownload size={12} />
          </a>
        </div>
      </figcaption>
    </figure>
  );
}

function InputTile({ img, onOpen }: { img: InputImage; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="print-frame group relative block overflow-hidden text-left" aria-label={`预览输入 ${img.filename}`}>
      <div className="checker relative aspect-square overflow-hidden">
        <img src={img.url} alt={img.filename} loading="lazy" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" />
        <span className="absolute left-1.5 top-1.5">
          <span className={`pill ${img.role === "target" ? "pill-amber" : "pill-violet"}`}>{img.role === "target" ? "编辑目标" : "参考图"}</span>
        </span>
      </div>
      <div className="flex items-center gap-1.5 border-t border-white/[0.06] bg-ink-900/60 px-2 py-1">
        <span className="truncate font-mono text-2xs text-fg-400">{img.filename}</span>
        <span className="ml-auto shrink-0 font-mono text-2xs text-fg-500">{fmtBytes(img.size_bytes)}</span>
      </div>
    </button>
  );
}

function InputLightbox({
  inputs,
  index,
  onClose,
  onIndex,
}: {
  inputs: InputImage[];
  index: number;
  onClose: () => void;
  onIndex: (i: number) => void;
}) {
  const img = inputs[index];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onIndex(Math.min(inputs.length - 1, index + 1));
      if (e.key === "ArrowLeft") onIndex(Math.max(0, index - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, inputs.length, onClose, onIndex]);
  if (!img) return null;
  return (
    <Modal
      open
      onClose={onClose}
      title={img.filename}
      subtitle={`${img.role === "target" ? "编辑目标" : "参考图"} · ${img.width && img.height ? `${img.width}×${img.height}` : "—"} · ${fmtBytes(img.size_bytes)}`}
      width="max-w-4xl"
      footer={
        <>
          <button className="btn btn-secondary" disabled={index === 0} onClick={() => onIndex(index - 1)}>
            上一张
          </button>
          <span className="text-2xs text-fg-500">
            {index + 1} / {inputs.length}
          </span>
          <button className="btn btn-secondary" disabled={index === inputs.length - 1} onClick={() => onIndex(index + 1)}>
            下一张
          </button>
          <a className="btn btn-primary" href={img.url} download={img.filename}>
            <IconDownload size={14} />
            下载
          </a>
        </>
      }
    >
      <div className="checker overflow-hidden rounded-xl border border-white/[0.08]">
        <img src={img.url} alt={img.filename} className="max-h-[62vh] w-full object-contain" />
      </div>
    </Modal>
  );
}

function TimelineRow({ event, prev, first }: { event: TaskEvent; prev?: TaskEvent; first: boolean }) {
  const meta = eventMeta(event.kind);
  const color = TONE_HEX[meta.tone] ?? "#a3a0a0";
  const gap = prev ? event.ts - prev.ts : null;
  return (
    <li className="relative flex gap-3 py-2">
      <span className="relative z-10 mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full border bg-ink-900" style={{ borderColor: `${color}66`, color }}>
        {meta.icon === "upload" ? (
          <IconUpload size={12} />
        ) : meta.icon === "pulse" ? (
          <IconWave size={12} />
        ) : meta.icon === "check" ? (
          <IconCheck size={12} />
        ) : meta.icon === "alert" ? (
          <IconAlert size={12} />
        ) : meta.icon === "stop" ? (
          <IconStop size={12} />
        ) : meta.icon === "code" ? (
          <IconCode size={12} />
        ) : meta.icon === "image" ? (
          <IconImage size={12} />
        ) : (
          <IconClock size={12} />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[0.8125rem] font-medium text-fg-100">{meta.label}</span>
          {first && <span className="rounded border border-white/10 px-1 py-px text-2xs text-fg-500">最新</span>}
          <span className="ml-auto font-mono text-2xs text-fg-400">{fmtTime(event.ts)}</span>
          {gap !== null && <span className="font-mono text-2xs text-fg-600">+{gap.toFixed(2)}s</span>}
        </div>
        <div className="mt-0.5 text-2xs text-fg-600">{fmtRelative(event.ts)}</div>
        <EventDetail event={event} />
      </div>
    </li>
  );
}

function EventDetail({ event }: { event: TaskEvent }) {
  const d = event.data;
  if (!d) return null;
  if (event.kind === "artifacts") {
    const ids = Array.isArray(d.ids) ? (d.ids as unknown[]).map(String) : [];
    const promptIds = Array.isArray(d.prompt_ids) ? (d.prompt_ids as unknown[]).map(String) : [];
    return (
      <div className="mt-1 space-y-1">
        {ids.map((artId) => (
          <div key={artId} className="flex items-center gap-1.5 text-2xs text-fg-400">
            <IconImage size={11} className="text-amber-300" />
            <span className="font-mono">{artId}</span>
          </div>
        ))}
        {promptIds.length > 0 && <div className="font-mono text-2xs text-fg-600">prompt {shortId(promptIds[0])}</div>}
      </div>
    );
  }
  if (event.kind === "comfy_text") {
    const entries = Object.entries(d).filter(([, v]) => typeof v === "string");
    return (
      <div className="mt-1 space-y-1">
        {entries.map(([node, text]) => (
          <div key={node} className="rounded-md border border-violet-500/20 bg-violet-500/[0.06] px-2 py-1">
            <div className="text-2xs text-violet-300">节点 {node} 输出的提示词</div>
            <div className="mt-0.5 line-clamp-3 whitespace-pre-wrap break-words text-2xs leading-relaxed text-fg-300">{String(text)}</div>
          </div>
        ))}
      </div>
    );
  }
  if (event.kind === "submitted") {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-fg-400">
        <span className="font-mono">{String(d.alias ?? "")}</span>
        <span className="font-mono text-fg-600">{shortId(String(d.prompt_id ?? ""))}</span>
        {d.index !== undefined && <span className="text-fg-600">#{String(d.index)}</span>}
      </div>
    );
  }
  if (event.kind.startsWith("status:")) {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-fg-400">
        {d.stage !== undefined && <span>阶段 {String(d.stage)}</span>}
        {d.progress !== undefined && <span className="font-mono">{String(d.progress)}%</span>}
        {d.code !== undefined && <span className="font-mono text-coral-300">{String(d.code)}</span>}
      </div>
    );
  }
  if (event.kind === "attempt_failed") {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-fg-400">
        <span className="font-mono">{String(d.alias ?? "")}</span>
        <span className="rounded border border-coral-500/25 bg-coral-500/[0.07] px-1 font-mono text-coral-300">{String(d.code ?? "")}</span>
      </div>
    );
  }
  if (event.kind === "created") {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-fg-400">
        <span className="font-mono">{String(d.model ?? "")}</span>
        <span>n = {String(d.n ?? 1)}</span>
      </div>
    );
  }
  return <div className="mt-1 break-all font-mono text-2xs text-fg-500">{truncate(JSON.stringify(d), 180)}</div>;
}
