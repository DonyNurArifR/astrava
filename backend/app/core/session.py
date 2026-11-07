"""Stateless signed operator session tokens (M1.5-1a).

Token format: ``v1.<b64url(json payload)>.<b64url(HMAC-SHA256(session_key, b"v1." + payload_b64))>``
with payload ``{"sid": 32 hex chars, "iat": int, "exp": int}``.

The session key is derived from OPERATOR_API_KEY, so rotating the key invalidates every
session. Logout revokes a session id in a bounded in-memory set (best effort: a process
restart forgets revocations until the cookie expires; single-process deployment assumed).
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

SESSION_COOKIE_NAME = "astrava_session"
SESSION_TOKEN_VERSION = "v1"
SESSION_KEY_LABEL = b"astrava/session/v1"
CSRF_LABEL = b"csrf:"
CLOCK_SKEW_SECONDS = 60
MAX_TOKEN_LENGTH = 1024
REVOKED_SESSIONS_MAX = 4096


@dataclass(frozen=True)
class IssuedSession:
    token: str
    sid: str
    csrf_token: str
    expires_at: int


@dataclass(frozen=True)
class SessionClaims:
    sid: str
    csrf_token: str
    issued_at: int
    expires_at: int


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def derive_session_key(operator_key: str) -> bytes:
    """Derive the HMAC key used to sign session tokens from the operator key."""
    return hmac.new(operator_key.encode("utf-8"), SESSION_KEY_LABEL, hashlib.sha256).digest()


def csrf_token_for(session_key: bytes, sid: str) -> str:
    """CSRF token bound to a session id; never stored, recomputed on every check."""
    digest = hmac.new(session_key, CSRF_LABEL + sid.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


class RevokedSessionStore:
    """Bounded, process-local set of revoked session ids (sid -> expiry epoch seconds)."""

    def __init__(self, max_entries: int = REVOKED_SESSIONS_MAX) -> None:
        self._entries: OrderedDict[str, int] = OrderedDict()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        expired = [sid for sid, expires_at in self._entries.items() if expires_at <= now]
        for sid in expired:
            del self._entries[sid]

    def revoke(self, sid: str, expires_at: int, now: float | None = None) -> None:
        current = time.time() if now is None else now
        with self._lock:
            self._purge_expired(current)
            if expires_at <= current:
                return
            self._entries[sid] = expires_at
            self._entries.move_to_end(sid)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def is_revoked(self, sid: str, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        with self._lock:
            expires_at = self._entries.get(sid)
            if expires_at is None:
                return False
            if expires_at <= current:
                del self._entries[sid]
                return False
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


revoked_sessions = RevokedSessionStore()


def issue_session(
    operator_key: str, *, ttl_seconds: int, now: float | None = None
) -> IssuedSession:
    """Create a signed session token for a successfully authenticated operator."""
    if not operator_key:
        raise ValueError("Cannot issue a session without an operator key")
    if ttl_seconds <= 0:
        raise ValueError("Session TTL must be positive")
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + ttl_seconds
    sid = secrets.token_hex(16)
    payload = {"sid": sid, "iat": issued_at, "exp": expires_at}
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )

    session_key = derive_session_key(operator_key)
    signing_input = f"{SESSION_TOKEN_VERSION}.{payload_b64}".encode("ascii")
    signature = hmac.new(session_key, signing_input, hashlib.sha256).digest()
    token = f"{SESSION_TOKEN_VERSION}.{payload_b64}.{_b64url_encode(signature)}"
    return IssuedSession(
        token=token,
        sid=sid,
        csrf_token=csrf_token_for(session_key, sid),
        expires_at=expires_at,
    )


def verify_session(
    operator_key: str | None,
    token: str | None,
    *,
    now: float | None = None,
    revoked: RevokedSessionStore | None = None,
) -> SessionClaims | None:
    """Return the session claims for a valid, unexpired, unrevoked token, else None."""
    if not operator_key or not token or not isinstance(token, str):
        return None
    if len(token) > MAX_TOKEN_LENGTH:
        return None
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != SESSION_TOKEN_VERSION:
        return None
    _, payload_b64, signature_b64 = parts

    session_key = derive_session_key(operator_key)
    try:
        signing_input = f"{SESSION_TOKEN_VERSION}.{payload_b64}".encode("ascii")
        presented_signature = _b64url_decode(signature_b64)
    except ValueError:
        return None
    expected_signature = hmac.new(session_key, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(presented_signature, expected_signature):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    sid = payload.get("sid")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(sid, str) or len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
        return None
    if type(issued_at) is not int or type(expires_at) is not int:
        return None

    current = time.time() if now is None else now
    if issued_at > current + CLOCK_SKEW_SECONDS:
        return None
    if current >= expires_at:
        return None
    if revoked is not None and revoked.is_revoked(sid, now=current):
        return None

    return SessionClaims(
        sid=sid,
        csrf_token=csrf_token_for(session_key, sid),
        issued_at=issued_at,
        expires_at=expires_at,
    )
