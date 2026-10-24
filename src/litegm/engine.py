"""Task execution engine.

A task moves through ``queued -> submitting -> running -> succeeded`` (or
``failed`` / ``cancelled``). Execution compiles the configured workflow, validates
it against the backend's node schemas, uploads input images, submits to ComfyUI,
polls for completion and downloads artifacts.

Work is queued per backend: at most ``backends[].concurrency`` tasks execute at a
time and at most ``backends[].queue_max`` may wait, after which new requests are
rejected with HTTP 429. Requests for ``n`` images submit the workflow ``n`` times
with distinct seeds (the templates do not support batching).

Configured fallbacks are tried in order when a variant fails before producing
output. Each attempt is recorded on the task for auditing and for the admin UI.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import random
import time
from typing import Any

from .backends import BackendRegistry
from .comfy import ComfyClient, iter_output_files, iter_text_outputs
from .config import Config, ModelVariant
from .errors import (
    GenerationFailedError,
    LiteGMError,
    QueueFullError,
)
from .requests import GenerationRequest, validate_request
from .storage import ArtifactStore, guess_mime, inspect_image
from .store import Task, TaskStore
from .workflow import (
    compile_workflow,
    load_image_node_ids,
    nodes_missing_inputs,
    validate_against_backend,
    wire_images,
)

log = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


class _BackendQueue:
    """Bounded queue enforcing per-backend concurrency and queue depth."""

    def __init__(self, backend_id: str, concurrency: int, queue_max: int) -> None:
        self.backend_id = backend_id
        self.concurrency = concurrency
        self.queue_max = queue_max
        self.running = 0
        self.waiting = 0
        self._sem = asyncio.Semaphore(concurrency)

    @contextlib.asynccontextmanager
    async def slot(self):
        if self.waiting >= self.queue_max:
            raise QueueFullError(
                f"backend {self.backend_id} queue is full "
                f"({self.running} running, {self.waiting} waiting)",
                self.backend_id,
            )
        self.waiting += 1
        try:
            await self._sem.acquire()
        except asyncio.CancelledError:
            self.waiting -= 1
            raise
        self.waiting -= 1
        self.running += 1
        try:
            yield
        finally:
            self.running -= 1
            self._sem.release()


class Engine:
    def __init__(
        self,
        config: Config,
        backends: BackendRegistry,
        tasks: TaskStore,
        artifacts: ArtifactStore,
    ) -> None:
        self._config = config
        self._backends = backends
        self._tasks = tasks
        self._artifacts = artifacts
        self._object_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._object_info_ttl = 300.0
        self._queues = {
            b.id: _BackendQueue(b.id, b.concurrency, b.queue_max) for b in config.backends
        }

    def queue_stats(self) -> dict[str, dict[str, int]]:
        return {
            bid: {"running": q.running, "waiting": q.waiting,
                  "concurrency": q.concurrency, "queue_max": q.queue_max}
            for bid, q in self._queues.items()
        }

    def apply_config(self, config: Config) -> None:
        """Swap in a reloaded configuration for subsequent tasks.

        In-flight tasks keep the configuration snapshot they were submitted with
        (they already hold their variant and compiled workflow), so swapping here
        only affects new work. Queues are rebuilt for the new backend set;
        queues of backends still in flight are preserved.
        """
        self._config = config
        new_queues: dict[str, _BackendQueue] = {}
        for b in config.backends:
            existing = self._queues.get(b.id)
            if existing is not None and existing.concurrency == b.concurrency \
                    and existing.queue_max == b.queue_max:
                new_queues[b.id] = existing
            else:
                new_queues[b.id] = _BackendQueue(b.id, b.concurrency, b.queue_max)
        for backend_id, queue in self._queues.items():
            if backend_id not in new_queues and (queue.running or queue.waiting):
                new_queues[backend_id] = queue
        self._queues = new_queues
        self.invalidate_object_info()

    # -- submission ------------------------------------------------------

    async def submit(self, req: GenerationRequest) -> Task:
        """Create a task. Raises validation errors before any GPU work."""
        variant = self._config.variant(req.task_type, req.model_alias)
        is_edit = req.task_type.endswith("edit")
        validate_request(req, variant, is_edit=is_edit)
        task = self._tasks.create_task(
            task_type=req.task_type,
            model_alias=req.model_alias,
            backend_id=variant.backend,
            prompt=req.prompt,
            request=req.to_audit(),
            status="queued",
        )
        self._tasks.add_event(task.id, "created", {"model": req.model_alias, "n": req.n})
        return task

    async def run(self, task: Task, req: GenerationRequest) -> None:
        """Execute a task to completion. Safe to call from a background task."""
        chain = self._fallback_chain(req.task_type, req.model_alias)
        attempts: list[dict[str, Any]] = []
        last_error: LiteGMError | None = None
        for idx, alias in enumerate(chain):
            if self._is_cancelled(task.id):
                self._finish(task.id, "cancelled", stage="cancelled")
                return
            attempt = {"alias": alias, "started_at": _now(), "status": "running"}
            attempts.append(attempt)
            self._tasks.update_task(task.id, attempts=attempts, model_alias=alias)
            try:
                await self._run_variant(task, req, alias)
                attempt.update(status="succeeded", finished_at=_now())
                self._tasks.update_task(task.id, attempts=attempts)
                return
            except LiteGMError as exc:
                attempt.update(
                    status="failed", finished_at=_now(),
                    error={"code": exc.code, "message": exc.message, "status": exc.status},
                )
                self._tasks.update_task(task.id, attempts=attempts)
                self._tasks.add_event(task.id, "attempt_failed", {"alias": alias, "code": exc.code})
                last_error = exc
                if idx + 1 < len(chain):
                    log.warning("task %s: %s failed (%s); falling back to %s",
                                task.id, alias, exc.code, chain[idx + 1])
                    continue
                break
            except asyncio.CancelledError:
                self._finish(task.id, "cancelled", stage="cancelled")
                raise
            except Exception as exc:  # noqa: BLE001 - surface unexpected errors to the client
                log.exception("task %s: unexpected error on %s", task.id, alias)
                attempt.update(
                    status="failed", finished_at=_now(),
                    error={"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"},
                )
                self._tasks.update_task(task.id, attempts=attempts)
                last_error = GenerationFailedError(
                    f"internal error while generating: {type(exc).__name__}: {exc}",
                    code="internal_error",
                )
                break

        err = last_error or GenerationFailedError("generation failed", code="generation_failed")
        if self._is_cancelled(task.id):
            self._finish(task.id, "cancelled", stage="cancelled")
            return
        self._finish(
            task.id,
            "failed",
            stage="failed",
            error={"code": err.code, "message": err.message, "status": err.status,
                   "details": err.details},
        )

    def _fallback_chain(self, task_type: str, alias: str) -> list[str]:
        chain = [alias]
        seen = {alias}
        cur = alias
        while True:
            variant = self._config.variant(task_type, cur)
            nxt = next((f for f in variant.fallbacks if f not in seen), None)
            if nxt is None:
                return chain
            chain.append(nxt)
            seen.add(nxt)
            cur = nxt

    # -- one attempt -----------------------------------------------------

    async def _run_variant(self, task: Task, req: GenerationRequest, alias: str) -> None:
        cfg = self._config
        variant = cfg.variant(req.task_type, alias)
        client = self._backends.get(variant.backend)
        queue = self._queues.get(variant.backend)

        self._tasks.update_task(task.id, status="queued", stage="waiting")
        if queue is None:
            await self._run_in_slot(task, req, alias, variant, client)
            return
        async with queue.slot():
            if self._is_cancelled(task.id):
                return
            await self._run_in_slot(task, req, alias, variant, client)

    async def _run_in_slot(
        self,
        task: Task,
        req: GenerationRequest,
        alias: str,
        variant: ModelVariant,
        client: ComfyClient,
    ) -> None:
        cfg = self._config
        self._tasks.update_task(task.id, status="submitting", stage="uploading", progress=5)
        uploads: list[str] = []
        if req.images:
            uploads = await self._upload_images(client, task.id, req)

        normalized = validate_request(req, variant, is_edit=req.task_type.endswith("edit"))
        quality_params = normalized.get("quality_params") or {}
        base_values: dict[str, Any] = {
            "prompt": req.prompt,
            "passthrough": req.prompt,
            "width": normalized["width"],
            "height": normalized["height"],
            "prefix": f"litegm/{task.id[:16]}",
            "negative_prompt": req.extra.get("negative_prompt", ""),
            "negative": req.extra.get("negative_prompt", ""),
            "output_format": normalized["output_format"],
            **quality_params,
        }
        if "seconds" in normalized:
            base_values["seconds"] = normalized["seconds"]
            base_values["duration"] = normalized["seconds"]

        object_info = await self._object_info(client)
        skip: set[str] = set()
        probe = compile_workflow(cfg, variant, {**base_values, "seed": int(normalized["seed"])})
        if req.images:
            wire_images(probe.workflow, variant, target_image=uploads[0],
                        reference_images=uploads[1:])
            skip |= load_image_node_ids(variant, len(req.images))
            if variant.image_slots and variant.image_slots.batch and variant.image_slots.batch.node:
                # Batch feeder contents are runtime uploads; link targets are checked.
                skip.add(variant.image_slots.batch.node)
            # Nodes whose required image inputs are absent from the template (e.g.
            # an i2v pipeline that derives its size from the uploaded frame).
            skip |= nodes_missing_inputs(probe.workflow, object_info, {"IMAGE"})

        total = max(1, normalized["n"])
        base_seed = int(normalized["seed"])
        saved: list[Any] = []
        prompt_ids: list[str] = []
        for i in range(total):
            seed = base_seed + i
            compiled = compile_workflow(cfg, variant, {**base_values, "seed": seed})
            if req.images:
                wire_images(
                    compiled.workflow,
                    variant,
                    target_image=uploads[0],
                    reference_images=uploads[1:],
                )
            if i == 0:
                self._tasks.update_task(task.id, stage="validating", progress=10,
                                        workflow=compiled.workflow)
            validate_against_backend(compiled.workflow, object_info, skip_nodes=skip)

            if self._is_cancelled(task.id):
                self._finish(task.id, "cancelled", stage="cancelled")
                return

            self._tasks.update_task(
                task.id, stage="submitting", progress=15 + int(10 * i / total),
            )
            prompt_id = await client.submit(compiled.workflow, client_id=f"litegm-{task.id}-{i}")
            prompt_ids.append(prompt_id)
            self._tasks.update_task(
                task.id, status="running", stage="generating",
                progress=20 + int(70 * i / total),
                comfy_prompt_id=prompt_id, started_at=_now(),
            )
            self._tasks.add_event(task.id, "submitted", {"alias": alias, "prompt_id": prompt_id, "index": i})

            entry = await self._poll(client, task.id, prompt_id)
            if entry.failed:
                raise GenerationFailedError(entry.error_text(), code="comfy_execution_error")
            files = iter_output_files(entry.outputs)
            if not files:
                raise GenerationFailedError("ComfyUI finished but produced no output files",
                                            code="no_output")
            self._tasks.update_task(task.id, stage="downloading", progress=90 + int(9 * i / total))
            for f in files:
                data = await client.download(f)
                kind = _kind_for(f)
                data, filename = _convert_format(data, f.filename, kind,
                                                 normalized["output_format"],
                                                 req.output_compression)
                saved.append(self._artifacts.save(
                    task_id=task.id, filename=filename, data=data, kind=kind,
                    meta={"backend": variant.backend, "prompt_id": prompt_id, "alias": alias,
                          "seed": seed, "index": i,
                          "comfy_file": {"filename": f.filename, "subfolder": f.subfolder,
                                         "type": f.type}},
                ))
            texts = iter_text_outputs(entry.outputs)
            if texts:
                self._tasks.add_event(task.id, "comfy_text", texts)

        self._finish(task.id, "succeeded", stage="completed", progress=100, error=None)
        self._tasks.add_event(task.id, "artifacts",
                              {"ids": [a.id for a in saved], "prompt_ids": prompt_ids})

    async def _upload_images(self, client: ComfyClient, task_id: str, req: GenerationRequest) -> list[str]:
        names: list[str] = []
        for idx, data in enumerate(req.images):
            name = req.image_names[idx] if idx < len(req.image_names) else f"image_{idx}.png"
            # Prefix with the task id so concurrent tasks cannot collide.
            stored = f"litegm_{task_id[5:21]}_{idx}_{os.path.basename(name) or 'image.png'}"
            path = self._artifacts.save_upload(stored, data)
            info = inspect_image(data)
            self._tasks.add_input_image(
                task_id, idx, os.path.basename(name) or "image.png", str(path), len(data),
                mime_type=guess_mime(name),
                width=info.get("width") if isinstance(info.get("width"), int) else None,
                height=info.get("height") if isinstance(info.get("height"), int) else None,
                role="target" if idx == 0 else "reference",
            )
            names.append(await client.upload_image(path))
        return names

    async def _poll(self, client: ComfyClient, task_id: str, prompt_id: str):
        """Wait for a prompt to finish, advancing an estimated progress.

        ComfyUI's ``/queue`` cannot report step-level progress, and the ``/ws``
        listener (``listen_progress``) is deferred to v4, so while a prompt is
        executing the progress is interpolated from elapsed time towards the
        per-image budget of this stage. The estimate never reaches 100 here;
        downloading and completion set the final values.

        The history endpoint remains the source of truth for completion.
        """
        variant_backend = client.backend
        started = time.monotonic()
        deadline = started + variant_backend.timeout_s
        interval = 2.0
        while True:
            entry = await client.history(prompt_id)
            if entry is not None and (entry.completed or entry.failed):
                return entry
            if self._is_cancelled(task_id):
                await client.interrupt()
                await client.delete_pending(prompt_id)
                return entry or _empty_history(prompt_id)
            if time.monotonic() > deadline:
                raise GenerationFailedError(
                    f"ComfyUI prompt {prompt_id} did not finish within {variant_backend.timeout_s:.0f}s",
                    code="backend_timeout",
                )
            self._advance_estimated_progress(task_id, started)
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, 10.0)

    def _advance_estimated_progress(self, task_id: str, started: float) -> None:
        """Move progress within the generating band using elapsed time.

        The band's floor is what the engine set when submitting; we only ever
        raise the value, and cap it just below the downloading stage.
        """
        from .observability import ESTIMATE_FULL_S

        task = self._tasks.get_task(task_id)
        if task is None:
            return
        elapsed = max(0.0, time.monotonic() - started)
        # 20%..88%: asymptotic so long tasks do not stall at the top.
        frac = min(1.0, elapsed / ESTIMATE_FULL_S)
        target = int(20 + 68 * frac)
        if target > task.progress:
            self._tasks.update_task(task_id, progress=min(target, 88))

    # -- helpers ---------------------------------------------------------

    async def _object_info(self, client: ComfyClient) -> dict[str, Any]:
        backend_id = client.backend.id
        cached = self._object_info_cache.get(backend_id)
        if cached and time.monotonic() - cached[0] < self._object_info_ttl:
            return cached[1]
        info = await client.object_info()
        self._object_info_cache[backend_id] = (time.monotonic(), info)
        return info

    def invalidate_object_info(self) -> None:
        self._object_info_cache.clear()

    def _is_cancelled(self, task_id: str) -> bool:
        t = self._tasks.get_task(task_id)
        return bool(t and t.cancel_requested)

    def _finish(self, task_id: str, status: str, **fields: Any) -> None:
        # A failed/cancelled task keeps the progress it reached; only terminal
        # success sets 100 explicitly (callers pass progress=100 there).
        self._tasks.update_task(task_id, status=status, finished_at=_now(), **fields)
        self._tasks.add_event(task_id, f"status:{status}", {k: v for k, v in fields.items() if k != "error"})
        task = self._tasks.get_task(task_id)
        if task is not None and task.started_at:
            from .observability import METRICS

            METRICS.observe_task(task.task_type, status, max(0.0, _now() - task.started_at))

    async def cancel(self, task_id: str) -> bool:
        t = self._tasks.get_task(task_id)
        if t is None:
            return False
        if t.status in ("succeeded", "failed", "cancelled", "timed_out"):
            return False
        self._tasks.update_task(task_id, cancel_requested=1)
        if t.comfy_prompt_id:
            client = self._backends.get(t.backend_id)
            await client.delete_pending(t.comfy_prompt_id)
            await client.interrupt()
        return True


def _empty_history(prompt_id: str):
    from .comfy import HistoryEntry

    return HistoryEntry(prompt_id=prompt_id, status_str="interrupted", completed=False,
                        messages=[], outputs={}, raw={})


def _kind_for(f) -> str:
    name = f.filename.lower()
    if name.endswith((".mp4", ".webm", ".mkv", ".mov")):
        return "video"
    if name.endswith((".flac", ".mp3", ".wav", ".ogg", ".opus")):
        return "audio"
    return "image"


def _convert_format(
    data: bytes,
    filename: str,
    kind: str,
    output_format: str,
    output_compression: int | None,
) -> tuple[bytes, str]:
    """Convert an image artifact to the requested format when necessary.

    ComfyUI saves PNG; ``webp``/``jpeg`` outputs are produced here so the API can
    honour ``output_format``/``output_compression`` regardless of the workflow.
    """
    if kind != "image" or output_format in ("", "png"):
        return data, filename
    target = "jpeg" if output_format in ("jpeg", "jpg") else output_format
    if target not in ("webp", "jpeg"):
        return data, filename
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im.load()
        quality = output_compression if output_compression is not None else 90
        if target == "jpeg":
            # JPEG has no alpha channel.
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format=target.upper(), quality=quality)
        stem = os.path.splitext(filename)[0]
        ext = ".jpg" if target == "jpeg" else ".webp"
        return buf.getvalue(), f"{stem}{ext}"
    except Exception as exc:  # noqa: BLE001 - keep the PNG rather than failing the task
        log.warning("failed to convert %s to %s: %s", filename, target, exc)
        return data, filename
