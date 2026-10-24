"""Async client for a single ComfyUI backend.

Only the documented HTTP API is used, so the adapter works against any ComfyUI
instance regardless of host, version or installed custom nodes:

* ``GET  /system_stats``            – health / queue info
* ``GET  /object_info``             – node schemas, used to validate workflows
* ``POST /prompt``                  – queue a workflow
* ``GET  /history/{prompt_id}``     – poll status and outputs
* ``GET  /view``                    – download an output file
* ``POST /upload/image``            – upload an input image
* ``POST /interrupt``, ``POST /queue`` – cancel
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import BackendConfig
from .errors import BackendUnavailableError, GenerationFailedError, QueueFullError

log = logging.getLogger(__name__)


@dataclass
class OutputFile:
    filename: str
    subfolder: str
    type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryEntry:
    prompt_id: str
    status_str: str | None
    completed: bool
    messages: list[dict[str, Any]]
    outputs: dict[str, Any]
    raw: dict[str, Any]

    @property
    def failed(self) -> bool:
        return self.status_str == "error"

    def error_text(self) -> str:
        parts: list[str] = []
        for msg in self.messages:
            if msg.get("type") == "execution_error":
                d = msg.get("data", {})
                node = d.get("node_type") or d.get("node_id")
                exc = d.get("exception_message") or d.get("exception_type")
                parts.append(f"{node}: {exc}" if node else str(exc))
            elif msg.get("type") == "execution_interrupted":
                parts.append("interrupted")
        return "; ".join(p for p in parts if p) or "ComfyUI reported an execution error"


def _progress_state_percent(data: dict[str, Any]) -> int | None:
    """Overall completion estimate from a ``progress_state`` message.

    ``data['nodes']`` maps node ids to their state; sampler nodes report
    ``value``/``max`` step counts. The estimate is the mean of per-node step
    fractions across nodes that have started, weighted by finished nodes.
    """
    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return None
    fractions: list[float] = []
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        state = node.get("state")
        if state == "finished":
            fractions.append(1.0)
            continue
        value, max_value = node.get("value"), node.get("max")
        if isinstance(value, int) and isinstance(max_value, int) and max_value > 0:
            fractions.append(min(1.0, value / max_value))
    if not fractions:
        return None
    return int(100 * sum(fractions) / len(fractions))


def iter_output_files(outputs: dict[str, Any]) -> list[OutputFile]:
    """Flatten ComfyUI ``outputs`` into files.

    SaveVideo stores its result under ``images`` (with ``animated: true``),
    SaveImage/SaveImageAdvanced under ``images`` and SaveAudio under ``audio``.
    """
    files: list[OutputFile] = []
    for node_id, node_out in outputs.items():
        if not isinstance(node_out, dict):
            continue
        for key in ("images", "audio", "gifs", "videos"):
            items = node_out.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or "filename" not in item:
                    continue
                files.append(
                    OutputFile(
                        filename=item["filename"],
                        subfolder=item.get("subfolder", ""),
                        type=item.get("type", "output"),
                        metadata={**(item.get("metadata") or {}), "node_id": node_id, "key": key},
                    )
                )
    return files


def iter_text_outputs(outputs: dict[str, Any]) -> dict[str, str]:
    """Text nodes (PreviewAny) expose the prompt actually used; useful for audit."""
    out: dict[str, str] = {}
    for node_id, node_out in outputs.items():
        if isinstance(node_out, dict) and isinstance(node_out.get("text"), list):
            texts = [t for t in node_out["text"] if isinstance(t, str)]
            if texts:
                out[node_id] = "\n".join(texts)
    return out


class ComfyClient:
    def __init__(self, backend: BackendConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.backend = backend
        self._own_client = client is None
        headers: dict[str, str] = {}
        if backend.auth_header:
            headers["Authorization"] = backend.auth_header
        self._client = client or httpx.AsyncClient(
            base_url=backend.base_url,
            timeout=httpx.Timeout(backend.timeout_s, connect=15.0),
            headers=headers,
            verify=backend.verify_tls,
        )
        self._semaphore = asyncio.Semaphore(backend.concurrency)

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    # -- health ----------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        try:
            r = await self._client.get("/system_stats", timeout=10.0)
            r.raise_for_status()
            stats = r.json()
        except Exception as exc:  # noqa: BLE001 - surfaced to caller as unhealthy
            return {"healthy": False, "error": f"{type(exc).__name__}: {exc}"}
        sysinfo = stats.get("system", {}) if isinstance(stats, dict) else {}
        devices = stats.get("devices", []) if isinstance(stats, dict) else []
        queue = await self.queue_status()
        return {
            "healthy": True,
            "comfyui_version": sysinfo.get("comfyui_version"),
            "os": sysinfo.get("os"),
            "ram_free": sysinfo.get("ram_free"),
            "ram_total": sysinfo.get("ram_total"),
            "devices": devices,
            "queue": queue,
        }

    async def queue_status(self) -> dict[str, Any]:
        try:
            r = await self._client.get("/queue", timeout=10.0)
            r.raise_for_status()
            data = r.json()
            return {
                "running": len(data.get("queue_running", []) or []),
                "pending": len(data.get("queue_pending", []) or []),
            }
        except Exception:  # noqa: BLE001
            return {"running": None, "pending": None}

    async def object_info(self) -> dict[str, Any]:
        r = await self._client.get("/object_info", timeout=60.0)
        r.raise_for_status()
        return r.json()

    async def object_info_for(self, class_types: set[str]) -> dict[str, Any]:
        """Fetch schemas for specific node classes only (keeps responses small)."""
        params = {"q": ",".join(sorted(class_types))} if class_types else {}
        try:
            r = await self._client.get("/object_info", params=params, timeout=60.0)
            r.raise_for_status()
            data = r.json()
        except Exception:  # noqa: BLE001 - fall back to full dump
            return await self.object_info()
        if not data:
            return await self.object_info()
        return data

    # -- submission ------------------------------------------------------

    async def submit(self, workflow: dict[str, Any], client_id: str) -> str:
        payload = {"prompt": workflow, "client_id": client_id}
        async with self._semaphore:
            try:
                r = await self._client.post("/prompt", json=payload)
            except httpx.ConnectError as exc:
                raise BackendUnavailableError(
                    f"ComfyUI backend {self.backend.id} is unreachable: {exc}", self.backend.id
                ) from exc
            except httpx.TimeoutException as exc:
                raise BackendUnavailableError(
                    f"ComfyUI backend {self.backend.id} timed out on submit", self.backend.id
                ) from exc
        if r.status_code >= 400:
            text = r.text[:2000]
            if "Queue full" in text or '"error"' in text and "queue" in text.lower():
                raise QueueFullError(f"ComfyUI queue full on backend {self.backend.id}", self.backend.id)
            raise GenerationFailedError(
                f"ComfyUI rejected the workflow (HTTP {r.status_code}): {text}",
                code="workflow_rejected",
            )
        data = r.json()
        if data.get("error"):
            raise GenerationFailedError(
                f"ComfyUI rejected the workflow: {json.dumps(data['error'], ensure_ascii=False)[:2000]}",
                code="workflow_rejected",
            )
        if data.get("node_errors"):
            raise GenerationFailedError(
                f"ComfyUI reported node errors: {json.dumps(data['node_errors'], ensure_ascii=False)[:2000]}",
                code="node_errors",
            )
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise GenerationFailedError("ComfyUI did not return a prompt_id", code="workflow_rejected")
        return str(prompt_id)

    async def interrupt(self) -> None:
        try:
            await self._client.post("/interrupt", json={})
        except Exception as exc:  # noqa: BLE001
            log.warning("interrupt on %s failed: %s", self.backend.id, exc)

    async def delete_pending(self, prompt_id: str) -> None:
        try:
            await self._client.post("/queue", json={"delete": [prompt_id]})
        except Exception as exc:  # noqa: BLE001
            log.warning("queue delete on %s failed: %s", self.backend.id, exc)

    # -- polling ---------------------------------------------------------

    async def history(self, prompt_id: str) -> HistoryEntry | None:
        try:
            r = await self._client.get(f"/history/{prompt_id}", timeout=30.0)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            raise BackendUnavailableError(
                f"ComfyUI backend {self.backend.id} history failed: {exc}", self.backend.id
            ) from exc
        entry = data.get(prompt_id)
        if not entry:
            return None
        status = entry.get("status", {}) or {}
        return HistoryEntry(
            prompt_id=prompt_id,
            status_str=status.get("status_str"),
            completed=bool(status.get("completed")),
            messages=list(status.get("messages", []) or []),
            outputs=entry.get("outputs", {}) or {},
            raw=entry,
        )

    async def progress(self, prompt_id: str) -> int:
        """Best-effort progress from /prompt's queue position or /progress."""
        try:
            r = await self._client.get("/queue", timeout=10.0)
            r.raise_for_status()
            data = r.json()
        except Exception:  # noqa: BLE001
            return 0
        running = data.get("queue_running", []) or []
        pending = data.get("queue_pending", []) or []
        for item in running:
            if len(item) > 1 and item[1] == prompt_id:
                return 50
        for idx, item in enumerate(pending):
            if len(item) > 1 and item[1] == prompt_id:
                return max(5, 40 - idx * 5)
        return 0

    async def listen_progress(self, client_id: str):
        """Stream progress events for a client from ComfyUI's ``/ws`` endpoint.

        ComfyUI reports step progress through a ``progress_state`` message
        (``nodes`` -> ``value``/``max``) and per-node ``executing`` messages; some
        builds also send the older ``progress`` message. Yields
        ``(prompt_id, percent, node_id)`` tuples where ``percent`` is the overall
        completion estimate for that prompt.
        """
        import websockets

        ws_url = self.backend.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws?clientId={client_id}"
        async with websockets.connect(ws_url, max_size=None) as ws:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                data = msg.get("data") or {}
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    continue
                if mtype == "progress_state":
                    percent = _progress_state_percent(data)
                    if percent is not None:
                        yield prompt_id, percent, None
                elif mtype == "progress":
                    value = data.get("value")
                    max_value = data.get("max") or data.get("max_value")
                    node = data.get("node") or data.get("node_id")
                    if isinstance(value, int) and isinstance(max_value, int) and max_value > 0:
                        yield prompt_id, int(100 * value / max_value), node
                elif mtype == "executing":
                    node = data.get("node")
                    if node is None:
                        yield prompt_id, 100, None


    async def wait_for(self, prompt_id: str, *, timeout_s: float, poll_interval: float = 3.0) -> HistoryEntry:
        deadline = time.monotonic() + timeout_s
        while True:
            entry = await self.history(prompt_id)
            if entry is not None and (entry.completed or entry.failed):
                return entry
            if time.monotonic() > deadline:
                raise GenerationFailedError(
                    f"ComfyUI prompt {prompt_id} did not finish within {timeout_s:.0f}s",
                    code="backend_timeout",
                )
            await asyncio.sleep(poll_interval)

    # -- artifacts -------------------------------------------------------

    async def download(self, file: OutputFile) -> bytes:
        params = {"filename": file.filename, "subfolder": file.subfolder, "type": file.type}
        try:
            r = await self._client.get("/view", params=params, timeout=300.0)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as exc:
            raise GenerationFailedError(
                f"failed to download {file.filename}: {exc}", code="download_failed"
            ) from exc

    async def upload_image(self, path: str | os.PathLike[str], *, name: str | None = None) -> str:
        p = os.fspath(path)
        filename = name or os.path.basename(p)
        mime = mimetypes.guess_type(filename)[0] or "image/png"
        with open(p, "rb") as fh:
            content = fh.read()
        files = {"image": (filename, content, mime)}
        data = {"overwrite": "true", "type": "input"}
        try:
            r = await self._client.post("/upload/image", files=files, data=data, timeout=120.0)
            r.raise_for_status()
            res = r.json()
        except httpx.HTTPError as exc:
            raise GenerationFailedError(
                f"failed to upload {filename}: {exc}", code="upload_failed"
            ) from exc
        name_out = res.get("name") or filename
        sub = res.get("subfolder") or ""
        return f"{sub}/{name_out}" if sub else name_out
