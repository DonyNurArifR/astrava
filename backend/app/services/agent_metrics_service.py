from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.project import StudioType
from app.models.task import Task, TaskStatus
from app.models.usage import ModelExecution
from app.schemas.agent import AgentMetricsResponse
from app.services.agent_service import DEFAULT_AGENTS

logger = logging.getLogger(__name__)


class AgentMetricsService:
    """Computes operational observability metrics, task success rates, and token/cost efficiency for agents."""

    @classmethod
    async def get_metrics_for_agent(
        cls, db: AsyncSession, agent_slug: str
    ) -> AgentMetricsResponse | None:
        # 1. Resolve agent identity and studio type
        agent_db = (
            await db.execute(select(Agent).where(Agent.slug == agent_slug))
        ).scalar_one_or_none()

        agent_name = agent_slug
        studio_type = StudioType.SAAS
        if agent_db:
            agent_name = agent_db.name
            studio_type = agent_db.studio_type
        else:
            # Fallback to default registry if not in DB
            def_ag = next((a for a in DEFAULT_AGENTS if a["slug"] == agent_slug), None)
            if def_ag:
                agent_name = def_ag["name"]
                studio_type = def_ag["studio_type"]
            else:
                # Check if tasks exist for this slug
                task_exists = await db.scalar(
                    select(func.count(Task.id)).where(Task.assigned_agent_slug == agent_slug)
                )
                if not task_exists:
                    return None

        # 2. Query task execution performance
        task_stmt = select(Task).where(Task.assigned_agent_slug == agent_slug)
        tasks = list((await db.execute(task_stmt)).scalars().all())

        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        failed_tasks = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        success_rate = (completed_tasks / total_tasks * 100.0) if total_tasks > 0 else 0.0

        # Compute total remediation cycles incurred
        total_remediations = 0
        task_ids = [t.id for t in tasks]
        for t in tasks:
            rem_hist = t.remediation_history_json or []
            if isinstance(rem_hist, list):
                total_remediations += len(rem_hist)

        # 3. Query usage metrics (cost, tokens, duration)
        total_cost_usd = 0.0
        total_tokens = 0
        avg_duration_ms = 0.0

        if task_ids:
            usage_stmt = select(
                func.coalesce(func.sum(ModelExecution.cost_usd), 0.0),
                func.coalesce(
                    func.sum(ModelExecution.input_tokens + ModelExecution.output_tokens), 0
                ),
                func.coalesce(func.avg(ModelExecution.duration_ms), 0.0),
            ).where(ModelExecution.task_id.in_(task_ids))

            usage_res = (await db.execute(usage_stmt)).one()
            total_cost_usd = float(usage_res[0] or 0.0)
            total_tokens = int(usage_res[1] or 0)
            avg_duration_ms = float(usage_res[2] or 0.0)

        return AgentMetricsResponse(
            agent_slug=agent_slug,
            agent_name=agent_name,
            studio_type=studio_type,
            total_tasks_assigned=total_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            success_rate=round(success_rate, 2),
            total_remediations=total_remediations,
            total_cost_usd=round(total_cost_usd, 4),
            total_tokens=total_tokens,
            avg_duration_ms=round(avg_duration_ms, 2),
        )

    @classmethod
    async def get_all_agent_metrics(
        cls, db: AsyncSession, studio_type: StudioType | None = None
    ) -> list[AgentMetricsResponse]:
        # Fetch all registered agents from DB, fallback to DEFAULT_AGENTS if empty
        stmt = select(Agent).order_by(Agent.name.asc())
        if studio_type:
            stmt = stmt.where(Agent.studio_type == studio_type)
        db_agents = list((await db.execute(stmt)).scalars().all())

        agent_slugs: list[str] = []
        if db_agents:
            agent_slugs = [a.slug for a in db_agents]
        else:
            filtered = [
                a for a in DEFAULT_AGENTS if not studio_type or a["studio_type"] == studio_type
            ]
            agent_slugs = [a["slug"] for a in filtered]

        metrics_list: list[AgentMetricsResponse] = []
        for slug in agent_slugs:
            metrics = await cls.get_metrics_for_agent(db, slug)
            if metrics:
                metrics_list.append(metrics)

        return metrics_list
