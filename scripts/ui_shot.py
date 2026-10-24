"""Screenshot litegm admin pages with headless Edge via the Chrome DevTools Protocol.

No Playwright, no cookie juggling: run the gateway with authentication disabled
(``LITEGM_AUTH_DISABLED=1`` or ``auth.enabled: false``) so the page loads
straight into the admin UI.

Why CDP instead of ``msedge --screenshot``: that one-shot flag cannot wait for
the SPA's API calls (``--virtual-time-budget`` deadlocks on the SSE event
stream), so data pages were captured while still showing "加载中…". Here we
open a CDP session, wait for the page to settle, then capture.

Usage:
    python scripts/ui_shot.py <url> <out.png> [view]

``view`` is one of ``overview`` (default), ``tasks``, ``studio``,
``playground`` (alias of studio), ``system``, ``detail``, or a raw hash such as
``#tasks/task_...``. Environment knobs: ``LITEGM_SHOT_SETTLE`` (seconds),
``LITEGM_SHOT_FULL=1`` (capture the full scroll height), ``LITEGM_SHOT_WIDTH``
and ``LITEGM_SHOT_HEIGHT``.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
VIEW_HASH = {
    "overview": "",
    "tasks": "#tasks",
    "studio": "#studio",
    "playground": "#studio",
    "system": "#system",
    "detail": "#tasks",
}


def _find_edge() -> str:
    env = os.environ.get("LITEGM_EDGE_PATH")
    if env and Path(env).exists():
        return env
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    raise SystemExit("msedge.exe not found; set LITEGM_EDGE_PATH")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CDP:
    """Minimal DevTools client over the browser's WebSocket endpoint."""

    def __init__(self, ws_url: str) -> None:
        from websockets.sync.client import connect

        self._ws = connect(ws_url, max_size=None)
        self._id = 0

    def call(self, method: str, params: dict | None = None, *, session: str | None = None) -> dict:
        self._id += 1
        msg: dict = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self._ws.send(json.dumps(msg))
        while True:
            resp = json.loads(self._ws.recv())
            if resp.get("id") != self._id:
                continue
            if "error" in resp:
                raise RuntimeError(f"{method} failed: {resp['error'].get('message')}")
            return resp.get("result") or {}

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass


def _wait_debugger(port: int, timeout: float = 30.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.load(r)["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise SystemExit("Edge DevTools endpoint did not come up")


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/admin/"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else ".cache/ui.png")
    view = sys.argv[3] if len(sys.argv) > 3 else "tasks"
    settle = float(os.environ.get("LITEGM_SHOT_SETTLE", "6"))
    out.parent.mkdir(parents=True, exist_ok=True)
    # ``view`` may be a named view or a raw hash such as ``#tasks/task_...``.
    target = url.rstrip("/") + (view if view.startswith("#") else VIEW_HASH.get(view, ""))
    full_page = os.environ.get("LITEGM_SHOT_FULL", "") not in ("", "0", "false")
    width = int(os.environ.get("LITEGM_SHOT_WIDTH", "1440"))
    height = int(os.environ.get("LITEGM_SHOT_HEIGHT", "1000"))

    edge = _find_edge()
    profile = Path(tempfile.mkdtemp(prefix="litegm-edge-", dir=str(out.parent)))
    port = _free_port()
    proc = subprocess.Popen(
        [
            edge, "--headless=old", "--no-sandbox", "--disable-gpu",
            "--no-first-run", "--hide-scrollbars", f"--window-size={width},{height}",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        cdp = CDP(_wait_debugger(port))
        target_info = cdp.call("Target.createTarget", {"url": "about:blank"})
        page = target_info["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId": page, "flatten": True})["sessionId"]
        cdp.call("Page.enable", session=session)
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
                 session=session)
        cdp.call("Page.navigate", {"url": target}, session=session)
        time.sleep(settle)  # let the SPA fetch its data
        if view == "detail":
            # Detail is addressable directly: pick a task that has a video
            # artifact so inline media previews are exercised, otherwise fall
            # back to opening the first row of the table view.
            js = (
                "(async () => {"
                " const res = await fetch('/admin/api/tasks?limit=60');"
                " const body = await res.json();"
                " const pick = body.items.find(t => t.task_type === 'video.generate' && t.artifact_count > 0)"
                "   || body.items.find(t => t.artifact_count > 0) || body.items[0];"
                " if (!pick) return false;"
                " location.hash = '#tasks/' + pick.id;"
                " return pick.id; })()"
            )
            cdp.call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True},
                     session=session)
            time.sleep(settle)
        params = {"format": "png", "captureBeyondViewport": False}
        if full_page:
            params["captureBeyondViewport"] = True
            metrics = cdp.call("Page.getLayoutMetrics", session=session)
            css = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            if css.get("height"):
                params["clip"] = {
                    "x": 0, "y": 0, "width": min(width, css.get("width", width)),
                    "height": min(6000, css["height"]), "scale": 1,
                }
        shot = cdp.call("Page.captureScreenshot", params, session=session)
        out.write_bytes(base64.b64decode(shot["data"]))
        print(f"saved {out} ({out.stat().st_size} bytes)")
        cdp.call("Browser.close")
        cdp.close()
        return 0
    finally:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
