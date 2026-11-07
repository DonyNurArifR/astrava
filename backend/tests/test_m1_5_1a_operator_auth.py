"""M1.5-1a (H2): route inventory, default-deny matrix, identity/audit and startup gates.

Complements tests/test_m1_5_1a_core.py (sessions, guards, auth routes, probe app). This file
walks the real application's routes (including FastAPI included-router wrappers), so that
every route is checked, not a sample.
"""

import importlib.util
import logging
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.v1.auth import login_rate_limiter
from app.config import Settings, settings
from app.core.auth import authenticate_request, is_public_route
from app.core.guard import SecurityGuardMiddleware
from app.core.security_config import SecurityConfigurationError
from app.core.session import SESSION_COOKIE_NAME, issue_session, revoked_sessions
from app.db.session import get_db
from app.main import app as real_app
from app.models.agent import Agent
from app.models.approval import Approval
from app.models.execution import WorkflowExecution
from app.models.goal import ProjectGoal
from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryProvenanceType,
    ProjectMemory,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.approval_service import ApprovalService
from app.services.memory_service import MemoryService
from app.services.workflow_service import WorkflowService

KEY = "h2-test-operator-key-0123456789abcdef"
WRONG = "h2-wrong-operator-key-0123456789abcd"
LOOPBACK = ("127.0.0.1", 50000)
MAIN_PATH = Path(__file__).resolve().parents[1] / "app" / "main.py"

PUBLIC_EXPECTED = {
    ("GET", "/"),
    ("GET", "/api/v1/healthz"),
    ("GET", "/api/v1/readyz"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/logout"),
}
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------
# Route inventory (walks FastAPI included-router wrappers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteRow:
    method: str
    path: str
    endpoint_name: str
    is_public: bool
    requires_auth: bool
    is_api_route: bool


def _dependant_calls(dependant):
    for child in dependant.dependencies:
        yield child.call
        yield from _dependant_calls(child)


def _walk_entries(items):
    """Yield (route, full_path, endpoint, effective_dependency_calls) for every leaf route."""
    for item in items:
        if hasattr(item, "effective_candidates"):
            yield from _walk_entries(item.effective_candidates())
        elif hasattr(item, "original_route"):
            calls = tuple(dep.dependency for dep in item.dependencies or [])
            yield item.original_route, item.path, item.endpoint, calls
        else:
            calls = tuple(dep.dependency for dep in (getattr(item, "dependencies", None) or []))
            yield item, item.path, getattr(item, "endpoint", None), calls


def build_inventory(application) -> list[RouteRow]:
    rows: list[RouteRow] = []
    for route, path, endpoint, effective_calls in _walk_entries(application.router.routes):
        if isinstance(route, APIRoute):
            tree_calls = set(_dependant_calls(route.dependant)) | set(effective_calls)
            requires_auth = authenticate_request in tree_calls
            is_public = is_public_route(endpoint)
            for method in sorted(route.methods or []):
                rows.append(
                    RouteRow(
                        method=method,
                        path=path,
                        endpoint_name=getattr(endpoint, "__name__", "?"),
                        is_public=is_public,
                        requires_auth=requires_auth,
                        is_api_route=True,
                    )
                )
        else:
            for method in sorted(getattr(route, "methods", None) or ["*"]):
                rows.append(
                    RouteRow(
                        method=method,
                        path=path,
                        endpoint_name=getattr(endpoint, "__name__", type(route).__name__),
                        is_public=False,
                        requires_auth=False,
                        is_api_route=False,
                    )
                )
    return rows


INVENTORY = build_inventory(real_app)
NON_PUBLIC = [row for row in INVENTORY if not row.is_public]
NON_PUBLIC_GET = [row for row in NON_PUBLIC if row.method == "GET"]
PATH_PARAM = re.compile(r"\{[^}]+\}")


def concrete(path: str) -> str:
    return PATH_PARAM.sub(lambda _: str(uuid.uuid4()), path)


def _route_id(row: RouteRow) -> str:
    return f"{row.method} {row.path}"


def _load_app_with_debug(debug: bool):
    """Load a fresh copy of app/main.py with settings.DEBUG set, preserving root logging."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    previous = settings.DEBUG
    settings.DEBUG = debug
    module_name = f"astrava_main_probe_debug_{debug}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, MAIN_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module.app
    finally:
        settings.DEBUG = previous
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        sys.modules.pop(module_name, None)


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


@pytest.fixture
def db_tripwire():
    """Fail loudly if any route resolves the database dependency (auth must come first)."""

    async def _touched():
        raise AssertionError("database dependency was resolved before authentication")
        yield  # pragma: no cover

    real_app.dependency_overrides[get_db] = _touched
    try:
        yield
    finally:
        real_app.dependency_overrides.pop(get_db, None)


def _client(app=real_app, client=LOOPBACK) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=client), base_url="http://test")


def _bearer(key: str = KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def _seed_project(db_session) -> Project:
    ws = Workspace(name="H2 WS", slug=f"ws-h2-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()
    project = Project(
        workspace_id=ws.id,
        name="H2 Project",
        slug=f"proj-h2-{uuid.uuid4().hex[:8]}",
        studio_type=StudioType.SAAS,
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _seed_memory(db_session, project_id):
    mem = await MemoryService.create_memory(
        db_session,
        project_id=project_id,
        category=MemoryCategory.DISCOVERY,
        summary="H2 discovery: cache stampede under burst load",
        content="Observed stampede on cold cache during burst traffic.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    await db_session.commit()
    return mem


async def _seed_pending_approval(db_session) -> Approval:
    from app.models.task import RiskLevel

    ws = Workspace(name="H2 Approval WS", slug=f"ws-h2a-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()
    proj = Project(
        name="H2 Approval Proj",
        slug=f"proj-h2a-{uuid.uuid4().hex[:8]}",
        workspace_id=ws.id,
        studio_type=StudioType.SAAS,
    )
    db_session.add(proj)
    await db_session.commit()
    wf = await WorkflowService.create_workflow(
        db_session, WorkflowCreate(project_id=proj.id, name="H2 WF", studio_type="saas")
    )
    execution = await WorkflowService.create_execution(
        db_session, ExecutionCreate(workflow_id=wf.id, project_id=proj.id)
    )
    approval = await ApprovalService.request_approval(
        db_session,
        execution_id=execution.id,
        action_type="high_risk_mutation",
        description="H2 high risk operation",
        risk_level=RiskLevel.HIGH,
    )
    await db_session.commit()
    return approval


# ---------------------------------------------------------------------------
# 1. Route inventory
# ---------------------------------------------------------------------------


def test_inventory_walks_included_routers_and_finds_every_route():
    api_paths = {row.path for row in INVENTORY if row.is_api_route}
    # Every real endpoint lives behind an included router, so the walk must reach them all.
    assert len(api_paths) >= 60, len(api_paths)
    assert "/api/v1/projects/{project_id}/memories/{memory_id}/verify" in api_paths
    assert "/api/v1/orchestrator/resume/{execution_id}" in api_paths


def test_public_route_set_is_exactly_the_spec_set():
    public = {(row.method, row.path) for row in INVENTORY if row.is_public}
    assert public == PUBLIC_EXPECTED


def test_every_non_public_route_has_authentication_dependency():
    unprotected = [_route_id(row) for row in NON_PUBLIC if not row.requires_auth]
    assert unprotected == [], f"routes without authenticate_request: {unprotected}"


def test_mutating_non_public_routes_do_not_disappear():
    mutating = [row for row in NON_PUBLIC if row.method in UNSAFE]
    assert len(mutating) >= 33, len(mutating)


def test_debug_off_exposes_no_unprotected_plain_routes():
    assert all(row.is_api_route for row in INVENTORY)
    paths = {row.path for row in INVENTORY}
    assert not (paths & DOCS_PATHS)


def test_inventory_security_matrix_printed(capsys):
    """Prints the route security matrix (METHOD PATH AUTH) for review with `pytest -s`."""
    lines = []
    for row in sorted(INVENTORY, key=lambda r: (r.path, r.method)):
        if row.is_public:
            auth = "PUBLIC"
        elif row.requires_auth:
            auth = "authenticated"
        else:
            auth = "UNPROTECTED"
        lines.append(f"{row.method:<7} {row.path:<70} {auth}")
    print("\nROUTE SECURITY MATRIX (METHOD PATH AUTH)")
    print("\n".join(lines))
    print(f"TOTAL {len(INVENTORY)} routes; public={sum(r.is_public for r in INVENTORY)}")
    assert all(row.requires_auth or row.is_public for row in INVENTORY)


def test_docs_routes_exist_only_when_debug_is_on():
    debug_off = _load_app_with_debug(False)
    off_paths = {row.path for row in build_inventory(debug_off)}
    assert not (off_paths & DOCS_PATHS)

    debug_on = _load_app_with_debug(True)
    on_inventory = build_inventory(debug_on)
    plain_paths = {row.path for row in on_inventory if not row.is_api_route}
    assert plain_paths == DOCS_PATHS
    # Nothing except the docs routes is unauthenticated-and-not-API when DEBUG is on.
    assert all(row.requires_auth or row.is_public for row in on_inventory if row.is_api_route)


async def test_docs_are_served_only_in_debug_mode():
    debug_on = _load_app_with_debug(True)
    async with _client(debug_on) as c:
        openapi = await c.get("/openapi.json")
        docs = await c.get("/docs")
    assert openapi.status_code == 200
    assert docs.status_code == 200


# ---------------------------------------------------------------------------
# 2. Default-deny 401 matrix over every non-public route (keyed mode)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", NON_PUBLIC, ids=_route_id)
async def test_non_public_route_rejects_every_unauthenticated_variant(row, keyed, db_tripwire):
    url = concrete(row.path)
    tampered = issue_session(KEY, ttl_seconds=600).token[:-2] + "AA"
    variants = {
        "no credential": {},
        "wrong bearer": {"Authorization": f"Bearer {WRONG}"},
        "wrong operator-key header": {"X-ASTRAVA-OPERATOR-KEY": WRONG},
        "tampered cookie": {"Cookie": f"{SESSION_COOKIE_NAME}={tampered}"},
    }
    async with _client() as c:
        for name, headers in variants.items():
            res = await c.request(row.method, url, headers=headers)
            assert res.status_code == 401, f"{name}: {res.status_code} {res.text[:200]}"
            assert res.json() == {"detail": "Missing or invalid operator credentials"}, name


@pytest.mark.parametrize("row", NON_PUBLIC, ids=_route_id)
async def test_empty_configured_key_fails_closed_on_every_route(row, monkeypatch, db_tripwire):
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "")
    async with _client() as c:
        res = await c.request(row.method, concrete(row.path), headers=_bearer(KEY))
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Authenticated pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", NON_PUBLIC_GET, ids=_route_id)
async def test_correct_bearer_passes_auth_on_every_get_route(row, keyed):
    async with _client() as c:
        res = await c.get(concrete(row.path), headers=_bearer())
    assert res.status_code not in (401, 403), f"{res.status_code} {res.text[:200]}"


REPRESENTATIVE_MUTATIONS = [
    ("POST", "/api/v1/executions", None),
    ("POST", "/api/v1/executions/{execution_id}/pause", None),
    ("POST", "/api/v1/approvals/{approval_id}/decide", None),
    ("POST", "/api/v1/projects/{project_id}/memories", None),
    ("POST", "/api/v1/projects/{project_id}/memories/{memory_id}/verify", None),
    ("POST", "/api/v1/projects/{project_id}/memories/{memory_id}/resolve", None),
    ("POST", "/api/v1/projects/{project_id}/goals", None),
    ("PATCH", "/api/v1/projects/{project_id}", None),
    ("PUT", "/api/v1/agents/{identifier}", None),
    ("POST", "/api/v1/orchestrator/execute", None),
]


async def _row_counts(db_session) -> dict[str, int]:
    counts = {}
    for name, model in {
        "projects": Project,
        "memories": ProjectMemory,
        "goals": ProjectGoal,
        "approvals": Approval,
        "agents": Agent,
    }.items():
        counts[name] = (
            await db_session.execute(select(func.count()).select_from(model))
        ).scalar_one()
    counts["executions"] = (
        await db_session.execute(select(func.count()).select_from(WorkflowExecution))
    ).scalar_one()
    return counts


@pytest.mark.parametrize(
    ("method", "template"),
    [(method, template) for method, template, _ in REPRESENTATIVE_MUTATIONS],
    ids=[f"{method} {template}" for method, template, _ in REPRESENTATIVE_MUTATIONS],
)
async def test_mutation_with_correct_bearer_and_invalid_body_never_401_403(
    method, template, keyed, db_session
):
    before = await _row_counts(db_session)
    url = concrete(template)
    async with _client() as c:
        res = await c.request(
            method,
            url,
            headers={**_bearer(), "Content-Type": "application/json"},
            content=b"{not valid json",
        )
    assert res.status_code in (400, 404, 422), f"{res.status_code} {res.text[:200]}"
    after = await _row_counts(db_session)
    assert after == before, "invalid request must not create or change rows"


# ---------------------------------------------------------------------------
# 4. Identity and audit attribution (server-derived only)
# ---------------------------------------------------------------------------


async def test_keyed_verify_records_server_identity_and_ignores_injected_fields(keyed, db_session):
    project = await _seed_project(db_session)
    mem = await _seed_memory(db_session, project.id)
    url = f"/api/v1/projects/{project.id}/memories/{mem.id}/verify"
    async with _client() as c:
        res = await c.post(
            url,
            headers={**_bearer(), "X-ASTRAVA-ACTOR-NAME": "attacker"},
            json={
                "verified_by": "Abstract",
                "actor_type": "system",
                "actor_id": "evil-actor",
                "reason": "Reproduced locally",
            },
        )
        audit = await c.get(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/audit", headers=_bearer()
        )
    assert res.status_code == 200, res.text
    assert res.json()["metadata_json"]["verified_by"] == "Abstract"
    verified = [e for e in audit.json()["items"] if e["action"] == MemoryAuditAction.VERIFIED.value]
    assert len(verified) == 1
    assert verified[0]["actor_type"] == "operator"
    assert verified[0]["actor_id"] == "Abstract"


async def test_local_dev_verify_records_operator_local_dev_actor_type(local_dev, db_session):
    project = await _seed_project(db_session)
    mem = await _seed_memory(db_session, project.id)
    url = f"/api/v1/projects/{project.id}/memories/{mem.id}/verify"
    async with _client() as c:
        res = await c.post(url, json={}, headers={"X-ASTRAVA-ACTOR-NAME": "attacker"})
        audit = await c.get(f"/api/v1/projects/{project.id}/memories/{mem.id}/audit")
    assert res.status_code == 200, res.text
    assert res.json()["metadata_json"]["verified_by"] == "Abstract"
    verified = [e for e in audit.json()["items"] if e["action"] == MemoryAuditAction.VERIFIED.value]
    assert verified[0]["actor_type"] == "operator_local_dev"
    assert verified[0]["actor_id"] == "Abstract"


async def test_verify_with_mismatched_verifier_is_403_and_changes_nothing(keyed, db_session):
    project = await _seed_project(db_session)
    mem = await _seed_memory(db_session, project.id)
    url = f"/api/v1/projects/{project.id}/memories/{mem.id}/verify"
    async with _client() as c:
        res = await c.post(url, headers=_bearer(), json={"verified_by": "Tech Lead"})
    assert res.status_code == 403
    await db_session.refresh(mem)
    assert mem.is_verified is False


async def test_resolve_with_mismatched_actor_is_403(keyed, db_session):
    project = await _seed_project(db_session)
    url = f"/api/v1/projects/{project.id}/memories/{uuid.uuid4()}/resolve"
    async with _client() as c:
        res = await c.post(
            url,
            headers=_bearer(),
            json={"resolution": "reject", "reason": "Duplicate", "actor_id": "someone-else"},
        )
    # The project exists; the mismatched identity is rejected before the memory is looked up.
    assert res.status_code == 403
    assert res.json()["detail"].startswith("Cannot impersonate operator")


async def test_approval_decision_identity_is_server_derived(keyed, db_session):
    approval = await _seed_pending_approval(db_session)
    url = f"/api/v1/approvals/{approval.id}/decide"
    async with _client() as c:
        mismatch = await c.post(
            url, headers=_bearer(), json={"decision": "approved", "decided_by": "Tech Lead"}
        )
        assert mismatch.status_code == 403
        await db_session.refresh(approval)
        assert approval.status.value == "pending"

        accepted = await c.post(
            url,
            headers={**_bearer(), "X-ASTRAVA-ACTOR-NAME": "attacker"},
            json={"decision": "approved", "decided_by": "Abstract", "reason": "Reviewed"},
        )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["decided_by"] == "Abstract"


async def test_approval_decision_without_decided_by_records_server_identity(keyed, db_session):
    approval = await _seed_pending_approval(db_session)
    async with _client() as c:
        res = await c.post(
            f"/api/v1/approvals/{approval.id}/decide",
            headers=_bearer(),
            json={"decision": "rejected", "reason": "Not acceptable"},
        )
    assert res.status_code == 200, res.text
    assert res.json()["decided_by"] == "Abstract"


async def test_orchestrator_resume_rejects_mismatched_identity_before_runner(keyed):
    async with _client() as c:
        res = await c.post(
            f"/api/v1/orchestrator/resume/{uuid.uuid4()}",
            headers=_bearer(),
            json={"decision": "approved", "decided_by": "Operator_1"},
        )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 5. CSRF and local-dev guards on real routes
# ---------------------------------------------------------------------------


async def test_real_route_cookie_session_unsafe_request_needs_csrf(keyed):
    issued = issue_session(KEY, ttl_seconds=600)
    async with _client() as c:
        res = await c.post(
            "/api/v1/executions",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={issued.token}"},
            json={},
        )
    assert res.status_code == 403
    assert res.json() == {"detail": "CSRF validation failed"}


@pytest.mark.parametrize(
    "header",
    ["Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP", "Via"],
)
async def test_local_dev_rejects_each_forwarding_header_on_real_route(local_dev, header):
    async with _client(client=("127.0.0.1", 5000)) as c:
        res = await c.get("/api/v1/auth/session", headers={header: "203.0.113.5"})
    assert res.status_code == 403


async def test_local_dev_accepts_ipv6_loopback_with_port_host(local_dev):
    async with _client(client=("::1", 5000)) as c:
        res = await c.get("/api/v1/healthz", headers={"Host": "[::1]:8000"})
    assert res.status_code == 200


async def test_local_dev_rejects_dns_rebinding_host_on_real_route(local_dev):
    async with _client(client=("127.0.0.1", 5000)) as c:
        res = await c.get("/api/v1/healthz", headers={"Host": "localhost.evil.com"})
    assert res.status_code == 403


async def test_middleware_denies_request_without_client_in_local_dev(local_dev):
    """ASGI scope with no client is treated as non-loopback and denied."""
    sent = []
    reached = []

    async def downstream(scope, receive, send):
        reached.append(scope)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/healthz",
        "headers": [(b"host", b"localhost:8000")],
    }
    await SecurityGuardMiddleware(downstream)(scope, receive, send)
    assert reached == []
    assert sent[0]["status"] == 403


# ---------------------------------------------------------------------------
# 6. Startup / lifespan refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("app_host", "key", "debug"),
    [
        ("0.0.0.0", None, False),
        ("127.0.0.1", "short-key", False),
        ("127.0.0.1", "", False),
        ("0.0.0.0", "h2-test-operator-key-0123456789abcdef", True),
    ],
    ids=["non-loopback-no-key", "short-key", "empty-key", "debug-on-non-loopback"],
)
async def test_lifespan_refuses_to_start_on_unsafe_configuration(app_host, key, debug, monkeypatch):
    monkeypatch.setattr(settings, "APP_HOST", app_host)
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", key)
    monkeypatch.setattr(settings, "DEBUG", debug)
    with pytest.raises(SecurityConfigurationError):
        async with real_app.router.lifespan_context(real_app):
            pass


async def test_lifespan_starts_with_safe_local_configuration(local_dev, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path / "artifacts")
    async with real_app.router.lifespan_context(real_app):
        assert (tmp_path / "artifacts").is_dir()


def test_secure_defaults_with_environment_cleared(monkeypatch):
    for name in ("APP_HOST", "DEBUG", "OPERATOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.APP_HOST == "127.0.0.1"
    assert fresh.DEBUG is False
    assert fresh.OPERATOR_API_KEY is None


# ---------------------------------------------------------------------------
# 7. Key leakage
# ---------------------------------------------------------------------------


async def test_configured_and_submitted_keys_never_leak_to_logs_or_bodies(
    keyed, caplog, db_tripwire
):
    caplog.set_level(logging.DEBUG)
    near_miss = KEY[:-1] + "Z"
    bodies: list[str] = []
    async with _client() as c:
        for submitted in (WRONG, near_miss, KEY[:10]):
            bodies.append(
                (
                    await c.post(
                        "/api/v1/auth/login",
                        json={"api_key": submitted},
                    )
                ).text
            )
            bodies.append(
                (
                    await c.get(
                        "/api/v1/projects", headers={"Authorization": f"Bearer {submitted}"}
                    )
                ).text
            )
        bodies.append((await c.get("/api/v1/auth/session")).text)
        bodies.append((await c.post("/api/v1/auth/logout")).text)

    for body in bodies:
        assert KEY not in body
    assert KEY not in caplog.text
    assert WRONG not in caplog.text
    assert near_miss not in caplog.text
    assert KEY[:10] not in caplog.text
    assert any(rec.name == "astrava.auth" for rec in caplog.records)
    # Login failures are logged at WARNING without the submitted value.
    assert all(WRONG not in str(rec.args) for rec in caplog.records if rec.name == "astrava.auth")


async def test_login_success_never_returns_or_logs_the_key(keyed, caplog):
    caplog.set_level(logging.DEBUG)
    async with _client() as c:
        res = await c.post("/api/v1/auth/login", json={"api_key": KEY})
    assert res.status_code == 200
    assert KEY not in res.text
    assert KEY not in res.headers.get("set-cookie", "")
    assert KEY not in caplog.text
