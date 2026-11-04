# ASTRAVA V1.4 — Milestone M1.4-2 Release Report
## Execution Budgets & Resource Governance

**Release Date:** 2026-11-03  
**Milestone:** M1.4-2  
**Status:** VERIFIED & COMPLETE  
**Git Author:** `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`  
**Base Commit:** `6e72ee3` (V1.4 Milestone M1.4-1 Baseline)  
**Alembic Head:** `9c4d2e1f8a7b`  
**AI Executor:** Canonical Claude Haiku 5.5 (`claude-haiku-5-5`) via non-interactive Claude Code CLI  
**Lead Architect & Reviewer:** Gemini  

---

### 1. Executive Summary

Milestone M1.4-2 delivers **centralized, persistent, deterministic execution budget governance**, resolving **TR-03 (Runaway Execution Costs & Token Depletion in Autonomous Loops)**.

Resource consumption is governed across the entire lifecycle of an execution—including initial agent dispatches, parallel execution waves, autonomous retries, automated remediation turns, dynamic replanning, and process restarts. Budgets belong durably to the `WorkflowExecution` in PostgreSQL, preventing workflows from bypassing resource limits across node restarts, graph resumes, or concurrent dispatches.

---

### 2. Core Architectural Deliverables

#### 2.1 Database Models & Migration (`backend/app/models/budget.py`)
- **`ExecutionBudget` Model:**
  - 1-to-1 relationship with `WorkflowExecution` (`execution_id` unique FK with CASCADE delete).
  - Configured Limits: `max_cost_usd` (default $1.00), `max_input_tokens` (250k), `max_output_tokens` (50k), `max_total_tokens` (300k), `max_agent_attempts` (10), `max_task_attempts` (3), `max_remediation_turns` (5), `max_replan_count` (2), `max_runtime_seconds` (600s).
  - Consumed Counters: `consumed_actual_cost_usd`, `consumed_estimated_cost_usd`, `is_cost_estimated`, `consumed_input_tokens`, `consumed_output_tokens`, `consumed_total_tokens`, `consumed_runtime_ms`, `total_agent_attempts`, `remediation_turns_count`, `replan_count`.
  - Active Holds: `reserved_input_tokens`, `reserved_output_tokens`, `reserved_cost_usd`, `active_reservations_count`.
  - Status Machine: `ACTIVE`, `WARNING` (>=80% utilization), `EXHAUSTED` (>=100%), `COMPLETED`, `CANCELLED`.
  - 12 PostgreSQL non-negative `CheckConstraint`s and composite indexes.
- **`BudgetReservation` Model:**
  - Tracks individual in-flight task reservations under unique constraint `uq_budget_reservations_budget_key` on `(budget_id, reservation_key)`.
  - Lifecycle: `ACTIVE` -> `RECONCILED` / `RELEASED` / `EXPIRED`.
  - Lease timestamp `expires_at` enabling automatic reclamation of abandoned holds.
- **Alembic Migration:**
  - `backend/alembic/versions/9c4d2e1f8a7b_add_execution_budgets_and_reservations.py` revising `7a8e1b2c3d4e`. Clean upgrade, downgrade, and re-upgrade verified against PostgreSQL 16.

#### 2.2 Centralized BudgetGovernor Service (`backend/app/services/budget_governor.py`)
- **Atomic Two-Phase Reservation Protocol:**
  - Mutating operations acquire row-level locks via `SELECT ... FOR UPDATE` on `execution_budgets`.
  - Prior to dispatch, projects usage: `consumed + reserved + requested <= limit`.
  - If limit is reached, transitions to `EXHAUSTED` and raises `BudgetExhaustedError` / `BudgetLimitExceededError`.
  - If capacity exists, increments reserved hold fields and inserts an `ACTIVE` `BudgetReservation`.
- **Settlement & Reconciliation:**
  - Upon completion, `reconcile()` releases the reserved hold and commits actual token usage, duration, and cost.
  - If a task is aborted before dispatch, `release()` drops the hold without incrementing consumed counters.
- **Worker Crash Recovery (`reclaim_expired_reservations`):**
  - Overdue active reservations (`expires_at <= now`) are charged at estimated values and transitioned to `EXPIRED`, preventing stalled or crashed workers from freeing budget by crashing.
- **Floating-Point Precision Guard:**
  - Clamps and rounds `reserved_cost_usd` to 6 decimal places to prevent negative IEEE-754 floating-point underflow from violating PostgreSQL check constraints.

#### 2.3 LangGraph Orchestrator Integration
- **`backend/app/orchestrator/runner.py`:**
  - `start_pipeline()` initializes `ExecutionBudget` immediately upon execution creation.
- **`backend/app/orchestrator/workflow_graph.py`:**
  - `dispatch_task_node`: Atomically reserves capacity for all ready tasks in a wave within a single transaction. If any task is refused, rolls back the wave holds, marks `budget_exhausted=True`, sets state `status="failed"` with descriptive error message, and routes directly to `END`.
  - `_execute_single_task`: Wraps execution; reconciles actual tokens, duration, and cost upon completion; releases reservation if aborted.
  - `plan_node`: Enforces `max_replan_count` via `record_replan()`. Refuses replanning when limit is reached.
  - Conditional edge `route_after_dispatch`: Routes immediately to `END` when `budget_exhausted` is set.

#### 2.4 REST APIs & Schemas
- **`backend/app/schemas/budget.py`:**
  - `BudgetLimitsUpdate`, `BudgetConsumedRead`, `BudgetReservedRead`, `BudgetSummaryResponse`, `BudgetReservationRead`.
- **`backend/app/api/v1/executions.py`:**
  - `GET /api/v1/executions/{execution_id}/budget`: Returns comprehensive budget summary with utilization percentages and remaining capacities.
  - `POST /api/v1/executions/{execution_id}/budget/increase`: Allows authorized operators to update limits, clearing `EXHAUSTED` status back to `ACTIVE` to permit resumption.

#### 2.5 Frontend Budget Experience
- **`frontend/src/types/api.ts` & `frontend/src/api/client.ts`:**
  - Full TypeScript interfaces for budget entities and API methods `getExecutionBudget`, `increaseExecutionBudget`.
- **`frontend/src/components/budget/BudgetIndicator.tsx`:**
  - Status badges (`ACTIVE`: emerald, `WARNING`: amber, `EXHAUSTED`: red, `COMPLETED`: slate).
  - Visual progress gauges for tokens and cost with amber (80%) and red (100%) thresholds.
  - Clear `(Estimated)` indicator when costs are estimated rather than provider-billed.
  - Agent attempts, remediation turns, and replans trackers.
  - Exhaustion alert banner with operator "Increase Budget" modal.
- **`frontend/src/pages/ExecutionsPage.tsx`:**
  - Integrated into the Execution Inspector drawer, auto-refreshing on status poll.

---

### 3. Governed Dimensions & Provider Measurement Capabilities

| Dimension | Default Limit | Measurement Type | Provider Measurement Capability & Limitations |
|---|---|---|---|
| **Monetary Cost** | $1.00 USD | Actual vs. Estimated | Claude Code CLI returns `total_cost_usd` based on Anthropic list prices (`costBasis: "list"`). For subscription-backed CLI users, this is an advisory expenditure metric rather than direct billable API cost. When provider cost is omitted, the governor marks `is_cost_estimated = True`. |
| **Input Tokens** | 250,000 | Actual Provider Usage | Reported directly by Claude Code CLI JSON output (`usage.input_tokens`). |
| **Output Tokens** | 50,000 | Actual Provider Usage | Reported directly by Claude Code CLI JSON output (`usage.output_tokens`). |
| **Total Tokens** | 300,000 | Actual Provider Usage | Derived from input + output tokens. |
| **Agent Attempts** | 10 per execution | Exact Counter | Tracked atomically per execution. Initial attempt counts as attempt 1. |
| **Task Attempts** | 3 per task | Exact Counter | Enforces maximum 3 attempts per task identifier. |
| **Remediation Turns** | 5 per execution | Exact Counter | Incremented on automated remediation turns. |
| **Replanning** | 2 per execution | Exact Counter | Incremented at `plan_node` during dynamic replanning; does not reset consumed counters. |
| **Runtime** | 600 seconds | Wall-Clock Duration | `duration_ms` accumulated across tasks and compared against max runtime. |

---

### 4. Verification & Testing Matrix

#### 4.1 Dedicated Budget Governance Test Suite (`backend/tests/test_v1_4_budget_governance.py`)
- **20/20 tests passed in 2.40s** against real PostgreSQL container (`astrava-postgres`):
  1. `test_budget_initialization`: Idempotent budget creation with default limits.
  2. `test_initial_execution_reservation`: Creates `ACTIVE` reservation and increments reserved hold counters.
  3. `test_successful_usage_reconciliation`: Settles hold, decrements reserved fields, and increments consumed counters.
  4. `test_unused_reservation_release`: Drops active reservation without consuming tokens or cost.
  5. `test_budget_exhaustion_before_dispatch`: Rejects reservation when limit is reached.
  6. `test_concurrent_reservations_cannot_over_reserve`: Launches 10 parallel async reservation requests when remaining capacity allows only 3; asserts exactly 3 succeed and 7 raise `BudgetLimitExceededError`.
  7. `test_token_usage_accounting`: Verifies exact accounting of input, output, and total tokens.
  8. `test_actual_vs_estimated_cost_representation`: Verifies actual vs. estimated cost accounting and `is_cost_estimated` flag.
  9. `test_unknown_provider_usage_representation`: Handles missing provider cost by charging reservation estimate and flagging estimated.
  10. `test_maximum_agent_attempt_enforcement`: Rejects dispatches exceeding `max_agent_attempts`.
  11. `test_maximum_remediation_turn_enforcement`: Enforces `max_remediation_turns` during settlement.
  12. `test_maximum_replan_enforcement`: Verifies `record_replan` caps iterations at `max_replan_count`.
  13. `test_runtime_limit_enforcement`: Rejects dispatches when projected duration exceeds `max_runtime_seconds`.
  14. `test_resume_after_process_restart`: Verifies existing budget and counters survive engine restarts.
  15. `test_recovery_from_crash_after_reservation`: Reclaims overdue expired reservations without orphaned holds.
  16. `test_parallel_workflow_waves_share_one_budget`: Parallel LangGraph wave tasks atomically reserve and share a single budget.
  17. `test_budget_exhaustion_during_workflow`: LangGraph halts cleanly at `dispatch_task` on exhaustion and routes to `END`.
  18. `test_no_dispatch_after_exhaustion`: Subsequent dispatches on exhausted execution are refused immediately.
  19. `test_existing_execution_compatibility`: Legacy executions without budgets initialize and run cleanly.
  20. `test_budget_increase_and_resumption`: Operator increases budget via `increase_budget`, unblocking `EXHAUSTED` execution back to `ACTIVE`.

#### 4.2 Full Regression Suite
- **Backend (Pytest):** **138/138 tests passed** in 22.89s (all 16 test files passing, +20 new tests, 0 regressions).
- **Frontend (Vitest):** **16/16 tests passed** in 1.68s (all 9 test files passing).
- **Code Hygiene (Ruff):** `ruff check` and `ruff format` 100% clean across all 94 backend files.
- **Frontend Quality:** `npm run lint` 0 errors, `npm run build` completed cleanly in 242ms.

---

### 5. Technical Risk Resolution Status

| Risk ID | Title | Previous Status | New Status |
|---|---|---|---|
| **TR-01** | Spoofed Verifier Identity & Audit Corruption | RESOLVED (M1.4-1) | **RESOLVED** |
| **TR-02** | Concurrent Ingestion Race & Partial Rollback Corruption | RESOLVED (M1.4-1) | **RESOLVED** |
| **TR-03** | Runaway Execution Costs & Token Depletion in Autonomous Loops | CRITICAL (Unmitigated) | **RESOLVED** |

---

### 6. Carry-Forward Limitations

The following architectural boundaries from previous milestones remain active and governed:
1. **Operator Attribution Header:** Single-operator authentication relies on shared key and `X-ASTRAVA-ACTOR-NAME` for display names; multi-user RBAC is deferred.
2. **Provider Cost Basis:** Costs reported by Claude Code CLI reflect Anthropic list prices, which represent compute value rather than direct invoice billing for subscription accounts.
3. **Task Retry Reservation Timeout:** Reservation leases default to one attempt's timeout (`timeout_seconds`), preventing multi-attempt multiplier over-estimation from prematurely exhausting runtime limits.
4. **Ingestion Polling Timeout:** Ingestion operation concurrency polling retains its documented bounded 3.0s window.

---

### 7. Stop Condition Enforced

Milestone **M1.4-2** is completely implemented, verified, and documented.
**STOP CONDITION ENFORCED:** Milestone M1.4-3 (Semantic Evaluator & Automated Remediation) has **not** been started.
