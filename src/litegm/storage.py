"""Artifact persistence: files on disk plus metadata in the task store.

Files are laid out per task under ``<storage.root>/artifacts/<task_id>/``.
A lightweight image sanity check flags all-black / empty results, which ComfyUI
itself reports as success.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import time
from pathlib import Path

from .config import Config
from .store import Artifact, TaskStore, new_id

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}

BLACK_MEAN_THRESHOLD = 3.0


def guess_mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return MIME_BY_EXT.get(suffix, "application/octet-stream")


def inspect_image(data: bytes) -> dict[str, object]:
    """Return width/height/mode and whether the image looks empty or black."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im.load()
        info: dict[str, object] = {"width": im.width, "height": im.height, "mode": im.mode}
        rgb = im.convert("RGB")
        # Sample a bounded, evenly-spaced set of pixels so huge images stay cheap.
        total = 0
        count = 0
        budget = 4096
        for y in range(im.height):
            for x in range(im.width):
                if (y * im.width + x) % max(1, (im.width * im.height) // budget) != 0:
                    continue
                r, g, b = rgb.getpixel((x, y))
                total += r + g + b
                count += 1
        if count:
            mean = total / (count * 3)
            info["mean"] = round(mean, 2)
            info["suspicious"] = mean < BLACK_MEAN_THRESHOLD
        else:
            info["suspicious"] = True
        return info
    except Exception as exc:  # noqa: BLE001 - never fail a task on inspection
        return {"inspect_error": f"{type(exc).__name__}: {exc}", "suspicious": False}


class ArtifactStore:
    def __init__(self, config: Config, tasks: TaskStore) -> None:
        self._config = config
        self._tasks = tasks
        self.root = config.storage_root()
        self.artifacts_dir = self.root / "artifacts"
        self.uploads_dir = self.root / "uploads"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        task_id: str,
        filename: str,
        data: bytes,
        kind: str = "image",
        meta: dict[str, object] | None = None,
    ) -> Artifact:
        safe_name = Path(filename).name or f"{kind}.bin"
        task_dir = self.artifacts_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        artifact_id = new_id("art")
        path = task_dir / f"{artifact_id}_{safe_name}"
        path.write_bytes(data)
        mime = guess_mime(safe_name)
        info: dict[str, object] = {}
        suspicious = False
        width = height = None
        if kind == "image":
            info = inspect_image(data)
            suspicious = bool(info.get("suspicious"))
            width = info.get("width") if isinstance(info.get("width"), int) else None
            height = info.get("height") if isinstance(info.get("height"), int) else None
        artifact = Artifact(
            id=artifact_id,
            task_id=task_id,
            kind=kind,
            filename=safe_name,
            path=str(path),
            mime_type=mime,
            size_bytes=len(data),
            width=width,
            height=height,
            suspicious=suspicious,
            meta={**(meta or {}), **info},
            created_at=time.time(),
        )
        self._tasks.add_artifact(task_id, artifact)
        return artifact

    def upload_path(self, name: str) -> Path:
        target = self.uploads_dir / Path(name).name
        return target

    def save_upload(self, name: str, data: bytes) -> Path:
        target = self.upload_path(name)
        target.write_bytes(data)
        return target

    def artifact_path(self, artifact: Artifact) -> Path:
        return Path(artifact.path)

    # -- signed download links ------------------------------------------

    def sign(self, artifact_id: str, expires_at: int) -> str:
        key = self._config.auth.master_key.encode()
        msg = f"{artifact_id}:{expires_at}".encode()
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def download_url(self, artifact_id: str, base_url: str | None = None) -> str:
        """Signed download link.

        ``base_url`` overrides the configured ``public_base_url`` so callers can
        build the link from the host the client actually used (see
        ``litegm.admin._request_base_url``). This keeps the URL correct when the
        gateway is reached on a port other than the configured public one.
        """
        expires = int(time.time()) + self._config.storage.download_url_ttl_s
        sig = self.sign(artifact_id, expires)
        path = f"/v1/files/{artifact_id}?expires={expires}&sig={sig}"
        if base_url:
            return base_url.rstrip("/") + "/" + path.lstrip("/")
        return self._config.public_url(path)

    def verify(self, artifact_id: str, expires: int, sig: str) -> bool:
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(self.sign(artifact_id, expires), sig)

    # -- retention -------------------------------------------------------

    def purge_expired(self) -> int:
        ttl_days = self._config.storage.artifact_ttl_days
        if ttl_days <= 0:
            return 0
        cutoff = time.time() - ttl_days * 86400
        removed = 0
        for art in self._tasks.delete_artifacts_before(cutoff):
            p = Path(art.path)
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
        return removed

    def usage(self) -> dict[str, int]:
        """Disk usage of the artifact and upload directories, in bytes."""
        def _size(directory: Path) -> int:
            total = 0
            for p in directory.rglob("*"):
                try:
                    if p.is_file():
                        total += p.stat().st_size
                except OSError:
                    continue
            return total

        artifacts = _size(self.artifacts_dir)
        uploads = _size(self.uploads_dir)
        return {"artifacts_bytes": artifacts, "uploads_bytes": uploads,
                "total_bytes": artifacts + uploads}

    def _remove_file(self, path: str) -> int:
        try:
            p = Path(path)
            size = p.stat().st_size if p.exists() else 0
            p.unlink(missing_ok=True)
            return size
        except OSError:
            return 0

    def sweep(self) -> dict[str, int]:
        """Apply retention rules: TTL by task outcome, then a disk budget (LRU).

        Failed/cancelled tasks keep their artifacts longer
        (``storage.failed_retention_days``) so they can be investigated.
        When ``storage.max_bytes`` is set, the oldest remaining items are evicted
        until usage fits the budget.
        """
        cfg = self._config.storage
        now = time.time()
        ttl = cfg.artifact_ttl_days
        failed_ttl = cfg.failed_retention_days
        if failed_ttl is None and ttl > 0:
            failed_ttl = ttl * 2
        removed = {"artifacts": 0, "input_images": 0, "bytes": 0}

        for art, status in self._tasks.list_artifacts_for_retention():
            days = failed_ttl if status in ("failed", "cancelled", "timed_out") else ttl
            if not days or days <= 0:
                continue
            if art.created_at < now - days * 86400:
                removed["bytes"] += self._remove_file(art.path)
                self._tasks.delete_artifact(art.id)
                removed["artifacts"] += 1

        for img, status in self._tasks.list_input_images_for_retention():
            days = failed_ttl if status in ("failed", "cancelled", "timed_out") else ttl
            if not days or days <= 0:
                continue
            created = img.get("created_at") or now
            if created < now - days * 86400:
                removed["bytes"] += self._remove_file(img["path"])
                self._tasks.delete_input_image(img["task_id"], img["index"])
                removed["input_images"] += 1

        max_bytes = cfg.max_bytes
        if max_bytes:
            used = self.usage()["total_bytes"]
            if used > max_bytes:
                for art, _status in self._tasks.list_artifacts_for_retention():
                    if used <= max_bytes:
                        break
                    size = self._remove_file(art.path)
                    self._tasks.delete_artifact(art.id)
                    removed["artifacts"] += 1
                    removed["bytes"] += size
                    used -= size
                for img, _status in self._tasks.list_input_images_for_retention():
                    if used <= max_bytes:
                        break
                    size = self._remove_file(img["path"])
                    self._tasks.delete_input_image(img["task_id"], img["index"])
                    removed["input_images"] += 1
                    removed["bytes"] += size
                    used -= size
        return removed

    def delete_task_files(self, task_id: str) -> int:
        """Remove a task's artifacts and uploaded inputs from disk."""
        freed = 0
        for art in self._tasks.list_artifacts(task_id):
            freed += self._remove_file(art.path)
        for path in self._tasks.delete_input_images(task_id):
            freed += self._remove_file(path)
        self._tasks.delete_task_artifacts(task_id)
        return freed
