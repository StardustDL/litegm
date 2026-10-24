/** Shared data hooks and layout primitives (contract module for view authors). */

import { useCallback, useEffect, useRef, useState } from "react";

/* ------------------------------------------------------------- data hooks */

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[],
  enabled = true,
): { data: T | null; error: string | null; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const next = await fetcherRef.current();
        if (!alive) return;
        setData(next);
        setError(null);
      } catch (err) {
        if (!alive) return;
        setError((err as Error).message);
      } finally {
        if (alive) setLoading(false);
      }
    };
    void run();
    if (!enabled || intervalMs <= 0) return () => { alive = false; };
    const timer = window.setInterval(run, intervalMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, tick, ...deps]);

  return { data, error, loading, refresh };
}

/* ---------------------------------------------------------------- layout */

export function Grid({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 ${className}`}>{children}</div>;
}

export function Stack({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`space-y-4 ${className}`}>{children}</div>;
}

export function TwoPane({
  left,
  right,
  leftClass = "",
  rightClass = "",
}: {
  left: React.ReactNode;
  right: React.ReactNode;
  leftClass?: string;
  rightClass?: string;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className={leftClass}>{left}</div>
      <div className={rightClass}>{right}</div>
    </div>
  );
}

export function Panel({
  title,
  actions,
  children,
  className = "",
  dense = false,
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  dense?: boolean;
}) {
  return (
    <section className={`surface ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-white/[0.07] px-4 py-3">
          <div className="eyebrow">{title}</div>
          {actions && <div className="flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={dense ? "" : "p-4"}>{children}</div>
    </section>
  );
}
