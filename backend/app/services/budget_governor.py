"""Centralized execution budget enforcement.

The BudgetGovernor is the single authority over per-execution resource budgets
(cost, tokens, runtime, agent/task attempts, remediation turns, replans).

Concurrency model
-----------------
Every mutating operation first takes ``SELECT ... FOR UPDATE`` on the
``execution_budgets`` row, so concurrent dispatches for the same execution are
serialized at the database. Reservations are recorded as ``BudgetReservation``
rows and the budget's ``reserved_*`` counters are updated in the same
transaction, so limit checks always see in-flight work.

Worker ownership & Fencing
--------------------------
Every reservation is issued a unique ``fence_token`` upon creation. When settling
(reconciling or releasing), the worker must provide its ``fence_token``. Stale
workers whose holds expired or were reclaimed are fenced out and rejected.

Monetary Precision
------------------
Monetary amounts are stored as PostgreSQL ``NUMERIC(12, 6)`` and manipulated as
Python ``Decimal``. Sub-cent rounding errors and IEEE-754 binary underflows are
eliminated.

Transactions
------------
Methods ``flush`` but never ``commit``; the caller owns the transaction and the
row locks are held until it ends.
"""

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import (
    BudgetAuditLog,
    BudgetReservation,
    BudgetReservationStatus,
    BudgetStatus,
    ExecutionBudget,
)

logger = logging.getLogger(__name__)

WARNING_THRESHOLD = 0.8
EXHAUSTION_THRESHOLD = 1.0

# Defaults from docs/V1_4_TARGET_ARCHITECTURE.md (section 3.6). Dimensions not listed
# here are unlimited (NULL) unless the caller passes an explicit limit.
DEFAULT_LIMITS: dict[str, Any] = {
    "max_cost_usd": Decimal("1.000000"),
    "max_input_tokens": 250_000,
    "max_output_tokens": 50_000,
    "max_remediation_turns": 5,
    "max_replan_count": 2,
    "max_runtime_seconds": 600,
}

# Configurable maximum ceilings for operator budget increases (F-01)
MAX_BUDGET_CEILINGS: dict[str, Any] = {
    "max_cost_usd": Decimal("50.000000"),
    "max_input_tokens": 5_000_000,
    "max_output_tokens": 1_000_000,
    "max_total_tokens": 6_000_000,
    "max_agent_attempts": 100,
    "max_task_attempts": 20,
    "max_remediation_turns": 20,
    "max_replan_count": 10,
    "max_runtime_seconds": 7200,
}

LIMIT_FIELDS: frozenset[str] = frozenset(
    {
        "max_cost_usd",
        "max_input_tokens",
        "max_output_tokens",
        "max_total_tokens",
        "max_agent_attempts",
        "max_task_attempts",
        "max_remediation_turns",
        "max_replan_count",
        "max_runtime_seconds",
    }
)

# Statuses in which no new work may be reserved.
_BLOCKED_STATUSES: frozenset[BudgetStatus] = frozenset(
    {BudgetStatus.EXHAUSTED, BudgetStatus.COMPLETED, BudgetStatus.CANCELLED}
)
# Statuses in which replanning and limit changes are refused.
_TERMINAL_STATUSES: frozenset[BudgetStatus] = frozenset(
    {BudgetStatus.COMPLETED, BudgetStatus.CANCELLED}
)
# Reservations that count as a spent task/agent attempt.
_ATTEMPT_STATUSES: tuple[BudgetReservationStatus, ...] = (
    BudgetReservationStatus.ACTIVE,
    BudgetReservationStatus.RECONCILED,
    BudgetReservationStatus.EXPIRED,
)


class BudgetGovernorError(Exception):
    """Base class for all BudgetGovernor failures."""


class BudgetExhaustedError(BudgetGovernorError):
    """The budget cannot accept new work (already exhausted, terminal, or over a limit)."""


class BudgetLimitExceededError(BudgetExhaustedError):
    """A specific request would exceed a limit (projected overflow or replan cap)."""


class ReservationNotFoundError(BudgetGovernorError):
    """No ACTIVE reservation exists with the given id."""


class FencingTokenMismatchError(BudgetGovernorError):
    """A stale worker presented an invalid or mismatched fencing token."""


class ReservationAlreadySettledError(BudgetGovernorError):
    """The requested reservation was already settled (reconciled or released)."""


# ---------------------------------------------------------------------------
# Internal helpers. These assume the caller already holds the budget row lock
# where noted, or take it themselves.
# ---------------------------------------------------------------------------


def _to_decimal(val: Decimal | float | int | str | None) -> Decimal | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise ValueError(f"Invalid monetary value {val!r}: {err}") from err


def _validate_limits(limits: Mapping[str, Any], enforce_ceilings: bool = False) -> dict[str, Any]:
    unknown = set(limits) - LIMIT_FIELDS
    if unknown:
        raise ValueError(f"Unknown budget limit(s): {sorted(unknown)}")
    validated: dict[str, Any] = {}
    for key, value in limits.items():
        if value is None:
            validated[key] = None
            continue
        if key == "max_cost_usd":
            dec_val = _to_decimal(value)
            assert dec_val is not None
            if dec_val < Decimal("0.0"):
                raise ValueError("Budget limit max_cost_usd must be >= 0 or None")
            if enforce_ceilings and dec_val > MAX_BUDGET_CEILINGS["max_cost_usd"]:
                raise ValueError(
                    f"max_cost_usd {dec_val} exceeds maximum permitted ceiling of {MAX_BUDGET_CEILINGS['max_cost_usd']}"
                )
            validated[key] = dec_val
        else:
            if value < 0:
                raise ValueError(f"Budget limit {key} must be >= 0 or None")
            if enforce_ceilings and key in MAX_BUDGET_CEILINGS:
                max_val = MAX_BUDGET_CEILINGS[key]
                if value > max_val:
                    raise ValueError(
                        f"{key} {value} exceeds maximum permitted ceiling of {max_val}"
                    )
            validated[key] = value
    return validated


def _validate_non_negative(**values: Decimal | float | int | None) -> None:
    for name, value in values.items():
        if value is not None and value < 0:
            raise ValueError(f"{name} must be >= 0")


async def _lock_budget(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID | None = None,
    budget_id: uuid.UUID | None = None,
) -> ExecutionBudget | None:
    """Load the budget row with FOR UPDATE, refreshing any stale identity-map copy."""
    stmt = select(ExecutionBudget).with_for_update().execution_options(populate_existing=True)
    if execution_id is not None:
        stmt = stmt.where(ExecutionBudget.execution_id == execution_id)
    elif budget_id is not None:
        stmt = stmt.where(ExecutionBudget.id == budget_id)
    else:
        raise ValueError("execution_id or budget_id is required")
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _require_locked_budget(db: AsyncSession, execution_id: uuid.UUID) -> ExecutionBudget:
    budget = await _lock_budget(db, execution_id=execution_id)
    if budget is None:
        raise BudgetGovernorError(f"No budget initialized for execution {execution_id}")
    return budget


async def _lock_active_reservation(
    db: AsyncSession, reservation_id: uuid.UUID, fence_token: str | None = None
) -> tuple[ExecutionBudget, BudgetReservation]:
    """Lock the parent budget, then the ACTIVE reservation. Lock order: budget -> reservation."""
    reservation = await db.get(BudgetReservation, reservation_id)
    if reservation is None:
        raise ReservationNotFoundError(f"Reservation {reservation_id} does not exist")
    budget = await _lock_budget(db, budget_id=reservation.budget_id)
    if budget is None:  # pragma: no cover - FK guarantees the parent exists
        raise BudgetGovernorError(f"Budget {reservation.budget_id} missing")
    locked = (
        await db.execute(
            select(BudgetReservation)
            .where(
                BudgetReservation.id == reservation_id,
                BudgetReservation.status == BudgetReservationStatus.ACTIVE,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if locked is None:
        raise ReservationNotFoundError(
            f"Reservation {reservation_id} is not ACTIVE (current status: {reservation.status})"
        )
    if fence_token is not None and locked.fence_token != fence_token:
        raise FencingTokenMismatchError(
            f"Fencing token mismatch for reservation {reservation_id}: stale worker rejected"
        )
    return budget, locked


def _release_reserved(budget: ExecutionBudget, reservation: BudgetReservation) -> None:
    budget.reserved_input_tokens = max(
        0, budget.reserved_input_tokens - reservation.reserved_input_tokens
    )
    budget.reserved_output_tokens = max(
        0, budget.reserved_output_tokens - reservation.reserved_output_tokens
    )
    budget.reserved_cost_usd = max(
        Decimal("0.0"), budget.reserved_cost_usd - reservation.reserved_cost_usd
    )
    budget.active_reservations_count = max(0, budget.active_reservations_count - 1)


def _consumed_dimensions(budget: ExecutionBudget) -> dict[str, tuple[Any, Any]]:
    """(limit, consumed) per dimension. Replan count is enforced in record_replan instead."""
    return {
        "cost_usd": (
            budget.max_cost_usd,
            budget.consumed_actual_cost_usd + budget.consumed_estimated_cost_usd,
        ),
        "input_tokens": (budget.max_input_tokens, budget.consumed_input_tokens),
        "output_tokens": (budget.max_output_tokens, budget.consumed_output_tokens),
        "total_tokens": (budget.max_total_tokens, budget.consumed_total_tokens),
        "runtime_seconds": (budget.max_runtime_seconds, budget.consumed_runtime_ms / 1000),
        "agent_attempts": (budget.max_agent_attempts, budget.total_agent_attempts),
        "remediation_turns": (budget.max_remediation_turns, budget.remediation_turns_count),
    }


def _apply_thresholds(budget: ExecutionBudget) -> None:
    """Move the budget to WARNING (>=80%) or EXHAUSTED (>=100%) based on consumed usage."""
    if budget.status in _TERMINAL_STATUSES:
        return

    exhausted: list[str] = []
    warning: list[str] = []
    for dimension, (limit, consumed) in _consumed_dimensions(budget).items():
        if limit is None:
            continue
        lim_float = float(limit)
        cons_float = float(consumed)
        if cons_float >= lim_float * EXHAUSTION_THRESHOLD:
            exhausted.append(dimension)
        elif cons_float >= lim_float * WARNING_THRESHOLD:
            warning.append(dimension)

    if exhausted:
        budget.status = BudgetStatus.EXHAUSTED
        budget.exhaustion_reason = "budget_exhausted"
        budget.metadata_json = {**budget.metadata_json, "exhausted_dimensions": exhausted}
        logger.warning(
            "Execution budget %s exhausted: %s",
            budget.execution_id,
            ", ".join(exhausted),
        )
    elif warning and budget.status == BudgetStatus.ACTIVE:
        budget.status = BudgetStatus.WARNING
        logger.warning(
            "Execution budget %s at >=80%%: %s",
            budget.execution_id,
            ", ".join(warning),
        )


async def _reclaim_expired(db: AsyncSession, budget: ExecutionBudget, now: datetime) -> int:
    """Expire overdue ACTIVE reservations. Caller must hold the budget lock.

    An expired reservation is treated as work that ran to its timeout: its estimates
    are charged to consumption so a stalled worker cannot free budget by timing out.
    """
    expired = (
        (
            await db.execute(
                select(BudgetReservation)
                .where(
                    BudgetReservation.budget_id == budget.id,
                    BudgetReservation.status == BudgetReservationStatus.ACTIVE,
                    BudgetReservation.expires_at.is_not(None),
                    BudgetReservation.expires_at <= now,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if not expired:
        return 0

    for reservation in expired:
        timeout_seconds = float(reservation.metadata_json.get("timeout_seconds", 0))
        _release_reserved(budget, reservation)
        reservation.status = BudgetReservationStatus.EXPIRED
        reservation.resolved_at = now
        budget.consumed_input_tokens += reservation.reserved_input_tokens
        budget.consumed_output_tokens += reservation.reserved_output_tokens
        budget.consumed_total_tokens += (
            reservation.reserved_input_tokens + reservation.reserved_output_tokens
        )
        budget.consumed_estimated_cost_usd += reservation.reserved_cost_usd
        budget.consumed_runtime_ms += int(timeout_seconds * 1000)
        budget.total_agent_attempts += 1
        budget.is_cost_estimated = True

    _apply_thresholds(budget)
    await db.flush()
    logger.info("Reclaimed %d expired reservation(s) for budget %s", len(expired), budget.id)
    return len(expired)


def _first_projected_violation(
    budget: ExecutionBudget,
    *,
    cost_usd: Decimal,
    input_tokens: int,
    output_tokens: int,
    timeout_seconds: int,
    task_attempts_used: int | None,
) -> str | None:
    """Return the first dimension a new reservation would push over its limit, else None."""
    committed_cost = (
        budget.consumed_actual_cost_usd
        + budget.consumed_estimated_cost_usd
        + budget.reserved_cost_usd
    )
    committed_input = budget.consumed_input_tokens + budget.reserved_input_tokens
    committed_output = budget.consumed_output_tokens + budget.reserved_output_tokens
    committed_total = (
        budget.consumed_total_tokens + budget.reserved_input_tokens + budget.reserved_output_tokens
    )

    if budget.max_cost_usd is not None and committed_cost + cost_usd > budget.max_cost_usd:
        return "cost_usd"
    if budget.max_input_tokens is not None and committed_input + input_tokens > (
        budget.max_input_tokens
    ):
        return "input_tokens"
    if budget.max_output_tokens is not None and committed_output + output_tokens > (
        budget.max_output_tokens
    ):
        return "output_tokens"
    if budget.max_total_tokens is not None and committed_total + input_tokens + output_tokens > (
        budget.max_total_tokens
    ):
        return "total_tokens"
    if budget.max_runtime_seconds is not None and (
        budget.consumed_runtime_ms / 1000 + timeout_seconds > budget.max_runtime_seconds
    ):
        return "runtime_seconds"
    if budget.max_agent_attempts is not None and (
        budget.total_agent_attempts + budget.active_reservations_count + 1
        > budget.max_agent_attempts
    ):
        return "agent_attempts"
    if (
        task_attempts_used is not None
        and budget.max_task_attempts is not None
        and task_attempts_used + 1 > budget.max_task_attempts
    ):
        return "task_attempts"
    return None


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


class BudgetGovernor:
    """Centralized, transactional enforcement of execution budgets."""

    @staticmethod
    async def initialize_budget(
        db: AsyncSession,
        execution_id: uuid.UUID,
        project_id: uuid.UUID,
        limits: Mapping[str, Any] | None = None,
    ) -> ExecutionBudget:
        """Create the budget for an execution. Idempotent: returns the existing budget
        unchanged if one already exists (the supplied limits are ignored in that case)."""
        existing = await BudgetGovernor.get_budget(db, execution_id)
        if existing is not None:
            return existing

        merged = {**DEFAULT_LIMITS, **_validate_limits(limits or {})}
        budget = ExecutionBudget(
            execution_id=execution_id,
            project_id=project_id,
            status=BudgetStatus.ACTIVE,
            metadata_json={},
            **merged,
        )
        try:
            async with db.begin_nested():
                db.add(budget)
                await db.flush()
        except IntegrityError:
            # Lost a creation race for the same execution; the winner's row is authoritative.
            winner = await BudgetGovernor.get_budget(db, execution_id)
            if winner is None:
                raise
            return winner

        await db.refresh(budget)
        return budget

    @staticmethod
    async def get_budget(db: AsyncSession, execution_id: uuid.UUID) -> ExecutionBudget | None:
        result = await db.execute(
            select(ExecutionBudget).where(ExecutionBudget.execution_id == execution_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_reservation_by_key(
        db: AsyncSession, budget_id: uuid.UUID, reservation_key: str
    ) -> BudgetReservation | None:
        """Query a reservation by key on a budget."""
        result = await db.execute(
            select(BudgetReservation).where(
                BudgetReservation.budget_id == budget_id,
                BudgetReservation.reservation_key == reservation_key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def reclaim_expired_reservations(db: AsyncSession, budget_id: uuid.UUID) -> int:
        """Expire overdue ACTIVE reservations on a budget. Returns how many were reclaimed."""
        budget = await _lock_budget(db, budget_id=budget_id)
        if budget is None:
            raise BudgetGovernorError(f"Budget {budget_id} does not exist")
        return await _reclaim_expired(db, budget, datetime.now(UTC))

    @staticmethod
    async def reserve(
        db: AsyncSession,
        execution_id: uuid.UUID,
        reservation_key: str,
        task_id: str | None = None,
        agent_slug: str | None = None,
        purpose: str = "agent_dispatch",
        attempt_number: int = 0,
        estimated_input_tokens: int = 4000,
        estimated_output_tokens: int = 2000,
        estimated_cost_usd: Decimal | float = Decimal("0.010000"),
        timeout_seconds: int = 120,
    ) -> BudgetReservation:
        """Hold budget for one unit of work before dispatch.

        Issues a unique ``fence_token`` protecting this reservation lease.
        Idempotent per ``reservation_key``: retrying with the same key returns the
        existing ACTIVE reservation without reserving twice.

        Raises:
            BudgetExhaustedError: budget is EXHAUSTED/COMPLETED/CANCELLED.
            BudgetLimitExceededError: this reservation would exceed a limit.
            ReservationAlreadySettledError: reservation was already settled.
        """
        cost_decimal = _to_decimal(estimated_cost_usd) or Decimal("0.010000")
        _validate_non_negative(
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            estimated_cost_usd=cost_decimal,
        )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        budget = await _require_locked_budget(db, execution_id)
        now = datetime.now(UTC)
        await _reclaim_expired(db, budget, now)

        existing = (
            await db.execute(
                select(BudgetReservation).where(
                    BudgetReservation.budget_id == budget.id,
                    BudgetReservation.reservation_key == reservation_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status == BudgetReservationStatus.ACTIVE:
                return existing
            if existing.status == BudgetReservationStatus.RECONCILED:
                raise ReservationAlreadySettledError(
                    f"reservation_key {reservation_key!r} already reconciled (attempt already completed)"
                )
            raise BudgetGovernorError(
                f"reservation_key {reservation_key!r} already used (status={existing.status})"
            )

        if budget.status in _BLOCKED_STATUSES:
            raise BudgetExhaustedError(f"Budget is {budget.status}: {budget.exhaustion_reason}")

        task_attempts_used: int | None = None
        if task_id is not None and budget.max_task_attempts is not None:
            task_attempts_used = await db.scalar(
                select(func.count(BudgetReservation.id)).where(
                    BudgetReservation.budget_id == budget.id,
                    BudgetReservation.task_id == task_id,
                    BudgetReservation.status.in_(_ATTEMPT_STATUSES),
                )
            )
            task_attempts_used = task_attempts_used or 0

        violation = _first_projected_violation(
            budget,
            cost_usd=cost_decimal,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            timeout_seconds=timeout_seconds,
            task_attempts_used=task_attempts_used,
        )
        if violation is not None:
            raise BudgetLimitExceededError(
                f"Reservation {reservation_key!r} would exceed {violation} limit"
            )

        fence_token = uuid.uuid4().hex
        reservation = BudgetReservation(
            budget_id=budget.id,
            execution_id=execution_id,
            reservation_key=reservation_key,
            purpose=purpose,
            agent_slug=agent_slug,
            task_id=task_id,
            reserved_input_tokens=estimated_input_tokens,
            reserved_output_tokens=estimated_output_tokens,
            reserved_cost_usd=cost_decimal,
            fence_token=fence_token,
            attempt_number=attempt_number,
            status=BudgetReservationStatus.ACTIVE,
            expires_at=now + timedelta(seconds=timeout_seconds),
            metadata_json={"timeout_seconds": timeout_seconds},
        )
        budget.reserved_input_tokens += estimated_input_tokens
        budget.reserved_output_tokens += estimated_output_tokens
        budget.reserved_cost_usd += cost_decimal
        budget.active_reservations_count += 1
        db.add(reservation)
        await db.flush()
        await db.refresh(reservation)
        return reservation

    @staticmethod
    async def reconcile(
        db: AsyncSession,
        reservation_id: uuid.UUID,
        actual_input_tokens: int,
        actual_output_tokens: int,
        duration_ms: int,
        actual_cost_usd: Decimal | float | None = None,
        is_cost_estimated: bool = False,
        is_cost_zero_confirmed: bool = False,
        is_remediation: bool = False,
        fence_token: str | None = None,
    ) -> ExecutionBudget:
        """Settle an ACTIVE reservation with actual usage, releasing its hold.

        If ``actual_cost_usd`` is None (or 0.0 with non-zero tokens without confirmation),
        the reserved estimate is charged and marked estimated. Missing metrics never
        coerce to $0.00 actual cost (F-03).
        Validates ``fence_token`` to reject stale workers (F-04).

        Raises:
            ReservationNotFoundError: no ACTIVE reservation with this id.
            FencingTokenMismatchError: fence_token does not match active lease.
        """
        cost_decimal = _to_decimal(actual_cost_usd) if actual_cost_usd is not None else None
        _validate_non_negative(
            actual_input_tokens=actual_input_tokens,
            actual_output_tokens=actual_output_tokens,
            duration_ms=duration_ms,
            actual_cost_usd=cost_decimal,
        )
        budget, reservation = await _lock_active_reservation(
            db, reservation_id, fence_token=fence_token
        )
        now = datetime.now(UTC)

        if cost_decimal is None:
            # Telemetry did not supply provider cost: charge the reserved estimate as estimated cost.
            cost = reservation.reserved_cost_usd
            cost_is_estimated = True
        elif (
            cost_decimal == Decimal("0.0")
            and (actual_input_tokens > 0 or actual_output_tokens > 0)
            and not is_cost_zero_confirmed
        ):
            # Coerced zero cost on token-consuming call: preserve estimated cost.
            cost = reservation.reserved_cost_usd
            cost_is_estimated = True
        else:
            cost = cost_decimal
            cost_is_estimated = is_cost_estimated

        _release_reserved(budget, reservation)
        budget.consumed_input_tokens += actual_input_tokens
        budget.consumed_output_tokens += actual_output_tokens
        budget.consumed_total_tokens += actual_input_tokens + actual_output_tokens
        budget.consumed_runtime_ms += duration_ms
        budget.total_agent_attempts += 1
        if cost_is_estimated:
            budget.consumed_estimated_cost_usd += cost
            budget.is_cost_estimated = True
        else:
            budget.consumed_actual_cost_usd += cost
        if is_remediation:
            budget.remediation_turns_count += 1

        reservation.status = BudgetReservationStatus.RECONCILED
        reservation.reconciled_cost_usd = cost
        reservation.resolved_at = now

        _apply_thresholds(budget)
        await db.flush()
        return budget

    @staticmethod
    async def release(
        db: AsyncSession, reservation_id: uuid.UUID, fence_token: str | None = None
    ) -> None:
        """Drop an ACTIVE reservation without consuming anything (work was never run)."""
        budget, reservation = await _lock_active_reservation(
            db, reservation_id, fence_token=fence_token
        )
        _release_reserved(budget, reservation)
        reservation.status = BudgetReservationStatus.RELEASED
        reservation.resolved_at = datetime.now(UTC)
        await db.flush()

    @staticmethod
    async def record_replan(db: AsyncSession, execution_id: uuid.UUID) -> ExecutionBudget:
        """Count one replanning iteration against ``max_replan_count``.

        Raises:
            BudgetExhaustedError: budget is EXHAUSTED/COMPLETED/CANCELLED.
            BudgetLimitExceededError: the replan cap has been reached.
        """
        budget = await _require_locked_budget(db, execution_id)
        if budget.status in _BLOCKED_STATUSES:
            raise BudgetExhaustedError(f"Budget is {budget.status}: {budget.exhaustion_reason}")
        if budget.max_replan_count is not None and budget.replan_count >= budget.max_replan_count:
            raise BudgetLimitExceededError(
                f"Replan limit reached ({budget.replan_count}/{budget.max_replan_count})"
            )
        budget.replan_count += 1
        await db.flush()
        return budget

    @staticmethod
    async def increase_budget(
        db: AsyncSession,
        execution_id: uuid.UUID,
        new_limits: Mapping[str, Any] | None = None,
        actor_id: str = "operator",
        actor_type: str = "operator",
        reason: str = "Operator manual limit increase",
    ) -> ExecutionBudget:
        """Raise or clear limits (operator action), record immutable audit log, and re-evaluate status.

        Requires mandatory non-empty reason and enforces ceiling boundaries (F-01).

        Raises:
            BudgetGovernorError: budget is COMPLETED or CANCELLED.
            ValueError: reason too short or requested limit exceeds maximum ceiling.
        """
        budget = await _require_locked_budget(db, execution_id)
        if budget.status in _TERMINAL_STATUSES:
            raise BudgetGovernorError(f"Cannot change limits of a {budget.status} budget")

        if not reason or len(reason.strip()) < 5:
            raise ValueError(
                "A non-empty reason of at least 5 characters is required for budget increase"
            )

        validated = _validate_limits(new_limits or {}, enforce_ceilings=True)
        previous_limits = {field: getattr(budget, field) for field in sorted(LIMIT_FIELDS)}

        for key, value in validated.items():
            setattr(budget, key, value)

        applied_limits = {field: getattr(budget, field) for field in sorted(LIMIT_FIELDS)}

        audit_entry = BudgetAuditLog(
            budget_id=budget.id,
            execution_id=budget.execution_id,
            action="budget_increase",
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason.strip(),
            previous_limits={
                k: float(v) if isinstance(v, Decimal) else v for k, v in previous_limits.items()
            },
            new_limits={
                k: float(v) if isinstance(v, Decimal) else v for k, v in applied_limits.items()
            },
        )
        db.add(audit_entry)

        if budget.status in (BudgetStatus.EXHAUSTED, BudgetStatus.WARNING):
            budget.status = BudgetStatus.ACTIVE
            budget.exhaustion_reason = None
        _apply_thresholds(budget)
        await db.flush()
        return budget

    @staticmethod
    async def get_summary(db: AsyncSession, execution_id: uuid.UUID) -> dict[str, Any]:
        """Snapshot of limits, consumption, reservations, and utilization for an execution.

        Raises:
            BudgetGovernorError: no budget exists for the execution.
        """
        budget = await BudgetGovernor.get_budget(db, execution_id)
        if budget is None:
            raise BudgetGovernorError(f"No budget initialized for execution {execution_id}")

        dims = _consumed_dimensions(budget)
        committed_cost = budget.consumed_actual_cost_usd + budget.consumed_estimated_cost_usd
        utilization: dict[str, float | None] = {}
        remaining: dict[str, float | None] = {}
        for dimension, (limit, consumed) in dims.items():
            if limit is None:
                utilization[dimension] = None
                remaining[dimension] = None
            else:
                lim_float = float(limit)
                cons_float = float(consumed)
                utilization[dimension] = cons_float / lim_float if lim_float > 0 else 1.0
                remaining[dimension] = max(lim_float - cons_float, 0.0)

        return {
            "budget_id": str(budget.id),
            "execution_id": str(budget.execution_id),
            "status": budget.status.value,
            "exhaustion_reason": budget.exhaustion_reason,
            "is_cost_estimated": budget.is_cost_estimated,
            "limits": {
                field: (
                    float(getattr(budget, field))
                    if isinstance(getattr(budget, field), Decimal)
                    else getattr(budget, field)
                )
                for field in sorted(LIMIT_FIELDS)
            },
            "consumed": {
                "cost_usd": float(committed_cost),
                "actual_cost_usd": float(budget.consumed_actual_cost_usd),
                "estimated_cost_usd": float(budget.consumed_estimated_cost_usd),
                "input_tokens": budget.consumed_input_tokens,
                "output_tokens": budget.consumed_output_tokens,
                "total_tokens": budget.consumed_total_tokens,
                "runtime_seconds": float(budget.consumed_runtime_ms / 1000),
                "agent_attempts": budget.total_agent_attempts,
                "remediation_turns": budget.remediation_turns_count,
                "replan_count": budget.replan_count,
            },
            "reserved": {
                "input_tokens": budget.reserved_input_tokens,
                "output_tokens": budget.reserved_output_tokens,
                "cost_usd": float(budget.reserved_cost_usd),
                "active_reservations": budget.active_reservations_count,
            },
            "remaining": remaining,
            "utilization": utilization,
        }
