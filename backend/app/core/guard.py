"""Request guards for the operator security model (M1.5-1a).

``SecurityGuardMiddleware`` is a pure-ASGI middleware placed inside CORSMiddleware. It
enforces, for every HTTP request:

- Host header allowlist (port stripped, bracketed IPv6 supported; DNS-rebinding defense);
- local-development guard when OPERATOR_API_KEY is unset (loopback peer, allowed Host,
  no forwarding headers);
- Origin check on unsafe methods (explicit CORS origins or same-origin only; ``null`` rejected);
- rejection of CSRF "simple request" content types on unsafe methods (JSON bodies only).

The same helpers are reused by ``get_operator_context`` as defense in depth.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from app.config import settings
from app.core.security_config import is_loopback_address

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FORWARDING_HEADERS = frozenset(
    {
        b"forwarded",
        b"x-forwarded-for",
        b"x-forwarded-host",
        b"x-forwarded-proto",
        b"x-real-ip",
        b"via",
        b"cf-connecting-ip",
        b"true-client-ip",
        b"x-client-ip",
        b"x-cluster-client-ip",
        b"x-original-forwarded-for",
        b"fastly-client-ip",
        b"x-envoy-external-address",
    }
)
SIMPLE_REQUEST_MEDIA_TYPES = frozenset(
    {"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"}
)
FORBIDDEN_DETAIL = "Forbidden"

Scope = Mapping[str, Any]


def _header_values(scope: Scope, name: bytes) -> list[str]:
    return [
        value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == name
    ]


def parse_host_header(raw: str) -> str | None:
    """Return the lowercase hostname of a Host header value (port stripped), or None if invalid."""
    value = raw.strip()
    if not value or any(ch.isspace() for ch in value) or any(ch in value for ch in ",/@"):
        return None
    if value.startswith("["):
        end = value.find("]")
        if end <= 1:
            return None
        rest = value[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return value[: end + 1].lower()
    if value.count(":") == 1:
        host, _, port = value.partition(":")
        if not host or not port.isdigit():
            return None
        return host.lower()
    # Bare hostname, or an unbracketed IPv6 literal (matched exactly against the allowlist).
    return value.lower()


def _allowed_hosts() -> frozenset[str]:
    return frozenset(host.lower() for host in settings.ALLOWED_HOSTS)


def host_header_allowed(scope: Scope) -> bool:
    """True when exactly one Host header is present and its hostname is allowlisted."""
    values = _header_values(scope, b"host")
    if len(values) != 1:
        return False
    hostname = parse_host_header(values[0])
    return hostname is not None and hostname in _allowed_hosts()


def is_loopback_peer(scope: Scope) -> bool:
    """True only for a concrete loopback peer address; a missing client is not loopback."""
    client = scope.get("client")
    if not client:
        return False
    return is_loopback_address(str(client[0]))


def forwarding_headers_present(scope: Scope) -> bool:
    return any(key.lower() in FORWARDING_HEADERS for key, _ in scope.get("headers", []))


def local_dev_request_allowed(scope: Scope) -> bool:
    """Local-development guard: loopback peer, allowed Host, and no forwarding headers."""
    return (
        is_loopback_peer(scope)
        and host_header_allowed(scope)
        and not forwarding_headers_present(scope)
    )


def origin_allowed(scope: Scope) -> bool:
    """Origin check for unsafe methods. A missing Origin is a non-browser client and is allowed."""
    values = _header_values(scope, b"origin")
    if not values:
        return True
    if len(values) != 1:
        return False
    origin = values[0].strip().lower()
    if not origin or origin == "null":
        return False
    if origin in {candidate.lower() for candidate in settings.CORS_ORIGINS}:
        return True
    hosts = _header_values(scope, b"host")
    if len(hosts) != 1:
        return False
    scheme = str(scope.get("scheme", "http")).lower()
    return origin == f"{scheme}://{hosts[0].strip().lower()}"


def simple_request_content_type(scope: Scope) -> bool:
    """True when any Content-Type is a CSRF 'simple request' media type."""
    for raw in _header_values(scope, b"content-type"):
        media_type = raw.split(";", 1)[0].strip().lower()
        if media_type in SIMPLE_REQUEST_MEDIA_TYPES:
            return True
    return False


async def _send_json_error(send: Callable[..., Any], status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityGuardMiddleware:
    """Pure-ASGI guard enforcing Host, local-dev, Origin and content-type rules."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        scope_type = scope["type"]
        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope_type == "websocket":
            # No websocket routes exist; refuse rather than pass through unguarded.
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope_type != "http":
            await self.app(scope, receive, send)
            return

        if not host_header_allowed(scope):
            await _send_json_error(send, 403, FORBIDDEN_DETAIL)
            return
        if settings.OPERATOR_API_KEY is None and not local_dev_request_allowed(scope):
            await _send_json_error(send, 403, FORBIDDEN_DETAIL)
            return

        method = str(scope.get("method", "GET")).upper()
        if method in UNSAFE_METHODS:
            if simple_request_content_type(scope):
                await _send_json_error(send, 415, "Unsupported media type; JSON bodies only")
                return
            if not origin_allowed(scope):
                await _send_json_error(send, 403, FORBIDDEN_DETAIL)
                return

        await self.app(scope, receive, send)


__all__ = [
    "FORBIDDEN_DETAIL",
    "FORWARDING_HEADERS",
    "SIMPLE_REQUEST_MEDIA_TYPES",
    "UNSAFE_METHODS",
    "SecurityGuardMiddleware",
    "forwarding_headers_present",
    "host_header_allowed",
    "is_loopback_peer",
    "local_dev_request_allowed",
    "origin_allowed",
    "parse_host_header",
    "simple_request_content_type",
]
