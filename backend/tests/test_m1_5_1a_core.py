"""M1.5-1a (H1) core security tests: sessions, startup validation, guards and auth routes.

Protected-route behaviour is exercised through a small probe app so these tests do not
depend on the database. The full route-inventory / identity / regression matrix is H2.
"""

import logging
import time
import types

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.auth import LoginRateLimiter, login_rate_limiter
from app.config import Settings, settings
from app.core.auth import (
    OperatorContext,
    authenticate_request,
    derive_client_identity,
    get_operator_context,
    public_route,
)
from app.core.guard import (
    SecurityGuardMiddleware,
    host_header_allowed,
    local_dev_request_allowed,
    origin_allowed,
    parse_host_header,
)
from app.core.security_config import (
    SecurityConfigurationError,
    is_loopback_address,
    security_warnings,
    validate_security_configuration,
)
from app.core.session import (
    SESSION_COOKIE_NAME,
    RevokedSessionStore,
    issue_session,
    revoked_sessions,
    verify_session,
)
from app.main import app as real_app

KEY = "h1-test-operator-key-0123456789abcdef"
ROTATED_KEY = "h1-rotated-operator-key-0123456789ab"
SUBMITTED_WRONG = "h1-submitted-wrong-value-XYZ"
LOGIN_URL = "/api/v1/auth/login"
SESSION_URL = "/api/v1/auth/session"
LOGOUT_URL = "/api/v1/auth/logout"
LOOPBACK = ("127.0.0.1", 50000)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_auth_state():
    revoked_sessions.clear()
    login_rate_limiter.reset()
    yield
    revoked_sessions.clear()
    login_rate_limiter.reset()


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", KEY)
    monkeypatch.setattr(settings, "DEFAULT_OPERATOR_NAME", "Abstract")


@pytest.fixture
def local_dev(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", None)
    monkeypatch.setattr(settings, "DEFAULT_OPERATOR_NAME", "Abstract")


def _client(app=real_app, client=LOOPBACK) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=client), base_url="http://test")


def _cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _build_probe_app() -> tuple[FastAPI, list[str]]:
    """Protected probe app using the same global dependency and guard as production."""
    calls: list[str] = []
    probe = FastAPI(dependencies=[Depends(authenticate_request)])
    probe.add_middleware(SecurityGuardMiddleware)

    @probe.get("/public")
    @public_route
    async def public_endpoint():
        return {"ok": True}

    @probe.get("/whoami")
    async def whoami(operator: OperatorContext = Depends(get_operator_context)):
        return {
            "actor_id": operator.actor_id,
            "actor_type": operator.actor_type,
            "auth_method": operator.auth_method,
        }

    @probe.post("/mutate")
    async def mutate():
        calls.append("mutated")
        return {"ok": True}

    return probe, calls


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------


def test_issued_session_verifies_and_csrf_is_bound_to_sid():
    issued = issue_session(KEY, ttl_seconds=3600)
    claims = verify_session(KEY, issued.token)
    assert claims is not None
    assert claims.sid == issued.sid
    assert claims.csrf_token == issued.csrf_token
    assert claims.expires_at == issued.expires_at


def test_session_rejected_under_rotated_key():
    issued = issue_session(KEY, ttl_seconds=3600)
    assert verify_session(ROTATED_KEY, issued.token) is None


def test_tampered_payload_and_signature_are_rejected():
    issued = issue_session(KEY, ttl_seconds=3600)
    version, payload, signature = issued.token.split(".")
    other_payload = issue_session(KEY, ttl_seconds=7200).token.split(".")[1]
    assert verify_session(KEY, f"{version}.{other_payload}.{signature}") is None
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert verify_session(KEY, f"{version}.{payload}.{flipped}") is None


@pytest.mark.parametrize(
    "token",
    [None, "", "not-a-token", "v2.a.b", "v1.onlytwo", "v1..", "v1.%%%.%%%", "x" * 2000],
)
def test_malformed_tokens_are_rejected(token):
    assert verify_session(KEY, token) is None


def test_expired_session_is_rejected():
    issued = issue_session(KEY, ttl_seconds=60, now=time.time() - 3600)
    assert verify_session(KEY, issued.token) is None


def test_future_dated_session_beyond_skew_is_rejected():
    issued = issue_session(KEY, ttl_seconds=600, now=time.time() + 3600)
    assert verify_session(KEY, issued.token) is None


def test_session_within_clock_skew_is_accepted():
    issued = issue_session(KEY, ttl_seconds=600, now=time.time() + 30)
    assert verify_session(KEY, issued.token) is not None


def test_revoked_session_is_rejected():
    issued = issue_session(KEY, ttl_seconds=3600)
    store = RevokedSessionStore()
    assert verify_session(KEY, issued.token, revoked=store) is not None
    store.revoke(issued.sid, issued.expires_at)
    assert verify_session(KEY, issued.token, revoked=store) is None


def test_revoked_store_is_bounded_and_expires_entries():
    store = RevokedSessionStore(max_entries=3)
    far_future = int(time.time()) + 3600
    for i in range(5):
        store.revoke(f"{i:032x}", far_future)
    assert len(store) == 3
    assert not store.is_revoked(f"{0:032x}")  # oldest evicted
    assert store.is_revoked(f"{4:032x}")

    store.revoke("f" * 32, int(time.time()) + 10)
    assert store.is_revoked("f" * 32, now=time.time())
    assert not store.is_revoked("f" * 32, now=time.time() + 3600)


# ---------------------------------------------------------------------------
# Startup security configuration
# ---------------------------------------------------------------------------


def _config(**overrides):
    base = {
        "OPERATOR_API_KEY": None,
        "APP_HOST": "127.0.0.1",
        "DEBUG": False,
        "CORS_ORIGINS": ["http://localhost:5173"],
        "ALLOWED_HOSTS": ["localhost", "127.0.0.1"],
        "COOKIE_SECURE": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"APP_HOST": "localhost"},
        {"OPERATOR_API_KEY": "x" * 32, "APP_HOST": "0.0.0.0", "COOKIE_SECURE": True},
        {"OPERATOR_API_KEY": "x" * 32},
        {"APP_HOST": "127.0.0.1", "COOKIE_SECURE": False},
        {"APP_HOST": "::1", "OPERATOR_API_KEY": "x" * 40, "COOKIE_SECURE": False},
    ],
)
def test_valid_security_configurations_pass(overrides):
    validate_security_configuration(_config(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"OPERATOR_API_KEY": ""},
        {"OPERATOR_API_KEY": "   "},
        {"OPERATOR_API_KEY": "x" * 31},
        {"APP_HOST": "0.0.0.0"},
        {"APP_HOST": "0.0.0.0", "OPERATOR_API_KEY": "x" * 32, "DEBUG": True},
        {"CORS_ORIGINS": ["*"]},
        {"ALLOWED_HOSTS": ["*"]},
        {"APP_HOST": "0.0.0.0", "OPERATOR_API_KEY": "x" * 32, "COOKIE_SECURE": False},
    ],
)
def test_unsafe_security_configurations_are_refused(overrides):
    with pytest.raises(SecurityConfigurationError):
        validate_security_configuration(_config(**overrides))


def test_security_error_never_echoes_the_operator_key():
    with pytest.raises(SecurityConfigurationError) as exc:
        validate_security_configuration(_config(OPERATOR_API_KEY="short-secret-value"))
    assert "short-secret-value" not in str(exc.value)


async def test_lifespan_refuses_to_start_on_unsafe_config(monkeypatch):
    monkeypatch.setattr(settings, "APP_HOST", "0.0.0.0")
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", None)
    with pytest.raises(SecurityConfigurationError):
        async with real_app.router.lifespan_context(real_app):
            pass


def test_loopback_detection():
    for value in ["127.0.0.1", "127.8.9.10", "::1", "[::1]", "::ffff:127.0.0.1", "localhost"]:
        assert is_loopback_address(value), value
    for value in ["0.0.0.0", "10.0.0.5", "192.168.1.2", "::", "evil.example", ""]:
        assert not is_loopback_address(value), value


def test_settings_secure_defaults():
    defaults = Settings(_env_file=None)
    assert defaults.APP_HOST == "127.0.0.1"
    assert defaults.DEBUG is False
    assert defaults.OPERATOR_API_KEY is None
    assert defaults.ALLOWED_HOSTS == ["localhost", "127.0.0.1", "[::1]", "::1"]


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("localhost:8000", "localhost"),
        ("127.0.0.1:3000", "127.0.0.1"),
        ("[::1]:8000", "[::1]"),
        ("[::1]", "[::1]"),
        ("LOCALHOST", "localhost"),
        ("localhost.evil.com", "localhost.evil.com"),
        ("evil.com:8000", "evil.com"),
        ("", None),
        ("   ", None),
        ("localhost:", None),
        ("localhost:abc", None),
        ("a,b", None),
        ("local host", None),
        ("[::1", None),
        ("[::1]junk", None),
    ],
)
def test_parse_host_header(raw, expected):
    assert parse_host_header(raw) == expected


def _scope(headers=(), client=LOOPBACK, method="GET", scheme="http"):
    scope = {
        "type": "http",
        "method": method,
        "scheme": scheme,
        "headers": [(k.lower(), v) for k, v in headers],
    }
    if client is not None:
        scope["client"] = client
    return scope


@pytest.mark.parametrize(
    ("host_values", "allowed"),
    [
        ([b"localhost:8000"], True),
        ([b"127.0.0.1:3000"], True),
        ([b"[::1]:8000"], True),
        ([b"test"], True),  # appended by conftest for httpx ASGI transport
        ([b"localhost.evil.com"], False),
        ([b"evil.com:8000"], False),
        ([], False),
        ([b"localhost", b"evil.com"], False),
    ],
)
def test_host_header_allowlist(host_values, allowed):
    scope = _scope([(b"host", value) for value in host_values])
    assert host_header_allowed(scope) is allowed


def test_local_dev_guard_requires_loopback_host_and_no_forwarding_headers():
    base = [(b"host", b"localhost:8000")]
    assert local_dev_request_allowed(_scope(base))
    assert not local_dev_request_allowed(_scope(base, client=None))
    assert not local_dev_request_allowed(_scope(base, client=("203.0.113.9", 1)))
    assert not local_dev_request_allowed(_scope([(b"host", b"evil.com")]))
    for name in [
        "Forwarded",
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Forwarded-Proto",
        "X-Real-IP",
        "Via",
    ]:
        assert not local_dev_request_allowed(_scope(base + [(name.lower().encode(), b"1")])), name


def test_origin_check_rules():
    host = [(b"host", b"test")]
    assert origin_allowed(_scope(host, method="POST"))  # non-browser client
    assert origin_allowed(
        _scope(host + [(b"origin", b"http://localhost:5173")], method="POST")
    )  # configured CORS origin
    assert origin_allowed(
        _scope(host + [(b"origin", b"http://test")], method="POST")
    )  # same origin
    assert not origin_allowed(_scope(host + [(b"origin", b"null")], method="POST"))
    assert not origin_allowed(_scope(host + [(b"origin", b"http://evil.example")], method="POST"))
    assert not origin_allowed(
        _scope(
            host + [(b"origin", b"http://evil.example"), (b"origin", b"http://test")],
            method="POST",
        )
    )


# ---------------------------------------------------------------------------
# Probe app: keyed and local-dev enforcement through the real middleware and dependency
# ---------------------------------------------------------------------------


async def test_keyed_public_route_needs_no_credentials(keyed):
    probe, _ = _build_probe_app()
    async with _client(probe) as c:
        res = await c.get("/public")
    assert res.status_code == 200


async def test_keyed_protected_route_rejects_missing_wrong_and_empty_credentials(keyed):
    probe, _ = _build_probe_app()
    async with _client(probe) as c:
        missing = await c.get("/whoami")
        wrong = await c.get("/whoami", headers={"Authorization": "Bearer wrong-key-value"})
        empty = await c.get("/whoami", headers={"X-ASTRAVA-OPERATOR-KEY": ""})
    for res in (missing, wrong, empty):
        assert res.status_code == 401
        assert res.json() == {"detail": "Missing or invalid operator credentials"}
        assert res.headers["www-authenticate"] == "Bearer"


async def test_empty_configured_key_fails_closed(monkeypatch):
    probe, _ = _build_probe_app()
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "")
    async with _client(probe) as c:
        res = await c.get("/whoami", headers={"Authorization": "Bearer "})
        res_public = await c.get("/public")
    assert res.status_code == 401
    assert res_public.status_code == 200


async def test_bearer_and_header_keys_authenticate_and_identity_is_server_derived(keyed):
    probe, _ = _build_probe_app()
    async with _client(probe) as c:
        bearer = await c.get(
            "/whoami",
            headers={"Authorization": f"Bearer {KEY}", "X-ASTRAVA-ACTOR-NAME": "attacker"},
        )
        header = await c.get(
            "/whoami",
            headers={"X-ASTRAVA-OPERATOR-KEY": KEY, "X-ASTRAVA-ACTOR-NAME": "attacker"},
        )
    for res in (bearer, header):
        assert res.status_code == 200
        assert res.json() == {
            "actor_id": "Abstract",
            "actor_type": "operator",
            "auth_method": "api_key",
        }


async def test_local_dev_identity_ignores_actor_header_and_is_unauthenticated(local_dev):
    probe, _ = _build_probe_app()
    async with _client(probe) as c:
        res = await c.get("/whoami", headers={"X-ASTRAVA-ACTOR-NAME": "attacker"})
    assert res.status_code == 200
    assert res.json() == {
        "actor_id": "Abstract",
        "actor_type": "operator_local_dev",
        "auth_method": "local_dev",
    }


async def test_local_dev_allows_loopback_allowed_host(local_dev):
    probe, _ = _build_probe_app()
    async with _client(probe, client=("127.0.0.1", 5000)) as c:
        res = await c.get("/whoami", headers={"Host": "localhost:8000"})
        res_v6 = await c.get("/whoami", headers={"Host": "[::1]:8000"})
    assert res.status_code == 200
    assert res_v6.status_code == 200


@pytest.mark.parametrize(
    ("peer", "host", "headers"),
    [
        (("203.0.113.9", 5000), "test", {}),
        (("127.0.0.1", 5000), "localhost.evil.com", {}),
        (("127.0.0.1", 5000), "evil.com:8000", {}),
        (("127.0.0.1", 5000), "test", {"X-Forwarded-For": "203.0.113.9"}),
        (("127.0.0.1", 5000), "test", {"Forwarded": "for=203.0.113.9"}),
        (("127.0.0.1", 5000), "test", {"X-Real-IP": "203.0.113.9"}),
    ],
)
async def test_local_dev_denies_untrusted_requests(local_dev, peer, host, headers):
    probe, _ = _build_probe_app()
    async with _client(probe, client=peer) as c:
        res = await c.get("/public", headers={"Host": host, **headers})
    assert res.status_code == 403
    assert res.json() == {"detail": "Forbidden"}


async def test_unsafe_methods_with_simple_content_types_are_415_with_no_side_effects(keyed):
    probe, calls = _build_probe_app()
    auth = {"Authorization": f"Bearer {KEY}"}
    async with _client(probe) as c:
        text = await c.post("/mutate", headers={**auth, "Content-Type": "text/plain"}, content=b"x")
        form = await c.post("/mutate", headers=auth, data={"a": "b"})
        multipart = await c.post("/mutate", headers=auth, files={"f": ("a.txt", b"x")})
    for res in (text, form, multipart):
        assert res.status_code == 415
    assert calls == []


async def test_json_unsafe_request_with_bearer_is_allowed(keyed):
    probe, calls = _build_probe_app()
    async with _client(probe) as c:
        res = await c.post(
            "/mutate",
            headers={"Authorization": f"Bearer {KEY}"},
            json={},
        )
    assert res.status_code == 200
    assert calls == ["mutated"]


async def test_cross_origin_unsafe_request_is_403_in_both_modes(keyed, monkeypatch):
    probe, calls = _build_probe_app()
    auth = {"Authorization": f"Bearer {KEY}"}
    async with _client(probe) as c:
        evil = await c.post("/mutate", headers={**auth, "Origin": "http://evil.example"})
        null = await c.post("/mutate", headers={**auth, "Origin": "null"})
        allowed = await c.post("/mutate", headers={**auth, "Origin": "http://localhost:5173"})
    assert evil.status_code == 403
    assert null.status_code == 403
    assert allowed.status_code == 200
    assert calls == ["mutated"]

    monkeypatch.setattr(settings, "OPERATOR_API_KEY", None)
    async with _client(probe) as c:
        local_evil = await c.post("/mutate", headers={"Origin": "http://evil.example"})
    assert local_evil.status_code == 403
    assert calls == ["mutated"]


# ---------------------------------------------------------------------------
# Cookie session and CSRF through the probe app
# ---------------------------------------------------------------------------


async def test_cookie_session_reads_but_unsafe_requires_matching_csrf(keyed):
    probe, calls = _build_probe_app()
    issued = issue_session(KEY, ttl_seconds=3600)
    async with _client(probe) as c:
        read = await c.get("/whoami", headers=_cookie(issued.token))
        missing = await c.post("/mutate", headers=_cookie(issued.token))
        wrong = await c.post(
            "/mutate", headers={**_cookie(issued.token), "X-CSRF-Token": "bogus-token"}
        )
        correct = await c.post(
            "/mutate",
            headers={**_cookie(issued.token), "X-CSRF-Token": issued.csrf_token},
        )
    assert read.status_code == 200
    assert read.json()["auth_method"] == "session"
    assert missing.status_code == 403
    assert missing.json() == {"detail": "CSRF validation failed"}
    assert wrong.status_code == 403
    assert correct.status_code == 200
    assert calls == ["mutated"]


async def test_bearer_unsafe_request_is_exempt_from_csrf(keyed):
    probe, calls = _build_probe_app()
    async with _client(probe) as c:
        res = await c.post("/mutate", headers={"Authorization": f"Bearer {KEY}"})
    assert res.status_code == 200
    assert calls == ["mutated"]


@pytest.mark.parametrize(
    "make_token",
    [
        lambda: issue_session(KEY, ttl_seconds=60, now=time.time() - 3600).token,
        lambda: issue_session("another-operator-key-0123456789abcdefgh", ttl_seconds=600).token,
        lambda: issue_session(KEY, ttl_seconds=600).token[:-2] + "AA",
    ],
    ids=["expired", "wrong-key", "tampered"],
)
async def test_invalid_session_cookies_are_401(keyed, make_token):
    probe, _ = _build_probe_app()
    async with _client(probe) as c:
        res = await c.get("/whoami", headers=_cookie(make_token()))
    assert res.status_code == 401


async def test_rotated_key_invalidates_existing_session_cookie(keyed, monkeypatch):
    probe, _ = _build_probe_app()
    issued = issue_session(KEY, ttl_seconds=3600)
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", ROTATED_KEY)
    async with _client(probe) as c:
        res = await c.get("/whoami", headers=_cookie(issued.token))
    assert res.status_code == 401


async def test_revoked_session_cookie_is_401(keyed):
    probe, _ = _build_probe_app()
    issued = issue_session(KEY, ttl_seconds=3600)
    revoked_sessions.revoke(issued.sid, issued.expires_at)
    async with _client(probe) as c:
        res = await c.get("/whoami", headers=_cookie(issued.token))
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Auth routes (real application; no database involved)
# ---------------------------------------------------------------------------


async def test_real_app_default_deny_on_unmarked_routes(keyed):
    async with _client() as c:
        projects = await c.get("/api/v1/projects")
        execution = await c.post("/api/v1/executions", json={})
    assert projects.status_code == 401
    assert execution.status_code == 401


async def test_real_app_public_routes_need_no_credentials(keyed):
    async with _client() as c:
        root = await c.get("/")
        health = await c.get("/api/v1/healthz")
        ready = await c.get("/api/v1/readyz")
    assert root.status_code == 200
    assert health.status_code == 200
    assert ready.status_code == 200


async def test_docs_are_absent_when_debug_is_off(keyed):
    async with _client() as c:
        docs = await c.get("/docs")
        openapi = await c.get("/openapi.json")
    assert docs.status_code == 404
    assert openapi.status_code == 404


async def test_login_success_sets_hardened_cookie_and_hides_key(keyed):
    async with _client() as c:
        res = await c.post(LOGIN_URL, json={"api_key": KEY})
    assert res.status_code == 200
    body = res.json()
    assert body["authenticated"] is True
    assert body["auth_method"] == "session"
    assert body["actor_id"] == "Abstract"
    assert body["csrf_token"]
    assert KEY not in res.text
    assert res.headers["cache-control"] == "no-store"

    set_cookie = res.headers["set-cookie"]
    lowered = set_cookie.lower()
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "httponly" in lowered
    assert "samesite=strict" in lowered
    assert "path=/" in lowered
    assert "max-age=28800" in lowered
    assert "secure" not in lowered  # loopback APP_HOST, COOKIE_SECURE unset


async def test_login_cookie_is_secure_when_configured(keyed, monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    async with _client() as c:
        res = await c.post(LOGIN_URL, json={"api_key": KEY})
    assert "secure" in res.headers["set-cookie"].lower()


async def test_session_status_roundtrip_and_logout_revokes(keyed):
    async with _client() as c:
        login = await c.post(LOGIN_URL, json={"api_key": KEY})
        csrf = login.json()["csrf_token"]
        token = c.cookies.get(SESSION_COOKIE_NAME)
        assert token

        status_before = await c.get(SESSION_URL)
        assert status_before.json() == {
            "authenticated": True,
            "auth_method": "session",
            "login_required": True,
            "actor_id": "Abstract",
            "csrf_token": csrf,
        }

        logout = await c.post(LOGOUT_URL)
        assert logout.status_code == 200
        assert logout.json() == {"authenticated": False}
        assert "max-age=0" in logout.headers["set-cookie"].lower()
        assert logout.headers["cache-control"] == "no-store"

        # The old cookie value is now revoked server-side.
        status_replayed = await c.get(SESSION_URL, headers=_cookie(token))
    assert status_replayed.json()["authenticated"] is False


async def test_session_endpoint_never_401s(keyed):
    async with _client() as c:
        res = await c.get(SESSION_URL)
        tampered = await c.get(SESSION_URL, headers=_cookie("v1.garbage.garbage"))
    assert res.status_code == 200
    assert res.json() == {
        "authenticated": False,
        "auth_method": None,
        "login_required": True,
        "actor_id": None,
        "csrf_token": None,
    }
    assert tampered.status_code == 200
    assert tampered.json()["authenticated"] is False


async def test_logout_always_succeeds(keyed):
    async with _client() as c:
        res = await c.post(LOGOUT_URL)
    assert res.status_code == 200
    assert res.json() == {"authenticated": False}


async def test_login_wrong_key_is_generic_401_and_never_logged(keyed, caplog):
    caplog.set_level(logging.DEBUG)
    async with _client() as c:
        res = await c.post(LOGIN_URL, json={"api_key": SUBMITTED_WRONG})
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid operator credentials"}
    assert SUBMITTED_WRONG not in res.text
    assert SUBMITTED_WRONG not in caplog.text
    assert KEY not in caplog.text
    assert any(
        rec.name == "astrava.auth" and rec.levelno == logging.WARNING for rec in caplog.records
    )


async def test_login_rate_limit_returns_429_with_retry_after(keyed):
    async with _client() as c:
        for _ in range(5):
            attempt = await c.post(LOGIN_URL, json={"api_key": SUBMITTED_WRONG})
            assert attempt.status_code == 401
        blocked = await c.post(LOGIN_URL, json={"api_key": KEY})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert KEY not in blocked.text
    assert SUBMITTED_WRONG not in blocked.text


async def test_successful_login_clears_failure_count(keyed):
    async with _client() as c:
        for _ in range(4):
            await c.post(LOGIN_URL, json={"api_key": SUBMITTED_WRONG})
        ok = await c.post(LOGIN_URL, json={"api_key": KEY})
        assert ok.status_code == 200
        for _ in range(5):
            assert (await c.post(LOGIN_URL, json={"api_key": SUBMITTED_WRONG})).status_code == 401


def test_login_rate_limiter_store_stays_bounded():
    limiter = LoginRateLimiter()
    now = time.time()
    for i in range(3000):
        limiter.record_failure(f"peer-{i}", now)
    assert len(limiter) <= 1024


def test_login_rate_limiter_purges_expired_windows(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_WINDOW_SECONDS", 10)
    limiter = LoginRateLimiter()
    limiter.record_failure("stale-peer", 0.0)
    assert limiter.retry_after("other-peer", 100.0) == 0
    assert len(limiter) == 0


async def test_login_is_conflict_in_local_dev(local_dev):
    async with _client() as c:
        res = await c.post(LOGIN_URL, json={"api_key": KEY})
    assert res.status_code == 409
    assert res.json() == {"detail": "Login not required in local development mode"}


async def test_session_status_reports_local_dev_without_login(local_dev):
    async with _client() as c:
        res = await c.get(SESSION_URL)
    assert res.status_code == 200
    assert res.json()["login_required"] is False
    assert res.json()["authenticated"] is False


async def test_login_with_empty_configured_key_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "")
    async with _client() as c:
        res = await c.post(LOGIN_URL, json={"api_key": "anything-at-all"})
    assert res.status_code == 401


async def test_login_body_is_length_limited(keyed):
    async with _client() as c:
        res = await c.post(LOGIN_URL, json={"api_key": "x" * 513})
    assert res.status_code == 422


async def test_cors_preflight_from_allowed_origin_succeeds_without_credentials():
    async with _client() as c:
        res = await c.options(
            "/api/v1/executions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-csrf-token",
            },
        )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in res.headers["access-control-allow-methods"]


async def test_cors_preflight_from_disallowed_origin_is_not_granted():
    async with _client() as c:
        res = await c.options(
            "/api/v1/executions",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert "access-control-allow-origin" not in res.headers


# ---------------------------------------------------------------------------
# Identity helper
# ---------------------------------------------------------------------------


def _operator() -> OperatorContext:
    return OperatorContext(
        actor_id="Abstract",
        display_name="Abstract",
        actor_type="operator",
        auth_method="api_key",
        is_authenticated=True,
        is_authorized_verifier=True,
    )


def test_derive_client_identity_accepts_absent_or_matching_values():
    operator = _operator()
    assert derive_client_identity(None, operator) == "Abstract"
    assert derive_client_identity("Abstract", operator) == "Abstract"
    assert derive_client_identity("  Abstract  ", operator) == "Abstract"


def test_derive_client_identity_rejects_mismatch_with_403():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        derive_client_identity("Tech Lead", _operator(), subject="verifier")
    assert exc.value.status_code == 403
    assert exc.value.detail == (
        "Cannot impersonate verifier; identity derived from authenticated operator context"
    )


# ---------------------------------------------------------------------------
# Review remediation (H4)
# ---------------------------------------------------------------------------


def test_security_warning_for_non_loopback_host_without_public_origin():
    warnings = security_warnings(_config(APP_HOST="0.0.0.0", OPERATOR_API_KEY="x" * 32))
    assert len(warnings) == 1
    assert "TLS-terminating proxy" in warnings[0]
    assert "CORS_ORIGINS" in warnings[0]


def test_no_security_warning_for_loopback_host():
    assert security_warnings(_config(APP_HOST="127.0.0.1")) == []


def test_no_security_warning_when_public_https_origin_is_listed():
    config = _config(
        APP_HOST="0.0.0.0",
        OPERATOR_API_KEY="x" * 32,
        CORS_ORIGINS=["http://localhost:5173", "https://astrava.example.com"],
    )
    assert security_warnings(config) == []


def test_security_warning_message_never_contains_the_key():
    secret = "warning-secret-value-" + "x" * 20
    config = _config(APP_HOST="0.0.0.0", OPERATOR_API_KEY=secret)
    for message in security_warnings(config):
        assert secret not in message


async def test_lifespan_logs_security_warning_without_refusing_to_start(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setattr(settings, "APP_HOST", "0.0.0.0")
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "x" * 32)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path / "artifacts")
    caplog.set_level(logging.WARNING)
    async with real_app.router.lifespan_context(real_app):
        pass
    assert any("TLS-terminating proxy" in rec.getMessage() for rec in caplog.records)
    assert ("x" * 32) not in caplog.text


def test_login_limiter_keeps_locked_out_peer_when_flooded_with_fresh_peers(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 5)
    limiter = LoginRateLimiter(max_tracked_peers=5)
    now = time.time()
    for _ in range(5):
        limiter.record_failure("locked-peer", now)
    assert limiter.retry_after("locked-peer", now) > 0
    for i in range(50):
        limiter.record_failure(f"fresh-{i}", now)
    assert len(limiter) <= 5
    assert limiter.retry_after("locked-peer", now) > 0


def test_login_limiter_evicts_locked_out_peers_only_when_all_are_locked(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    limiter = LoginRateLimiter(max_tracked_peers=3)
    now = time.time()
    for i in range(10):
        for _ in range(2):
            limiter.record_failure(f"locked-{i}", now)
    assert len(limiter) <= 3


@pytest.mark.parametrize(
    "header",
    [
        "cf-connecting-ip",
        "true-client-ip",
        "x-client-ip",
        "x-cluster-client-ip",
        "x-original-forwarded-for",
        "fastly-client-ip",
        "x-envoy-external-address",
    ],
)
def test_vendor_forwarding_headers_break_local_dev_guard(header):
    loopback_with_host = [(b"host", b"localhost:8000")]
    assert local_dev_request_allowed(_scope(loopback_with_host))
    assert not local_dev_request_allowed(
        _scope(loopback_with_host + [(header.encode(), b"203.0.113.5")])
    )


async def test_vendor_forwarding_header_is_403_on_real_route(local_dev):
    async with _client(client=("127.0.0.1", 5000)) as c:
        res = await c.get("/api/v1/auth/session", headers={"CF-Connecting-IP": "203.0.113.5"})
    assert res.status_code == 403
