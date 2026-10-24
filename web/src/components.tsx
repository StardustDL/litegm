/** Shared presentational helpers: status pills, media previews, cards. */

import { useState } from "react";
import { Artifact } from "./api";
import {
  aspectRatio,
  artifactPrimaryUrl,
  artifactSeed,
  artifactThumbUrl,
  fmtBytes,
  statusMeta,
  taskTypeMeta,
} from "./format";
import {
  IconAlert,
  IconAudio,
  IconCheck,
  IconClock,
  IconDownload,
  IconEdit,
  IconExpand,
  IconImage,
  IconInfo,
  IconStop,
  IconUpload,
  IconVideo,
  IconWave,
} from "./icons";
import { Chip, IconButton, Lightbox, ProgressBar, useToast } from "./ui";

const STATUS_ICONS: Record<string, React.ReactNode> = {
  check: <IconCheck size={11} />,
  pulse: <IconWave size={11} />,
  upload: <IconUpload size={11} />,
  clock: <IconClock size={11} />,
  alert: <IconAlert size={11} />,
  stop: <IconStop size={11} />,
  info: <IconInfo size={11} />,
};

export function StatusPill({ status }: { status: string }) {
  const meta = statusMeta(status);
  const live = ["running", "submitting", "queued"].includes(status);
  return (
    <Chip tone={meta.tone} pulse={live}>
      {meta.label}
    </Chip>
  );
}

export function TypeTag({ type }: { type: string }) {
  const meta = taskTypeMeta(type);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono text-[0.6875rem] tracking-tight text-fg-300">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
      {meta.short}
    </span>
  );
}

/** Inline preview for an artifact: images render directly, video/audio get players. */
export function MediaPreview({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  const src = artifactPrimaryUrl(artifact);
  const height = compact ? "h-40" : "h-56";
  if (artifact.kind === "image") {
    return (
      <a href={src} target="_blank" rel="noreferrer" className="block">
        <img
          src={src}
          alt={artifact.filename}
          className={`${height} w-full rounded-lg border border-white/10 bg-ink-950 object-contain`}
        />
      </a>
    );
  }
  if (artifact.kind === "video") {
    return (
      <video
        src={src}
        controls
        preload="metadata"
        className={`${height} w-full rounded-lg border border-white/10 bg-black`}
      />
    );
  }
  if (artifact.kind === "audio") {
    return (
      <div className="rounded-lg border border-white/10 bg-ink-900 p-3">
        <div className="mb-2 text-xs text-fg-500">{artifact.filename}</div>
        <audio src={src} controls className="w-full" />
      </div>
    );
  }
  return (
    <a href={src} target="_blank" rel="noreferrer" className="text-sm text-amber-300 hover:underline">
      {artifact.filename}
    </a>
  );
}

/** Framed "print" presentation of an artifact with metadata and actions. */
export function ArtifactCard({
  artifact,
  onOpen,
}: {
  artifact: Artifact;
  onOpen?: () => void;
}) {
  const toast = useToast();
  const src = artifactPrimaryUrl(artifact);
  const seed = artifactSeed(artifact);
  const meta = taskTypeMeta(artifact.kind);
  const icon =
    artifact.kind === "video" ? <IconVideo size={20} /> : artifact.kind === "audio" ? <IconAudio size={20} /> : <IconImage size={20} />;

  return (
    <div className="group surface overflow-hidden transition-colors hover:border-white/[0.14]">
      <button
        type="button"
        onClick={onOpen}
        className="relative block w-full text-left"
        aria-label={`查看 ${artifact.filename}`}
      >
        <div className="checker relative aspect-[4/3] overflow-hidden">
          {artifact.kind === "video" ? (
            <video
              src={src}
              muted
              playsInline
              preload="metadata"
              className="h-full w-full object-cover"
              onMouseEnter={(e) => void e.currentTarget.play().catch(() => undefined)}
              onMouseLeave={(e) => {
                e.currentTarget.pause();
                e.currentTarget.currentTime = 0;
              }}
            />
          ) : artifact.kind === "audio" ? (
            <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-jade-500/10 via-ink-900 to-ink-950">
              <div className="flex h-10 items-end gap-[3px]">
                {[0.4, 0.75, 1, 0.55, 0.85, 0.35, 0.7].map((h, i) => (
                  <span
                    key={i}
                    className="w-1 rounded-full bg-jade-400/80"
                    style={{ height: `${h * 100}%` }}
                  />
                ))}
              </div>
              <span className="text-2xs uppercase tracking-[0.18em] text-jade-300/70">audio</span>
            </div>
          ) : (
            <img
              src={src}
              alt={artifact.filename}
              loading="lazy"
              className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.03]"
            />
          )}
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950/70 via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
          <div className="pointer-events-none absolute right-2 top-2 flex gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
            <span className="rounded-md border border-white/15 bg-black/50 p-1 text-white/80 backdrop-blur">
              <IconExpand size={13} />
            </span>
          </div>
          {artifact.kind === "image" && (
            <span className="pointer-events-none absolute bottom-2 left-2 rounded-md border border-white/10 bg-black/55 px-1.5 py-0.5 font-mono text-[0.65rem] text-white/75 backdrop-blur">
              {artifact.width && artifact.height ? `${artifact.width}×${artifact.height}` : "—"}
            </span>
          )}
        </div>
      </button>

      <div className="space-y-2 p-3">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md border border-white/10 bg-white/[0.04] text-fg-300">
            {icon}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-[0.72rem] text-fg-200" title={artifact.filename}>
              {artifact.filename}
            </div>
            <div className="text-2xs text-fg-500">
              {meta.label} · {fmtBytes(artifact.size_bytes)}
              {artifact.width && artifact.height ? ` · ${aspectRatio(artifact.width, artifact.height)}` : ""}
            </div>
          </div>
        </div>
        {artifact.suspicious && (
          <div className="flex items-center gap-1.5 rounded-md border border-amber-400/25 bg-amber-400/[0.08] px-2 py-1 text-2xs text-amber-300">
            <IconAlert size={12} /> 疑似全黑或空白
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <a className="btn btn-secondary h-7 flex-1 px-2 text-xs" href={src} download={artifact.filename}>
            <IconDownload size={13} />
            下载
          </a>
          {seed && (
            <button
              className="btn btn-secondary h-7 px-2 text-xs"
              title="复制 seed"
              onClick={() => {
                void navigator.clipboard?.writeText(seed);
                toast.push("success", "已复制 seed", seed);
              }}
            >
              seed
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Click-to-open gallery used by task detail and Studio results. */
export function ArtifactGallery({ artifacts, prompt }: { artifacts: Artifact[]; prompt?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {artifacts.map((a, i) => (
          <ArtifactCard key={a.id} artifact={a} onOpen={() => setOpen(i)} />
        ))}
      </div>
      {open !== null && (
        <Lightbox
          artifacts={artifacts}
          index={open}
          prompt={prompt}
          onClose={() => setOpen(null)}
          onIndex={setOpen}
        />
      )}
    </>
  );
}

export function InputImageCard({
  img,
  onPreview,
}: {
  img: {
    index: number;
    role: string | null;
    filename: string;
    size_bytes: number;
    width: number | null;
    height: number | null;
    url: string;
  };
  onPreview?: () => void;
}) {
  const isTarget = img.role === "target";
  return (
    <div className="group surface overflow-hidden">
      <button
        type="button"
        onClick={onPreview}
        className="checker relative block aspect-square w-full overflow-hidden"
        aria-label={`预览 ${img.filename}`}
      >
        <img
          src={img.url}
          alt={img.filename}
          loading="lazy"
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
        />
        <span className="absolute left-2 top-2">
          <Chip tone={isTarget ? "amber" : "violet"}>
            {isTarget ? "编辑目标" : "参考图"} #{img.index + 1}
          </Chip>
        </span>
      </button>
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate font-mono text-[0.72rem] text-fg-300">{img.filename}</div>
          <div className="text-2xs text-fg-500">
            {fmtBytes(img.size_bytes)}
            {img.width && img.height ? ` · ${img.width}×${img.height}` : ""}
          </div>
        </div>
        <IconButton label="在新窗口查看" onClick={() => window.open(img.url, "_blank")}>
          <IconExpand size={14} />
        </IconButton>
      </div>
    </div>
  );
}

export function PromptBlock({ prompt, className = "" }: { prompt: string; className?: string }) {
  const toast = useToast();
  return (
    <div className={`group relative rounded-xl border border-white/[0.07] bg-ink-950/60 p-3.5 ${className}`}>
      <div className="eyebrow mb-1.5">提示词</div>
      <div className="whitespace-pre-wrap break-words text-[0.8125rem] leading-relaxed text-fg-200">{prompt}</div>
      <button
        className="btn btn-ghost absolute right-2 top-2 h-6 px-1.5 text-2xs opacity-0 transition-opacity group-hover:opacity-100"
        onClick={() => {
          void navigator.clipboard?.writeText(prompt);
          toast.push("success", "提示词已复制");
        }}
      >
        复制
      </button>
    </div>
  );
}

export function MetricTile({
  label,
  value,
  hint,
  tone = "neutral",
  icon,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "neutral" | "good" | "warn" | "bad";
  icon?: React.ReactNode;
}) {
  const accent =
    tone === "good"
      ? "text-jade-300"
      : tone === "warn"
        ? "text-amber-300"
        : tone === "bad"
          ? "text-coral-300"
          : "text-fg-100";
  return (
    <div className="surface relative overflow-hidden p-4">
      <div className="flex items-start justify-between">
        <span className="eyebrow">{label}</span>
        {icon && <span className="text-fg-500">{icon}</span>}
      </div>
      <div className={`mt-2 font-display text-[1.55rem] font-semibold leading-none tracking-tight ${accent}`}>
        {value}
      </div>
      {hint && <div className="mt-1.5 text-2xs text-fg-500">{hint}</div>}
    </div>
  );
}

export function StageProgress({
  stage,
  progress,
  status,
}: {
  stage?: string | null;
  progress: number;
  status: string;
}) {
  const active = ["queued", "submitting", "running"].includes(status);
  const stages = ["queued", "submitting", "running", "downloading", "completed"];
  const current = Math.max(0, stages.indexOf(stage ?? ""));
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-2xs text-fg-500">
        <span>阶段：{stage ?? "—"}</span>
        <span className="font-mono">{Math.round(progress)}%</span>
      </div>
      <ProgressBar
        value={progress}
        tone={status === "failed" ? "amber" : status === "succeeded" ? "jade" : "amber"}
        animated={active}
      />
      <div className="flex gap-1">
        {stages.map((s, i) => (
          <div
            key={s}
            className={`h-0.5 flex-1 rounded-full ${
              i <= current && current >= 0 ? "bg-white/35" : "bg-white/[0.07]"
            }`}
            title={s}
          />
        ))}
      </div>
    </div>
  );
}

export function KeyValue({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.05] py-2 last:border-0">
      <span className="shrink-0 text-2xs uppercase tracking-[0.1em] text-fg-500">{label}</span>
      <span className={`min-w-0 truncate text-right text-[0.8125rem] text-fg-200 ${mono ? "font-mono" : ""}`}>
        {children}
      </span>
    </div>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h1 className="display text-[1.65rem] leading-tight">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-fg-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function IconForStatus(status: string): React.ReactNode {
  const meta = statusMeta(status);
  return STATUS_ICONS[meta.icon] ?? <IconInfo size={11} />;
}

export function TypeIcon({ type, size = 16 }: { type: string; size?: number }) {
  const meta = taskTypeMeta(type);
  const icons: Record<string, React.ReactNode> = {
    image: <IconImage size={size} />,
    edit: <IconEdit size={size} />,
    video: <IconVideo size={size} />,
    audio: <IconAudio size={size} />,
    layers: <IconImage size={size} />,
  };
  return <>{icons[meta.icon] ?? <IconImage size={size} />}</>;
}

export function ThumbSrc(a: Artifact): string {
  return artifactThumbUrl(a);
}


