# ASTRAVA V1.4 — Next-Generation Autonomous Intelligence: Technical Risk Catalog

**Author:** Lead Architect, Principal Technical Strategist & Development Coordinator  
**Date:** 2026-11-03  
**Status:** PLANNING ONLY — RISK ANALYSIS  
**Baseline Release:** V1.3 Frozen Baseline (`08355ab5b18c92aa62c06dd7160f784ace964f93`)  

---

## 1. Risk Matrix Overview

| Risk ID | Risk Title | Severity | Likelihood | Impact Area | Mitigation Complexity | Status |
|---|---|---|---|---|---|---|
| **TR-01** | Spoofed Verifier Identity & Audit Corruption (V1.3 R1) | **HIGH** | HIGH | Governance & Trust | Low | **RESOLVED (M1.4-1)** |
| **TR-02** | Concurrent Ingestion Race & Partial Rollback Corruption (V1.3 R2) | **HIGH** | MEDIUM | Relational Consistency | Medium | **RESOLVED (M1.4-1)** |
| **TR-03** | Runaway Execution Costs & Token Depletion in Autonomous Loops | **CRITICAL** | HIGH | Operational Cost | Low-Medium | PENDING (M1.4-2) |
| **TR-04** | Infinite Replanning Cycles & Graph Deadlocks | **HIGH** | MEDIUM | Orchestrator Liveness | Medium | PENDING (M1.4-3) |
| **TR-05** | Repository Worktree Leaks & Working Tree Contamination | **CRITICAL** | LOW-MEDIUM | User Data Integrity | Medium | PENDING (M1.4-4) |
| **TR-06** | Evaluator Sycophancy & False Positive Verifications | **MEDIUM** | HIGH | Quality Assurance | Medium | PENDING (M1.4-5) |
| **TR-07** | LangGraph State Bloat across Multi-Stage Replans | **MEDIUM** | MEDIUM | Memory & Checkpoint Size | Low | PENDING (M1.4-3) |
| **TR-08** | Subprocess Concurrency Semaphore Starvation | **MEDIUM** | LOW | Engine Scalability | Low | PENDING (M1.4-6) |

---

## 2. In-Depth Risk Analysis & Mitigation Strategies

### TR-01: Spoofed Verifier Identity & Audit Corruption (V1.3 R1)
- **Status:** **RESOLVED (Milestone M1.4-1)**
- **Severity:** HIGH
- **Likelihood:** HIGH (resolved)
- **Mechanism:** In V1.3, `POST /api/v1/projects/{project_id}/memories/{memory_id}/verify` accepted arbitrary client-supplied `verified_by: "..."`. Because there was no authentication layer, unverified callers or third-party scripts could promote unverified agent conclusions to `VERIFIED_FINDING` under false credentials. The audit log faithfully recorded this forged identity.
- **Architectural Resolution Implemented in M1.4-1:**
  1. Created `backend/app/core/auth.py` with `OperatorContext`, `get_operator_context`, and `require_authorized_verifier`.
  2. Single-user local mode defaults to `settings.DEFAULT_OPERATOR_NAME` (`"Abstract"`); secured mode validates `OPERATOR_API_KEY` via `X-ASTRAVA-API-KEY` or Bearer token (HTTP 401 on failure).
  3. `require_authorized_verifier` dependency rejects any caller attempt to supply a `verified_by` that does not match the authenticated operator's display name with HTTP 403 Forbidden.
  4. Omitting `verified_by` derives the identity from `operator.display_name`. Authentic `actor_id` (`operator.operator_id`) and `actor_type` (`operator.actor_type`) are immutably written into `MemoryAuditLog`.
- **Verification:** 19/19 automated tests passing in `backend/tests/test_v1_4_security.py`.

---

### TR-02: Concurrent Ingestion Race & Partial Rollback Corruption (V1.3 R2)
- **Status:** **RESOLVED (Milestone M1.4-1)**
- **Severity:** HIGH
- **Likelihood:** MEDIUM (resolved)
- **Mechanism:**
  - V1.3 checked for duplicates in Python via a `SELECT` statement before `INSERT`. If two concurrent workers or executions ran simultaneously for the same project, both saw 0 rows and both inserted, creating duplicate memories.
  - In `workflow_graph.py`, line 620 executed `await session.rollback()` on a single candidate error. This rolled back the entire transaction for all previous candidates in the loop, leaving the session in an undefined state.
- **Architectural Resolution Implemented in M1.4-1:**
  1. Added deterministic SHA-256 `fingerprint` column to `ProjectMemory` based on `(project_id, category, summary, source_task_id)`.
  2. Created PostgreSQL unique partial index:
     `CREATE UNIQUE INDEX uq_project_memories_fingerprint ON project_memories (project_id, fingerprint) WHERE fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED');`
     enforced via Alembic migration `7a8e1b2c3d4e`.
  3. Implemented `IngestionOperation` model tracking operations by `(project_id, operation_token)`. Concurrent losing workers poll the winner with backoff using fresh database sessions, cleanly receiving the committed result without duplicate insertion or failure.
  4. Wrapped individual candidate inserts in SQLAlchemy savepoints: `async with session.begin_nested():`. A duplicate collision or candidate error rolls back only that candidate, leaving preceding valid candidates intact.
- **Verification:** 11/11 automated concurrency & idempotency tests passing in `backend/tests/test_v1_4_concurrency_idempotency.py` (including 10 simultaneous concurrent workers creating 0 duplicates).


---

### TR-03: Runaway Execution Costs & Token Depletion in Autonomous Loops
- **Severity:** CRITICAL
- **Likelihood:** HIGH
- **Mechanism:** In an autonomous system with dynamic replanning and remediation feedback loops, an agent stuck in a debugging failure cycle (e.g., trying to fix an unsolvable dependency conflict or oscillating between two failing tests) could loop indefinitely, consuming tokens and API quotas.
- **Architectural Mitigation:**
  1. **Strict Tri-Partite Budget Bounds:** Every execution is initialized with an immutable `ExecutionBudget`:
     - `max_cost_usd` (hard cap, default $1.00).
     - `max_remediation_cycles_per_task` (hard cap, default 3).
     - `max_total_remediations` (hard cap, default 5 across entire DAG).
     - `max_replan_count` (hard cap, default 2).
     - `max_wall_clock_seconds` (hard cap, default 600s).
  2. **Proactive Budget Governor:** Checked before every task dispatch and every replanning cycle. If any limit is exceeded, the pipeline transitions to `ExecutionStatus.PAUSED`, records `"budget_exhausted"`, and interrupts execution, requiring operator authorization to expand limits.
- **Verification Strategy:** Integration test configuring an intentionally failing task with `max_remediation_cycles = 2`; assert that the pipeline halts precisely after 2 attempts with status `paused` and does not run unboundedly.

---

### TR-04: Infinite Replanning Cycles & Graph Deadlocks
- **Severity:** HIGH
- **Likelihood:** MEDIUM
- **Mechanism:** The `replan_node` evaluates uncompleted tasks. If the replanner repeatedly decomposes tasks into new subtasks that fail, or if Kahn's algorithm detects circular dependencies in generated subtasks, the pipeline could oscillate or deadlock.
- **Architectural Mitigation:**
  1. **Replan Monotonicity Rule:** Completed tasks are immutable and cannot be deleted or re-executed by a replan.
  2. **Replan Iteration Counter:** A hard ceiling (`replan_count < 2`) in the LangGraph conditional routing function `route_after_evaluation`. Once reached, replanning is disabled; the pipeline either finishes with remaining valid tasks or transitions to `WAITING_APPROVAL`.
  3. **Strict DAG Validation:** Every generated or modified plan must pass `PlannerService.validate_and_compute_stages` before state update. If an LLM-generated plan contains a cycle or missing dependency, the replan is rejected and the previous plan is retained.
- **Verification Strategy:** Unit and integration tests supplying contradictory or circular task modifications; assert that `validate_and_compute_stages` raises `ValueError` and falls back gracefully.

---

### TR-05: Repository Worktree Leaks & Working Tree Contamination
- **Severity:** CRITICAL
- **Likelihood:** LOW-MEDIUM
- **Mechanism:** Operating on real code repositories risks modifying uncommitted user files, leaving detached `git worktree` locks, or corrupting git references if the backend process crashes during execution.
- **Architectural Mitigation:**
  1. **Isolated Git Worktrees in Dedicated Directory:** Worktrees are created exclusively under `storage/worktrees/<execution_id>` on an isolated feature branch `astrava/exec-<execution_id>`. The developer's primary working directory (`HEAD`) is never modified directly.
  2. **Lifespan and Crash Cleanup:** `GitWorktreeManager.cleanup(execution_id)` runs `git worktree remove --force` in a `finally:` block. On backend startup, a reconciliation routine scans `storage/worktrees/` and removes orphan worktrees whose execution status is `COMPLETED`, `FAILED`, or `CANCELLED`.
  3. **Diff Isolation:** Git diffs are computed using `git diff <base_branch>...HEAD` within the isolated branch. Merging back into the base repository is never automated; it requires an explicit `POST /executions/{id}/merge` operator call.
- **Verification Strategy:** Test verifying that creating an execution worktree, modifying files, and calling cleanup completely removes the worktree and leaves the main repository `git status` 100% clean.

---

### TR-06: Evaluator Sycophancy & False Positive Verifications
- **Severity:** MEDIUM
- **Likelihood:** HIGH
- **Mechanism:** LLM-based evaluators (Tier 2 Semantic Evaluator) have a known tendency toward sycophancy—marking deliverables as "satisfying acceptance criteria" even when code is incomplete, mocked, or non-functional.
- **Architectural Mitigation:**
  1. **Tier 1 Gating Priority:** Deterministic verification (syntax check, test execution, exit code 0) is an absolute prerequisite. The semantic evaluator is never invoked if deterministic checks fail.
  2. **Negative Evidence Verification:** The evaluator prompt requires quoting specific lines of code or artifact text for each satisfied criterion. If an assertion lacks verbatim line quotes, it is rejected as unverified.
  3. **Decoupled Evaluator Persona:** Evaluator tasks use a distinct system persona (`qa-auditor` or `code-critic`) with strict skeptical instructions, rather than reusing the generating agent's prompt.
- **Verification Strategy:** Test feeding mock/incomplete code (e.g. `def test_feature(): pass`) to the verification engine; assert that empty or mocked tests fail acceptance criteria.

---

### TR-07: LangGraph State Bloat across Multi-Stage Replans
- **Severity:** MEDIUM
- **Likelihood:** MEDIUM
- **Mechanism:** LangGraph checkpoints the entire `OrchestrationState` in PostgreSQL JSONB columns on every state transition. In long-running executions with multiple task waves, large artifact contents, and repeated remediation feedback traces, state data could grow to tens of megabytes, slowing down database serialization and checkpoint loading.
- **Architectural Mitigation:**
  1. **State Trimming & Reference Pointers:** Large deliverables (code diffs, file bodies, research reports) are persisted to the filesystem/artifact table, and only lightweight metadata references (`artifact_id`, `file_path`, `summary`) are stored in `OrchestrationState`.
  2. **Remediation Context Slicing:** Error diagnostics injected into the remediation prompt are bounded to the last 2,500 characters of compiler/test output. Historical error traces are not accumulated unboundedly in state.
- **Verification Strategy:** Measure `WorkflowExecution.state_data` JSON byte size across a 15-task execution with 2 replanning cycles; assert that total state size remains under 250 KB.

---

### TR-08: Subprocess Concurrency Semaphore Starvation
- **Severity:** MEDIUM
- **Likelihood:** LOW
- **Mechanism:** Multi-agent waves use `asyncio.gather` under `_execution_semaphore` (`MAX_CONCURRENT_EXECUTIONS = 2`). If one task hangs in a long-running subshell command or interactive prompt, it could starve other tasks from completing.
- **Architectural Mitigation:**
  1. Strict per-process timeout: `timeout_seconds = 120` enforced via `asyncio.wait_for`.
  2. Process group termination: `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)` followed by `SIGKILL` ensures runaway child processes do not linger in the background.
- **Verification Strategy:** Verified existing provider test `test_claude_provider_timeout_handling`.
