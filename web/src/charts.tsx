/** Tiny hand-drawn SVG charts: sparkline, donut meter, radial gauge, bar meter.
 *
 * No chart library — everything is inline SVG with the Darkroom tokens so the
 * dashboards stay visually consistent with the rest of the console. Each chart
 * also carries a text equivalent for assistive technology.
 */

import { useId } from "react";

export type SeriesPoint = { t: number; v: number };

const STROKE: Record<string, string> = {
  amber: "#f0b04a",
  jade: "#45d6c4",
  coral: "#ff6b81",
  azure: "#5aa8ff",
  violet: "#a68cff",
};

export function toneColor(tone: string): string {
  return STROKE[tone] ?? "#a3a0a0";
}

/** Monotone-ish polyline used by the pulse strip and queue sparkline. */
export function Sparkline({
  data,
  width = 220,
  height = 48,
  tone = "amber",
  fill = true,
  label,
  className = "",
}: {
  data: SeriesPoint[];
  width?: number;
  height?: number;
  tone?: string;
  fill?: boolean;
  label?: string;
  className?: string;
}) {
  const uid = useId().replace(/[:]/g, "");
  const color = toneColor(tone);
  const pad = 3;
  const values = data.map((d) => d.v);
  const max = Math.max(1, ...values);
  const n = data.length;
  const step = n > 1 ? (width - pad * 2) / (n - 1) : 0;
  const points = data.map((d, i) => {
    const x = pad + i * step;
    const y = height - pad - (Math.max(0, d.v) / max) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  const area = `${line} L${(pad + (n - 1) * step).toFixed(2)} ${height - pad} L${pad} ${height - pad} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={label ?? `趋势图，峰值 ${max}`}
      className={className}
    >
      <defs>
        <linearGradient id={`spark-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.32" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
        <line
          key={f}
          x1={pad}
          x2={width - pad}
          y1={pad + f * (height - pad * 2)}
          y2={pad + f * (height - pad * 2)}
          stroke="rgba(255,255,255,0.05)"
          strokeWidth="1"
        />
      ))}
      {fill && n > 1 && <path d={area} fill={`url(#spark-${uid})`} />}
      {n > 1 && <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />}
      {n > 0 && (
        <circle
          cx={points[points.length - 1][0]}
          cy={points[points.length - 1][1]}
          r="2.4"
          fill={color}
          stroke="#06070a"
          strokeWidth="1.2"
        />
      )}
      {n <= 1 && (
        <line x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} stroke="rgba(255,255,255,0.14)" strokeDasharray="2 3" />
      )}
    </svg>
  );
}

/** Radial usage meter (storage budget, queue saturation). */
export function RadialMeter({
  value,
  size = 132,
  stroke = 9,
  tone = "amber",
  track = "rgba(255,255,255,0.07)",
  center,
  ariaLabel,
}: {
  value: number;
  size?: number;
  stroke?: number;
  tone?: string;
  track?: string;
  center?: React.ReactNode;
  ariaLabel?: string;
}) {
  const v = Math.max(0, Math.min(100, value));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  // Leave a 20% gap at the bottom so the meter reads as a gauge, not a spinner.
  const span = c * 0.8;
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={ariaLabel ?? `使用率 ${Math.round(v)}%`}>
      <svg width={size} height={size} className="rotate-[126deg]">
        <circle cx={size / 2} cy={size / 2} r={r} stroke={track} strokeWidth={stroke} fill="none" strokeLinecap="round" strokeDasharray={`${span} ${c}`} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={toneColor(tone)}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${(v / 100) * span} ${c}`}
          className="transition-[stroke-dasharray] duration-700 ease-out"
          style={{ filter: `drop-shadow(0 0 6px ${toneColor(tone)}55)` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">{center}</div>
    </div>
  );
}

/** Horizontal composition bar (storage split, task mix). */
export function StackBar({
  segments,
  height = 8,
  ariaLabel,
}: {
  segments: Array<{ value: number; tone: string; label: string }>;
  height?: number;
  ariaLabel?: string;
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0) || 1;
  return (
    <div
      className="flex w-full overflow-hidden rounded-full bg-white/[0.06]"
      style={{ height }}
      role="img"
      aria-label={ariaLabel ?? segments.map((s) => `${s.label} ${Math.round((s.value / total) * 100)}%`).join("，")}
    >
      {segments.map((s) => (
        <span
          key={s.label}
          className="h-full transition-[width] duration-500 ease-out"
          style={{ width: `${(Math.max(0, s.value) / total) * 100}%`, background: toneColor(s.tone) }}
          title={`${s.label}`}
        />
      ))}
    </div>
  );
}

/** Discrete queue lane: running slots, waiting slots and free headroom. */
export function QueueLanes({
  running,
  concurrency,
  waiting,
  queueMax,
}: {
  running: number;
  concurrency: number;
  waiting: number;
  queueMax: number;
}) {
  const conc = Math.max(1, concurrency);
  const slots = Math.min(conc, 8);
  const filled = Math.min(conc, Math.max(0, running));
  const waitPct = queueMax > 0 ? Math.min(100, (waiting / queueMax) * 100) : 0;
  return (
    <div className="space-y-2">
      <div>
        <div className="mb-1 flex items-center justify-between text-2xs text-fg-500">
          <span>执行槽位</span>
          <span className="font-mono text-fg-300">
            {running}/{concurrency}
          </span>
        </div>
        <div className="flex gap-1" role="img" aria-label={`执行槽位 ${running} 已用，共 ${concurrency}`}>
          {Array.from({ length: slots }).map((_, i) => (
            <span
              key={i}
              className={`h-2 flex-1 rounded-full ${
                i < filled ? "bg-jade-400 shadow-[0_0_10px_rgba(69,214,196,0.45)]" : "bg-white/[0.08]"
              }`}
            />
          ))}
          {concurrency > slots && <span className="pl-1 font-mono text-2xs text-fg-500">+{concurrency - slots}</span>}
        </div>
      </div>
      <div>
        <div className="mb-1 flex items-center justify-between text-2xs text-fg-500">
          <span>等待队列</span>
          <span className="font-mono text-fg-300">
            {waiting}/{queueMax || "∞"}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.06]" role="img" aria-label={`等待队列 ${waiting}，上限 ${queueMax}`}>
          <div
            className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-300 transition-[width] duration-500"
            style={{ width: `${queueMax > 0 ? Math.max(waiting > 0 ? 4 : 0, waitPct) : waiting > 0 ? 100 : 0}%` }}
          />
        </div>
      </div>
    </div>
  );
}

/** Small activity histogram for "last 24h" style strips. */
export function ActivityBars({
  buckets,
  tone = "amber",
  height = 40,
  label,
}: {
  buckets: number[];
  tone?: string;
  height?: number;
  label?: string;
}) {
  const max = Math.max(1, ...buckets);
  return (
    <div className="flex items-end gap-[3px]" style={{ height }} role="img" aria-label={label ?? "活动分布"}>
      {buckets.map((b, i) => (
        <span
          key={i}
          className="flex-1 rounded-sm transition-[height] duration-500"
          style={{
            height: `${Math.max(2, (b / max) * 100)}%`,
            background: b > 0 ? toneColor(tone) : "rgba(255,255,255,0.07)",
            opacity: b > 0 ? 0.35 + (b / max) * 0.65 : 1,
          }}
        />
      ))}
    </div>
  );
}
