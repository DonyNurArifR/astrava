"""Trusted operator identity for privileged API actions (V1.4 M1.4-1).

Identity is derived server-side, never from client-supplied verifier labels.

Modes:
- ``OPERATOR_API_KEY`` configured: requests must present the key via
  ``X-ASTRAVA-OPERATOR-KEY`` or ``Authorization: Bearer <key>``. Missing or wrong
  credentials yield 401. The optional ``X-ASTRAVA-ACTOR-NAME`` header supplies the
  display name (defaults to ``DEFAULT_OPERATOR_NAME``).
- ``OPERATOR_API_KEY`` unset (local development): the request is trusted. The
  display name comes from ``X-ASTRAVA-ACTOR-NAME`` or ``DEFAULT_OPERATOR_NAME``.
"""

import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.config import settings

OPERATOR_KEY_HEADER = "X-ASTRAVA-OPERATOR-KEY"
ACTOR_NAME_HEADER = "X-ASTRAVA-ACTOR-NAME"


@dataclass(frozen=True, kw_only=True)
class OperatorContext:
    """Authoritative identity of the caller for the current request."""

    actor_id: str
    actor_type: str = "operator"
    display_name: str
    is_authenticated: bool
    is_authorized_verifier: bool


def _resolve_display_name(request: Request) -> str:
    """Return the trimmed actor-name header, or the default when absent or blank."""
    raw = request.headers.get(ACTOR_NAME_HEADER)
    if raw is not None and raw.strip():
        return raw.strip()
    return settings.DEFAULT_OPERATOR_NAME


def _extract_presented_key(request: Request) -> list[str]:
    """Collect every credential candidate presented by the client."""
    candidates: list[str] = []
    header_key = request.headers.get(OPERATOR_KEY_HEADER)
    if header_key:
        candidates.append(header_key.strip())
    authorization = request.headers.get("Authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            candidates.append(token.strip())
    return candidates


async def get_operator_context(request: Request) -> OperatorContext:
    """FastAPI dependency that resolves the trusted operator for this request."""
    display_name = _resolve_display_name(request)
    configured_key = settings.OPERATOR_API_KEY

    if configured_key is not None:
        presented = _extract_presented_key(request)
        # Constant-time comparison; an empty configured key never matches (fail closed).
        authenticated = bool(configured_key) and any(
            secrets.compare_digest(candidate, configured_key) for candidate in presented
        )
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid operator credentials",
            )

    return OperatorContext(
        actor_id=display_name,
        display_name=display_name,
        is_authenticated=True,
        is_authorized_verifier=True,
    )


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
