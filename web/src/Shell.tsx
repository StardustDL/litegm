/** Console shell: rail navigation, top bar, command palette and shortcuts. */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, TaskSummary } from "./api";
import { fmtRelative, shortId, statusMeta, taskThumb, taskTypeMeta, truncate } from "./format";
import {
  IconAlert,
  IconChip,
  IconCommand,
  IconGallery,
  IconKeyboard,
  IconLogo,
  IconLogout,
  IconPulse,
  IconSearch,
  IconSpark,
  IconUser,
} from "./icons";
import { Chip, Modal, MediaThumb, useToast } from "./ui";

export type View = "overview" | "tasks" | "detail" | "studio" | "system";

const NAV: Array<{
  id: Exclude<View, "detail">;
  label: string;
  hint: string;
  icon: (p: { size?: number }) => ReactNode;
  hash: string;
  key: string;
}> = [
  {
    id: "overview",
    label: "概览",
    hint: "运行脉搏与最近生成",
    icon: IconPulse,
    hash: "",
    key: "o",
  },
  {
    id: "tasks",
    label: "任务库",
    hint: "检索、对比与重跑历史任务",
    icon: IconGallery,
    hash: "tasks",
    key: "t",
  },
  {
    id: "studio",
    label: "创作台",
    hint: "直接提交生成任务",
    icon: IconSpark,
    hash: "studio",
    key: "s",
  },
  {
    id: "system",
    label: "系统",
    hint: "后端、队列、存储与路由",
    icon: IconChip,
    hash: "system",
    key: "y",
  },
];

const VIEW_LABEL: Record<View, string> = {
  overview: "概览",
  tasks: "任务库",
  detail: "任务详情",
  studio: "创作台",
  system: "系统",
};

function parseHash(): { view: View; taskId: string | null } {
  const raw = window.location.hash.replace(/^#/, "");
  const [head, ...rest] = raw.split("/");
  if (head === "tasks") return { view: rest[0] ? "detail" : "tasks", taskId: rest[0] ?? null };
  if (head === "studio") return { view: "studio", taskId: null };
  if (head === "system") return { view: "system", taskId: null };
  return { view: "overview", taskId: null };
}

export function hashFor(view: View, taskId?: string | null): string {
  if (view === "detail" && taskId) return `#tasks/${taskId}`;
  const nav = NAV.find((n) => n.id === view);
  return nav && nav.hash ? `#${nav.hash}` : "";
}

export function Shell({
  apiKey,
  live,
  onToggleLive,
  children,
  view,
  onNavigate,
  refreshKey,
}: {
  apiKey: string;
  live: boolean;
  onToggleLive: (v: boolean) => void;
  children: ReactNode;
  view: View;
  onNavigate: (view: View, taskId?: string | null) => void;
  refreshKey: number;
}) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [liveCount, setLiveCount] = useState<number | null>(null);
  const toast = useToast();

  // Live badge: number of in-flight tasks, refreshed with the app.
  useEffect(() => {
    let alive = true;
    api
      .tasks({ limit: 200 })
      .then((r) => {
        if (!alive) return;
        setLiveCount(r.items.filter((t) => ["queued", "submitting", "running"].includes(t.status)).length);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  const go = useCallback(
    (next: View, taskId?: string | null) => {
      onNavigate(next, taskId);
      setPaletteOpen(false);
      setShortcutsOpen(false);
    },
    [onNavigate],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      if (typing) return;
      if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen(true);
      } else if (e.key === "/") {
        e.preventDefault();
        setPaletteOpen(true);
      } else if (e.key.toLowerCase() === "g") {
        const onNext = (ev: KeyboardEvent) => {
          const k = ev.key.toLowerCase();
          const hit = NAV.find((n) => n.key === k);
          if (hit) {
            ev.preventDefault();
            go(hit.id);
          }
          window.removeEventListener("keydown", onNext, true);
        };
        window.addEventListener("keydown", onNext, true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  return (
    <div className="app-canvas flex min-h-full flex-col md:flex-row">
      {/* rail — bottom bar on narrow screens, fixed rail on desktop */}
      <aside className="fixed inset-x-0 bottom-0 z-40 flex h-16 items-center justify-around border-t border-white/[0.08] bg-ink-900/90 px-2 backdrop-blur-xl md:sticky md:top-0 md:h-screen md:w-[var(--rail-w)] md:shrink-0 md:flex-col md:justify-start md:border-r md:border-t-0 md:px-0 md:py-4">
        <button
          className="mb-6 hidden h-11 w-11 place-items-center rounded-xl border border-white/[0.08] bg-ink-850 shadow-lift transition-transform hover:scale-[1.04] md:grid"
          onClick={() => go("overview")}
          title="litegm 控制台"
          aria-label="返回概览"
        >
          <IconLogo size={24} />
        </button>
        <nav className="flex flex-1 items-center justify-around gap-1 md:flex-col md:items-center md:justify-start md:gap-1.5">
          {NAV.map((n) => {
            const active = view === n.id || (view === "detail" && n.id === "tasks");
            const Icon = n.icon;
            return (
              <button
                key={n.id}
                className={`rail-link group !h-14 !w-14 md:!h-[58px] md:!w-[58px] ${active ? "rail-link-active" : ""}`}
                onClick={() => go(n.id)}
                aria-label={n.label}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={20} />
                <span className="text-[0.6rem] font-medium tracking-wide">{n.label}</span>
                <span className="pointer-events-none absolute left-[calc(100%+10px)] z-50 hidden whitespace-nowrap rounded-lg border border-white/10 bg-ink-750 px-2.5 py-1.5 text-2xs text-fg-200 shadow-lift group-hover:block">
                  {n.hint}
                </span>
              </button>
            );
          })}
        </nav>
        <div className="mt-2 flex items-center gap-2 md:flex-col">
          <button
            className="rail-link hidden md:flex"
            onClick={() => setPaletteOpen(true)}
            aria-label="打开命令面板"
            title="命令面板 (⌘K)"
          >
            <IconCommand size={19} />
          </button>
          <button
            className="rail-link hidden md:flex"
            onClick={() => setShortcutsOpen(true)}
            aria-label="快捷键"
            title="快捷键 (?)"
          >
            <IconKeyboard size={19} />
          </button>
          <button
            className={`rail-link ${sessionOpen ? "rail-link-active" : ""}`}
            onClick={() => setSessionOpen(true)}
            aria-label="账户"
            title="账户与登录"
          >
            <IconUser size={19} />
          </button>
        </div>
      </aside>

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-[var(--topbar-h)] items-center gap-2 border-b border-white/[0.06] bg-ink-950/70 px-3 backdrop-blur-xl md:gap-3 md:px-5">
          <div className="hidden items-center gap-2 text-[0.8125rem] sm:flex">
            <span className="text-fg-500">litegm</span>
            <span className="text-fg-600">/</span>
            <span className="font-medium text-fg-100">{VIEW_LABEL[view]}</span>
          </div>
          <button
            className="ml-0 flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-left text-xs text-fg-500 transition-colors hover:border-white/15 hover:bg-white/[0.06] sm:ml-2 md:w-[min(46vw,420px)] md:flex-none"
            onClick={() => setPaletteOpen(true)}
          >
            <IconSearch size={15} className="shrink-0" />
            <span className="flex-1 truncate">搜索任务、模型或跳转到…</span>
            <span className="kbd hidden sm:inline-flex">⌘K</span>
          </button>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {liveCount !== null && liveCount > 0 && (
              <button
                className="hidden items-center gap-1.5 rounded-full border border-azure-500/30 bg-azure-500/10 px-2.5 py-1 text-2xs font-medium text-azure-300 sm:flex"
                onClick={() => go("tasks")}
                title="查看进行中的任务"
              >
                <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-azure-400" />
                {liveCount} 个进行中
              </button>
            )}
            <button
              className={`flex items-center gap-2 whitespace-nowrap rounded-lg border px-2.5 py-1.5 text-2xs font-medium transition-colors ${
                live
                  ? "border-jade-500/25 bg-jade-500/[0.08] text-jade-300"
                  : "border-white/10 bg-white/[0.03] text-fg-500"
              }`}
              onClick={() => {
                onToggleLive(!live);
                toast.push("info", live ? "已暂停实时刷新" : "已恢复实时刷新");
              }}
              title="实时刷新开关"
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${live ? "animate-breathe bg-jade-400" : "bg-fg-600"}`}
              />
              {live ? "实时" : "已暂停"}
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 px-3 pb-24 pt-5 md:px-5 md:pb-16 md:pt-6">{children}</main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={go}
        refreshKey={refreshKey}
      />
      <ShortcutsSheet open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <SessionModal
        open={sessionOpen}
        onClose={() => setSessionOpen(false)}
        apiKey={apiKey}
        onLogout={async () => {
          await api.logout().catch(() => undefined);
          localStorage.removeItem("litegm.api_key");
          window.location.reload();
        }}
      />
    </div>
  );
}

/* --------------------------------------------------------- command palette */

type PaletteItem = {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: ReactNode;
  run: () => void;
};

function CommandPalette({
  open,
  onClose,
  onNavigate,
  refreshKey,
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (view: View, taskId?: string | null) => void;
  refreshKey: number;
}) {
  const [q, setQ] = useState("");
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setSel(0);
    window.setTimeout(() => inputRef.current?.focus(), 30);
    api
      .tasks({ limit: 60 })
      .then((r) => setTasks(r.items))
      .catch(() => setTasks([]));
  }, [open, refreshKey]);

  const items = useMemo<PaletteItem[]>(() => {
    const nav: PaletteItem[] = NAV.map((n) => ({
      id: `nav-${n.id}`,
      label: n.label,
      hint: n.hint,
      group: "导航",
      icon: <n.icon size={16} />,
      run: () => onNavigate(n.id),
    }));
    const acts: PaletteItem[] = [
      {
        id: "act-reload",
        label: "热载配置",
        hint: "重新读取 tasks / routing / backends",
        group: "操作",
        icon: <IconSpark size={16} />,
        run: () => {
          void api.reloadConfig().catch(() => undefined);
          onNavigate("system");
        },
      },
      {
        id: "act-sweep",
        label: "清理存储",
        hint: "按保留策略移除过期产物",
        group: "操作",
        icon: <IconChip size={16} />,
        run: () => {
          void api.sweep().catch(() => undefined);
          onNavigate("system");
        },
      },
    ];
    const taskItems: PaletteItem[] = tasks.map((t) => ({
      id: `task-${t.id}`,
      label: truncate(t.prompt || "(无提示词)", 60),
      hint: `${t.model_alias} · ${statusMeta(t.status).label} · ${fmtRelative(t.created_at)}`,
      group: "任务",
      icon: (
        <MediaThumb
          src={taskThumb(t)?.url ?? null}
          kind={taskThumb(t)?.kind}
          ratio="aspect-square"
          className="h-6 w-6 rounded-md"
        />
      ),
      run: () => onNavigate("detail", t.id),
    }));
    const needle = q.trim().toLowerCase();
    const all = [...nav, ...acts, ...taskItems];
    if (!needle) return all.slice(0, 18);
    return all
      .filter(
        (i) =>
          i.label.toLowerCase().includes(needle) ||
          (i.hint ?? "").toLowerCase().includes(needle) ||
          i.group.toLowerCase().includes(needle),
      )
      .slice(0, 24);
  }, [q, tasks, onNavigate]);

  useEffect(() => {
    setSel(0);
  }, [q]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[130] flex items-start justify-center p-4 pt-[12vh]">
      <div className="absolute inset-0 animate-fade-in bg-ink-950/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-xl animate-scale-in overflow-hidden rounded-2xl border border-white/10 bg-ink-850 shadow-glass">
        <div className="flex items-center gap-2 border-b border-white/[0.07] px-3.5 py-3">
          <IconSearch size={17} className="text-fg-500" />
          <input
            ref={inputRef}
            className="flex-1 bg-transparent text-sm text-fg-100 placeholder:text-fg-600 focus:outline-none"
            placeholder="输入命令、任务提示词、模型名…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((s) => Math.min(items.length - 1, s + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((s) => Math.max(0, s - 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                items[sel]?.run();
                onClose();
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
          />
          <span className="kbd">ESC</span>
        </div>
        <div className="max-h-[52vh] overflow-y-auto py-1.5">
          {items.length === 0 && (
            <div className="px-4 py-8 text-center text-xs text-fg-500">没有匹配项</div>
          )}
          {items.map((item, i) => (
            <button
              key={item.id}
              className={`flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors ${
                i === sel ? "bg-white/[0.07]" : "hover:bg-white/[0.04]"
              }`}
              onMouseEnter={() => setSel(i)}
              onClick={() => {
                item.run();
                onClose();
              }}
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center overflow-hidden rounded-md border border-white/10 bg-white/[0.03] text-fg-300">
                {item.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8125rem] text-fg-200">{item.label}</span>
                {item.hint && <span className="block truncate text-2xs text-fg-500">{item.hint}</span>}
              </span>
              <span className="shrink-0 text-2xs uppercase tracking-wider text-fg-600">{item.group}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 border-t border-white/[0.07] bg-ink-900/60 px-3.5 py-2 text-2xs text-fg-600">
          <span>
            <span className="kbd">↑</span> <span className="kbd">↓</span> 选择
          </span>
          <span>
            <span className="kbd">↵</span> 打开
          </span>
          <span className="ml-auto">litegm 命令面板</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* -------------------------------------------------------------- shortcuts */

function ShortcutsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const rows: Array<[string, string]> = [
    ["⌘ K / /", "打开命令面板"],
    ["G 然后 O", "概览"],
    ["G 然后 T", "任务库"],
    ["G 然后 S", "创作台"],
    ["G 然后 Y", "系统"],
    ["?", "快捷键说明"],
    ["Esc", "关闭浮层"],
    ["← / →", "大图浏览切换"],
  ];
  return (
    <Modal open={open} onClose={onClose} title="键盘快捷键" subtitle="在任何页面都能使用" width="max-w-md">
      <div className="space-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-white/[0.03]">
            <span className="text-[0.8125rem] text-fg-300">{v}</span>
            <span className="kbd">{k}</span>
          </div>
        ))}
      </div>
    </Modal>
  );
}

/* ----------------------------------------------------------------- session */

function SessionModal({
  open,
  onClose,
  apiKey,
  onLogout,
}: {
  open: boolean;
  onClose: () => void;
  apiKey: string;
  onLogout: () => Promise<void>;
}) {
  const [reveal, setReveal] = useState(false);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="会话与访问"
      subtitle="当前控制台使用会话 Cookie 访问管理接口"
      width="max-w-md"
      footer={
        <button className="btn btn-danger" onClick={() => void onLogout()}>
          <IconLogout size={15} />
          退出登录
        </button>
      }
    >
      <div className="space-y-3">
        <div className="rounded-xl border border-white/[0.07] bg-ink-900/70 p-3">
          <div className="eyebrow mb-1">API 密钥</div>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate font-mono text-xs text-fg-200">
              {reveal ? apiKey : "•".repeat(Math.min(32, Math.max(8, apiKey.length)))}
            </code>
            <button className="btn btn-secondary h-7 px-2 text-2xs" onClick={() => setReveal((v) => !v)}>
              {reveal ? "隐藏" : "显示"}
            </button>
            <button
              className="btn btn-secondary h-7 px-2 text-2xs"
              onClick={() => void navigator.clipboard?.writeText(apiKey)}
            >
              复制
            </button>
          </div>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-ink-900/70 p-3 text-xs leading-relaxed text-fg-400">
          管理台通过 <span className="font-mono text-fg-200">/admin/api</span> 读写任务；生成接口位于{" "}
          <span className="font-mono text-fg-200">/v1</span>，使用 Bearer 密钥调用。
        </div>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------- login */

export function Login({ onLogin }: { onLogin: (apiKey: string) => void }) {
  const [username, setUsername] = useState("admin");
  const [key, setKey] = useState(localStorage.getItem("litegm.api_key") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username, key);
      localStorage.setItem("litegm.api_key", key);
      onLogin(key);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app-canvas flex min-h-full items-center justify-center p-6">
      <div className="relative z-10 grid w-full max-w-3xl overflow-hidden rounded-3xl border border-white/[0.08] bg-ink-850/80 shadow-glass backdrop-blur-xl md:grid-cols-[1.05fr_1fr]">
        <div className="relative hidden flex-col justify-between overflow-hidden border-r border-white/[0.06] p-8 md:flex">
          <div className="absolute inset-0 bg-[radial-gradient(120%_100%_at_0%_0%,rgba(240,176,74,0.16),transparent_60%)]" />
          <div className="relative">
            <div className="flex items-center gap-3">
              <IconLogo size={34} />
              <div>
                <div className="display text-lg">litegm</div>
                <div className="text-2xs uppercase tracking-[0.2em] text-fg-500">ComfyUI generation gateway</div>
              </div>
            </div>
            <p className="mt-8 max-w-xs text-sm leading-relaxed text-fg-400">
              私有的生成控制室：图像、视频与音频任务的统一编排、审计与产物管理。
            </p>
          </div>
          <div className="relative space-y-2">
            {[
              ["实时", "任务状态、队列与进度"],
              ["可追溯", "输入与产物的完整对照"],
              ["可控", "后端健康与存储治理"],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-xs text-fg-500">
                <span className="h-1 w-1 rounded-full bg-amber-400" />
                <span className="font-medium text-fg-300">{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
        </div>
        <form onSubmit={submit} className="space-y-4 p-8">
          <div className="md:hidden flex items-center gap-2">
            <IconLogo size={26} />
            <span className="display text-base">litegm</span>
          </div>
          <div>
            <h1 className="display text-xl">进入控制台</h1>
            <p className="mt-1 text-xs text-fg-500">使用配置中的用户名与 master key。</p>
          </div>
          <label>
            <span className="label">用户名</span>
            <input className="field" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          </label>
          <label>
            <span className="label">Master key</span>
            <div className="relative">
              <input
                type={reveal ? "text" : "password"}
                className="field pr-16"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                autoFocus
                autoComplete="current-password"
              />
              <button
                type="button"
                className="btn btn-ghost absolute right-1 top-1 h-7 px-2 text-2xs"
                onClick={() => setReveal((v) => !v)}
              >
                {reveal ? "隐藏" : "显示"}
              </button>
            </div>
          </label>
          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-coral-500/25 bg-coral-500/[0.08] p-2.5 text-xs text-coral-300">
              <IconAlert size={14} className="mt-0.5 shrink-0" />
              <span className="break-words">{error}</span>
            </div>
          )}
          <button className="btn btn-primary w-full py-2.5" disabled={busy}>
            {busy ? "验证中…" : "登录"}
          </button>
          <p className="text-center text-2xs text-fg-600">密钥只保存在本地浏览器</p>
        </form>
      </div>
    </div>
  );
}

export function TaskHashLink({ id }: { id: string }) {
  return <span className="mono-id">{shortId(id)}</span>;
}

/** Short, human label for a task type (used by the shell breadcrumb). */
export function taskTypeLabel(type: string): string {
  return taskTypeMeta(type).label;
}

export { VIEW_LABEL, parseHash };