"""Simple authentication from the configuration: a username plus a master key.

* API calls: ``Authorization: Bearer <master_key>`` — matches the OpenAI SDK's
  ``api_key`` parameter, so standard clients work unchanged.
* Admin UI: HTTP Basic (``username`` + ``master_key``) exchanged for a signed,
  HttpOnly session cookie.

All comparisons are constant-time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from .config import AuthConfig
from .errors import AuthError

SESSION_COOKIE = "litegm_session"


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


@dataclass
class Authenticator:
    config: AuthConfig

    def _key(self) -> bytes:
        return hashlib.sha256(self.config.master_key.encode("utf-8")).digest()

    # -- API -------------------------------------------------------------

    def check_bearer(self, authorization: str | None) -> bool:
        if not authorization:
            return False
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return False
        return hmac.compare_digest(token.strip().encode(), self.config.master_key.encode())

    def require_bearer(self, authorization: str | None) -> None:
        if not self.config.enabled:
            return
        if not self.check_bearer(authorization):
            raise AuthError()

    # -- admin -----------------------------------------------------------

    def check_basic(self, authorization: str | None) -> bool:
        if not self.config.enabled:
            return True
        if not authorization:
            return False
        scheme, _, payload = authorization.partition(" ")
        if scheme.lower() != "basic" or not payload:
            return False
        try:
            decoded = base64.b64decode(payload).decode("utf-8")
        except Exception:  # noqa: BLE001
            return False
        user, _, password = decoded.partition(":")
        ok_user = hmac.compare_digest(user.encode(), self.config.username.encode())
        ok_pass = hmac.compare_digest(password.encode(), self.config.master_key.encode())
        return ok_user and ok_pass

    def issue_session(self) -> str:
        expires = int(time.time()) + self.config.session_ttl_s
        body = {"u": self.config.username, "exp": expires}
        payload = _b64e(json.dumps(body, separators=(",", ":")).encode())
        sig = hmac.new(self._key(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def verify_session(self, token: str | None) -> bool:
        if not self.config.enabled:
            return True
        if not token or "." not in token:
            return False
        payload, _, sig = token.rpartition(".")
        expected = hmac.new(self._key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        try:
            body = json.loads(_b64d(payload))
        except Exception:  # noqa: BLE001
            return False
        if body.get("u") != self.config.username:
            return False
        return int(body.get("exp", 0)) >= int(time.time())
