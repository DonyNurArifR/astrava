import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_agent_registry_seed_and_listing():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Trigger agent seeding
        seed_res = await client.post("/api/v1/agents/seed")
        assert seed_res.status_code == 200

        # 2. List all agents
        list_res = await client.get("/api/v1/agents")
        assert list_res.status_code == 200
        agents = list_res.json()
        assert len(agents) >= 16

        # Check SaaS studio agents
        saas_res = await client.get("/api/v1/agents?studio_type=saas")
        assert saas_res.status_code == 200
        saas_agents = saas_res.json()
        assert len(saas_agents) >= 7
        saas_slugs = {a["slug"] for a in saas_agents}
        assert "product-researcher" in saas_slugs
        assert "solution-architect" in saas_slugs
        assert "developer" in saas_slugs
        assert "qa-engineer" in saas_slugs

        # Check Media studio agents
        media_res = await client.get("/api/v1/agents?studio_type=media")
        assert media_res.status_code == 200
        media_agents = media_res.json()
        assert len(media_agents) >= 9
        media_slugs = {a["slug"] for a in media_agents}
        assert "content-researcher" in media_slugs
        assert "scriptwriter" in media_slugs
        assert "storyboard-designer" in media_slugs
        assert "seo-analyst" in media_slugs


@pytest.mark.asyncio
async def test_agent_retrieval_and_status_update():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Retrieve by slug
        get_res = await client.get("/api/v1/agents/product-researcher")
        assert get_res.status_code == 200
        agent = get_res.json()
        assert agent["name"] == "Product Researcher"
        assert "market_research" in agent["capabilities"]
        agent_id = agent["id"]

        # Retrieve by UUID
        uuid_res = await client.get(f"/api/v1/agents/{agent_id}")
        assert uuid_res.status_code == 200
        assert uuid_res.json()["slug"] == "product-researcher"

        # Toggle disabled
        patch_res = await client.patch(
            f"/api/v1/agents/{agent_id}/status",
            json={"is_enabled": False},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["is_enabled"] is False

        # Verify filtered listing
        enabled_res = await client.get("/api/v1/agents?is_enabled=true&studio_type=saas")
        assert enabled_res.status_code == 200
        enabled_slugs = {a["slug"] for a in enabled_res.json()}
        assert "product-researcher" not in enabled_slugs

        # Re-enable
        re_enable = await client.patch(
            f"/api/v1/agents/{agent_id}/status",
            json={"is_enabled": True},
        )
        assert re_enable.status_code == 200
        assert re_enable.json()["is_enabled"] is True


@pytest.mark.asyncio
async def test_agent_creation_and_validation():
    unique_slug = f"custom-security-{uuid.uuid4().hex[:6]}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Reject invalid slug pattern
        invalid_res = await client.post(
            "/api/v1/agents",
            json={
                "slug": "Invalid Slug With Spaces",
                "name": "Invalid Agent",
                "description": "Test",
                "studio_type": "saas",
                "instructions": "Do something",
            },
        )
        assert invalid_res.status_code == 422

        # Create valid custom agent
        valid_res = await client.post(
            "/api/v1/agents",
            json={
                "slug": unique_slug,
                "name": "Security Auditor",
                "description": "Performs static application security testing",
                "studio_type": "saas",
                "capabilities": ["sast", "cve_scanning"],
                "instructions": "Inspect dependencies and AST for security vulnerabilities.",
                "available_tools": ["claude_code"],
            },
        )
        assert valid_res.status_code == 201
        data = valid_res.json()
        assert data["slug"] == unique_slug
        assert data["is_enabled"] is True
