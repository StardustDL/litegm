"""Persistent task storage.

Tasks are the unit of work in the gateway. A task records the normalized request,
the chosen model/backend, the compiled workflow snapshot, the ComfyUI prompt id,
timing and produced artifacts. Persisting these lets the gateway resume polling
after a restart and lets the admin UI show history and status.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    model_alias: Mapped[str] = mapped_column(String(128), index=True)
    backend_id: Mapped[str] = mapped_column(String(64), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    workflow_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    comfy_prompt_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(Float, index=True)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    cancel_requested: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[int] = mapped_column(Integer, default=0)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # image / video / audio
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suspicious: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any] | None] = mapped_column("meta_json", JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, index=True)


class EventRow(Base):
    """Append-only audit trail per task (state transitions, attempts, downloads)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    kind: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class InputImageRow(Base):
    """Uploaded input images kept so a task can be retried with identical inputs."""

    __tablename__ = "input_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """``target`` for the edited image, ``reference`` for extra inputs."""


Index("ix_artifacts_task", ArtifactRow.task_id)
Index("ix_events_task_ts", EventRow.task_id, EventRow.ts)
Index("ix_input_images_task", InputImageRow.task_id)

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


@dataclass
class Artifact:
    id: str
    task_id: str
    kind: str
    filename: str
    path: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    suspicious: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass
class Task:
    id: str
    task_type: str
    status: str
    model_alias: str
    backend_id: str
    prompt: str
    request: dict[str, Any]
    workflow: dict[str, Any] | None
    comfy_prompt_id: str | None
    progress: int
    stage: str | None
    error: dict[str, Any] | None
    attempts: list[dict[str, Any]]
    created_at: float
    started_at: float | None
    finished_at: float | None
    cancel_requested: bool


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite+pysqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        with self._engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
            conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        Base.metadata.create_all(self._engine)
        self._migrate()
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False)

    def _migrate(self) -> None:
        """Additive schema migration: bring existing databases up to date.

        ``create_all`` does not alter existing tables, so columns added in later
        versions are introduced here when missing.
        """
        additions = {
            "input_images": {
                "mime_type": "VARCHAR(128)",
                "width": "INTEGER",
                "height": "INTEGER",
                "role": "VARCHAR(32)",
            },
            "tasks": {
                "deleted": "INTEGER DEFAULT 0",
            },
        }
        with self._engine.connect() as conn:
            for table, columns in additions.items():
                existing = {
                    row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                }
                if not existing:
                    continue  # table not created yet (older layout)
                for name, ddl in columns.items():
                    if name not in existing:
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            conn.commit()

    def close(self) -> None:
        self._engine.dispose()

    # -- tasks -----------------------------------------------------------

    def create_task(
        self,
        *,
        task_type: str,
        model_alias: str,
        backend_id: str,
        prompt: str,
        request: dict[str, Any],
        status: str = "queued",
    ) -> Task:
        now = time.time()
        row = TaskRow(
            id=new_id("task"),
            task_type=task_type,
            status=status,
            model_alias=model_alias,
            backend_id=backend_id,
            prompt=prompt,
            request_json=request,
            workflow_json=None,
            comfy_prompt_id=None,
            progress=0,
            stage="queued",
            error_json=None,
            attempts=[],
            created_at=now,
            started_at=None,
            finished_at=None,
            cancel_requested=0,
        )
        with self._sessionmaker() as s:
            s.add(row)
            s.commit()
        return _to_task(row)

    def get_task(self, task_id: str) -> Task | None:
        with self._sessionmaker() as s:
            row = s.get(TaskRow, task_id)
            return _to_task(row) if row else None

    def list_tasks(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        task_type: str | None = None,
        model_alias: str | None = None,
        backend_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Task], int]:
        stmt = select(TaskRow)
        count_stmt = select(TaskRow.id)
        conds = []
        if not include_deleted:
            conds.append(TaskRow.deleted == 0)
        if status:
            conds.append(TaskRow.status == status)
        if task_type:
            conds.append(TaskRow.task_type == task_type)
        if model_alias:
            conds.append(TaskRow.model_alias == model_alias)
        if backend_id:
            conds.append(TaskRow.backend_id == backend_id)
        if since is not None:
            conds.append(TaskRow.created_at >= since)
        if until is not None:
            conds.append(TaskRow.created_at <= until)
        if search:
            # Case-insensitive substring match on the prompt or task id.
            pattern = f"%{search.lower()}%"
            conds.append(
                func.lower(TaskRow.prompt).like(pattern) | func.lower(TaskRow.id).like(pattern)
            )
        for c in conds:
            stmt = stmt.where(c)
            count_stmt = count_stmt.where(c)
        stmt = stmt.order_by(TaskRow.created_at.desc()).limit(limit).offset(offset)
        with self._sessionmaker() as s:
            rows = s.execute(stmt).scalars().all()
            total = len(s.execute(count_stmt).scalars().all())
        return [_to_task(r) for r in rows], total

    def update_task(self, task_id: str, **fields: Any) -> Task | None:
        mapping = {
            "status": "status",
            "stage": "stage",
            "progress": "progress",
            "comfy_prompt_id": "comfy_prompt_id",
            "error": "error_json",
            "attempts": "attempts",
            "workflow": "workflow_json",
            "started_at": "started_at",
            "finished_at": "finished_at",
            "cancel_requested": "cancel_requested",
        }
        with self._sessionmaker() as s:
            row = s.get(TaskRow, task_id)
            if row is None:
                return None
            for k, v in fields.items():
                col = mapping.get(k)
                if col is None:
                    continue
                setattr(row, col, int(v) if k == "cancel_requested" else v)
            s.commit()
            return _to_task(row)

    def active_tasks(self) -> list[Task]:
        """Tasks that were not finished — used to resume polling after a restart."""
        with self._sessionmaker() as s:
            rows = s.execute(
                select(TaskRow).where(TaskRow.status.in_(["queued", "submitting", "running"]))
            ).scalars().all()
        return [_to_task(r) for r in rows]

    def count_active_by_backend(self) -> dict[str, int]:
        with self._sessionmaker() as s:
            rows = s.execute(
                select(TaskRow.backend_id).where(TaskRow.status.in_(["submitting", "running"]))
            ).scalars().all()
        out: dict[str, int] = {}
        for b in rows:
            out[b] = out.get(b, 0) + 1
        return out

    def mark_interrupted(self) -> int:
        """On startup: tasks that were running in-process must be re-checked against ComfyUI."""
        now = time.time()
        with self._sessionmaker() as s:
            rows = s.execute(
                select(TaskRow).where(TaskRow.status.in_(["submitting", "running"]))
            ).scalars().all()
            for row in rows:
                if row.status == "submitting" and not row.comfy_prompt_id:
                    row.status = "queued"
                    row.stage = "queued"
                else:
                    row.stage = "resuming"
                row.finished_at = None
                _ = now
            s.commit()
            return len(rows)

    # -- artifacts -------------------------------------------------------

    def add_artifact(self, task_id: str, artifact: Artifact) -> None:
        row = ArtifactRow(
            id=artifact.id,
            task_id=task_id,
            kind=artifact.kind,
            filename=artifact.filename,
            path=artifact.path,
            mime_type=artifact.mime_type,
            size_bytes=artifact.size_bytes,
            width=artifact.width,
            height=artifact.height,
            suspicious=int(artifact.suspicious),
            meta=artifact.meta,
            created_at=artifact.created_at or time.time(),
        )
        with self._sessionmaker() as s:
            s.add(row)
            s.commit()

    def list_artifacts(self, task_id: str) -> list[Artifact]:
        with self._sessionmaker() as s:
            rows = s.execute(
                select(ArtifactRow).where(ArtifactRow.task_id == task_id).order_by(ArtifactRow.created_at)
            ).scalars().all()
        return [_to_artifact(r) for r in rows]

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        with self._sessionmaker() as s:
            row = s.get(ArtifactRow, artifact_id)
            return _to_artifact(row) if row else None

    def artifacts_for_tasks(self, task_ids: list[str]) -> dict[str, list[Artifact]]:
        if not task_ids:
            return {}
        with self._sessionmaker() as s:
            rows = s.execute(
                select(ArtifactRow).where(ArtifactRow.task_id.in_(task_ids))
            ).scalars().all()
        out: dict[str, list[Artifact]] = {}
        for r in rows:
            out.setdefault(r.task_id, []).append(_to_artifact(r))
        return out

    def list_artifacts_for_retention(self) -> list[tuple[Artifact, str]]:
        """All artifacts with their task status, oldest first (for retention)."""
        with self._sessionmaker() as s:
            rows = s.execute(
                select(ArtifactRow, TaskRow.status)
                .join(TaskRow, TaskRow.id == ArtifactRow.task_id, isouter=True)
                .order_by(ArtifactRow.created_at)
            ).all()
        return [(_to_artifact(r[0]), r[1] or "unknown") for r in rows]

    def delete_artifact(self, artifact_id: str) -> bool:
        with self._sessionmaker() as s:
            row = s.get(ArtifactRow, artifact_id)
            if row is None:
                return False
            s.delete(row)
            s.commit()
        return True

    def list_input_images_for_retention(self) -> list[tuple[dict[str, Any], str]]:
        """Input images with their task status, oldest first."""
        with self._sessionmaker() as s:
            rows = s.execute(
                select(InputImageRow, TaskRow.status, TaskRow.created_at)
                .join(TaskRow, TaskRow.id == InputImageRow.task_id, isouter=True)
                .order_by(TaskRow.created_at)
            ).all()
        out: list[tuple[dict[str, Any], str]] = []
        for img, status, created in rows:
            out.append(({
                "task_id": img.task_id,
                "index": img.idx,
                "filename": img.filename,
                "path": img.path,
                "size_bytes": img.size_bytes,
                "created_at": created,
            }, status or "unknown"))
        return out

    def delete_input_images(self, task_id: str) -> list[str]:
        """Remove input-image rows for a task; returns the removed file paths."""
        with self._sessionmaker() as s:
            rows = s.execute(
                select(InputImageRow).where(InputImageRow.task_id == task_id)
            ).scalars().all()
            paths = [r.path for r in rows]
            if rows:
                s.execute(delete(InputImageRow).where(InputImageRow.task_id == task_id))
                s.commit()
        return paths

    def delete_input_image(self, task_id: str, index: int) -> str | None:
        with self._sessionmaker() as s:
            row = s.execute(
                select(InputImageRow).where(InputImageRow.task_id == task_id, InputImageRow.idx == index)
            ).scalars().first()
            if row is None:
                return None
            path = row.path
            s.delete(row)
            s.commit()
        return path

    def delete_artifacts_before(self, cutoff: float) -> list[Artifact]:
        with self._sessionmaker() as s:
            rows = s.execute(
                select(ArtifactRow).where(ArtifactRow.created_at < cutoff)
            ).scalars().all()
            arts = [_to_artifact(r) for r in rows]
            if arts:
                s.execute(delete(ArtifactRow).where(ArtifactRow.created_at < cutoff))
                s.commit()
        return arts

    def delete_task_artifacts(self, task_id: str) -> None:
        with self._sessionmaker() as s:
            s.execute(delete(ArtifactRow).where(ArtifactRow.task_id == task_id))
            s.commit()

    def soft_delete_task(self, task_id: str) -> bool:
        """Hide a task from listings while keeping its audit record."""
        with self._sessionmaker() as s:
            row = s.get(TaskRow, task_id)
            if row is None:
                return False
            row.deleted = 1
            s.commit()
        return True

    def delete_task(self, task_id: str) -> None:
        with self._sessionmaker() as s:
            s.execute(delete(ArtifactRow).where(ArtifactRow.task_id == task_id))
            s.execute(delete(EventRow).where(EventRow.task_id == task_id))
            s.execute(delete(InputImageRow).where(InputImageRow.task_id == task_id))
            s.execute(delete(TaskRow).where(TaskRow.id == task_id))
            s.commit()

    # -- input images ----------------------------------------------------

    def add_input_image(
        self,
        task_id: str,
        idx: int,
        filename: str,
        path: str,
        size_bytes: int,
        *,
        mime_type: str | None = None,
        width: int | None = None,
        height: int | None = None,
        role: str | None = None,
    ) -> None:
        with self._sessionmaker() as s:
            s.add(InputImageRow(task_id=task_id, idx=idx, filename=filename,
                                path=path, size_bytes=size_bytes, mime_type=mime_type,
                                width=width, height=height, role=role))
            s.commit()

    def list_input_images(self, task_id: str) -> list[dict[str, Any]]:
        """Metadata for a task's uploaded inputs, in upload order."""
        with self._sessionmaker() as s:
            rows = s.execute(
                select(InputImageRow).where(InputImageRow.task_id == task_id).order_by(InputImageRow.idx)
            ).scalars().all()
        return [
            {
                "index": r.idx,
                "filename": r.filename,
                "path": r.path,
                "size_bytes": r.size_bytes,
                "mime_type": r.mime_type,
                "width": r.width,
                "height": r.height,
                "role": r.role,
            }
            for r in rows
        ]

    def get_input_image(self, task_id: str, index: int) -> dict[str, Any] | None:
        for item in self.list_input_images(task_id):
            if item["index"] == index:
                return item
        return None

    def input_images_for_tasks(self, task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Batch variant of ``list_input_images`` for list views (avoids N+1)."""
        if not task_ids:
            return {}
        with self._sessionmaker() as s:
            rows = s.execute(
                select(InputImageRow)
                .where(InputImageRow.task_id.in_(task_ids))
                .order_by(InputImageRow.task_id, InputImageRow.idx)
            ).scalars().all()
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(r.task_id, []).append({
                "index": r.idx,
                "filename": r.filename,
                "path": r.path,
                "size_bytes": r.size_bytes,
                "mime_type": r.mime_type,
                "width": r.width,
                "height": r.height,
                "role": r.role,
            })
        return out

    def get_task_inputs(self, task_id: str) -> list[tuple[str, bytes]]:
        """Return ``(filename, data)`` for a task's uploaded inputs, in order."""
        with self._sessionmaker() as s:
            rows = s.execute(
                select(InputImageRow).where(InputImageRow.task_id == task_id).order_by(InputImageRow.idx)
            ).scalars().all()
        out: list[tuple[str, bytes]] = []
        for r in rows:
            try:
                out.append((r.filename, Path(r.path).read_bytes()))
            except OSError:
                continue
        return out

    # -- events ----------------------------------------------------------

    def add_event(self, task_id: str, kind: str, data: dict[str, Any] | None = None) -> None:
        with self._sessionmaker() as s:
            s.add(EventRow(task_id=task_id, ts=time.time(), kind=kind, data=data))
            s.commit()

    def list_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._sessionmaker() as s:
            rows = s.execute(
                select(EventRow).where(EventRow.task_id == task_id).order_by(EventRow.ts.desc()).limit(limit)
            ).scalars().all()
        return [{"ts": r.ts, "kind": r.kind, "data": r.data} for r in rows]

    def counts_by_status(self) -> dict[str, int]:
        with self._sessionmaker() as s:
            rows = s.execute(select(TaskRow.status, TaskRow.id)).all()
        out: dict[str, int] = {}
        for status, _ in rows:
            out[status] = out.get(status, 0) + 1
        return out


def _to_task(row: TaskRow) -> Task:
    return Task(
        id=row.id,
        task_type=row.task_type,
        status=row.status,
        model_alias=row.model_alias,
        backend_id=row.backend_id,
        prompt=row.prompt,
        request=row.request_json or {},
        workflow=row.workflow_json,
        comfy_prompt_id=row.comfy_prompt_id,
        progress=row.progress or 0,
        stage=row.stage,
        error=row.error_json,
        attempts=row.attempts or [],
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        cancel_requested=bool(row.cancel_requested),
    )


def _to_artifact(row: ArtifactRow) -> Artifact:
    return Artifact(
        id=row.id,
        task_id=row.task_id,
        kind=row.kind,
        filename=row.filename,
        path=row.path,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        width=row.width,
        height=row.height,
        suspicious=bool(row.suspicious),
        meta=row.meta or {},
        created_at=row.created_at,
    )


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


__all__ = [
    "TaskStore",
    "Task",
    "Artifact",
    "TERMINAL_STATUSES",
    "new_id",
    "Session",
]
