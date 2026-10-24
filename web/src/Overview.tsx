/** Overview: the "pulse" dashboard — live counters, backend/queue, storage
 * budget, recent media strip and a failure digest with one-click retry. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ConfigView, type HealthResponse, type StorageStats, type TaskSummary } from "./api";
import { ActivityBars, QueueLanes, RadialMeter, Sparkline, StackBar } from "./charts";
import { SectionHeader, StatusPill, TypeTag, TypeIcon } from "./components";
import {
  fmtBytes,
  fmtDuration,
  fmtNumber,
  fmtRelative,
  fmtUptime,
  isActive,
  shortId,
  statusMeta,
  taskThumb,
  taskTypeMeta,
  truncate,
  TASK_TYPES,
} from "./format";
import {
  IconAlert,
  IconArrowUpRight,
  IconAudio,
  IconBolt,
  IconChip,
  IconClock,
  IconDatabase,
  IconGallery,
  IconImage,
  IconPlay,
  IconPulse,
  IconRefresh,
  IconRetry,
  IconSpark,
  IconVideo,
} from "./icons";
import { Chip, ErrorBanner, IconButton, MediaThumb, Skeleton, Tooltip, useToast } from "./ui";

type Props = {
  refreshKey: number;
  onOpenTask: (id: string) => void;
  onOpenTasks: () => void;
  onOpenStudio: () => void;
  onOpenSystem: () => void;
  onChanged: () => void;
};

type OverviewData = {
  health: HealthResponse | null;
  storage: StorageStats | null;
  config: ConfigView | null;
  recent: TaskSummary[];
  total: number;
};

const WINDOW_HOURS = 24;

function bucketTasks(items: TaskSummary[], hours: number): { buckets: number[]; count: number } {
  const now = Date.now() / 1000;
  const span = hours * 3600;
  const size = span / 12;
  const buckets = new Array(12).fill(0) as number[];
  let count = 0;
  for (const t of items) {
    const age = now - t.created_at;
    if (age < 0 || age > span) continue;
    count += 1;
    const idx = 11 - Math.min(11, Math.floor(age / size));
    buckets[idx] += 1;
  }
  return { buckets, count };
}

export default function Overview({ refreshKey, onOpenTask, onOpenTasks, onOpenStudio, onOpenSystem, onChanged }: Props) {
  const toast = useToast();
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now() / 1000);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const [health, storage, config, list] = await Promise.all([
        api.health(),
        api.storage(),
        api.config(),
        api.tasks({ limit: 200 }),
      ]);
      if (!alive.current) return;
      setData({ health, storage, config, recent: list.items, total: list.total });
      setError(null);
    } catch (err) {
      if (!alive.current) return;
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load, refreshKey]);

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), 30000);
    return () => window.clearInterval(t);
  }, []);

  const retry = async (task: TaskSummary) => {
    setRetrying(task.id);
    try {
      const res = await api.retry(task.id);
      toast.push("success", "已重新提交", `新任务 ${shortId(res.task_id)} · ${task.model_alias}`);
      onChanged();
      void load();
    } catch (err) {
      toast.push("error", "重试失败", (err as Error).message);
    } finally {
      setRetrying(null);
    }
  };

  const derived = useMemo(() => {
    if (!data) return null;
    const items = data.recent;
    const active = items.filter((t) => isActive(t.status));
    const failed = items.filter((t) => t.status === "failed" || t.status === "timed_out");
    const succeeded = items.filter((t) => t.status === "succeeded");
    const activity = bucketTasks(items, WINDOW_HOURS);
    const byType: Record<string, number> = {};
    for (const t of items) byType[t.task_type] = (byType[t.task_type] ?? 0) + 1;
    const media = items
      .filter((t) => t.status === "succeeded" && t.artifact_count > 0)
      .sort((a, b) => b.created_at - a.created_at);
    const failByCode: Record<string, number> = {};
    for (const t of failed) {
      const code = t.error_code ?? "unknown";
      failByCode[code] = (failByCode[code] ?? 0) + 1;
    }
    const failureCodes = Object.entries(failByCode).sort((a, b) => b[1] - a[1]);
    const backends = Object.entries(data.health?.backends ?? {});
    const queueTotals = Object.values(data.health?.queues ?? {}).reduce(
      (acc, q) => ({ running: acc.running + (q.running ?? 0), waiting: acc.waiting + (q.waiting ?? 0) }),
      { running: 0, waiting: 0 },
    );
    const usage = data.storage?.usage;
    const limit = data.storage?.limits.max_bytes;
    const usedPct = usage && limit ? (usage.total_bytes / limit) * 100 : null;
    const models = Object.values(data.config?.tasks ?? {}).reduce((s, t) => s + t.models.length, 0);
    const successRate = succeeded.length + failed.length > 0 ? (succeeded.length / (succeeded.length + failed.length)) * 100 : null;
    return {
      active,
      failed,
      succeeded,
      recent: items,
      activity,
      byType,
      media,
      failureCodes,
      backends,
      queueTotals,
      usedPct,
      models,
      successRate,
      running: data.health?.active ?? 0,
    };
  }, [data]);

  /* ------------------------------------------------------------- loading */
  if (!data && !error) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="正在加载概览">
        <div className="space-y-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-9 w-64" />
        </div>
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="aspect-[4/5]" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || !derived) {
    return (
      <div className="space-y-4">
        <ErrorBanner message={`概览数据加载失败：${error ?? "未知错误"}`} onRetry={() => void load()} />
      </div>
    );
  }

  const d = derived;
  const healthy = d.backends.filter(([, b]) => b.healthy).length;
  const liveTone = d.running > 0 ? "jade" : "gray";

  return (
    <div className="space-y-6 animate-fade-up">
      {error && <ErrorBanner message={`部分数据刷新失败：${error}`} onRetry={() => void load()} />}

      {/* ---------------------------------------------------------- pulse */}
      <section className="relative overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850/70">
        <div className="pointer-events-none absolute inset-0 bg-safelight" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-400/40 to-transparent" />
        <div className="relative grid gap-8 p-6 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <span className="eyebrow flex items-center gap-1.5">
                <IconPulse size={13} className="text-amber-400" />
                实时脉搏
              </span>
              <span className="text-fg-600">·</span>
              <span className="text-2xs text-fg-500">过去 {WINDOW_HOURS} 小时</span>
              <span className="ml-auto flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${d.running > 0 ? "animate-breathe bg-jade-400" : "bg-fg-600"}`} />
                <span className="text-2xs text-fg-500">{d.running > 0 ? "正在出片" : "空闲"}</span>
                <IconButton label="刷新概览" onClick={() => void load()}>
                  <IconRefresh size={15} />
                </IconButton>
              </span>
            </div>

            <div className="mt-4 flex flex-wrap items-end gap-x-10 gap-y-4">
              <div>
                <div className="flex items-baseline gap-2">
                  <span className="display text-[3.1rem] leading-none">{fmtNumber(d.active.length)}</span>
                  <span className="text-xs text-fg-500">进行中</span>
                </div>
                <div className="mt-1.5 text-2xs text-fg-500">
                  队列 {d.queueTotals.waiting} · 后端 {healthy}/{d.backends.length} 在线
                </div>
              </div>
              <div>
                <div className="flex items-baseline gap-2">
                  <span className="display text-[2.1rem] leading-none text-fg-200">{fmtNumber(d.activity.count)}</span>
                  <span className="text-xs text-fg-500">24h 内提交</span>
                </div>
                <div className="mt-1.5 text-2xs text-fg-500">累计 {fmtNumber(data.total)} 条记录</div>
              </div>
              <div>
                <div className="flex items-baseline gap-2">
                  <span className={`display text-[2.1rem] leading-none ${d.failed.length ? "text-coral-300" : "text-fg-200"}`}>
                    {fmtNumber(d.failed.length)}
                  </span>
                  <span className="text-xs text-fg-500">失败</span>
                </div>
                <div className="mt-1.5 text-2xs text-fg-500">
                  {d.successRate === null ? "暂无完成记录" : `成功率 ${d.successRate.toFixed(1)}%`}
                </div>
              </div>
            </div>

            <div className="mt-6">
              <div className="mb-1.5 flex items-center justify-between text-2xs text-fg-500">
                <span>提交节律</span>
                <span className="font-mono">-{WINDOW_HOURS}h → 现在</span>
              </div>
              <ActivityBars buckets={d.activity.buckets} tone={liveTone === "jade" ? "jade" : "amber"} height={46} label={`过去 ${WINDOW_HOURS} 小时提交分布`} />
            </div>

            <div className="mt-5 flex flex-wrap gap-1.5">
              {Object.entries(TASK_TYPES).map(([type, meta]) => (
                <button
                  key={type}
                  className="group inline-flex items-center gap-1.5 rounded-lg border border-white/[0.07] bg-white/[0.02] px-2 py-1 text-2xs text-fg-400 transition-colors hover:border-white/15 hover:text-fg-100"
                  onClick={onOpenTasks}
                  aria-label={`查看${meta.label}任务`}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
                  {meta.label}
                  <span className="font-mono text-fg-200">{d.byType[type] ?? 0}</span>
                </button>
              ))}
            </div>
          </div>

          {/* backend + queue */}
          <div className="space-y-4 rounded-xl border border-white/[0.06] bg-ink-900/50 p-4">
            <div className="flex items-center justify-between">
              <span className="eyebrow">后端与队列</span>
              <button className="btn btn-ghost h-6 px-1.5 text-2xs" onClick={onOpenSystem}>
                系统
                <IconArrowUpRight size={12} />
              </button>
            </div>
            {d.backends.length === 0 && <div className="text-xs text-fg-500">未配置后端</div>}
            {d.backends.map(([id, b]) => {
              const q = data.health?.queues?.[id];
              return (
                <div key={id} className="space-y-2.5">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${b.healthy ? "bg-jade-400 shadow-[0_0_8px_rgba(69,214,196,0.6)]" : "bg-coral-400"}`} />
                    <span className="font-mono text-xs text-fg-100">{id}</span>
                    <span className="ml-auto text-2xs text-fg-500">{b.healthy ? `ComfyUI ${b.comfyui_version ?? "?"}` : "离线"}</span>
                  </div>
                  {b.healthy && q ? (
                    <QueueLanes running={q.running} concurrency={q.concurrency} waiting={q.waiting} queueMax={q.queue_max} />
                  ) : (
                    <div className="rounded-md border border-coral-500/20 bg-coral-500/[0.06] px-2 py-1 text-2xs text-coral-300">
                      {truncate(b.error ?? "后端不可达", 70)}
                    </div>
                  )}
                </div>
              );
            })}
            <div className="divider" />
            <div className="flex items-center justify-between text-2xs text-fg-500">
              <span>运行时长</span>
              <span className="font-mono text-fg-300">{fmtUptime(data.health?.uptime_s)}</span>
            </div>
            <div className="flex items-center justify-between text-2xs text-fg-500">
              <span>已注册模型</span>
              <span className="font-mono text-fg-300">{d.models}</span>
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------- metric tiles */}
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="关键指标">
        <Tile
          eyebrow="存储预算"
          value={data.storage ? fmtBytes(data.storage.usage.total_bytes) : "—"}
          hint={
            data.storage
              ? data.storage.limits.max_bytes
                ? `上限 ${fmtBytes(data.storage.limits.max_bytes)} · 保留 ${data.storage.limits.artifact_ttl_days} 天`
                : `未设上限 · 保留 ${data.storage.limits.artifact_ttl_days} 天`
              : undefined
          }
          icon={<IconDatabase size={16} />}
          footer={
            data.storage ? (
              <StackBar
                segments={[
                  { label: "产物", value: data.storage.usage.artifacts_bytes, tone: "amber" },
                  { label: "上传", value: data.storage.usage.uploads_bytes, tone: "azure" },
                ]}
                ariaLabel={`产物 ${fmtBytes(data.storage.usage.artifacts_bytes)}，上传 ${fmtBytes(data.storage.usage.uploads_bytes)}`}
              />
            ) : null
          }
          onClick={onOpenSystem}
        />
        <Tile
          eyebrow="成功 / 失败"
          value={
            <span className="flex items-baseline gap-2">
              <span className="text-jade-300">{fmtNumber(d.succeeded.length)}</span>
              <span className="text-fg-600">/</span>
              <span className={d.failed.length ? "text-coral-300" : "text-fg-200"}>{fmtNumber(d.failed.length)}</span>
            </span>
          }
          hint={d.failureCodes.length ? `主要错误 ${d.failureCodes[0][0]}` : "近 200 条内无失败"}
          icon={<IconAlert size={16} />}
          footer={
            <div className="flex h-6 items-end gap-[2px]">
              {d.activity.buckets.map((b, i) => (
                <span
                  key={i}
                  className="flex-1 rounded-sm bg-white/[0.07]"
                  style={{ height: `${Math.max(8, (b / Math.max(1, ...d.activity.buckets)) * 100)}%` }}
                />
              ))}
            </div>
          }
          onClick={onOpenTasks}
        />
        <Tile
          eyebrow="平均耗时"
          value={avgDuration(d.recent)}
          hint={`基于 ${d.recent.filter((t) => t.finished_at).length} 条已完成记录`}
          icon={<IconClock size={16} />}
          footer={
            <div className="flex items-center gap-2 text-2xs text-fg-500">
              <IconBolt size={12} className="text-amber-400" />
              最快 {minDuration(d.recent)}
            </div>
          }
        />
        <Tile
          eyebrow="媒体产出"
          value={fmtNumber(d.recent.reduce((s, t) => s + t.artifact_count, 0))}
          hint="近 200 条记录内的产物总数"
          icon={<IconGallery size={16} />}
          footer={
            <div className="flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 rounded border border-white/10 px-1.5 py-0.5 text-2xs text-fg-400">
                <IconImage size={11} /> {countKind(d.recent, "image")}
              </span>
              <span className="inline-flex items-center gap-1 rounded border border-white/10 px-1.5 py-0.5 text-2xs text-fg-400">
                <IconVideo size={11} /> {countKind(d.recent, "video")}
              </span>
              <span className="inline-flex items-center gap-1 rounded border border-white/10 px-1.5 py-0.5 text-2xs text-fg-400">
                <IconAudio size={11} /> {countKind(d.recent, "audio")}
              </span>
            </div>
          }
          onClick={onOpenTasks}
        />
      </section>

      {/* ------------------------------------------------ recent media */}
      <section aria-label="最近生成">
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <div className="eyebrow">最近出片</div>
            <h2 className="display mt-1 text-lg">刚刚显影的作品</h2>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn btn-secondary h-8 text-xs" onClick={onOpenStudio}>
              <IconSpark size={14} />
              去创作
            </button>
            <button className="btn btn-ghost h-8 text-xs" onClick={onOpenTasks}>
              全部历史
              <IconArrowUpRight size={13} />
            </button>
          </div>
        </div>
        {d.media.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.015] px-6 py-10 text-center">
            <div className="text-sm text-fg-300">还没有完成的媒体产物</div>
            <div className="mt-1 text-xs text-fg-500">在创作台提交第一个任务，作品会出现在这里。</div>
            <button className="btn btn-primary mt-4 h-8 text-xs" onClick={onOpenStudio}>
              <IconSpark size={14} />
              打开创作台
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {d.media.slice(0, 6).map((t) => (
              <RecentFrame key={t.id} task={t} now={now} onOpen={() => onOpenTask(t.id)} />
            ))}
          </div>
        )}
      </section>

      {/* ------------------------------------------------- failure digest */}
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]" aria-label="失败摘要">
        <div className="surface overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.07] px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-coral-500/[0.12] text-coral-300">
                <IconAlert size={15} />
              </span>
              <div>
                <div className="text-[0.8125rem] font-medium text-fg-100">失败摘要</div>
                <div className="text-2xs text-fg-500">最近失败的请求与错误码，可一键重跑</div>
              </div>
            </div>
            <button className="btn btn-ghost h-7 px-2 text-xs" onClick={onOpenTasks}>
              全部任务
              <IconArrowUpRight size={12} />
            </button>
          </div>
          {d.failed.length === 0 ? (
            <div className="flex items-center gap-3 px-4 py-8 text-xs text-fg-400">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-jade-500/[0.12] text-jade-300">
                <IconPulse size={16} />
              </span>
              最近 {WINDOW_HOURS} 小时没有失败任务。
            </div>
          ) : (
            <ul className="divide-y divide-white/[0.05]">
              {d.failed.slice(0, 5).map((t) => (
                <li key={t.id} className="group flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-white/[0.025]">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-white/10 bg-white/[0.03] text-fg-400">
                    <TypeIcon type={t.task_type} size={14} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <button
                      className="block w-full truncate text-left text-[0.8125rem] text-fg-200 hover:text-fg-100"
                      onClick={() => onOpenTask(t.id)}
                      title={t.prompt}
                    >
                      {truncate(t.prompt || "(无提示词)", 64)}
                    </button>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-2xs text-fg-500">
                      <span className="mono-id">{shortId(t.id)}</span>
                      <span className="font-mono text-fg-400">{t.model_alias}</span>
                      <span className="rounded border border-coral-500/25 bg-coral-500/[0.07] px-1 py-px font-mono text-coral-300">
                        {t.error_code ?? "unknown"}
                      </span>
                      <span>{fmtRelative(t.created_at, now)}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1 opacity-60 transition-opacity group-hover:opacity-100">
                    <Tooltip text="查看详情">
                      <IconButton label="查看详情" onClick={() => onOpenTask(t.id)}>
                        <IconArrowUpRight size={14} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip text="重新提交">
                      <IconButton
                        label={`重试 ${shortId(t.id)}`}
                        onClick={() => void retry(t)}
                        className={retrying === t.id ? "animate-breathe" : ""}
                      >
                        <IconRetry size={14} />
                      </IconButton>
                    </Tooltip>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="surface p-4">
          <div className="eyebrow mb-3">错误分布</div>
          {d.failureCodes.length === 0 ? (
            <div className="text-xs text-fg-500">暂无错误</div>
          ) : (
            <div className="space-y-3">
              <StackBar
                segments={d.failureCodes.map(([code, n], i) => ({
                  label: code,
                  value: n,
                  tone: ["coral", "amber", "violet", "azure"][i % 4],
                }))}
                height={10}
                ariaLabel={`错误分布：${d.failureCodes.map(([c, n]) => `${c} ${n}`).join("，")}`}
              />
              {d.failureCodes.map(([code, n], i) => (
                <div key={code} className="flex items-center gap-2 text-2xs">
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: ["#ff6b81", "#f0b04a", "#a68cff", "#5aa8ff"][i % 4] }}
                  />
                  <span className="font-mono text-fg-300">{code}</span>
                  <span className="ml-auto font-mono text-fg-400">{n}</span>
                  <div className="w-20">
                    <div className="h-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(n / d.failureCodes[0][1]) * 100}%`,
                          background: ["#ff6b81", "#f0b04a", "#a68cff", "#5aa8ff"][i % 4],
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="divider my-3" />
          <div className="flex items-center justify-between text-2xs text-fg-500">
            <span>存储上限</span>
            <span className="font-mono text-fg-300">{data.storage?.limits.max_bytes ? fmtBytes(data.storage.limits.max_bytes) : "未设置"}</span>
          </div>
          {d.usedPct !== null && (
            <div className="mt-3 flex items-center gap-3">
              <RadialMeter value={d.usedPct} size={64} stroke={6} tone={d.usedPct > 85 ? "coral" : "amber"} center={<span className="font-mono text-2xs text-fg-200">{Math.round(d.usedPct)}%</span>} />
              <div className="text-2xs text-fg-500">预算占用</div>
            </div>
          )}
        </div>
      </section>

      {/* ------------------------------------------------ routing summary */}
      <section className="surface overflow-hidden" aria-label="路由摘要">
        <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-fg-300">
              <IconChip size={15} />
            </span>
            <span className="text-[0.8125rem] font-medium text-fg-100">路由与模型</span>
          </div>
          <button className="btn btn-ghost h-7 px-2 text-xs" onClick={onOpenSystem}>
            系统面板
            <IconArrowUpRight size={12} />
          </button>
        </div>
        <div className="grid gap-0 divide-y divide-white/[0.05] md:grid-cols-2 md:divide-x md:divide-y-0">
          {(data.config?.routing?.unified_image_models ?? []).map((u) => (
            <div key={u.alias} className="p-4">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-fg-100">{u.alias}</span>
                <Chip tone="amber">统一入口</Chip>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-2xs text-fg-500">
                <div className="rounded-md border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
                  <div className="text-fg-600">无图</div>
                  <div className="mt-0.5 font-mono text-fg-300">{u.generate_task}</div>
                </div>
                <div className="rounded-md border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
                  <div className="text-fg-600">带图</div>
                  <div className="mt-0.5 font-mono text-fg-300">{u.edit_task}</div>
                </div>
              </div>
            </div>
          ))}
          <div className="p-4">
            <div className="eyebrow mb-2">任务类型覆盖</div>
            <div className="space-y-1.5">
              {Object.entries(data.config?.tasks ?? {}).map(([task, cfg]) => {
                const meta = taskTypeMeta(task);
                return (
                  <div key={task} className="flex items-center gap-2 text-2xs">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
                    <span className="text-fg-300">{meta.label}</span>
                    <span className="ml-auto font-mono text-fg-400">{cfg.models.length} 个模型</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- helpers */

function Tile({
  eyebrow,
  value,
  hint,
  icon,
  footer,
  onClick,
}: {
  eyebrow: string;
  value: React.ReactNode;
  hint?: string;
  icon: React.ReactNode;
  footer?: React.ReactNode;
  onClick?: () => void;
}) {
  const inner = (
    <>
      <div className="flex items-start justify-between">
        <span className="eyebrow">{eyebrow}</span>
        <span className="text-fg-500">{icon}</span>
      </div>
      <div className="mt-2 font-display text-[1.5rem] font-semibold leading-none tracking-tight text-fg-100">{value}</div>
      {hint && <div className="mt-1.5 text-2xs text-fg-500">{hint}</div>}
      {footer && <div className="mt-3">{footer}</div>}
    </>
  );
  if (!onClick) return <div className="surface p-4">{inner}</div>;
  return (
    <button
      className="surface group block w-full p-4 text-left transition-colors hover:border-white/[0.14]"
      onClick={onClick}
    >
      {inner}
      <span className="pointer-events-none absolute right-3 top-3 text-fg-600 opacity-0 transition-opacity group-hover:opacity-100">
        <IconArrowUpRight size={13} />
      </span>
    </button>
  );
}

function RecentFrame({ task, now, onOpen }: { task: TaskSummary; now: number; onOpen: () => void }) {
  const thumb = taskThumb(task);
  const meta = taskTypeMeta(task.task_type);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative block overflow-hidden rounded-xl border border-white/[0.08] bg-ink-950 text-left transition-colors hover:border-white/20"
      aria-label={`打开任务 ${shortId(task.id)}`}
    >
      <MediaThumb src={thumb?.url ?? null} kind={thumb?.kind ?? "image"} ratio="aspect-[4/5]" alt={task.prompt} />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950/90 via-ink-950/10 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 p-2.5">
        <div className="flex items-center gap-1.5 text-2xs text-fg-300">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
          <span>{meta.short}</span>
          <span className="ml-auto text-fg-500">{fmtRelative(task.created_at, now)}</span>
        </div>
        <div className="mt-1 truncate text-2xs text-fg-200/90">{truncate(task.prompt || task.model_alias, 40)}</div>
      </div>
      <span className="pointer-events-none absolute right-2 top-2 grid h-6 w-6 place-items-center rounded-md border border-white/15 bg-black/45 text-white/85 opacity-0 backdrop-blur transition-opacity group-hover:opacity-100">
        <IconPlay size={11} />
      </span>
    </button>
  );
}

function avgDuration(items: TaskSummary[]): string {
  const done = items.filter((t) => t.status === "succeeded" && t.finished_at && t.finished_at > t.created_at);
  if (!done.length) return "—";
  const total = done.reduce((s, t) => s + ((t.finished_at as number) - t.created_at), 0);
  return fmtDuration(total / done.length);
}

function minDuration(items: TaskSummary[]): string {
  const done = items.filter((t) => t.status === "succeeded" && t.finished_at && t.finished_at > t.created_at);
  if (!done.length) return "—";
  return fmtDuration(Math.min(...done.map((t) => (t.finished_at as number) - t.created_at)));
}

const KIND_TASKS: Record<string, string[]> = {
  image: ["image.generate", "image.edit"],
  video: ["video.generate"],
  audio: ["audio.generate"],
};

function countKind(items: TaskSummary[], kind: string): number {
  const types = KIND_TASKS[kind] ?? [];
  return items.filter((t) => t.status === "succeeded" && t.artifact_count > 0 && types.includes(t.task_type)).length;
}
