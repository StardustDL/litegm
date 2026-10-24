/** litegm console: session handling, routing and live refresh. */

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Overview from "./Overview";
import Playground from "./Playground";
import { hashFor, Login, parseHash, Shell, type View } from "./Shell";
import System from "./System";
import TaskDetailView from "./TaskDetail";
import TaskList from "./TaskList";
import { ToastProvider } from "./ui";

const SESSION_KEY = "litegm.api_key";

export default function App() {
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const initial = parseHash();
  const [view, setView] = useState<View>(initial.view);
  const [selected, setSelected] = useState<string | null>(initial.taskId);
  const [refreshKey, setRefreshKey] = useState(0);
  const [live, setLive] = useState(true);
  const [reloadConfig, setReloadConfig] = useState(0);

  const navigate = useCallback((next: View, taskId?: string | null) => {
    setView(next);
    setSelected(next === "detail" ? taskId ?? null : null);
    const hash = hashFor(next, taskId);
    if (window.location.hash !== hash) {
      window.history.replaceState(null, "", `${window.location.pathname}${hash}`);
    }
  }, []);

  useEffect(() => {
    const onHash = () => {
      const next = parseHash();
      setView(next.view);
      setSelected(next.taskId);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    api
      .me()
      .then((r) => {
        // With auth disabled the gateway accepts every admin call, so the UI can
        // skip the login screen and use a placeholder key for the public API.
        if (r.authenticated) {
          setApiKey(r.auth_enabled === false ? "anonymous" : localStorage.getItem(SESSION_KEY) ?? "");
        }
        setChecked(true);
      })
      .catch(() => setChecked(true));
  }, []);

  useEffect(() => {
    if (!apiKey || !live) return;
    const es = new EventSource("/admin/api/events", { withCredentials: true });
    let pending = false;
    es.addEventListener("task", () => {
      if (pending) return;
      pending = true;
      window.setTimeout(() => {
        pending = false;
        setRefreshKey((k) => k + 1);
      }, 600);
    });
    return () => es.close();
  }, [apiKey, live]);

  if (!checked) {
    return (
      <div className="app-canvas flex min-h-full flex-col items-center justify-center gap-4">
        <div className="relative z-10 flex items-center gap-3">
          <span className="h-2 w-2 animate-breathe rounded-full bg-amber-400" />
          <span className="text-sm text-fg-400">正在连接控制台…</span>
        </div>
        <div className="relative z-10 w-56">
          <div className="skeleton h-1 rounded-full" />
        </div>
      </div>
    );
  }
  if (!apiKey) {
    return (
      <ToastProvider>
        <Login onLogin={setApiKey} />
      </ToastProvider>
    );
  }

  return (
    <ToastProvider>
      <Shell
        apiKey={apiKey}
        live={live}
        onToggleLive={setLive}
        view={view}
        onNavigate={navigate}
        refreshKey={refreshKey}
      >
        {view === "overview" && (
          <Overview
            refreshKey={refreshKey}
            onOpenTask={(id) => navigate("detail", id)}
            onOpenTasks={() => navigate("tasks")}
            onOpenStudio={() => navigate("studio")}
            onOpenSystem={() => navigate("system")}
            onChanged={() => setRefreshKey((k) => k + 1)}
          />
        )}
        {view === "tasks" && (
          <TaskList
            refreshKey={refreshKey}
            onOpen={(id) => navigate("detail", id)}
            onOpenStudio={() => navigate("studio")}
            onChanged={() => setRefreshKey((k) => k + 1)}
          />
        )}
        {view === "detail" && selected && (
          <TaskDetailView
            key={selected}
            id={selected}
            refreshKey={refreshKey}
            onBack={() => navigate("tasks")}
            onChanged={() => setRefreshKey((k) => k + 1)}
            onOpen={(id) => navigate("detail", id)}
            onReloadConfig={() => setReloadConfig((n) => n + 1)}
            configVersion={reloadConfig}
          />
        )}
        {view === "studio" && (
          <Playground
            apiKey={apiKey}
            onOpenTask={(id) => navigate("detail", id)}
            onSubmitted={() => setRefreshKey((k) => k + 1)}
          />
        )}
        {view === "system" && <System refreshKey={refreshKey} />}
      </Shell>
    </ToastProvider>
  );
}
