# ASTRAVA V1.4 — Milestone M1.4-2.2 Release Report
## Budget Governance Hardening

**Release Date:** 2026-11-04  
**Milestone:** M1.4-2.2  
**Status:** VERIFIED & COMPLETE  
**Git Author:** `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`  
**Base Commit:** `3219517` (V1.4 Milestone M1.4-2 Baseline)  
**Alembic Head:** `d4e5f6a1b2c3`  
**AI Executor:** Canonical Claude Haiku 5.5 (`claude-haiku-5-5`) via non-interactive Claude Code CLI  
**Lead Architect & Reviewer:** Gemini  

---

### 1. Executive Summary

Milestone M1.4-2.2 systematically resolves all six critical operational findings (**F-01 through F-06**) identified during the M1.4-2.1 Independent Acceptance Audit.

Execution budget governance is now fully resilient against:
1. **Unauthorized or Unaudited Budget Increases (F-01):** Secured with `OperatorContext`, `require_authorized_verifier`, mandatory justification reasons ($\ge 5$ chars), hard safety ceilings (`MAX_BUDGET_CEILINGS`), and transactional immutable audit logs.
2. **Unbudgeted Autonomous Retries (F-02):** Dynamic per-attempt reservations (`task:{id}:attempt:{attempt}`) halt retries mid-task immediately if budget is depleted; actual provider attempts are tracked via `total_agent_attempts += 1`.
3. **Provider Telemetry Gaps (F-03):** Telemetry omissions no longer coerce costs to $0.00; reserved estimates are strictly preserved as estimated cost when provider cost is missing, with verified zero cost explicitly confirmed.
4. **Stale Worker Reconciliation Races (F-04):** Cryptographically secure 64-character `fence_token` validation rejects stale, superseded, or zombie workers with `FencingTokenMismatchError`.
5. **Floating-Point Precision Drift (F-05):** Full relational migration from `Float` to PostgreSQL `Numeric(12, 6)` and Python `Decimal` eliminates IEEE-754 binary arithmetic errors.
6. **Crash Resumption Settlement Collisions (F-06):** Workflows safely adopt already-reconciled attempt 0 results upon restart instead of raising unhandled reservation errors.

---

### 2. Resolution of Audit Findings (F-01 through F-06)

| Finding ID | Audit Description | Root Cause in M1.4-2 | Implemented Solution in M1.4-2.2 | Verification Test |
|---|---|---|---|---|
| **F-01** | Unauthenticated budget increase API without audit logging | `POST /budget/increase` lacked authentication dependency, reason field, ceiling checks, and audit logging table | Integrated `OperatorContext` & `require_authorized_verifier`; added mandatory `reason` ($\ge 5$ chars); enforced `MAX_BUDGET_CEILINGS`; created `BudgetAuditLog` relational model; emitted `pipeline_budget_increased` event | `test_f01_budget_increase_authentication_and_authorization`, `test_f01_budget_increase_audit_log_and_events` |
| **F-02** | Retries bypassed budget reservation and masked attempt count | Task retries in `_execute_single_task` ran without reserving budget; attempt counter counted tasks rather than provider attempts | Replaced task-level reservation with dynamic per-attempt reservation (`attempt:N`); dynamically verifies budget before each retry; increments `total_agent_attempts += 1` per actual provider attempt | `test_f02_retry_aware_budget_accounting`, `test_f02_retries_halt_on_budget_exhaustion` |
| **F-03** | Missing provider metrics coerced to $0.00 | If provider returned `None` cost, governor defaulted to zero actual cost, masking expenses | `reconcile()` accepts `is_cost_zero_confirmed`; when cost is missing/None or zero with tokens, preserves reserved estimate as `consumed_estimated_cost_usd` | `test_f03_missing_provider_cost_preserves_reserved_estimate`, `test_f03_coerced_zero_cost_with_tokens_preserves_estimate`, `test_f03_deterministic_zero_cost_allowed` |
| **F-04** | Zombie/stale workers could settle reservations | Reservations lacked fencing tokens; any worker with reservation ID could reconcile | Added secure 64-character `fence_token` generated on `reserve()`; required on `reconcile()` and `release()`; raises `FencingTokenMismatchError` on mismatch | `test_f04_fencing_token_rejects_stale_workers` |
| **F-05** | IEEE-754 binary float drift violated check constraints | PostgreSQL columns used `Float`; Python used `float`, causing precision underflow (e.g. `-1e-16`) | Migrated database schema to `Numeric(12, 6)`; migrated service layer and models to Python `Decimal` across all arithmetic | `test_f05_decimal_precision_sub_cent_increments` |
| **F-06** | Crashed worker recovery failed on already-reconciled reservations | Resumption tried to create attempt 0 reservation; hit unique constraint error if already reconciled | Added `get_reservation_by_key()`; workflow checks settled state and cleanly adopts completed task deliverables if attempt 0 already succeeded | `test_f06_resumed_execution_adopts_already_reconciled_attempt` |

---

### 3. Detailed Architectural & Implementation Changes

#### 3.1 Relational Schema & Migration (`backend/alembic/versions/d4e5f6a1b2c3_harden_budget_governance_and_audit.py`)
- **Monetary Precision Migration:**
  - `execution_budgets`: `max_cost_usd`, `consumed_actual_cost_usd`, `consumed_estimated_cost_usd`, `reserved_cost_usd` migrated from `Float` to `Numeric(12, 6)`.
  - `budget_reservations`: `reserved_cost_usd`, `reconciled_cost_usd` migrated from `Float` to `Numeric(12, 6)`.
- **Fencing & Retry Tracking on `budget_reservations`:**
  - `fence_token`: `VARCHAR(64)` NOT NULL.
  - `attempt_number`: `INTEGER` DEFAULT 0 NOT NULL.
- **Audit Logging Table `budget_audit_logs`:**
  - Columns: `id` (UUID), `execution_id` (UUID FK), `budget_id` (UUID FK), `action` (VARCHAR 32), `actor_id` (VARCHAR 128), `actor_type` (VARCHAR 32), `reason` (TEXT NOT NULL), `previous_limits` (JSONB), `new_limits` (JSONB), `created_at` (TIMESTAMP).
  - Indexes: `ix_budget_audit_logs_execution_id`, `ix_budget_audit_logs_budget_id`, `ix_budget_audit_logs_action`.
- **Migration Verification:**
  - Revisions: `9c4d2e1f8a7b` -> `d4e5f6a1b2c3`.
  - Tested `alembic upgrade head`, `alembic downgrade -1`, and re-`upgrade head` cleanly against PostgreSQL 16.

#### 3.2 Core Service Layer (`backend/app/services/budget_governor.py`)
- **Decimal Accounting:**
  - Uses `Decimal` internally for all limits, reservations, and reconciliations.
  - Added helper `_to_decimal()` handling `int`, `float`, `str`, and `Decimal`.
  - `get_summary()` converts values to `float` for backward-compatible JSON API serialization.
- **Fencing Token Lifecycle:**
  - `reserve()` generates `fence_token = secrets.token_hex(32)`.
  - `_lock_active_reservation()`, `reconcile()`, and `release()` require `fence_token` matching the stored token; mismatches raise `FencingTokenMismatchError`.
- **Estimate Preservation:**
  - `reconcile(actual_cost_usd, is_cost_zero_confirmed=False)`:
    - If `actual_cost_usd is None`: preserves `reservation.reserved_cost_usd` as `consumed_estimated_cost_usd` and sets `is_cost_estimated = True`.
    - If `actual_cost_usd == 0` and tokens were consumed and `not is_cost_zero_confirmed`: treats as missing metric and preserves estimate.
    - If `is_cost_zero_confirmed=True`: accepts genuine zero cost without warning.
- **Budget Increase Governance:**
  - `increase_budget(execution_id, updates, reason, actor_id, actor_type)`:
    - Validates `reason` length ($\ge 5$ characters).
    - Validates increases against hard safety ceilings (`MAX_BUDGET_CEILINGS`: $50.00 max cost, 5M tokens, 50 attempts, 20 remediation turns, 10 replans, 7200s runtime).
    - Verifies budget belongs to the specified `execution_id`.
    - Persists immutable `BudgetAuditLog` within the same transaction.

#### 3.3 Orchestrator & Provider Telemetry (`workflow_graph.py`, `claude_code.py`, `base.py`)
- **`ProviderResponse`:** Allows `cost_usd: float | None = None` and adds `cost_unavailable`, `tokens_unavailable`.
- **`ClaudeCodeProvider`:** Correctly reports unavailable costs and sets `is_cost_estimated = True` for list-price estimations.
- **Per-Attempt Workflow Reservation:**
  - Ready tasks reserved as `task:{task_id}:attempt:0` with `fence_token`.
  - Before retry (`attempt > 0`), dynamically reserves `task:{task_id}:attempt:{attempt}`. If budget is exhausted, retries stop cleanly mid-task.
  - Reconciles each attempt individually, recording actual provider usage and incrementing `total_agent_attempts += 1` per attempt.
  - Resumed workflows after crashes inspect `get_reservation_by_key()`: if attempt 0 is already reconciled, the workflow adopts completed deliverables without duplicate execution.

#### 3.4 REST APIs & Frontend UI
- `POST /api/v1/executions/{execution_id}/budget/increase`: Protected by `require_authorized_verifier`. Rejects missing/invalid keys with HTTP 401; rejects short reasons or ceiling violations with HTTP 422; records `pipeline_budget_increased` event in `WorkflowExecution.events`.
- Frontend `IncreaseBudgetModal` in `BudgetIndicator.tsx`: Added mandatory reason text area with validation.

---

### 4. Verification & Testing Matrix

| Test Suite | File | Tests | Duration | Status |
|---|---|---|---|---|
| **V1.4 Budget Governance Suite** | `backend/tests/test_v1_4_budget_governance.py` | 20 / 20 | 2.68s | PASS |
| **V1.4 Budget Hardening Suite** | `backend/tests/test_v1_4_budget_hardening.py` | 10 / 10 | 4.44s | PASS |
| **Full Backend Regression Suite** | `backend/tests/` (15 test modules) | 148 / 148 | 23.57s | PASS |
| **Frontend Vitest Suite** | `frontend/src/__tests__/` (9 test files) | 16 / 16 | 1.36s | PASS |
| **Frontend Production Build** | `tsc -b && vite build` | 0 errors | 164ms | PASS |
| **Code Hygiene & Linting** | `ruff check .` & `ruff format --check .` | 95 files | clean | PASS |

---

### 5. Architectural Invariants Maintained

1. **Deterministic Bounded Resource Consumption:** Autonomous loops cannot exceed configured resource ceilings across initial attempts, retries, remediation turns, or dynamic replans.
2. **Tamper-Proof Audit Provenance:** No execution budget can be inflated without an authenticated operator identity, non-empty justification reason, ceiling compliance, and immutable audit logging.
3. **Stale Worker Immunity:** Zombie or delayed workers cannot corrupt budget accounting due to distributed fencing tokens.
4. **Zero Financial Drift:** Fixed-point `Numeric(12, 6)` arithmetic guarantees absolute monetary accounting integrity across millions of sub-cent operations.
5. **Crash Resilience:** Abrupt process crashes mid-execution resume safely and adopt pre-committed attempts without state collisions.

---

### 6. Sign-Off & Freeze

- **Alembic Head:** `d4e5f6a1b2c3`
- **Milestone Status:** M1.4-2.2 COMPLETE AND FROZEN.
- **Stop Condition:** M1.4-3 (Semantic Evaluation & Automated Remediation) has NOT been started.
