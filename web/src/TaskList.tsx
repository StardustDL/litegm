/** Task history browser: gallery (uniform print grid) and dense table modes with
 * facets, bulk actions, export and pagination. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type TaskSummary } from "./api";
import { SectionHeader, StatusPill, TypeIcon } from "./components";
import {
  fmtDuration,
  fmtRelative,
  fmtTime,
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
  IconCheck,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconClose,
  IconDownload,
  IconFilter,
  IconGallery,
  IconGrid,
  IconList,
  IconPlay,
  IconRefresh,
  IconRetry,
  IconSearch,
  IconSpark,
  IconTrash,
} from "./icons";
import { ConfirmDialog, EmptyState, ErrorBanner, IconButton, MediaThumb, Skeleton, Tooltip, useToast } from "./ui";

type Props = {
  refreshKey: number;
  onOpen: (id: string) => void;
  onOpenStudio: () => void;
  onChanged: () => void;
};

type Filters = {
  search: string;
  status: string;
  task_type: string;
  model_alias: string;
  backend_id: string;
  since: string;
  until: string;
};

const EMPTY: Filters = {
  search: "",
  status: "",
  task_type: "",
  model_alias: "",
  backend_id: "",
  since: "",
  until: "",
};

const PAGE_SIZES = [24, 48, 96];
const TABLE_SIZES = [25, 50, 100, 200];

const STATUS_FACETS: Array<{ id: string; label: string }> = [
  { id: "", label: "全部状态" },
  { id: "succeeded", label: "已完成" },
  { id: "running", label: "生成中" },
  { id: "queued", label: "排队中" },
  { id: "submitting", label: "提交中" },
  { id: "failed", label: "失败" },
  { id: "cancelled", label: "已取消" },
  { id: "timed_out", label: "超时" },
];

const TIME_FACETS: Array<{ id: string; label: string; hours: number | null }> = [
  { id: "", label: "全部时间", hours: null },
  { id: "1h", label: "最近 1 小时", hours: 1 },
  { id: "24h", label: "最近 24 小时", hours: 24 },
  { id: "7d", label: "最近 7 天", hours: 24 * 7 },
  { id: "30d", label: "最近 30 天", hours: 24 * 30 },
];

const TONE_DOT: Record<string, string> = {
  green: "#45d6c4",
  blue: "#5aa8ff",
  amber: "#f0b04a",
  red: "#ff6b81",
  violet: "#a68cff",
  gray: "#a3a0a0",
};

function timeRange(hours: number | null): { since?: number; until?: number } {
  if (!hours) return {};
  const now = Date.now() / 1000;
  return { since: now - hours * 3600, until: now };
}

function dayStart(date: string): number | undefined {
  if (!date) return undefined;
  const t = new Date(`${date}T00:00:00`).getTime();
  return Number.isFinite(t) ? t / 1000 : undefined;
}

function dayEnd(date: string): number | undefined {
  if (!date) return undefined;
  const t = new Date(`${date}T23:59:59`).getTime();
  return Number.isFinite(t) ? t / 1000 : undefined;
}

function durationOf(t: TaskSummary): string {
  if (!t.finished_at) return "—";
  return fmtDuration(Math.max(0, t.finished_at - t.created_at));
}

function dayLabel(ts: number): string {
  const d = new Date(ts * 1000);
  const today = new Date();
  const sameDay =
    d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${sameDay ? "今天" : `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function facetButtonClass(on: boolean): string {
  return `rounded-lg border px-2 py-1 text-2xs transition-colors ${
    on
      ? "border-amber-400/40 bg-amber-400/[0.12] text-amber-200"
      : "border-white/[0.08] bg-white/[0.02] text-fg-400 hover:border-white/20 hover:text-fg-200"
  }`;
}

export default function TaskList({ refreshKey, onOpen, onOpenStudio, onChanged }: Props) {
  const toast = useToast();
  const [mode, setMode] = useState<"gallery" | "table">("gallery");
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [timeFacet, setTimeFacet] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(24);
  const [items, setItems] = useState<TaskSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<{
    key: "created_at" | "finished_at" | "status" | "task_type" | "model_alias";
    dir: 1 | -1;
  }>({ key: "created_at", dir: -1 });
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<null | "delete" | "retry">(null);
  const [facetsOpen, setFacetsOpen] = useState(true);
  const searchRef = useRef<HTMLInputElement>(null);
  const alive = useRef(true);

  const hours = TIME_FACETS.find((t) => t.id === timeFacet)?.hours ?? null;
  const effectivePageSize = mode === "table" ? Math.max(pageSize, 25) : pageSize;

  const query = useMemo(() => {
    const since = dayStart(applied.since);
    const until = dayEnd(applied.until);
    const range = since || until ? { since, until } : timeRange(hours);
    return {
      search: applied.search,
      status: applied.status,
      task_type: applied.task_type,
      model_alias: applied.model_alias,
      backend_id: applied.backend_id,
      since: range.since,
      until: range.until,
      limit: effectivePageSize,
      offset: page * effectivePageSize,
    };
  }, [applied, hours, page, effectivePageSize]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.tasks(query);
      if (!alive.current) return;
      setItems(res.items);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      if (!alive.current) return;
      setError((err as Error).message);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load, refreshKey]);

  // Drop selections that are no longer visible after a reload.
  useEffect(() => {
    setSelected((s) => {
      const ids = new Set(items.map((t) => t.id));
      const next = new Set([...s].filter((id) => ids.has(id)));
      return next.size === s.size ? s : next;
    });
  }, [items]);

  useEffect(() => {
    setPage(0);
  }, [mode, pageSize, applied, timeFacet]);

  const apply = () => {
    setApplied({ ...filters, search: filters.search.trim() });
    setPage(0);
  };

  const clearAll = () => {
    setFilters(EMPTY);
    setApplied(EMPTY);
    setTimeFacet("");
    setPage(0);
  };

  const activeFilters =
    (applied.search ? 1 : 0) +
    (applied.status ? 1 : 0) +
    (applied.task_type ? 1 : 0) +
    (applied.model_alias ? 1 : 0) +
    (applied.backend_id ? 1 : 0) +
    (applied.since || applied.until ? 1 : 0) +
    (timeFacet ? 1 : 0);

  const sorted = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => {
      const av = a[sort.key] ?? 0;
      const bv = b[sort.key] ?? 0;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sort.dir;
      return String(av).localeCompare(String(bv)) * sort.dir;
    });
    return copy;
  }, [items, sort]);

  const modelOptions = useMemo(() => Array.from(new Set(items.map((t) => t.model_alias))).sort(), [items]);

  const toggleSort = (key: typeof sort.key) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: key === "created_at" ? -1 : 1 }));
  };

  const toggleSelect = (id: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const allSelected = items.length > 0 && items.every((t) => selected.has(t.id));
  const selectAll = () => setSelected(allSelected ? new Set() : new Set(items.map((t) => t.id)));

  const runBulk = async (kind: "retry" | "delete") => {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy(true);
    let ok = 0;
    let failed = 0;
    for (const id of ids) {
      try {
        if (kind === "retry") await api.retry(id);
        else await api.remove(id);
        ok += 1;
      } catch {
        failed += 1;
      }
    }
    setBusy(false);
    setSelected(new Set());
    setConfirm(null);
    if (failed) toast.push("error", `${kind === "retry" ? "重试" : "删除"}部分失败`, `${ok} 成功 · ${failed} 失败`);
    else
      toast.push(
        "success",
        kind === "retry" ? `已重新提交 ${ok} 个任务` : `已删除 ${ok} 个任务`,
        kind === "delete" ? "产物与上传文件已释放，任务记录保留" : undefined,
      );
    onChanged();
    void load();
  };

  const retryOne = async (t: TaskSummary) => {
    try {
      const res = await api.retry(t.id);
      toast.push("success", "已重新提交", `${shortId(res.task_id)} · ${t.model_alias}`);
      onChanged();
      void load();
    } catch (err) {
      toast.push("error", "重试失败", (err as Error).message);
    }
  };

  const exportQuery = useMemo(() => {
    const since = dayStart(applied.since);
    const until = dayEnd(applied.until);
    const range = since || until ? { since, until } : timeRange(hours);
    return {
      search: applied.search,
      status: applied.status,
      task_type: applied.task_type,
      model_alias: applied.model_alias,
      backend_id: applied.backend_id,
      since: range.since,
      until: range.until,
    };
  }, [applied, hours]);

  /**
   * Export: an empty selection exports the whole filtered set via the server
   * endpoint; an explicit selection is serialised locally.
   */
  const downloadSelection = (format: "json" | "csv") => {
    const picked = items.filter((t) => selected.has(t.id));
    if (selected.size === 0) {
      window.open(api.exportUrl(format, exportQuery), "_blank");
      toast.push("success", `正在导出 ${format.toUpperCase()}`, `按当前筛选（${total} 条）`);
      return;
    }
    let text: string;
    if (format === "json") {
      text = JSON.stringify({ total: picked.length, items: picked }, null, 2);
    } else {
      const head = ["id", "task_type", "status", "model_alias", "backend_id", "prompt", "created_at", "finished_at", "error_code"];
      const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
      text = [
        head.join(","),
        ...picked.map((r) => head.map((k) => esc((r as unknown as Record<string, unknown>)[k])).join(",")),
      ].join("\n");
    }
    const url = URL.createObjectURL(new Blob([text], { type: format === "json" ? "application/json" : "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `litegm-tasks-${picked.length}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
    toast.push("success", `已导出 ${picked.length} 条`, format.toUpperCase());
  };

  const pages = Math.max(1, Math.ceil(total / effectivePageSize));

  return (
    <div className="space-y-5 animate-fade-up">
      <SectionHeader
        eyebrow="历史档案"
        title="任务库"
        description="检索、对比并重跑历史任务；支持按状态、类型、模型与时间窗口筛选，批量重试或清理产物。"
        actions={
          <>
            <button className="btn btn-secondary" onClick={() => void load()}>
              <IconRefresh size={15} className={loading ? "animate-spin-slow" : ""} />
              刷新
            </button>
            <button className="btn btn-primary" onClick={onOpenStudio}>
              <IconSpark size={15} />
              新建任务
            </button>
          </>
        }
      />

      {/* ------------------------------------------------------ toolbar */}
      <div className="surface overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.07] px-3 py-2.5">
          <div className="seg" role="tablist" aria-label="视图模式">
            <button
              role="tab"
              aria-selected={mode === "gallery"}
              className={`seg-item ${mode === "gallery" ? "seg-item-active" : ""}`}
              onClick={() => setMode("gallery")}
            >
              <IconGrid size={14} />
              画廊
            </button>
            <button
              role="tab"
              aria-selected={mode === "table"}
              className={`seg-item ${mode === "table" ? "seg-item-active" : ""}`}
              onClick={() => setMode("table")}
            >
              <IconList size={14} />
              列表
            </button>
          </div>

          <div className="relative min-w-[200px] flex-1">
            <IconSearch size={15} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-500" />
            <input
              ref={searchRef}
              className="field pl-8"
              placeholder="搜索提示词、任务 ID 或模型…"
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") apply();
                if (e.key === "Escape") {
                  setFilters({ ...filters, search: "" });
                  setApplied({ ...applied, search: "" });
                }
              }}
              aria-label="搜索任务"
            />
          </div>

          <button
            className={`btn ${facetsOpen ? "btn-secondary" : "btn-ghost"} h-9`}
            onClick={() => setFacetsOpen((v) => !v)}
            aria-expanded={facetsOpen}
          >
            <IconFilter size={14} />
            筛选
            {activeFilters > 0 && (
              <span className="ml-0.5 rounded-full bg-amber-400/20 px-1.5 font-mono text-2xs text-amber-300">{activeFilters}</span>
            )}
            <IconChevronDown size={13} className={`transition-transform ${facetsOpen ? "rotate-180" : ""}`} />
          </button>
          <button className="btn btn-primary h-9" onClick={apply} disabled={loading}>
            查询
          </button>
        </div>

        {facetsOpen && (
          <div className="animate-fade-in space-y-4 px-3 py-3.5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div>
                <div className="label">状态</div>
                <div className="flex flex-wrap gap-1.5">
                  {STATUS_FACETS.map((s) => {
                    const on = filters.status === s.id;
                    return (
                      <button
                        key={s.id || "all"}
                        className={facetButtonClass(on)}
                        onClick={() => setFilters({ ...filters, status: s.id })}
                        aria-pressed={on}
                      >
                        {s.id && (
                          <span
                            className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle"
                            style={{ background: TONE_DOT[statusMeta(s.id).tone] }}
                          />
                        )}
                        {s.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <div className="label">类型</div>
                <div className="flex flex-wrap gap-1.5">
                  {[{ id: "", label: "全部类型" }, ...Object.entries(TASK_TYPES).map(([id, m]) => ({ id, label: m.label }))].map((t) => {
                    const on = filters.task_type === t.id;
                    return (
                      <button
                        key={t.id || "all"}
                        className={facetButtonClass(on)}
                        onClick={() => setFilters({ ...filters, task_type: t.id })}
                        aria-pressed={on}
                      >
                        <span
                          className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle"
                          style={{ background: t.id ? taskTypeMeta(t.id).accent : "#a3a0a0" }}
                        />
                        {t.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <div className="label">时间窗口</div>
                <div className="flex flex-wrap gap-1.5">
                  {TIME_FACETS.map((t) => (
                    <button
                      key={t.id || "all"}
                      className={facetButtonClass(timeFacet === t.id)}
                      onClick={() => setTimeFacet(t.id)}
                      aria-pressed={timeFacet === t.id}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex items-center gap-1.5">
                  <input
                    type="date"
                    className="field h-8 px-2 py-1 text-2xs"
                    value={filters.since}
                    onChange={(e) => setFilters({ ...filters, since: e.target.value })}
                    aria-label="起始日期"
                  />
                  <span className="text-2xs text-fg-600">→</span>
                  <input
                    type="date"
                    className="field h-8 px-2 py-1 text-2xs"
                    value={filters.until}
                    onChange={(e) => setFilters({ ...filters, until: e.target.value })}
                    aria-label="结束日期"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <div>
                  <div className="label">模型</div>
                  <div className="relative">
                    <select
                      className="field appearance-none pr-8"
                      value={filters.model_alias}
                      onChange={(e) => setFilters({ ...filters, model_alias: e.target.value })}
                      aria-label="模型筛选"
                    >
                      <option value="">全部模型</option>
                      {modelOptions.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                    <IconChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-500" />
                  </div>
                </div>
                <div>
                  <div className="label">后端</div>
                  <input
                    className="field font-mono"
                    placeholder="全部后端（例如 gpu-1）"
                    value={filters.backend_id}
                    onChange={(e) => setFilters({ ...filters, backend_id: e.target.value })}
                    aria-label="后端筛选"
                  />
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn btn-secondary h-8 text-xs" onClick={apply}>
                <IconCheck size={13} />
                应用筛选
              </button>
              <button className="btn btn-ghost h-8 text-xs" onClick={clearAll} disabled={activeFilters === 0}>
                <IconClose size={13} />
                清除全部
              </button>
              <div className="ml-auto flex items-center gap-2 text-2xs text-fg-500">
                <span className="kbd">Enter</span> 查询
                <span className="kbd">Esc</span> 清空搜索
              </div>
            </div>
          </div>
        )}
      </div>

      {error && <ErrorBanner message={`任务加载失败：${error}`} onRetry={() => void load()} />}

      {/* ------------------------------------------------ result header */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-xs text-fg-500">
          共 <span className="font-mono text-fg-200">{total}</span> 条 · 第 {page + 1}/{pages} 页
          {activeFilters > 0 && <span className="ml-1.5 text-amber-300">（已筛选）</span>}
        </div>
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-amber-400/25 bg-amber-400/[0.07] px-2 py-1 animate-fade-in">
            <span className="text-2xs text-amber-200">已选 {selected.size} 项</span>
            <button className="btn btn-ghost h-6 px-1.5 text-2xs" onClick={() => setSelected(new Set())}>
              取消选择
            </button>
            <button className="btn btn-secondary h-6 px-2 text-2xs" onClick={() => setConfirm("retry")} disabled={busy}>
              <IconRetry size={12} />
              批量重试
            </button>
            <button className="btn btn-secondary h-6 px-2 text-2xs" onClick={() => downloadSelection("json")}>
              <IconDownload size={12} />
              导出 JSON
            </button>
            <button className="btn btn-secondary h-6 px-2 text-2xs" onClick={() => downloadSelection("csv")}>
              <IconDownload size={12} />
              CSV
            </button>
            <button className="btn btn-danger h-6 px-2 text-2xs" onClick={() => setConfirm("delete")} disabled={busy}>
              <IconTrash size={12} />
              删除
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button className="btn btn-ghost h-7 px-2 text-2xs" onClick={() => downloadSelection("csv")}>
            <IconDownload size={12} />
            导出 CSV
          </button>
          <button className="btn btn-ghost h-7 px-2 text-2xs" onClick={() => downloadSelection("json")}>
            <IconDownload size={12} />
            导出 JSON
          </button>
          <div className="relative">
            <select
              className="field h-7 appearance-none py-0 pl-2 pr-7 text-2xs"
              value={effectivePageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              aria-label="每页数量"
            >
              {(mode === "table" ? TABLE_SIZES : PAGE_SIZES).map((s) => (
                <option key={s} value={s}>
                  每页 {s}
                </option>
              ))}
            </select>
            <IconChevronDown size={12} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-fg-500" />
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------ content */}
      {loading && items.length === 0 ? (
        mode === "gallery" ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-busy="true">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="overflow-hidden rounded-xl border border-white/[0.07]">
                <Skeleton className="aspect-[4/5] rounded-none" />
                <div className="space-y-1.5 p-2.5">
                  <Skeleton className="h-2 w-3/4" />
                  <Skeleton className="h-2 w-1/3" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="surface overflow-hidden" aria-busy="true">
            <div className="space-y-px p-3">
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          </div>
        )
      ) : items.length === 0 ? (
        <EmptyState
          icon={<IconGallery size={22} />}
          title={activeFilters > 0 ? "没有符合筛选条件的任务" : "任务库还是空的"}
          hint={
            activeFilters > 0
              ? "尝试放宽状态、类型或时间窗口，或清除全部筛选。"
              : "在创作台提交一个任务，产物会出现在这里。"
          }
          action={
            <div className="flex items-center gap-2">
              {activeFilters > 0 && (
                <button className="btn btn-secondary h-8 text-xs" onClick={clearAll}>
                  清除筛选
                </button>
              )}
              <button className="btn btn-primary h-8 text-xs" onClick={onOpenStudio}>
                <IconSpark size={13} />
                打开创作台
              </button>
            </div>
          }
        />
      ) : mode === "gallery" ? (
        <GalleryView
          items={sorted}
          selected={selected}
          onToggle={toggleSelect}
          onOpen={onOpen}
          onRetry={(t) => void retryOne(t)}
          allSelected={allSelected}
          onSelectAll={selectAll}
        />
      ) : (
        <TableView
          items={sorted}
          selected={selected}
          onToggle={toggleSelect}
          onOpen={onOpen}
          onRetry={(t) => void retryOne(t)}
          sort={sort}
          onSort={toggleSort}
          allSelected={allSelected}
          onSelectAll={selectAll}
        />
      )}

      {/* ----------------------------------------------------- paginator */}
      {items.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] pt-4">
          <div className="text-2xs text-fg-500">
            显示 {page * effectivePageSize + 1}–{Math.min(total, (page + 1) * effectivePageSize)} / {total}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              className="btn btn-secondary h-8 px-2 text-xs"
              disabled={page === 0 || loading}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <IconChevronLeft size={14} />
              上一页
            </button>
            <div className="flex items-center gap-1">
              {paginationWindow(page, pages).map((p, i) =>
                p === null ? (
                  <span key={`gap-${i}`} className="px-1 text-2xs text-fg-600">
                    …
                  </span>
                ) : (
                  <button
                    key={p}
                    className={`h-8 min-w-8 rounded-lg px-2 font-mono text-2xs transition-colors ${
                      p === page
                        ? "bg-amber-400/15 text-amber-200 ring-1 ring-amber-400/30"
                        : "text-fg-400 hover:bg-white/[0.06] hover:text-fg-200"
                    }`}
                    onClick={() => setPage(p)}
                    aria-current={p === page ? "page" : undefined}
                    aria-label={`第 ${p + 1} 页`}
                  >
                    {p + 1}
                  </button>
                ),
              )}
            </div>
            <button
              className="btn btn-secondary h-8 px-2 text-xs"
              disabled={page + 1 >= pages || loading}
              onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            >
              下一页
              <IconChevronRight size={14} />
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirm === "delete"}
        title="删除选中的任务？"
        message={
          <>
            将移除 <span className="font-mono text-fg-100">{selected.size}</span> 个任务的产物与上传文件，任务记录保留。此操作不可撤销。
          </>
        }
        confirmLabel={`删除 ${selected.size} 项`}
        onConfirm={() => void runBulk("delete")}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "retry"}
        title="重新提交选中的任务？"
        message={
          <>
            将以原模型与参数重新提交 <span className="font-mono text-fg-100">{selected.size}</span> 个任务，生成新的任务记录。
          </>
        }
        danger={false}
        confirmLabel={`重试 ${selected.size} 项`}
        onConfirm={() => void runBulk("retry")}
        onClose={() => setConfirm(null)}
      />
    </div>
  );
}

/* --------------------------------------------------------------- gallery */

function GalleryView({
  items,
  selected,
  onToggle,
  onOpen,
  onRetry,
  allSelected,
  onSelectAll,
}: {
  items: TaskSummary[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
  onRetry: (t: TaskSummary) => void;
  allSelected: boolean;
  onSelectAll: () => void;
}) {
  const [cols, setCols] = useState(4);
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 1280px)");
    const mid = window.matchMedia("(min-width: 900px)");
    const update = () => setCols(wide.matches ? 4 : mid.matches ? 3 : 2);
    update();
    wide.addEventListener("change", update);
    mid.addEventListener("change", update);
    return () => {
      wide.removeEventListener("change", update);
      mid.removeEventListener("change", update);
    };
  }, []);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-2xs text-fg-500">
        <button className="btn btn-ghost h-6 px-1.5 text-2xs" onClick={onSelectAll}>
          <IconCheck size={12} />
          {allSelected ? "取消全选" : "全选本页"}
        </button>
        <span className="text-fg-600">·</span>
        <span>悬停显示操作，勾选后可批量处理</span>
      </div>
      <div className="grid items-start gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
        {items.map((t) => (
          <PrintCard
            key={t.id}
            task={t}
            selected={selected.has(t.id)}
            onToggle={() => onToggle(t.id)}
            onOpen={() => onOpen(t.id)}
            onRetry={() => onRetry(t)}
          />
        ))}
      </div>
    </div>
  );
}

function PrintCard({
  task,
  selected,
  onToggle,
  onOpen,
  onRetry,
}: {
  task: TaskSummary;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onRetry: () => void;
}) {
  const thumb = taskThumb(task);
  const meta = taskTypeMeta(task.task_type);
  const active = isActive(task.status);
  const failed = task.status === "failed" || task.status === "timed_out";
  const kind = thumb?.kind ?? (task.task_type === "video.generate" ? "video" : task.task_type === "audio.generate" ? "audio" : "image");
  const hasPreview = Boolean(thumb?.url);
  return (
    <div
      className={`group relative overflow-hidden rounded-xl border bg-ink-950 transition-all duration-150 ${
        selected ? "border-amber-400/50 ring-1 ring-amber-400/30" : "border-white/[0.08] hover:border-white/[0.18]"
      }`}
    >
      <button
        type="button"
        className={`relative block w-full overflow-hidden text-left ${hasPreview ? "checker" : ""}`}
        style={{ aspectRatio: "4 / 5" }}
        onClick={onOpen}
        aria-label={`打开任务 ${shortId(task.id)}：${truncate(task.prompt || meta.label, 48)}`}
      >
        {hasPreview ? (
          <MediaThumb src={thumb?.url ?? null} kind={kind} alt={task.prompt} ratio="h-full" className="!aspect-auto" />
        ) : (
          // No media to show: a typographic cover keeps the grid visually even
          // instead of leaving an empty checker block.
          <div className="flex h-full w-full flex-col justify-between bg-[radial-gradient(120%_90%_at_20%_0%,rgba(240,176,74,0.10),transparent_60%)] p-3">
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
              <span className="text-2xs uppercase tracking-[0.16em] text-fg-500">{meta.label}</span>
            </div>
            <div className="flex items-end justify-between">
              <span className="font-display text-[2.6rem] font-semibold leading-none tracking-tight text-fg-500/70">
                {meta.short}
              </span>
              <span className="text-right font-mono text-2xs leading-tight text-fg-600">
                {task.model_alias}
              </span>
            </div>
          </div>
        )}
        {kind === "video" && hasPreview && (
          <span className="pointer-events-none absolute bottom-2 right-2 grid h-6 w-6 place-items-center rounded-full border border-white/20 bg-black/55 text-white/85 backdrop-blur">
            <IconPlay size={11} />
          </span>
        )}
        {active && <div className="absolute inset-0 animate-breathe bg-gradient-to-t from-azure-500/20 via-transparent to-transparent" />}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950/95 via-ink-950/20 to-transparent" />
        <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-1">
          <span className="inline-flex items-center gap-1 rounded-md border border-white/15 bg-black/50 px-1.5 py-0.5 text-2xs text-white/85 backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.accent }} />
            {meta.short}
          </span>
          {task.artifact_count > 1 && (
            <span className="rounded-md border border-white/15 bg-black/50 px-1.5 py-0.5 font-mono text-2xs text-white/85 backdrop-blur">
              ×{task.artifact_count}
            </span>
          )}
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 space-y-1 p-2.5">
          <div className="flex items-center gap-1.5">
            <StatusPill status={task.status} />
            {task.suspicious && (
              <span className="inline-flex items-center gap-0.5 rounded border border-amber-400/30 bg-amber-400/10 px-1 py-px text-2xs text-amber-300">
                <IconAlert size={10} />
                异常
              </span>
            )}
            <span className="ml-auto text-2xs text-fg-500">{dayLabel(task.created_at)}</span>
          </div>
          <div className="truncate text-2xs leading-snug text-fg-200">{truncate(task.prompt || "(无提示词)", 80)}</div>
          <div className="flex items-center gap-1.5 text-2xs text-fg-500">
            <span className="truncate font-mono">{task.model_alias}</span>
            <span>·</span>
            <span className="font-mono">{durationOf(task)}</span>
          </div>
          {failed && task.error_code && (
            <div className="truncate rounded border border-coral-500/25 bg-coral-500/[0.08] px-1 py-px font-mono text-2xs text-coral-300">
              {task.error_code}
            </div>
          )}
        </div>
      </button>

      <label
        className={`absolute right-2 top-2 flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border transition-all ${
          selected
            ? "border-amber-400 bg-amber-400 text-ink-950"
            : "border-white/20 bg-black/45 text-transparent opacity-0 backdrop-blur group-hover:opacity-100 hover:border-white/50"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <input type="checkbox" checked={selected} onChange={onToggle} className="sr-only" aria-label={`选择 ${shortId(task.id)}`} />
        <IconCheck size={13} />
      </label>

      <div className="absolute bottom-2 right-2 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <Tooltip text="详情">
          <IconButton label="查看详情" onClick={onOpen} className="h-7 w-7 border-white/15 bg-black/50 backdrop-blur hover:bg-black/70">
            <IconArrowUpRight size={13} />
          </IconButton>
        </Tooltip>
        <Tooltip text="重试">
          <IconButton label="重试" onClick={onRetry} className="h-7 w-7 border-white/15 bg-black/50 backdrop-blur hover:bg-black/70">
            <IconRetry size={13} />
          </IconButton>
        </Tooltip>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- table */

function TableView({
  items,
  selected,
  onToggle,
  onOpen,
  onRetry,
  sort,
  onSort,
  allSelected,
  onSelectAll,
}: {
  items: TaskSummary[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
  onRetry: (t: TaskSummary) => void;
  sort: { key: "created_at" | "finished_at" | "status" | "task_type" | "model_alias"; dir: 1 | -1 };
  onSort: (key: "created_at" | "finished_at" | "status" | "task_type" | "model_alias") => void;
  allSelected: boolean;
  onSelectAll: () => void;
}) {
  const cols: Array<{ key: typeof sort.key | null; label: string }> = [
    { key: null, label: "" },
    { key: "created_at", label: "时间" },
    { key: "status", label: "状态" },
    { key: "task_type", label: "类型" },
    { key: "model_alias", label: "模型" },
    { key: null, label: "提示词" },
    { key: null, label: "产物" },
    { key: "finished_at", label: "耗时" },
    { key: null, label: "" },
  ];
  return (
    <div className="surface overflow-hidden">
      <div className="max-h-[calc(100vh-280px)] overflow-auto">
        <table className="data-table">
          <thead>
            <tr>
              {cols.map((c, i) => (
                <th key={i} scope="col">
                  {c.key ? (
                    <button className="inline-flex items-center gap-1 hover:text-fg-200" onClick={() => onSort(c.key as typeof sort.key)}>
                      {c.label}
                      <span className={`text-[0.6rem] ${sort.key === c.key ? "text-amber-300" : "text-fg-600"}`}>
                        {sort.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  ) : i === 0 ? (
                    <input type="checkbox" checked={allSelected} onChange={onSelectAll} className="h-3.5 w-3.5 accent-amber-400" aria-label="全选本页" />
                  ) : (
                    c.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id} className={selected.has(t.id) ? "bg-amber-400/[0.05]" : undefined}>
                <td className="w-8">
                  <input
                    type="checkbox"
                    checked={selected.has(t.id)}
                    onChange={() => onToggle(t.id)}
                    className="h-3.5 w-3.5 accent-amber-400"
                    aria-label={`选择 ${shortId(t.id)}`}
                  />
                </td>
                <td className="whitespace-nowrap">
                  <div className="text-fg-300">{fmtTime(t.created_at)}</div>
                  <div className="text-2xs text-fg-500">{fmtRelative(t.created_at)}</div>
                </td>
                <td>
                  <StatusPill status={t.status} />
                </td>
                <td>
                  <span className="inline-flex items-center gap-1.5 text-2xs text-fg-300">
                    <TypeIcon type={t.task_type} size={13} />
                    {taskTypeMeta(t.task_type).label}
                  </span>
                </td>
                <td className="font-mono text-2xs text-fg-300">{t.model_alias}</td>
                <td className="max-w-[360px]">
                  <button className="block w-full truncate text-left text-fg-200 hover:text-fg-100" onClick={() => onOpen(t.id)} title={t.prompt}>
                    {t.prompt || <span className="text-fg-500">(无提示词)</span>}
                  </button>
                  <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-fg-500">
                    <span className="mono-id">{shortId(t.id)}</span>
                    <span className="font-mono">{t.backend_id}</span>
                    {t.error_code && (
                      <span className="rounded border border-coral-500/25 bg-coral-500/[0.07] px-1 font-mono text-coral-300">{t.error_code}</span>
                    )}
                  </div>
                </td>
                <td>
                  <span className="inline-flex items-center gap-1 font-mono text-2xs text-fg-300">
                    {t.artifact_count}
                    {t.suspicious && <IconAlert size={11} className="text-amber-400" />}
                  </span>
                </td>
                <td className="whitespace-nowrap font-mono text-2xs text-fg-400">{durationOf(t)}</td>
                <td className="w-20">
                  <div className="flex items-center justify-end gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                    <Tooltip text="详情">
                      <IconButton label="查看详情" onClick={() => onOpen(t.id)}>
                        <IconArrowUpRight size={13} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip text="重试">
                      <IconButton label="重试" onClick={() => onRetry(t)}>
                        <IconRetry size={13} />
                      </IconButton>
                    </Tooltip>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function paginationWindow(page: number, pages: number): Array<number | null> {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i);
  const out: Array<number | null> = [0];
  const start = Math.max(1, page - 1);
  const end = Math.min(pages - 2, page + 1);
  if (start > 1) out.push(null);
  for (let i = start; i <= end; i += 1) out.push(i);
  if (end < pages - 2) out.push(null);
  out.push(pages - 1);
  return out;
}
