"""V1.4 M1.4-1 (Phase B): Trusted operator identity for memory verification.

Covers:
- Verifier identity is derived from OperatorContext, not the client payload.
- Keyed mode: missing/wrong credentials return 401; valid key via either header works.
- Impersonation (client verified_by != operator display name) returns 403.
- Blank / missing actor-name headers fall back to DEFAULT_OPERATOR_NAME.
- Audit log records authentic actor_id and actor_type.
- Unknown memory ID returns 404.
- Terminal status (SUPERSEDED) verification returns 400.
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import OperatorContext, get_operator_context, require_authorized_verifier
from app.main import app
from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryProvenanceType,
    MemoryStatus,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.services.memory_service import MemoryService

OPERATOR_KEY = "test-operator-key-123"
ACTOR_HEADER = "X-ASTRAVA-ACTOR-NAME"
KEY_HEADER = "X-ASTRAVA-OPERATOR-KEY"


@pytest.fixture
def dev_mode(monkeypatch):
    """Local development mode: no operator key configured."""
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", None)
    monkeypatch.setattr(settings, "DEFAULT_OPERATOR_NAME", "Abstract")


@pytest.fixture
def keyed_mode(monkeypatch):
    """Keyed mode: operator API key required."""
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", OPERATOR_KEY)
    monkeypatch.setattr(settings, "DEFAULT_OPERATOR_NAME", "Abstract")


async def _seed_project(db_session: AsyncSession) -> Project:
    ws = Workspace(name="Security WS", slug=f"ws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()
    project = Project(
        workspace_id=ws.id,
        name="Security Project",
        slug=f"proj-{uuid.uuid4().hex[:6]}",
        studio_type=StudioType.SAAS,
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _seed_agent_memory(db_session: AsyncSession, project_id: uuid.UUID):
    mem = await MemoryService.create_memory(
        db_session,
        project_id=project_id,
        category=MemoryCategory.DISCOVERY,
        summary="Discovery: queue latency spikes under load",
        content="Observed p99 queue latency spikes during batch ingestion.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    await db_session.commit()
    return mem


def _verify_url(project_id: uuid.UUID, memory_id: uuid.UUID) -> str:
    return f"/api/v1/projects/{project_id}/memories/{memory_id}/verify"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Unit-level dependency behaviour
# ---------------------------------------------------------------------------


async def test_dev_mode_context_defaults_to_default_operator(dev_mode):
    from starlette.requests import Request

    # Local-dev guard (M1.5-1a): loopback peer and allowed Host are required.
    scope = {
        "type": "http",
        "headers": [(b"host", b"localhost:8000")],
        "client": ("127.0.0.1", 50000),
    }
    ctx = await get_operator_context(Request(scope))
    assert ctx.display_name == "Abstract"
    assert ctx.actor_id == "Abstract"
    assert ctx.actor_type == "operator_local_dev"
    assert ctx.auth_method == "local_dev"
    assert ctx.is_authenticated is False
    assert ctx.is_authorized_verifier is True


async def test_require_authorized_verifier_rejects_unauthorized_actor():
    ctx = OperatorContext(
        actor_id="viewer",
        display_name="viewer",
        auth_method="api_key",
        is_authenticated=True,
        is_authorized_verifier=False,
    )
    with pytest.raises(HTTPException) as exc:
        await require_authorized_verifier(ctx)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Actor is not authorized to verify memories"


# ---------------------------------------------------------------------------
# Authorized verification
# ---------------------------------------------------------------------------


async def test_authorized_verification_derives_verifier_from_operator_context(
    db_session: AsyncSession, keyed_mode
):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={"reason": "Reviewed"},
            headers={KEY_HEADER: OPERATOR_KEY, ACTOR_HEADER: "Tech Lead"},
        )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["is_verified"] is True
    assert data["provenance_type"] == MemoryProvenanceType.VERIFIED_FINDING.value
    # Client-supplied X-ASTRAVA-ACTOR-NAME is ignored; server identity is recorded.
    assert data["metadata_json"]["verified_by"] == "Abstract"


async def test_bearer_token_authenticates_verification(db_session: AsyncSession, keyed_mode):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={},
            headers={"Authorization": f"Bearer {OPERATOR_KEY}"},
        )
    assert res.status_code == 200, res.text
    assert res.json()["metadata_json"]["verified_by"] == settings.DEFAULT_OPERATOR_NAME


# ---------------------------------------------------------------------------
# Unauthorized verification (keyed mode)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {KEY_HEADER: "wrong-key"},
        {"Authorization": "Bearer wrong-key"},
        {"Authorization": f"Basic {OPERATOR_KEY}"},
        {KEY_HEADER: ""},
    ],
)
async def test_missing_or_wrong_credentials_return_401(
    db_session: AsyncSession, keyed_mode, headers
):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={"verified_by": "Abstract"},
            headers=headers,
        )
    assert res.status_code == 401
    assert res.json()["detail"] == "Missing or invalid operator credentials"

    # Memory must remain untouched.
    refreshed = await MemoryService.get_memory(db_session, project.id, mem.id)
    assert refreshed.is_verified is False


async def test_empty_configured_key_fails_closed(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "")
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={},
            headers={KEY_HEADER: ""},
        )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Impersonation
# ---------------------------------------------------------------------------


async def test_impersonation_attempt_returns_403(db_session: AsyncSession, keyed_mode):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={"verified_by": "Senior QA Engineer"},
            headers={KEY_HEADER: OPERATOR_KEY, ACTOR_HEADER: "Tech Lead"},
        )
    assert res.status_code == 403
    assert res.json()["detail"] == (
        "Cannot impersonate verifier; identity derived from authenticated operator context"
    )

    refreshed = await MemoryService.get_memory(db_session, project.id, mem.id)
    assert refreshed.is_verified is False


async def test_matching_verified_by_label_is_accepted(db_session: AsyncSession, dev_mode):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={"verified_by": "Abstract"},
            headers={ACTOR_HEADER: "Abstract"},
        )
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# Actor header handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("actor_header", [None, "", "   "])
async def test_missing_or_blank_actor_header_defaults_to_operator(
    db_session: AsyncSession, dev_mode, actor_header
):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    headers = {} if actor_header is None else {ACTOR_HEADER: actor_header}
    async with _client() as client:
        res = await client.post(_verify_url(project.id, mem.id), json={}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["metadata_json"]["verified_by"] == "Abstract"


async def test_blank_verified_by_in_body_is_rejected(db_session: AsyncSession, dev_mode):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={"verified_by": "   "},
        )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Audit attribution
# ---------------------------------------------------------------------------


async def test_audit_log_records_authentic_actor(db_session: AsyncSession, keyed_mode):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    async with _client() as client:
        res = await client.post(
            _verify_url(project.id, mem.id),
            json={},
            headers={KEY_HEADER: OPERATOR_KEY, ACTOR_HEADER: "Tech Lead"},
        )
        assert res.status_code == 200, res.text

        audit = await client.get(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/audit",
            headers={KEY_HEADER: OPERATOR_KEY},
        )
    assert audit.status_code == 200
    verified_entries = [
        e for e in audit.json()["items"] if e["action"] == MemoryAuditAction.VERIFIED.value
    ]
    assert len(verified_entries) == 1
    assert verified_entries[0]["actor_type"] == "operator"
    # Client-supplied X-ASTRAVA-ACTOR-NAME is ignored; server identity is recorded.
    assert verified_entries[0]["actor_id"] == "Abstract"


# ---------------------------------------------------------------------------
# Not-found and terminal-status handling
# ---------------------------------------------------------------------------


async def test_verify_unknown_memory_returns_404(db_session: AsyncSession, dev_mode):
    project = await _seed_project(db_session)

    async with _client() as client:
        res = await client.post(_verify_url(project.id, uuid.uuid4()), json={})
    assert res.status_code == 404


async def test_verify_superseded_memory_returns_400(db_session: AsyncSession, dev_mode):
    project = await _seed_project(db_session)
    mem = await _seed_agent_memory(db_session, project.id)

    # Creating revision 2 marks revision 1 (this memory id) as SUPERSEDED.
    await MemoryService.update_memory(
        db_session,
        project.id,
        mem.id,
        summary="Discovery: queue latency spikes (revised)",
        expected_revision=1,
        actor_type="user",
        actor_id="test",
        reason="Revision for terminal-status test",
    )
    await db_session.commit()
    stale = await MemoryService.get_memory(db_session, project.id, mem.id)
    assert stale.status == MemoryStatus.SUPERSEDED

    async with _client() as client:
        res = await client.post(_verify_url(project.id, mem.id), json={})
    assert res.status_code == 400
    assert "superseded" in res.json()["detail"].lower()
