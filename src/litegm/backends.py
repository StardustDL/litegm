"""Backend registry: owns one ComfyUI client per configured backend.

The registry can be replaced atomically on configuration hot-reload; clients that
are still executing work are retained until their tasks finish.
"""

from __future__ import annotations

import logging

from .comfy import ComfyClient
from .config import Config

log = logging.getLogger(__name__)


class BackendRegistry:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._clients: dict[str, ComfyClient] = {
            b.id: ComfyClient(b) for b in config.backends
        }

    def get(self, backend_id: str) -> ComfyClient:
        return self._clients[backend_id]

    def ids(self) -> list[str]:
        return list(self._clients)

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "id": b.id,
                "base_url": b.base_url,
                "concurrency": b.concurrency,
                "timeout_s": b.timeout_s,
                "tags": b.tags,
                "queue_max": b.queue_max,
            }
            for b in self._config.backends
        ]

    async def health_all(self) -> dict[str, dict[str, object]]:
        import asyncio

        ids = self.ids()
        results = await asyncio.gather(
            *(self._clients[i].health() for i in ids), return_exceptions=True
        )
        out: dict[str, dict[str, object]] = {}
        for backend_id, res in zip(ids, results, strict=True):
            if isinstance(res, BaseException):
                out[backend_id] = {"healthy": False, "error": f"{type(res).__name__}: {res}"}
            else:
                out[backend_id] = res
        return out

    async def replace(self, config: Config, *, keep: set[str]) -> None:
        """Swap in clients for a new configuration.

        Clients whose backends remain configured are reused (keeping pooled
        connections); backends that were removed are only closed once no task
        using them is active (``keep``).
        """
        new_clients: dict[str, ComfyClient] = {}
        retired: list[ComfyClient] = []
        for b in config.backends:
            existing = self._clients.get(b.id)
            if existing is not None and existing.backend == b:
                new_clients[b.id] = existing
            else:
                if existing is not None:
                    retired.append(existing)
                new_clients[b.id] = ComfyClient(b)
        for backend_id, client in self._clients.items():
            if backend_id not in new_clients:
                retired.append(client)
        self._config = config
        self._clients = new_clients
        for client in retired:
            if client.backend.id in keep:
                log.info("keeping retired backend client %s for in-flight tasks", client.backend.id)
            else:
                await client.aclose()

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
