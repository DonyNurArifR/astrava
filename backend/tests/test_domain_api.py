import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_project_crud_and_stats():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create Project
        payload = {
            "name": "Astrava Core SaaS",
            "description": "Core autonomous SaaS production engine",
            "studio_type": "saas",
            "target_objectives": ["Automate PRD generation", "Generate architecture"],
        }
        res = await client.post("/api/v1/projects", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Astrava Core SaaS"
        assert data["studio_type"] == "saas"
        project_id = data["id"]

        # Get Project
        get_res = await client.get(f"/api/v1/projects/{project_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == project_id

        # List Projects
        list_res = await client.get("/api/v1/projects")
        assert list_res.status_code == 200
        projects = list_res.json()
        assert any(p["id"] == project_id for p in projects)

        # Get Stats
        stats_res = await client.get("/api/v1/projects/stats")
        assert stats_res.status_code == 200
        stats = stats_res.json()
        assert stats["total_projects"] >= 1


@pytest.mark.asyncio
async def test_task_creation_and_listing():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create project first
        p_res = await client.post(
            "/api/v1/projects",
            json={"name": "Task Test Project", "studio_type": "saas"},
        )
        project_id = p_res.json()["id"]

        # Create Task
        t_payload = {
            "project_id": project_id,
            "title": "Design Database Schema",
            "description": "Create relational models for tasks and workflows",
            "executor_type": "claude_code",
            "assigned_model": "claude-haiku-5-5",
            "risk_level": "low",
        }
        t_res = await client.post("/api/v1/tasks", json=t_payload)
        assert t_res.status_code == 201
        task_data = t_res.json()
        assert task_data["title"] == "Design Database Schema"
        assert task_data["status"] == "pending"
        task_id = task_data["id"]

        # List Tasks
        t_list = await client.get(f"/api/v1/tasks/project/{project_id}")
        assert t_list.status_code == 200
        tasks = t_list.json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == task_id


@pytest.mark.asyncio
async def test_artifact_registration_and_retrieval():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create project
        p_res = await client.post(
            "/api/v1/projects",
            json={"name": "Artifact Test Project", "studio_type": "media"},
        )
        project_id = p_res.json()["id"]

        # Register artifact
        art_payload = {
            "project_id": project_id,
            "name": "system_design.md",
            "file_path": f"{project_id}/system_design.md",
            "artifact_type": "architecture",
            "mime_type": "text/markdown",
            "file_size_bytes": 100,
        }
        art_res = await client.post("/api/v1/artifacts", json=art_payload)
        assert art_res.status_code == 201
        art_data = art_res.json()
        assert art_data["name"] == "system_design.md"
        assert art_data["id"] is not None

        # List project artifacts
        list_art = await client.get(f"/api/v1/artifacts/project/{project_id}")
        assert list_art.status_code == 200
        assert len(list_art.json()) >= 1


@pytest.mark.asyncio
async def test_input_validation_boundaries():
    """Verify that schemas enforce string boundaries and reject invalid/blank inputs with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Blank project name
        res = await client.post("/api/v1/projects", json={"name": "   ", "studio_type": "saas"})
        assert res.status_code == 422

        # 2. Project name too short
        res = await client.post("/api/v1/projects", json={"name": "a", "studio_type": "saas"})
        assert res.status_code == 422

        # 3. Valid project
        res = await client.post(
            "/api/v1/projects", json={"name": "Valid Project", "studio_type": "saas"}
        )
        assert res.status_code == 201
        proj_id = res.json()["id"]

        # 4. Blank task title
        res = await client.post(
            "/api/v1/tasks",
            json={"project_id": proj_id, "title": "  "},
        )
        assert res.status_code == 422

        # 5. Empty/blank orchestrator objective
        res = await client.post(
            "/api/v1/orchestrator/plan",
            json={"project_id": proj_id, "objective": "   ", "studio_type": "saas"},
        )
        assert res.status_code == 422
