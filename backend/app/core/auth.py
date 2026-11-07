"""Operator authentication and audit identity (V1.4 M1.4-1, hardened in M1.5-1a).

Identity is derived server-side only. No client header or body field can set the actor
id, actor type or display name; ``X-ASTRAVA-ACTOR-NAME`` has been removed.

Modes, decided per request by ``settings.OPERATOR_API_KEY``:

- Keyed (key set): every route not marked ``@public_route`` requires ``Authorization:
  Bearer <key>``, ``X-ASTRAVA-OPERATOR-KEY: <key>`` or a valid signed session cookie.
  Cookie-authenticated unsafe requests additionally require a matching ``X-CSRF-Token``.
- Local development (key unset): allowed only through the local-dev guard (loopback peer,
  allowed Host, no forwarding headers).

``authenticate_request`` is installed as a global FastAPI dependency (default deny).
"""

import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.core.guard import host_header_allowed, local_dev_request_allowed
from app.core.session import SESSION_COOKIE_NAME, revoked_sessions, verify_session

OPERATOR_KEY_HEADER = "X-ASTRAVA-OPERATOR-KEY"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PUBLIC_ROUTE_MARKER = "__astrava_public_route__"
FORBIDDEN_DETAIL = "Forbidden"
CREDENTIALS_DETAIL = "Missing or invalid operator credentials"

AuthMethod = Literal["api_key", "session", "local_dev"]


def public_route(endpoint):
    """Mark an endpoint as exempt from the global authentication dependency."""
    setattr(endpoint, PUBLIC_ROUTE_MARKER, True)
    return endpoint


def is_public_route(endpoint: object) -> bool:
    return getattr(endpoint, PUBLIC_ROUTE_MARKER, False) is True


@dataclass(frozen=True, kw_only=True)
class OperatorContext:
    """Authoritative identity of the caller for the current request."""

    actor_id: str
    actor_type: str = "operator"
    display_name: str
    auth_method: AuthMethod
    is_authenticated: bool
    is_authorized_verifier: bool


def _server_operator(
    auth_method: AuthMethod, actor_type: str, authenticated: bool
) -> OperatorContext:
    name = settings.DEFAULT_OPERATOR_NAME
    return OperatorContext(
        actor_id=name,
        display_name=name,
        actor_type=actor_type,
        auth_method=auth_method,
        is_authenticated=authenticated,
        is_authorized_verifier=True,
    )


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=CREDENTIALS_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _presented_keys(request: Request) -> list[str]:
    """Collect every operator-key candidate presented by the client."""
    candidates: list[str] = []
    header_key = request.headers.get(OPERATOR_KEY_HEADER)
    if header_key and header_key.strip():
        candidates.append(header_key.strip())
    authorization = request.headers.get("Authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            candidates.append(token.strip())
    return candidates


def _key_matches(presented: list[str], configured: str) -> bool:
    """Constant-time comparison; an empty configured key never matches (fail closed)."""
    if not configured:
        return False
    expected = configured.encode("utf-8")
    matched = False
    for candidate in presented:
        if secrets.compare_digest(candidate.encode("utf-8"), expected):
            matched = True
    return matched


async def get_operator_context(request: Request) -> OperatorContext:
    """Resolve the trusted operator for this request, or raise 401/403."""
    scope = request.scope
    if not host_header_allowed(scope):
        raise _forbidden()

    configured = settings.OPERATOR_API_KEY
    if configured is None:
        if not local_dev_request_allowed(scope):
            raise _forbidden()
        return _server_operator("local_dev", "operator_local_dev", authenticated=False)

    if _key_matches(_presented_keys(request), configured):
        return _server_operator("api_key", "operator", authenticated=True)

    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    claims = verify_session(configured, cookie, revoked=revoked_sessions)
    if claims is None:
        raise _unauthorized()

    if request.method.upper() in UNSAFE_METHODS:
        presented_csrf = request.headers.get(CSRF_HEADER, "")
        if not presented_csrf or not secrets.compare_digest(
            presented_csrf.encode("utf-8"), claims.csrf_token.encode("utf-8")
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed"
            )

    return _server_operator("session", "operator", authenticated=True)


async def authenticate_request(request: Request) -> None:
    """Global dependency: every route is authenticated unless marked ``@public_route``."""
    endpoint = request.scope.get("endpoint")
    if endpoint is not None and is_public_route(endpoint):
        return None
    await get_operator_context(request)
    return None


async def require_authorized_verifier(
    operator: OperatorContext = Depends(get_operator_context),
) -> OperatorContext:
    """FastAPI dependency that additionally requires verifier authorization."""
    if not operator.is_authorized_verifier:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Actor is not authorized to verify memories",
        )
    return operator


def derive_client_identity(
    client_value: str | None, operator: OperatorContext, *, subject: str = "operator"
) -> str:
    """Return the server-derived identity; a client-supplied value must match it or 403."""
    if client_value is None:
        return operator.display_name
    if client_value.strip() != operator.display_name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot impersonate {subject}; identity derived from authenticated operator context",
        )
    return operator.display_name
