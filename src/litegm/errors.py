"""Typed error hierarchy.

Every error carries an HTTP status, an OpenAI-style error ``type`` and ``code``
so that the API layer can render a compliant error body without leaking
implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiteGMError(Exception):
    message: str
    status: int = 500
    type: str = "server_error"
    code: str | None = None
    param: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_openai(self) -> dict[str, Any]:
        return {
            "error": {
                "type": self.type,
                "code": self.code,
                "message": self.message,
                "param": self.param,
            }
        }


class ConfigError(LiteGMError):
    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, status=500, type="server_error", code="config_error", **kw)


class AuthError(LiteGMError):
    def __init__(self, message: str = "Invalid or missing API key.") -> None:
        super().__init__(message, status=401, type="invalid_request_error", code="invalid_api_key")


class NotFoundError(LiteGMError):
    def __init__(self, message: str, code: str = "not_found", param: str | None = None) -> None:
        super().__init__(message, status=404, type="invalid_request_error", code=code, param=param)


class UnknownModelError(NotFoundError):
    def __init__(self, alias: str, task_type: str) -> None:
        super().__init__(
            f"model {alias!r} is not configured for {task_type}", code="model_not_found", param="model"
        )


class BadRequestError(LiteGMError):
    def __init__(self, message: str, code: str = "invalid_request", param: str | None = None) -> None:
        super().__init__(message, status=400, type="invalid_request_error", code=code, param=param)


class UnsupportedParameterError(BadRequestError):
    def __init__(self, message: str, param: str) -> None:
        super().__init__(message, code="unsupported_parameter", param=param)


class ValidationError(BadRequestError):
    def __init__(self, message: str, param: str | None = None) -> None:
        super().__init__(message, code="invalid_value", param=param)


class BackendUnavailableError(LiteGMError):
    def __init__(self, message: str, backend: str) -> None:
        super().__init__(
            message, status=503, type="server_error", code="backend_unavailable",
            details={"backend": backend},
        )


class QueueFullError(LiteGMError):
    def __init__(self, message: str, backend: str) -> None:
        super().__init__(
            message, status=429, type="rate_limit_error", code="rate_limit_exceeded",
            details={"backend": backend},
        )


class GenerationFailedError(LiteGMError):
    def __init__(self, message: str, code: str = "generation_failed", **kw: Any) -> None:
        super().__init__(message, status=422, type="invalid_request_error", code=code, **kw)


class SyncTimeoutError(LiteGMError):
    def __init__(self, message: str, task_id: str) -> None:
        super().__init__(
            message, status=504, type="server_error", code="sync_timeout",
            details={"task_id": task_id},
        )


class TaskCancelledError(LiteGMError):
    def __init__(self, message: str = "The task was cancelled.") -> None:
        super().__init__(message, status=409, type="invalid_request_error", code="task_cancelled")
