/** Formatting, status vocabulary and media helpers shared by every surface. */

import { Artifact, TaskSummary } from "./api";

/* ------------------------------------------------------------------ status */

export type StatusTone = "green" | "blue" | "amber" | "red" | "gray" | "violet";

export const STATUS: Record<string, { label: string; tone: StatusTone; icon: string }> = {
  succeeded: { label: "已完成", tone: "green", icon: "check" },
  running: { label: "生成中", tone: "blue", icon: "pulse" },
  submitting: { label: "提交中", tone: "blue", icon: "upload" },
  queued: { label: "排队中", tone: "amber", icon: "clock" },
  failed: { label: "失败", tone: "red", icon: "alert" },
  cancelled: { label: "已取消", tone: "gray", icon: "stop" },
  timed_out: { label: "超时", tone: "amber", icon: "clock" },
};

export function statusMeta(status: string) {
  return STATUS[status] ?? { label: status, tone: "gray" as StatusTone, icon: "info" };
}

export function isActive(status: string): boolean {
  return ["queued", "submitting", "running"].includes(status);
}

/* --------------------------------------------------------------- task types */

export const TASK_TYPES: Record<
  string,
  { label: string; short: string; tone: StatusTone; icon: string; accent: string }
> = {
  "image.generate": { label: "文生图", short: "T2I", tone: "amber", icon: "image", accent: "#f0b04a" },
  "image.edit": { label: "图生图", short: "I2I", tone: "violet", icon: "edit", accent: "#a68cff" },
  "video.generate": { label: "视频生成", short: "VIDEO", tone: "blue", icon: "video", accent: "#5aa8ff" },
  "audio.generate": { label: "音频生成", short: "AUDIO", tone: "green", icon: "audio", accent: "#45d6c4" },
};

export function taskTypeMeta(type: string) {
  return (
    TASK_TYPES[type] ?? {
      label: type,
      short: type.split(".")[0]?.toUpperCase() ?? "TASK",
      tone: "gray" as StatusTone,
      icon: "layers",
      accent: "#a3a0a0",
    }
  );
}

/* ------------------------------------------------------------------- media */

export const ARTIFACT_KINDS: Record<string, { label: string; icon: string; tone: StatusTone }> = {
  image: { label: "图片", icon: "image", tone: "amber" },
  video: { label: "视频", icon: "video", tone: "blue" },
  audio: { label: "音频", icon: "audio", tone: "green" },
};

/** Best thumbnail URL for a task row: artifact preview, then input, then full file. */
export function taskThumb(task: TaskSummary): { url: string; kind: string } | null {
  if (task.preview?.url) return { url: task.preview.url, kind: task.preview.kind };
  if (task.input_preview?.url) return { url: task.input_preview.url, kind: task.input_preview.kind };
  return null;
}

export function artifactThumbUrl(a: Artifact, size = 384): string {
  return `/admin/api/artifacts/${a.id}/thumb?size=${size}`;
}

export function artifactPrimaryUrl(a: Artifact): string {
  return a.signed_url || a.url;
}

export function isMediaArtifact(a: Artifact): boolean {
  return a.kind === "image" || a.kind === "video" || a.kind === "audio";
}

/** Extract the seed recorded on an artifact, if the backend stored one. */
export function artifactSeed(a: Artifact): string | null {
  const seed = a.meta?.seed;
  return typeof seed === "number" || typeof seed === "string" ? String(seed) : null;
}

/* --------------------------------------------------------------- formatting */

const pad = (n: number) => String(n).padStart(2, "0");

export function fmtTime(ts: number | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}:${pad(d.getSeconds())}`;
}

export function fmtDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function fmtClock(ts: number | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtRelative(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return "—";
  const delta = Math.max(0, now - ts);
  if (delta < 45) return "刚刚";
  if (delta < 3600) return `${Math.floor(delta / 60)} 分钟前`;
  if (delta < 86400) return `${Math.floor(delta / 3600)} 小时前`;
  if (delta < 86400 * 30) return `${Math.floor(delta / 86400)} 天前`;
  return fmtDate(ts);
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${pad(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h${pad(Math.floor((s % 3600) / 60))}m`;
  return `${Math.floor(s / 86400)}d${Math.floor((s % 86400) / 3600)}h`;
}

export function fmtUptime(seconds: number | null | undefined): string {
  if (!seconds || !Number.isFinite(seconds)) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d} 天 ${h} 小时`;
  if (h) return `${h} 小时 ${m} 分`;
  return `${m} 分`;
}

export function fmtSize(size: string | null | undefined): string {
  if (!size) return "自动";
  return size.replace("x", " × ");
}

export function fmtNumber(n: number): string {
  return new Intl.NumberFormat("zh-CN").format(n);
}

export function shortId(id: string): string {
  return id.replace(/^task_/, "").slice(0, 12);
}

export function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max).trimEnd()}…`;
}

export function aspectRatio(w: number | null | undefined, h: number | null | undefined): string {
  if (!w || !h) return "—";
  const g = gcd(w, h);
  return `${w / g}:${h / g}`;
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

export function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const el = document.createElement("textarea");
  el.value = text;
  el.style.position = "fixed";
  el.style.opacity = "0";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
  return Promise.resolve();
}
