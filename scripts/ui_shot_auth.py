"""Screenshot the litegm admin UI through an authenticated session.

Unlike ``ui_shot.py`` (which assumes auth is disabled), this logs in with the
configured username + master key, injects the signed session cookie into a
headless Edge instance and captures the requested view. Used to verify the
containerised production build.

Usage:
    python scripts/ui_shot_auth.py <base_url> <out.png> <view> [api_key]
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


def _wait_debugger(port: int, timeout: float = 40.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.load(r)["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise SystemExit("Edge DevTools endpoint did not come up")


def _login(base: str, username: str, key: str) -> str:
    """POST Basic auth to the admin login route and return the session cookie."""
    cred = base64.b64encode(f"{username}:{key}".encode()).decode()
    req = urllib.request.Request(
        f"{base}/admin/api/login", method="POST", headers={"Authorization": f"Basic {cred}"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        cookies = r.headers.get_all("Set-Cookie") or []
    for raw in cookies:
        name, _, rest = raw.partition("=")
        if name.strip() == "litegm_session":
            return rest.split(";", 1)[0]
    raise SystemExit("login succeeded but no litegm_session cookie was returned")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else ".cache/ui-auth.png")
    view = sys.argv[3] if len(sys.argv) > 3 else "overview"
    key = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("LITEGM_MASTER_KEY", "")
    if not key:
        raise SystemExit("master key required as 4th argument or LITEGM_MASTER_KEY")
    settle = float(os.environ.get("LITEGM_SHOT_SETTLE", "9"))
    full_page = os.environ.get("LITEGM_SHOT_FULL", "") not in ("", "0", "false")
    width = int(os.environ.get("LITEGM_SHOT_WIDTH", "1440"))
    height = int(os.environ.get("LITEGM_SHOT_HEIGHT", "1000"))

    cookie = _login(base, "admin", key)
    target = base + "/admin/" + (view if view.startswith("#") else VIEW_HASH.get(view, ""))
    out.parent.mkdir(parents=True, exist_ok=True)

    edge = _find_edge()
    profile = Path(tempfile.mkdtemp(prefix="litegm-edge-auth-", dir=str(out.parent)))
    port = _free_port()
    proc = subprocess.Popen(
        [
            edge, "--headless=old", "--no-sandbox", "--disable-gpu",
            "--no-first-run", "--hide-scrollbars", f"--window-size={width},{height}",
            f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        browser = CDP(_wait_debugger(port))
        host = base.split("//", 1)[1].split(":", 1)[0]
        # Set the cookie on the browser-level endpoint so it applies to the
        # navigation that follows, then load the app.
        browser.call("Storage.setCookies", {
            "cookies": [{
                "name": "litegm_session", "value": cookie, "domain": host,
                "path": "/", "httpOnly": True, "sameSite": "Lax",
            }]
        })
        info = browser.call("Target.createTarget", {"url": "about:blank"})
        session = browser.call(
            "Target.attachToTarget", {"targetId": info["targetId"], "flatten": True}
        )["sessionId"]
        browser.call("Page.enable", session=session)
        browser.call("Emulation.setDeviceMetricsOverride",
                     {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
                     session=session)
        browser.call("Page.navigate", {"url": target}, session=session)
        time.sleep(2)
        # The SPA checks /admin/api/me on first load; reload once the session
        # cookie is in place so it enters the console instead of the login page.
        browser.call("Page.navigate", {"url": target}, session=session)
        time.sleep(settle)
        probe = browser.call(
            "Runtime.evaluate",
            {"expression": "location.hash + ' | ' + document.body.innerText.slice(0, 60)",
             "returnByValue": True},
            session=session,
        )
        print("page:", probe.get("result", {}).get("value"))
        if view == "detail":
            js = (
                "(async () => {"
                " const res = await fetch('/admin/api/tasks?limit=60');"
                " const body = await res.json();"
                " const pick = body.items.find(t => t.artifact_count > 0) || body.items[0];"
                " if (!pick) return false;"
                " location.hash = '#tasks/' + pick.id; return pick.id; })()"
            )
            browser.call("Runtime.evaluate",
                         {"expression": js, "awaitPromise": True, "returnByValue": True},
                         session=session)
            time.sleep(settle)
        params = {"format": "png", "captureBeyondViewport": False}
        if full_page:
            params["captureBeyondViewport"] = True
            metrics = browser.call("Page.getLayoutMetrics", session=session)
            css = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            if css.get("height"):
                params["clip"] = {
                    "x": 0, "y": 0, "width": min(width, css.get("width", width)),
                    "height": min(6000, css["height"]), "scale": 1,
                }
        shot = browser.call("Page.captureScreenshot", params, session=session)
        out.write_bytes(base64.b64decode(shot["data"]))
        print(f"saved {out} ({out.stat().st_size} bytes)")
        browser.call("Browser.close")
        browser.close()
        return 0
    finally:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
