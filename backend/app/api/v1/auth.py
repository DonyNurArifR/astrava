"""Operator session endpoints (M1.5-1a): login, session status and logout.

All three endpoints are public (``@public_route``): login performs its own key check,
session status never returns 401, and logout always succeeds.
"""

import logging
import math
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr

from app.config import settings
from app.core.auth import public_route
from app.core.security_config import is_loopback_address
from app.core.session import (
    SESSION_COOKIE_NAME,
    issue_session,
    revoked_sessions,
    verify_session,
)

logger = logging.getLogger("astrava.auth")
router = APIRouter(prefix="/auth", tags=["Auth"])

MAX_TRACKED_PEERS = 1024


class LoginRequest(BaseModel):
    api_key: SecretStr = Field(..., max_length=512)


class LoginResponse(BaseModel):
    authenticated: Literal[True] = True
    auth_method: Literal["session"] = "session"
    actor_id: str
    csrf_token: str
    expires_at: datetime


class SessionStatus(BaseModel):
    authenticated: bool
    auth_method: str | None
    login_required: bool
    actor_id: str | None
    csrf_token: str | None


class LogoutResponse(BaseModel):
    authenticated: Literal[False] = False


@dataclass
class _FailureWindow:
    count: int
    window_start: float


class LoginRateLimiter:
    """Per-peer failure counter. Bounded (max tracked peers) and purged of expired windows."""

    def __init__(self, max_tracked_peers: int = MAX_TRACKED_PEERS) -> None:
        self._windows: OrderedDict[str, _FailureWindow] = OrderedDict()
        self._max_tracked_peers = max_tracked_peers
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        window_seconds = settings.LOGIN_WINDOW_SECONDS
        expired = [
            peer for peer, win in self._windows.items() if now - win.window_start >= window_seconds
        ]
        for peer in expired:
            del self._windows[peer]

    def retry_after(self, peer: str, now: float) -> int:
        """Seconds until the peer may try again, or 0 when a login attempt is allowed."""
        with self._lock:
            self._purge_expired(now)
            win = self._windows.get(peer)
            if win is None or win.count < settings.LOGIN_MAX_FAILURES:
                return 0
            remaining = win.window_start + settings.LOGIN_WINDOW_SECONDS - now
            return max(1, math.ceil(remaining))

    def record_failure(self, peer: str, now: float) -> None:
        with self._lock:
            self._purge_expired(now)
            win = self._windows.get(peer)
            if win is None:
                win = _FailureWindow(count=0, window_start=now)
                self._windows[peer] = win
            win.count += 1
            while len(self._windows) > self._max_tracked_peers:
                self._evict_one(protect=peer)

    def _evict_one(self, protect: str) -> None:
        """Evict the oldest entry that is not yet locked out; a locked-out entry only if all are.

        Evicting a locked-out peer would let an attacker reset their lockout by flooding the
        store with fresh peers, so unlocked entries are always dropped first.
        """
        max_failures = settings.LOGIN_MAX_FAILURES
        for peer, win in self._windows.items():
            if peer != protect and win.count < max_failures:
                del self._windows[peer]
                return
        self._windows.popitem(last=False)

    def clear(self, peer: str) -> None:
        with self._lock:
            self._windows.pop(peer, None)

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._windows)


login_rate_limiter = LoginRateLimiter()


def _peer_key(request: Request) -> str:
    client = request.scope.get("client")
    return str(client[0]) if client else "unknown"


def _cookie_secure(request: Request) -> bool:
    if settings.COOKIE_SECURE is not None:
        return settings.COOKIE_SECURE
    return request.scope.get("scheme") == "https" or not is_loopback_address(settings.APP_HOST)


def _keys_equal(submitted: str, configured: str) -> bool:
    return secrets.compare_digest(submitted.encode("utf-8"), configured.encode("utf-8"))


@router.post("/login", response_model=LoginResponse)
@public_route
async def login(body: LoginRequest, request: Request, response: Response) -> LoginResponse:
    configured = settings.OPERATOR_API_KEY
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Login not required in local development mode",
        )

    peer = _peer_key(request)
    now = time.time()
    retry_after = login_rate_limiter.retry_after(peer, now)
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts",
            headers={"Retry-After": str(retry_after)},
        )

    submitted = body.api_key.get_secret_value()
    # An empty configured key never matches (fail closed).
    if not configured or not _keys_equal(submitted, configured):
        login_rate_limiter.record_failure(peer, now)
        logger.warning("Operator login rejected for peer %s", peer)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator credentials",
        )

    login_rate_limiter.clear(peer)
    issued = issue_session(configured, ttl_seconds=settings.SESSION_TTL_SECONDS, now=now)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=issued.token,
        max_age=settings.SESSION_TTL_SECONDS,
        path="/",
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(
        actor_id=settings.DEFAULT_OPERATOR_NAME,
        csrf_token=issued.csrf_token,
        expires_at=datetime.fromtimestamp(issued.expires_at, tz=UTC),
    )


@router.get("/session", response_model=SessionStatus)
@public_route
async def session_status(request: Request) -> SessionStatus:
    configured = settings.OPERATOR_API_KEY
    if configured is None:
        return SessionStatus(
            authenticated=False,
            auth_method="local_dev",
            login_required=False,
            actor_id=settings.DEFAULT_OPERATOR_NAME,
            csrf_token=None,
        )

    claims = verify_session(
        configured,
        request.cookies.get(SESSION_COOKIE_NAME),
        revoked=revoked_sessions,
    )
    if claims is None:
        return SessionStatus(
            authenticated=False,
            auth_method=None,
            login_required=True,
            actor_id=None,
            csrf_token=None,
        )
    return SessionStatus(
        authenticated=True,
        auth_method="session",
        login_required=True,
        actor_id=settings.DEFAULT_OPERATOR_NAME,
        csrf_token=claims.csrf_token,
    )


@router.post("/logout", response_model=LogoutResponse)
@public_route
async def logout(request: Request, response: Response) -> LogoutResponse:
    configured = settings.OPERATOR_API_KEY
    if configured:
        claims = verify_session(configured, request.cookies.get(SESSION_COOKIE_NAME))
        if claims is not None:
            revoked_sessions.revoke(claims.sid, claims.expires_at)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return LogoutResponse(authenticated=False)
