/** System control room: backend health + queue lanes, storage budget and
 * retention, routing/model tables with capability badges, config hot reload
 * and manual storage sweep. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type BackendHealth,
  type ConfigView,
  type HealthResponse,
  type QueueStats,
  type StorageStats,
  type TaskModel,
} from "./api";
import { QueueLanes, RadialMeter, Sparkline, StackBar } from "./charts";
import { Chip } from "./ui";
import {
  fmtBytes,
  fmtDuration,
  fmtNumber,
  fmtUptime,
  taskTypeMeta,
  TASK_TYPES,
  truncate,
} from "./format";
import {
  IconAlert,
  IconArrowUpRight,
  IconBolt,
  IconCheck,
  IconChip,
  IconClock,
  IconDatabase,
  IconInfo,
  IconRefresh,
  IconRoute,
  IconServer,
  IconSliders,
  IconTerminal,
  IconTrash,
} from "./icons";
import { ConfirmDialog, ErrorBanner, Skeleton, useToast } from "./ui";

type Props = { refreshKey: number };

type Snapshot = { health: HealthResponse; storage: StorageStats; config: ConfigView };

const POLL_MS = 8000;

function capabilityBadges(model: TaskModel, task: string) {
  const c = model.constraints;
  const badges: Array<{ label: string; tone: string }> = [];
  if (c.n_max) badges.push({ label: `n≤${c.n_max}`, tone: "gray" });
  if (c.size_policy) badges.push({ label: c.size_policy, tone: "gray" });
  if (c.duration_max) badges.push({ label: `≤${c.duration_max}s`, tone: "blue" });
  if (c.output_formats?.length) badges.push({ label: c.output_formats.join("/"), tone: "gray" });
  if (model.fallbacks?.length) badges.push({ label: `回退 ${model.fallbacks.length}`, tone: "amber" });
  if (task === "image.edit") badges.push({ label: "需输入图", tone: "violet" });
  if (c.quality_map && Object.keys(c.quality_map).length) badges.push({ label: "质量档", tone: "violet" });
  return badges;
}

export default function System({ refreshKey }: Props) {
  const toast = useToast();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmSweep, setConfirmSweep] = useState(false);
  const [reloadResult, setReloadResult] = useState<{ ok: boolean; restart_required: string[] } | null>(null);
  const [tab, setTab] = useState<"routing" | "models" | "retention">("routing");
  const [taskFilter, setTaskFilter] = useState("");
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const [health, storage, config] = await Promise.all([api.health(), api.storage(), api.config()]);
      if (!alive.current) return;
      setSnap({ health, storage, config });
      setError(null);
    } catch (err) {
      if (!alive.current) return;
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [load]);

  useEffect(() => {
    if (refreshKey > 0 && snap) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const reload = async () => {
    setBusy("reload");
    setReloadResult(null);
    try {
      const res = await api.reloadConfig();
      setReloadResult(res);
      if (res.restart_required.length) {
        toast.push("info", "配置已热载", `以下变更需重启：${res.restart_required.join(", ")}`);
      } else {
        toast.push("success", "配置已热载", "tasks / routing / backends 已生效，无需重启");
      }
      await load();
    } catch (err) {
      toast.push("error", "热载失败", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const sweep = async () => {
    setBusy("sweep");
    try {
      const res = await api.sweep();
      const removed = res.removed ?? {};
      const freed = res.removed?.bytes ?? 0;
      toast.push(
        "success",
        "存储清理完成",
        `移除产物 ${removed.artifacts ?? 0} 个 · 输入图 ${removed.input_images ?? 0} 个 · 释放 ${fmtBytes(freed)}`,
      );
      await load();
    } catch (err) {
      toast.push("error", "清理失败", (err as Error).message);
    } finally {
      setBusy(null);
      setConfirmSweep(false);
    }
  };

  const derived = useMemo(() => {
    if (!snap) return null;
    const backends = Object.entries(snap.health.backends ?? {});
    const healthy = backends.filter(([, b]) => b.healthy).length;
    const queues = snap.health.queues ?? {};
    const totalRunning = Object.values(queues).reduce((s, q) => s + (q.running ?? 0), 0);
    const totalWaiting = Object.values(queues).reduce((s, q) => s + (q.waiting ?? 0), 0);
    const capacity = Object.values(queues).reduce((s, q) => s + (q.concurrency ?? 0), 0);
    const limit = snap.storage.limits.max_bytes;
    const usedPct = limit ? (snap.storage.usage.total_bytes / limit) * 100 : null;
    const taskCounts = Object.entries(snap.health.tasks ?? {});
    const models: Array<{ task: string; model: TaskModel }> = [];
    for (const [task, cfg] of Object.entries(snap.config.tasks ?? {})) {
      for (const m of cfg.models ?? []) models.push({ task, model: m });
    }
    return { backends, healthy, queues, totalRunning, totalWaiting, capacity, limit, usedPct, taskCounts, models };
  }, [snap]);

  if (!snap && !error) {
    return (
      <div className="space-y-5" aria-busy="true" aria-label="正在加载系统状态">
        <Skeleton className="h-9 w-56" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!snap || !derived) {
    return <ErrorBanner message={`系统状态加载失败：${error ?? "未知错误"}`} onRetry={() => void load()} />;
  }

  const d = derived;
  const uptime = snap.health.uptime_s;
  const failedCount = snap.health.tasks?.failed ?? 0;
  const succeededCount = snap.health.tasks?.succeeded ?? 0;
  const totalFinished = failedCount + succeededCount;
  const errorRate = totalFinished ? (failedCount / totalFinished) * 100 : 0;

  return (
    <div className="space-y-5 animate-fade-up">
      {error && <ErrorBanner message={`状态刷新失败：${error}`} onRetry={() => void load()} />}

      {/* --------------------------------------------------------- header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">系统</div>
          <h1 className="display mt-1.5 text-[1.65rem] leading-tight">控制室</h1>
          <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-fg-500">
            后端健康、队列容量、磁盘预算与路由配置。所有数值来自网关实时接口，每 {POLL_MS / 1000} 秒刷新。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1.5 text-2xs text-fg-500">
            <IconClock size={12} />
            运行 {fmtUptime(uptime)}
          </span>
          <span className="flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1.5 font-mono text-2xs text-fg-400">
            v{snap.health.version}
          </span>
          <button className="btn btn-secondary h-8" onClick={() => void load()}>
            <IconRefresh size={14} />
            刷新
          </button>
          <button className="btn btn-primary h-8" onClick={() => void reload()} disabled={busy === "reload"}>
            <IconBolt size={14} />
            {busy === "reload" ? "热载中…" : "热载配置"}
          </button>
          <button className="btn btn-secondary h-8" onClick={() => setConfirmSweep(true)} disabled={busy === "sweep"}>
            <IconTrash size={14} />
            清理存储
          </button>
        </div>
      </div>

      {reloadResult && (
        <div
          className={`flex flex-wrap items-center gap-2 rounded-xl border px-3.5 py-2.5 text-xs ${
            reloadResult.restart_required.length
              ? "border-amber-400/25 bg-amber-400/[0.07] text-amber-200"
              : "border-jade-500/25 bg-jade-500/[0.07] text-jade-200"
          }`}
        >
          {reloadResult.restart_required.length ? <IconAlert size={14} /> : <IconCheck size={14} />}
          <span className="font-medium">{reloadResult.restart_required.length ? "已热载，但部分变更需重启" : "配置热载成功"}</span>
          {reloadResult.restart_required.length > 0 && (
            <span className="font-mono text-2xs">{reloadResult.restart_required.join(" · ")}</span>
          )}
          <button className="btn btn-ghost ml-auto h-6 px-1.5 text-2xs" onClick={() => setReloadResult(null)}>
            关闭
          </button>
        </div>
      )}

      {/* ----------------------------------------------------- top tiles */}
      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" aria-label="运行指标">
        <div className="surface p-4">
          <div className="flex items-start justify-between">
            <span className="eyebrow">后端</span>
            <IconServer size={16} className="text-fg-500" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`display text-[1.6rem] leading-none ${d.healthy === d.backends.length ? "text-jade-300" : "text-amber-300"}`}>
              {d.healthy}/{d.backends.length}
            </span>
            <span className="text-xs text-fg-500">在线</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {d.backends.map(([id, b]) => (
              <span
                key={id}
                className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-2xs ${
                  b.healthy ? "border-jade-500/30 bg-jade-500/[0.08] text-jade-300" : "border-coral-500/30 bg-coral-500/[0.08] text-coral-300"
                }`}
              >
                <span className={`h-1 w-1 rounded-full ${b.healthy ? "bg-jade-400" : "bg-coral-400"}`} />
                {id}
              </span>
            ))}
          </div>
        </div>

        <div className="surface p-4">
          <div className="flex items-start justify-between">
            <span className="eyebrow">队列</span>
            <IconBolt size={16} className="text-fg-500" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="display text-[1.6rem] leading-none">{fmtNumber(d.totalRunning)}</span>
            <span className="text-xs text-fg-500">执行 · 等待 {fmtNumber(d.totalWaiting)}</span>
          </div>
          <div className="mt-3">
            <StackBar
              segments={[
                { label: "执行", value: d.totalRunning, tone: "jade" },
                { label: "等待", value: d.totalWaiting, tone: "amber" },
                { label: "空闲", value: Math.max(0, d.capacity - d.totalRunning), tone: "gray" },
              ]}
              ariaLabel={`执行 ${d.totalRunning}，等待 ${d.totalWaiting}，并发上限 ${d.capacity}`}
            />
          </div>
          <div className="mt-1.5 text-2xs text-fg-500">并发上限 {d.capacity}</div>
        </div>

        <div className="surface p-4">
          <div className="flex items-start justify-between">
            <span className="eyebrow">磁盘预算</span>
            <IconDatabase size={16} className="text-fg-500" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="display text-[1.6rem] leading-none text-fg-100">{fmtBytes(snap.storage.usage.total_bytes)}</span>
            {d.usedPct !== null && (
              <span className={`text-xs ${d.usedPct > 85 ? "text-coral-300" : "text-fg-500"}`}>
                / {fmtBytes(d.limit ?? 0)} · {Math.round(d.usedPct)}%
              </span>
            )}
          </div>
          <div className="mt-2">
            <StackBar
              segments={
                d.usedPct !== null
                  ? [
                      { label: "产物", value: snap.storage.usage.artifacts_bytes, tone: "amber" },
                      { label: "上传", value: snap.storage.usage.uploads_bytes, tone: "azure" },
                      { label: "剩余", value: Math.max(0, (d.limit ?? 0) - snap.storage.usage.total_bytes), tone: "gray" },
                    ]
                  : [
                      { label: "产物", value: snap.storage.usage.artifacts_bytes, tone: "amber" },
                      { label: "上传", value: snap.storage.usage.uploads_bytes, tone: "azure" },
                    ]
              }
              ariaLabel={
                d.limit
                  ? `产物 ${fmtBytes(snap.storage.usage.artifacts_bytes)}，上传 ${fmtBytes(snap.storage.usage.uploads_bytes)}，上限 ${fmtBytes(d.limit)}`
                  : `产物 ${fmtBytes(snap.storage.usage.artifacts_bytes)}，上传 ${fmtBytes(snap.storage.usage.uploads_bytes)}，未设置上限`
              }
            />
          </div>
          <div className="mt-1.5 text-2xs text-fg-500">{d.limit ? `上限 ${fmtBytes(d.limit)}` : "未设置上限 · 仅按保留策略清理"}</div>
        </div>

        <div className="surface p-4">
          <div className="flex items-start justify-between">
            <span className="eyebrow">历史成功率</span>
            <IconCheck size={16} className="text-fg-500" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`display text-[1.6rem] leading-none ${errorRate > 10 ? "text-amber-300" : "text-jade-300"}`}>
              {(100 - errorRate).toFixed(1)}%
            </span>
            <span className="text-xs text-fg-500">
              {fmtNumber(totalFinished - failedCount)} 成功 · {fmtNumber(failedCount)} 失败
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
            <div className="h-full rounded-full bg-jade-400/70" style={{ width: `${100 - errorRate}%` }} />
          </div>
          <div className="mt-1.5 text-2xs text-fg-500">
            累计 {fmtNumber(totalFinished)} 条已结束任务
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- backends */}
      <section className="space-y-3" aria-label="后端健康">
        <div className="flex items-end justify-between">
          <div>
            <div className="eyebrow">后端</div>
            <h2 className="display mt-1 text-lg">健康与队列</h2>
          </div>
          <span className="text-2xs text-fg-500">{d.backends.length} 个已配置后端</span>
        </div>
        {d.backends.length === 0 ? (
          <div className="surface px-4 py-8 text-center text-xs text-fg-500">配置中未定义后端</div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {d.backends.map(([id, b]) => (
              <BackendPanel key={id} id={id} health={b} queue={d.queues[id]} />
            ))}
          </div>
        )}
      </section>

      {/* ------------------------------------------- storage + retention */}
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]" aria-label="存储与保留策略">
        <div className="surface overflow-hidden">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-fg-300">
                <IconDatabase size={15} />
              </span>
              <div>
                <div className="text-[0.8125rem] font-medium text-fg-100">存储预算</div>
                <div className="text-2xs text-fg-500">产物与上传的占用分布，及清理策略</div>
              </div>
            </div>
            <button className="btn btn-secondary h-7 px-2 text-2xs" onClick={() => setConfirmSweep(true)} disabled={busy === "sweep"}>
              <IconTrash size={12} />
              立即清理
            </button>
          </div>
          <div className="grid gap-4 p-4 md:grid-cols-[180px_minmax(0,1fr)]">
            <div className="flex flex-col items-center gap-2">
              {d.usedPct !== null ? (
                <RadialMeter
                  value={d.usedPct}
                  size={132}
                  stroke={9}
                  tone={d.usedPct > 85 ? "coral" : "amber"}
                  center={
                    <div className="text-center">
                      <div className="font-display text-lg font-semibold text-fg-100">{Math.round(d.usedPct)}%</div>
                      <div className="text-2xs text-fg-500">预算占用</div>
                    </div>
                  }
                  ariaLabel="磁盘预算占用"
                />
              ) : (
                // Without a configured cap a ring is meaningless: show the raw
                // figure in the same footprint instead.
                <div className="grid h-[132px] w-[132px] place-items-center rounded-full border border-dashed border-white/10 bg-white/[0.015]">
                  <div className="text-center">
                    <div className="font-display text-base font-semibold text-fg-100">{fmtBytes(snap.storage.usage.total_bytes)}</div>
                    <div className="mt-0.5 text-2xs text-fg-500">无上限</div>
                  </div>
                </div>
              )}
              <div className="text-2xs text-fg-500">
                {d.limit ? `${fmtBytes(snap.storage.usage.total_bytes)} / ${fmtBytes(d.limit)}` : `${fmtBytes(snap.storage.usage.total_bytes)} · 无上限`}
              </div>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-2">
                  <div className="text-2xs text-fg-500">产物</div>
                  <div className="mt-0.5 font-mono text-sm text-fg-100">{fmtBytes(snap.storage.usage.artifacts_bytes)}</div>
                </div>
                <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-2">
                  <div className="text-2xs text-fg-500">上传</div>
                  <div className="mt-0.5 font-mono text-sm text-fg-100">{fmtBytes(snap.storage.usage.uploads_bytes)}</div>
                </div>
              </div>
              <StackBar
                segments={[
                  { label: "产物", value: snap.storage.usage.artifacts_bytes, tone: "amber" },
                  { label: "上传", value: snap.storage.usage.uploads_bytes, tone: "azure" },
                ]}
                height={10}
                ariaLabel="产物与上传占用分布"
              />
              <div className="space-y-1.5">
                <RetentionRow label="产物保留" value={`${snap.storage.limits.artifact_ttl_days} 天`} tone="amber" />
                <RetentionRow
                  label="失败任务保留"
                  value={snap.storage.limits.failed_retention_days === null ? "不清理" : `${snap.storage.limits.failed_retention_days} 天`}
                  tone="coral"
                />
                <RetentionRow label="自动清理间隔" value={fmtDuration(snap.storage.limits.sweep_interval_s)} tone="azure" />
                <RetentionRow label="磁盘上限" value={d.limit ? fmtBytes(d.limit) : "未设置"} tone="gray" />
              </div>
            </div>
          </div>
        </div>

        <div className="surface overflow-hidden">
          <div className="flex items-center gap-2 border-b border-white/[0.07] px-4 py-3">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-fg-300">
              <IconSliders size={15} />
            </span>
            <div>
              <div className="text-[0.8125rem] font-medium text-fg-100">服务端</div>
              <div className="text-2xs text-fg-500">监听与公共地址</div>
            </div>
          </div>
          <div className="space-y-1.5 p-4">
            {Object.entries(snap.config.server ?? {}).map(([k, v]) => (
              <div key={k} className="flex items-baseline justify-between gap-3 border-b border-white/[0.05] py-1.5 last:border-0">
                <span className="text-2xs uppercase tracking-[0.1em] text-fg-500">{k}</span>
                <span className="min-w-0 truncate font-mono text-xs text-fg-200">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------ routing/models */}
      <section className="surface overflow-hidden" aria-label="路由与模型">
        <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.07] px-4 py-3">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-fg-300">
            <IconRoute size={15} />
          </span>
          <div>
            <div className="text-[0.8125rem] font-medium text-fg-100">路由与模型</div>
            <div className="text-2xs text-fg-500">{d.models.length} 个模型 · {Object.keys(snap.config.tasks ?? {}).length} 种任务</div>
          </div>
          <div className="seg ml-auto" role="tablist" aria-label="路由视图">
            {(
              [
                { id: "routing", label: "路由" },
                { id: "models", label: "模型" },
                { id: "retention", label: "能力矩阵" },
              ] as const
            ).map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={tab === t.id}
                className={`seg-item ${tab === t.id ? "seg-item-active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {tab === "routing" && (
          <div className="p-4">
            <div className="mb-2 flex items-center gap-2">
              <IconRoute size={14} className="text-fg-500" />
              <span className="text-xs text-fg-300">统一图像入口</span>
              <span className="text-2xs text-fg-500">同一别名按是否带图分流到不同任务</span>
            </div>
            {(snap.config.routing?.unified_image_models ?? []).length === 0 ? (
              <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-xs text-fg-500">未配置统一图像路由</div>
            ) : (
              <div className="space-y-2">
                {(snap.config.routing?.unified_image_models ?? []).map((u) => (
                  <div key={u.alias} className="grid gap-2 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 md:grid-cols-[200px_1fr_1fr]">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-fg-100">{u.alias}</span>
                      <Chip tone="amber">统一</Chip>
                    </div>
                    <div className="rounded-lg border border-white/[0.06] bg-ink-900/50 px-2.5 py-1.5">
                      <div className="text-2xs text-fg-500">无图 → 文生图</div>
                      <div className="mt-0.5 font-mono text-2xs text-fg-300">{u.generate_task}</div>
                    </div>
                    <div className="rounded-lg border border-white/[0.06] bg-ink-900/50 px-2.5 py-1.5">
                      <div className="text-2xs text-fg-500">带图 → 图生图</div>
                      <div className="mt-0.5 font-mono text-2xs text-fg-300">{u.edit_task}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="divider my-4" />
            <div className="mb-2 flex items-center gap-2">
              <IconChip size={14} className="text-fg-500" />
              <span className="text-xs text-fg-300">任务族与变体</span>
            </div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {Object.entries(snap.config.tasks ?? {}).map(([task, cfg]) => {
                const meta = taskTypeMeta(task);
                return (
                  <div key={task} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
                    <div className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
                      <span className="text-xs text-fg-200">{meta.label}</span>
                      <span className="ml-auto font-mono text-2xs text-fg-500">{cfg.models.length}</span>
                    </div>
                    <div className="mt-2 space-y-1">
                      {cfg.models.map((m) => (
                        <div key={m.alias} className="flex items-center gap-1.5 text-2xs">
                          <span className="truncate font-mono text-fg-400">{m.alias}</span>
                          {m.fallbacks?.length ? (
                            <span className="ml-auto shrink-0 text-amber-300/80">→ {truncate(m.fallbacks.join(","), 18)}</span>
                          ) : (
                            <span className="ml-auto shrink-0 text-fg-600">—</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {tab === "models" && (
          <div className="p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {[{ id: "", label: "全部任务" }, ...Object.entries(TASK_TYPES).map(([id, m]) => ({ id, label: m.label }))].map((f) => (
                <button
                  key={f.id || "all"}
                  className={`rounded-lg border px-2 py-1 text-2xs transition-colors ${
                    taskFilter === f.id
                      ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-200"
                      : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20 hover:text-fg-200"
                  }`}
                  onClick={() => setTaskFilter(f.id)}
                  aria-pressed={taskFilter === f.id}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="max-h-[520px] overflow-auto rounded-xl border border-white/[0.07]">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>别名</th>
                    <th>任务</th>
                    <th>后端</th>
                    <th>模板</th>
                    <th>约束</th>
                    <th>回退</th>
                  </tr>
                </thead>
                <tbody>
                  {d.models
                    .filter((m) => !taskFilter || m.task === taskFilter)
                    .map(({ task, model }) => (
                      <tr key={`${task}-${model.alias}`}>
                        <td className="font-mono text-xs text-fg-100">{model.alias}</td>
                        <td>
                          <span className="inline-flex items-center gap-1.5 text-2xs text-fg-300">
                            <span className="h-1.5 w-1.5 rounded-full" style={{ background: taskTypeMeta(task).accent }} />
                            {taskTypeMeta(task).label}
                          </span>
                        </td>
                        <td className="font-mono text-2xs text-fg-400">{model.backend}</td>
                        <td className="max-w-[220px]">
                          <span className="block truncate font-mono text-2xs text-fg-500" title={model.template}>
                            {model.template.split("/").pop()}
                          </span>
                        </td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            {capabilityBadges(model, task).map((b) => (
                              <span key={b.label} className={`pill ${b.tone === "amber" ? "pill-amber" : b.tone === "violet" ? "pill-violet" : b.tone === "blue" ? "pill-blue" : "pill-gray"}`}>
                                {b.label}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="font-mono text-2xs text-fg-500">{model.fallbacks?.join(", ") || "—"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === "retention" && (
          <div className="p-4">
            <div className="mb-2 flex items-center gap-2">
              <IconInfo size={13} className="text-fg-500" />
              <span className="text-xs text-fg-300">模型能力矩阵</span>
              <span className="text-2xs text-fg-500">尺寸 / 时长 / 数量 / 格式约束来自配置</span>
            </div>
            <div className="max-h-[520px] overflow-auto rounded-xl border border-white/[0.07]">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>模型</th>
                    <th>尺寸策略</th>
                    <th>步进</th>
                    <th>边缘范围</th>
                    <th>默认尺寸</th>
                    <th>n 上限</th>
                    <th>时长</th>
                    <th>格式</th>
                  </tr>
                </thead>
                <tbody>
                  {d.models.map(({ task, model }) => {
                    const c = model.constraints;
                    return (
                      <tr key={`${task}-${model.alias}`}>
                        <td>
                          <div className="font-mono text-xs text-fg-100">{model.alias}</div>
                          <div className="text-2xs text-fg-500">{taskTypeMeta(task).label}</div>
                        </td>
                        <td className="font-mono text-2xs text-fg-400">{c.size_policy ?? "—"}</td>
                        <td className="font-mono text-2xs text-fg-400">{c.size_step ?? "—"}</td>
                        <td className="font-mono text-2xs text-fg-400">
                          {c.min_edge ?? "—"}–{c.max_edge ?? "—"}
                        </td>
                        <td className="font-mono text-2xs text-fg-400">{c.default_size ?? "—"}</td>
                        <td className="font-mono text-2xs text-fg-400">{c.n_max ?? "—"}</td>
                        <td className="font-mono text-2xs text-fg-400">
                          {c.duration_min != null && c.duration_max != null ? `${c.duration_min}–${c.duration_max}s` : "—"}
                        </td>
                        <td className="font-mono text-2xs text-fg-400">{(c.output_formats ?? []).join("/") || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* ------------------------------------------------ history stats */}
      <section className="grid gap-4 md:grid-cols-2" aria-label="历史统计">
        <div className="surface p-4">
          <div className="eyebrow mb-3">任务累计</div>
          <div className="space-y-2">
            {d.taskCounts.length === 0 ? (
              <div className="text-xs text-fg-500">暂无记录</div>
            ) : (
              d.taskCounts.map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-2xs">
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: k === "succeeded" ? "#45d6c4" : k === "failed" ? "#ff6b81" : "#f0b04a" }}
                  />
                  <span className="text-fg-300">{k === "succeeded" ? "已完成" : k === "failed" ? "失败" : k}</span>
                  <span className="ml-auto font-mono text-fg-200">{fmtNumber(v)}</span>
                  <div className="w-24">
                    <div className="h-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(v / Math.max(1, ...d.taskCounts.map(([, x]) => x))) * 100}%`,
                          background: k === "succeeded" ? "#45d6c4" : k === "failed" ? "#ff6b81" : "#f0b04a",
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
        <div className="surface p-4">
          <div className="eyebrow mb-3">队列负载</div>
          {Object.keys(d.queues).length === 0 ? (
            <div className="text-xs text-fg-500">没有队列数据</div>
          ) : (
            Object.entries(d.queues).map(([id, q]) => (
              <div key={id} className="mb-3 last:mb-0">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="font-mono text-xs text-fg-200">{id}</span>
                  <span className="text-2xs text-fg-500">
                    执行 {q.running}/{q.concurrency} · 等待 {q.waiting}/{q.queue_max}
                  </span>
                </div>
                <QueueLanes running={q.running} concurrency={q.concurrency} waiting={q.waiting} queueMax={q.queue_max} />
              </div>
            ))
          )}
        </div>
      </section>

      <ConfirmDialog
        open={confirmSweep}
        title="立即清理存储？"
        message={
          <>
            将按保留策略移除超过 {snap.storage.limits.artifact_ttl_days} 天的产物
            {snap.storage.limits.failed_retention_days !== null && `，以及超过 ${snap.storage.limits.failed_retention_days} 天的失败任务文件`}
            。任务记录会保留。
          </>
        }
        danger={false}
        confirmLabel="开始清理"
        onConfirm={() => void sweep()}
        onClose={() => setConfirmSweep(false)}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- pieces */

function BackendPanel({ id, health, queue }: { id: string; health: BackendHealth; queue?: QueueStats }) {
  const ok = health.healthy === true;
  const devices = health.devices ?? [];
  const ramPct = health.ram_total && health.ram_free ? (1 - health.ram_free / health.ram_total) * 100 : null;
  const device = devices[0] ?? null;
  const vramTotal = typeof device?.vram_total === "number" ? (device.vram_total as number) : null;
  const vramFree = typeof device?.vram_free === "number" ? (device.vram_free as number) : null;
  const vramPct = vramTotal && vramFree !== null ? (1 - vramFree / vramTotal) * 100 : null;
  return (
    <div className={`surface overflow-hidden ${ok ? "" : "border-coral-500/25"}`}>
      <div className="flex items-center gap-2 border-b border-white/[0.07] px-4 py-3">
        <span className={`h-2 w-2 rounded-full ${ok ? "bg-jade-400 shadow-[0_0_8px_rgba(69,214,196,0.6)]" : "bg-coral-400"}`} />
        <span className="font-mono text-xs text-fg-100">{id}</span>
        {ok ? <Chip tone="green">在线</Chip> : <Chip tone="red">离线</Chip>}
        <span className="ml-auto text-2xs text-fg-500">
          {ok ? `ComfyUI ${health.comfyui_version ?? "?"} · ${health.os ?? "?"}` : "不可达"}
        </span>
      </div>
      <div className="space-y-3 p-4">
        {!ok ? (
          <div className="rounded-lg border border-coral-500/25 bg-coral-500/[0.06] px-2.5 py-2 font-mono text-2xs leading-relaxed text-coral-300">
            {truncate(health.error ?? "后端健康检查失败", 220)}
          </div>
        ) : (
          <>
            {queue ? (
              <QueueLanes running={queue.running} concurrency={queue.concurrency} waiting={queue.waiting} queueMax={queue.queue_max} />
            ) : (
              <div className="text-2xs text-fg-500">没有队列统计</div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <Meter label="内存占用" value={ramPct} detail={health.ram_total ? `${fmtBytes(health.ram_free)} 可用 / ${fmtBytes(health.ram_total)}` : "—"} />
              <Meter label="显存占用" value={vramPct} detail={vramTotal ? `${fmtBytes(vramFree)} 可用 / ${fmtBytes(vramTotal)}` : "—"} />
            </div>
            {device && (
              <div className="flex items-center gap-1.5 text-2xs text-fg-500">
                <IconChip size={11} />
                <span className="truncate font-mono">{String(device.name ?? device.type ?? "")}</span>
              </div>
            )}
            {health.queue && (
              <div className="flex items-center gap-2 text-2xs text-fg-500">
                <IconClock size={11} />
                后端自报队列 running {health.queue.running ?? "—"} · pending {health.queue.pending ?? "—"}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Meter({ label, value, detail }: { label: string; value: number | null; detail: string }) {
  const v = value === null ? 0 : Math.max(0, Math.min(100, value));
  const tone = v > 85 ? "bg-coral-400" : v > 60 ? "bg-amber-400" : "bg-jade-400";
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-2">
      <div className="flex items-center justify-between text-2xs text-fg-500">
        <span>{label}</span>
        <span className="font-mono text-fg-300">{value === null ? "—" : `${Math.round(v)}%`}</span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.06]" role="img" aria-label={`${label} ${value === null ? "未知" : `${Math.round(v)}%`}`}>
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${v}%` }} />
      </div>
      <div className="mt-1 truncate font-mono text-2xs text-fg-600">{detail}</div>
    </div>
  );
}

function RetentionRow({ label, value, tone }: { label: string; value: string; tone: string }) {
  const color = tone === "amber" ? "text-amber-300" : tone === "coral" ? "text-coral-300" : tone === "azure" ? "text-azure-300" : "text-fg-300";
  return (
    <div className="flex items-center gap-2 border-b border-white/[0.05] py-1.5 last:border-0">
      <span className="text-2xs text-fg-500">{label}</span>
      <span className={`ml-auto font-mono text-2xs ${color}`}>{value}</span>
    </div>
  );
}
