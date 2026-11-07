"""Startup security validation and loopback helpers (M1.5-1a).

``validate_security_configuration`` is called from the FastAPI lifespan before the
application starts serving, so a misconfigured process refuses to start. Error
messages never include configuration values (in particular the operator key).
"""

import ipaddress
from typing import Any
from urllib.parse import urlsplit

MIN_OPERATOR_KEY_LENGTH = 32


class SecurityConfigurationError(RuntimeError):
    """Raised when the runtime security configuration is unsafe."""


def is_loopback_address(value: str) -> bool:
    """Return True for localhost, 127.0.0.0/8, ::1 and IPv4-mapped loopback addresses."""
    candidate = value.strip().strip("[]").lower()
    if candidate == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def validate_security_configuration(config: Any) -> None:
    """Raise SecurityConfigurationError when the settings object is unsafe to serve with."""
    key = config.OPERATOR_API_KEY
    app_host_is_loopback = is_loopback_address(config.APP_HOST)

    if key is not None and (not key.strip() or len(key) < MIN_OPERATOR_KEY_LENGTH):
        raise SecurityConfigurationError(
            f"OPERATOR_API_KEY must be non-blank and at least {MIN_OPERATOR_KEY_LENGTH} characters"
        )
    if not app_host_is_loopback and key is None:
        raise SecurityConfigurationError(
            "APP_HOST is non-loopback but OPERATOR_API_KEY is not configured"
        )
    if not app_host_is_loopback and config.DEBUG:
        raise SecurityConfigurationError("DEBUG must be disabled when APP_HOST is non-loopback")
    if "*" in config.CORS_ORIGINS or "*" in config.ALLOWED_HOSTS:
        raise SecurityConfigurationError(
            "Wildcard entries are not allowed in CORS_ORIGINS or ALLOWED_HOSTS"
        )
    if config.COOKIE_SECURE is False and not app_host_is_loopback:
        raise SecurityConfigurationError(
            "COOKIE_SECURE cannot be disabled when APP_HOST is non-loopback"
        )


def _is_public_https_origin(origin: str) -> bool:
    parts = urlsplit(origin.strip())
    host = parts.hostname or ""
    return parts.scheme.lower() == "https" and bool(host) and not is_loopback_address(host)


def security_warnings(config: Any) -> list[str]:
    """Non-fatal configuration warnings. Never includes configuration values or secrets."""
    if is_loopback_address(config.APP_HOST):
        return []
    if any(_is_public_https_origin(origin) for origin in config.CORS_ORIGINS):
        return []
    return [
        "APP_HOST is non-loopback and CORS_ORIGINS lists no public https origin: browser "
        "mutations will be rejected (403) behind a TLS-terminating proxy unless the public "
        "https origin is added to CORS_ORIGINS."
    ]
