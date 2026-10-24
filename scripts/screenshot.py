"""Headless screenshot helper for the admin UI (used for visual verification).

Starts Edge with remote debugging, injects the session cookie into the page,
waits for the app to load and captures a screenshot.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def _ws_url(port: int) -> str:
    for _ in range(60):
        try:
            data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
            for page in data:
                if page.get("type") == "page":
                    return page["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("Edge devtools did not come up")


def _devtools_ws_url(port: int) -> str:
    """Browser-level endpoint; used for cookies that apply to future navigations."""
    for _ in range(60):
        try:
            data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2))
            return data["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("Edge browser endpoint did not come up")


def main(url: str, cookie: str, out: Path) -> int:
    from websockets.sync.client import connect

    port = 9333
    proc = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={port}", "--window-size=1400,1400",
        f"--user-data-dir={out.parent / 'edge-profile'}",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with connect(_ws_url(port), max_size=64 * 1024 * 1024) as ws:
            msg_id = 0

            def call(method: str, params: dict | None = None):
                nonlocal msg_id
                msg_id += 1
                ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
                while True:
                    reply = json.loads(ws.recv())
                    if reply.get("id") == msg_id:
                        return reply

            call("Page.enable")
            call("Emulation.setDeviceMetricsOverride",
                 {"width": 1400, "height": 1400, "deviceScaleFactor": 1, "mobile": False})
            call("Page.navigate", {"url": url})
            time.sleep(2)

        # Set the cookie through the browser-level endpoint so it applies to the
        # already-loaded document, then reload.
        with connect(_devtools_ws_url(port), max_size=64 * 1024 * 1024) as bws:
            msg_id = 0

            def bcall(method: str, params: dict | None = None):
                nonlocal msg_id
                msg_id += 1
                bws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
                while True:
                    reply = json.loads(bws.recv())
                    if reply.get("id") == msg_id:
                        return reply

            bcall("Storage.setCookies", {"cookies": [{
                "name": "litegm_session", "value": cookie, "domain": "127.0.0.1",
                "path": "/", "httpOnly": True, "sameSite": "Lax",
            }]})

        with connect(_ws_url(port), max_size=64 * 1024 * 1024) as ws:
            msg_id = 0

            def call2(method: str, params: dict | None = None):
                nonlocal msg_id
                msg_id += 1
                ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
                while True:
                    reply = json.loads(ws.recv())
                    if reply.get("id") == msg_id:
                        return reply

            call2("Page.navigate", {"url": url})
            time.sleep(6)
            shot = call2("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            out.write_bytes(base64.b64decode(shot["result"]["data"]))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], Path(sys.argv[3])))
