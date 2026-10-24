/** Shared UI kit for the console: toasts, dialogs, overlays, media frames. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Artifact } from "./api";
import { fmtBytes, fmtSize } from "./format";
import {
  IconAlert,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconClose,
  IconDownload,
  IconExternal,
  IconImage,
  IconInfo,
  IconPlay,
  IconSpark,
} from "./icons";

/* ------------------------------------------------------------------ toasts */

type ToastTone = "success" | "error" | "info";
type Toast = { id: number; tone: ToastTone; title: string; detail?: string };

const ToastContext = createContext<{
  push: (tone: ToastTone, title: string, detail?: string) => void;
}>({ push: () => undefined });

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const seq = useRef(0);

  const push = useCallback((tone: ToastTone, title: string, detail?: string) => {
    const id = ++seq.current;
    setItems((list) => [...list.slice(-3), { id, tone, title, detail }]);
    window.setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), tone === "error" ? 6500 : 4200);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed bottom-5 right-5 z-[120] flex w-[min(92vw,380px)] flex-col gap-2">
          {items.map((t) => (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto animate-slide-right overflow-hidden rounded-xl border border-white/10 bg-ink-800/95 shadow-lift backdrop-blur"
            >
              <div className="flex items-start gap-2.5 p-3.5">
                <span
                  className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md ${
                    t.tone === "success"
                      ? "bg-jade-500/15 text-jade-300"
                      : t.tone === "error"
                        ? "bg-coral-500/15 text-coral-300"
                        : "bg-amber-400/15 text-amber-300"
                  }`}
                >
                  {t.tone === "success" ? (
                    <IconCheck size={14} />
                  ) : t.tone === "error" ? (
                    <IconAlert size={14} />
                  ) : (
                    <IconInfo size={14} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[0.8125rem] font-medium text-fg-100">{t.title}</div>
                  {t.detail && <div className="mt-0.5 break-words text-xs text-fg-400">{t.detail}</div>}
                </div>
                <button
                  className="btn btn-ghost h-6 w-6 p-0"
                  onClick={() => setItems((list) => list.filter((x) => x.id !== t.id))}
                  aria-label="关闭提示"
                >
                  <IconClose size={13} />
                </button>
              </div>
              <div
                className={`h-0.5 w-full ${
                  t.tone === "success" ? "bg-jade-400/60" : t.tone === "error" ? "bg-coral-400/60" : "bg-amber-400/60"
                }`}
              />
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

/* ----------------------------------------------------------------- dialogs */

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[110] flex items-center justify-center p-4">
      <div className="absolute inset-0 animate-fade-in bg-ink-950/70 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        className={`relative w-full ${width} animate-scale-in overflow-hidden rounded-2xl border border-white/10 bg-ink-800 shadow-glass`}
      >
        <div className="border-b border-white/[0.07] px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="display text-base">{title}</h2>
              {subtitle && <div className="mt-1 text-xs text-fg-400">{subtitle}</div>}
            </div>
            <button className="btn btn-icon" onClick={onClose} aria-label="关闭">
              <IconClose size={16} />
            </button>
          </div>
        </div>
        {children && <div className="px-5 py-4">{children}</div>}
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-white/[0.07] bg-ink-850/60 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  danger = true,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            取消
          </button>
          <button
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm leading-relaxed text-fg-300">{message}</div>
    </Modal>
  );
}

/* ------------------------------------------------------------------- chips */

const TONE_CLASS: Record<string, string> = {
  green: "pill-green",
  blue: "pill-blue",
  amber: "pill-amber",
  red: "pill-red",
  gray: "pill-gray",
  violet: "pill-violet",
};

export function Chip({
  tone = "gray",
  children,
  pulse = false,
  className = "",
}: {
  tone?: string;
  children: ReactNode;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={`pill ${TONE_CLASS[tone] ?? "pill-gray"} ${className}`}>
      <span
        className={`pill-dot ${
          tone === "green"
            ? "bg-jade-400"
            : tone === "blue"
              ? "bg-azure-400"
              : tone === "amber"
                ? "bg-amber-400"
                : tone === "red"
                  ? "bg-coral-400"
                  : tone === "violet"
                    ? "bg-violet-400"
                    : "bg-fg-500"
        } ${pulse ? "animate-breathe" : ""}`}
      />
      {children}
    </span>
  );
}

export function IconButton({
  label,
  children,
  onClick,
  active = false,
  danger = false,
  className = "",
}: {
  label: string;
  children: ReactNode;
  onClick: (e: React.MouseEvent) => void;
  active?: boolean;
  danger?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`btn btn-icon ${active ? "border-amber-400/30 bg-amber-400/10 text-amber-300" : ""} ${
        danger ? "hover:bg-coral-500/10 hover:text-coral-300" : ""
      } ${className}`}
    >
      {children}
    </button>
  );
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group/tt relative inline-flex">
      {children}
      <span className="pointer-events-none absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-ink-750 px-2 py-1 text-2xs text-fg-200 opacity-0 shadow-lift transition-opacity duration-150 group-hover/tt:opacity-100">
        {text}
      </span>
    </span>
  );
}

/* --------------------------------------------------------------- states */

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.015] px-6 py-14 text-center">
      <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl border border-white/10 bg-ink-850 text-fg-500">
        {icon ?? <IconSpark size={22} />}
      </div>
      <div className="text-sm font-medium text-fg-200">{title}</div>
      {hint && <div className="mt-1 max-w-sm text-xs leading-relaxed text-fg-500">{hint}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-coral-500/25 bg-coral-500/[0.08] p-3.5 text-[0.8125rem] text-coral-300">
      <IconAlert size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 break-words">{message}</div>
      {onRetry && (
        <button className="btn btn-secondary h-7 px-2 text-xs" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- progress */

export function ProgressBar({
  value,
  tone = "amber",
  animated = false,
  className = "",
}: {
  value: number;
  tone?: "amber" | "jade" | "azure";
  animated?: boolean;
  className?: string;
}) {
  const v = Math.max(0, Math.min(100, value));
  const fill =
    tone === "jade" ? "bg-jade-400" : tone === "azure" ? "bg-azure-400" : "bg-gradient-to-r from-amber-500 to-amber-300";
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07] ${className}`}>
      <div
        className={`relative h-full rounded-full ${fill} transition-[width] duration-500 ease-out`}
        style={{ width: `${v}%` }}
      >
        {animated && (
          <div className="absolute inset-0 animate-shimmer bg-sheen bg-[length:200%_100%]" />
        )}
      </div>
    </div>
  );
}

export function ProgressRing({
  value,
  size = 88,
  stroke = 6,
  tone = "#f0b04a",
  label,
}: {
  value: number;
  size?: number;
  stroke?: number;
  tone?: string;
  label?: ReactNode;
}) {
  const v = Math.max(0, Math.min(100, value));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,0.08)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={tone}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={`${(v / 100) * c} ${c}`}
          className="transition-[stroke-dasharray] duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">{label ?? <span className="mono-id">{Math.round(v)}%</span>}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ media */

export function MediaThumb({
  src,
  kind,
  alt,
  className = "",
  ratio = "aspect-square",
  fallback,
}: {
  src: string | null;
  kind?: string;
  alt?: string;
  className?: string;
  ratio?: string;
  fallback?: ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const icon = kind === "video" ? <IconPlay size={22} /> : kind === "audio" ? <IconSpark size={22} /> : <IconImage size={22} />;
  return (
    <div className={`checker relative overflow-hidden ${ratio} ${className}`}>
      {src && !failed ? (
        <img
          src={src}
          alt={alt ?? ""}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-fg-600">{fallback ?? icon}</div>
      )}
      {kind === "video" && src && !failed && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <span className="grid h-10 w-10 place-items-center rounded-full border border-white/25 bg-black/40 text-white/90 backdrop-blur-sm">
            <IconPlay size={16} />
          </span>
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- lightbox */

export function Lightbox({
  artifacts,
  index,
  onClose,
  onIndex,
  prompt,
}: {
  artifacts: Artifact[];
  index: number;
  onClose: () => void;
  onIndex: (i: number) => void;
  prompt?: string;
}) {
  const a = artifacts[index];
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    setZoom(1);
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onIndex(Math.min(artifacts.length - 1, index + 1));
      if (e.key === "ArrowLeft") onIndex(Math.max(0, index - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, artifacts.length, onClose, onIndex]);

  if (!a) return null;
  const src = a.signed_url || a.url;

  return createPortal(
    <div className="fixed inset-0 z-[115] flex flex-col bg-ink-950/95 backdrop-blur-md">
      <div className="flex items-center gap-3 border-b border-white/[0.07] px-5 py-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-fg-100">{a.filename}</div>
          <div className="mono-id mt-0.5">
            {fmtBytes(a.size_bytes)}
            {a.width && a.height ? ` · ${fmtSize(`${a.width}x${a.height}`)}` : ""}
            {` · ${a.mime_type}`}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="mr-2 text-xs text-fg-500">
            {index + 1} / {artifacts.length}
          </span>
          <button
            className="btn btn-icon"
            onClick={() => setZoom((z) => Math.max(1, +(z - 0.25).toFixed(2)))}
            aria-label="缩小"
          >
            <span className="text-sm">−</span>
          </button>
          <button
            className="btn btn-icon"
            onClick={() => setZoom((z) => Math.min(4, +(z + 0.25).toFixed(2)))}
            aria-label="放大"
          >
            <span className="text-sm">+</span>
          </button>
          <a className="btn btn-secondary" href={src} download={a.filename}>
            <IconDownload size={15} />
            下载
          </a>
          <a className="btn btn-icon" href={src} target="_blank" rel="noreferrer" aria-label="新窗口打开">
            <IconExternal size={15} />
          </a>
          <button className="btn btn-icon" onClick={onClose} aria-label="关闭">
            <IconClose size={16} />
          </button>
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto p-6">
        {index > 0 && (
          <button
            className="btn btn-icon absolute left-4 top-1/2 z-10 -translate-y-1/2 bg-ink-800/80"
            onClick={() => onIndex(index - 1)}
            aria-label="上一张"
          >
            <IconChevronLeft size={18} />
          </button>
        )}
        {index < artifacts.length - 1 && (
          <button
            className="btn btn-icon absolute right-4 top-1/2 z-10 -translate-y-1/2 bg-ink-800/80"
            onClick={() => onIndex(index + 1)}
            aria-label="下一张"
          >
            <IconChevronRight size={18} />
          </button>
        )}
        {a.kind === "video" ? (
          <video
            key={a.id}
            src={src}
            controls
            autoPlay
            className="max-h-full max-w-full rounded-lg bg-black shadow-print"
          />
        ) : a.kind === "audio" ? (
          <div className="w-full max-w-xl rounded-2xl border border-white/10 bg-ink-850 p-6">
            <div className="mb-4 flex items-center gap-3">
              <div className="grid h-12 w-12 place-items-center rounded-xl bg-jade-500/10 text-jade-300">
                <IconSpark size={20} />
              </div>
              <div>
                <div className="text-sm font-medium text-fg-100">{a.filename}</div>
                <div className="text-xs text-fg-500">音频产物</div>
              </div>
            </div>
            <audio src={src} controls autoPlay className="w-full" />
          </div>
        ) : (
          <img
            src={src}
            alt={a.filename}
            style={{ transform: `scale(${zoom})` }}
            className="max-h-full max-w-full rounded-lg object-contain shadow-print transition-transform duration-200"
          />
        )}
      </div>
      {prompt && (
        <div className="border-t border-white/[0.07] px-6 py-3">
          <div className="eyebrow mb-1">Prompt</div>
          <div className="max-h-24 overflow-y-auto text-xs leading-relaxed text-fg-300">{prompt}</div>
        </div>
      )}
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------ json viewer */

export function JsonBlock({
  value,
  collapsed = false,
  maxHeight = "max-h-96",
}: {
  value: unknown;
  collapsed?: boolean;
  maxHeight?: string;
}) {
  const [open, setOpen] = useState(!collapsed);
  const text = JSON.stringify(value, null, 2) ?? "";
  const lines = text.split("\n").length;
  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.07] bg-ink-950/80">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="pill pill-gray">{lines} 行</span>
          <span className="text-2xs text-fg-600">JSON</span>
        </div>
        <div className="flex items-center gap-1">
          <button className="btn btn-ghost h-7 px-2 text-xs" onClick={() => setOpen(!open)}>
            {open ? "折叠" : "展开"}
          </button>
          <button
            className="btn btn-ghost h-7 px-2 text-xs"
            onClick={() => navigator.clipboard?.writeText(text)}
          >
            复制
          </button>
        </div>
      </div>
      {open && (
        <pre className={`${maxHeight} overflow-auto p-3 font-mono text-[0.72rem] leading-[1.55] text-fg-300`}>
          {highlightJson(text)}
        </pre>
      )}
    </div>
  );
}

/** Very small JSON tokeniser for syntax colouring. */
export function highlightJson(text: string): ReactNode {
  const parts: ReactNode[] = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(\btrue\b|\bfalse\b|\bnull\b)|([{}[\],])/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1]) {
      const isKey = Boolean(m[2]);
      parts.push(
        <span key={key++} className={isKey ? "text-amber-300" : "text-jade-300"}>
          {m[1]}
        </span>,
      );
      if (m[2]) parts.push(<span key={key++} className="text-fg-500">{m[2]}</span>);
    } else if (m[3]) {
      parts.push(<span key={key++} className="text-violet-300">{m[3]}</span>);
    } else if (m[4]) {
      parts.push(<span key={key++} className="text-azure-300">{m[4]}</span>);
    } else if (m[5]) {
      parts.push(<span key={key++} className="text-fg-600">{m[5]}</span>);
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
