# M1.5-1c — Orchestration Recovery and Retry Correctness (design and spec)

Status: authorized by the operator (SD-03, SD-04). Base commit `552165c`. This file is written **before** implementation and then updated with the results.

## 1. Verified facts about the current architecture (source-inspected, not assumed)
| # | Fact | Evidence |
|---|---|---|
| F1 | **There is no LangGraph checkpointer.** `build_orchestrator_graph()` returns `workflow.compile()` with no `checkpointer`. Recovery can only be database-based. | `workflow_graph.py` `build_orchestrator_graph` |
| F2 | The graph state dict is persisted only by `_sync_state_to_db`, which `start_pipeline` calls after the nodes `retrieve_knowledge`, `plan`, `artifact`, `ingest_knowledge`, `complete` (resume: `artifact`, `ingest_knowledge`, `complete`). **`dispatch_task`, `verify`, `remediation`, `replan` results are not persisted.** | `runner.py` |
| F3 | `resume_pipeline` is **approval-resume only**. It never inspects reservations, has no lease, does not check that the execution is `WAITING_APPROVAL` (a RUNNING or FAILED execution can be "resumed"), and no code path recovers a `RUNNING` execution whose process died. Such an execution stays `RUNNING` forever. | `runner.py` `resume_pipeline` |
| F4 | Re-entering `astream(state)` always starts at `retrieve_knowledge`, which returns `{}` when `state["plan"]` exists; `plan_node` likewise returns `{}`; `approval_check` recomputes ready tasks from `completed_task_ids`/`failed_task_ids`/`status`. If the crash preceded the plan sync, the graph re-plans (planning is a provider call: at-least-once). | `workflow_graph.py` |
| F5 | `dispatch_task_node` already contains adoption logic: for each ready task it inspects RECONCILED reservations (latest attempt first), and adopts an attempt only if `metadata_json["success"] is True`, output non-empty, and expected deliverables exist, are non-empty and are not older than the reservation (rejects stale files). A reconciled reservation alone never proves completion. | `workflow_graph.py` ~L683-775 |
| F6 | `BudgetGovernor.reserve` is idempotent per `reservation_key` and **returns the existing ACTIVE reservation, including its original `fence_token`**, to any caller. A recovering worker would therefore inherit the dead (or merely slow) worker's token, so fencing would not separate old and new owner. | `budget_governor.py` `reserve` |
| F7 | An ACTIVE reservation of a dead worker is reclaimed only lazily, when some later `reserve()` runs after `expires_at`. Until then the budget carries a permanently active hold; there is no documented recovery path. `_reclaim_expired` charges the reserved estimate (conservative) and counts the attempt. | `budget_governor.py` |
| F8 | In `_run_single_task` the retry loop is `for attempt in range(max_retries + 1)` and **always starts at 0**, but `dispatch_task_node` reserves attempt number `attempts_used`. After a restart (or a remediation re-dispatch) the first loop pass uses reservation `attempt:N` as "attempt 0", the next loop pass tries to reserve `attempt:N` again (`ReservationAlreadySettledError`, not caught as `BudgetExhaustedError`), and total provider attempts can exceed `max_retries + 1`. | `workflow_graph.py` L477-545 |
| F9 | `_sync_state_to_db` and `update_execution_status` write unconditionally: no ownership check, no terminal-state guard. A stale worker can overwrite a newer worker's state, and a `COMPLETED`/`FAILED`/`CANCELLED` execution can be written back to `RUNNING`. | `runner.py`, `workflow_service.py` |
| F10 | Task rows are matched across the **whole project by title** (`existing_by_title`), so two executions of the same project with equal task titles would share and overwrite each other's task rows. `tasks` has no `execution_id`. | `runner.py` `_sync_state_to_db` |
| F11 | Artifact registration de-duplicates on `(execution_id, file_path)` in application code only (no unique constraint). Safe only if registration is serialized per execution. | `artifact_service.py` |
| F12 | Usage rows (`ModelExecution`) come from in-memory `usage_records`; usage of an attempt whose settlement survived but whose state sync did not is not re-created. Budget consumption itself is correct because it is written in the settlement transaction. | `_sync_state_to_db` |
| F13 | Verification (`SemanticEvaluator`), planning and knowledge extraction are provider calls. Re-running them after a crash is at-least-once. | `workflow_graph.py` |

## 2. Recovery design
### 2.1 Mechanisms (database-based, no new infrastructure)
1. **Execution lease with epoch fencing** (one Alembic migration, three nullable/defaulted columns on `workflow_executions`: `run_epoch INT NOT NULL DEFAULT 0`, `lease_owner VARCHAR(100)`, `lease_expires_at TIMESTAMPTZ`).
   - `claim`: a single atomic `UPDATE ... SET run_epoch = run_epoch + 1, lease_owner = :me, lease_expires_at = now() + ttl WHERE id = :id AND status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= now()) RETURNING run_epoch`. Of two simultaneous claimers exactly one row update succeeds.
   - `heartbeat`: `UPDATE ... SET lease_expires_at = ... WHERE id = :id AND run_epoch = :epoch AND lease_owner = :me`; zero rows means the lease was lost, and the worker cancels its own graph run.
   - **Fenced state writes**: `_sync_state_to_db` first locks the execution row `FOR UPDATE` and compares `run_epoch`; a mismatch raises `StaleWorkerError` before any task, artifact, usage or status write (the whole transaction rolls back).
   - **Terminal-state guard**: `update_execution_status` refuses to move out of `COMPLETED`/`FAILED`/`CANCELLED`.
2. **Reservation fencing**. On recovery claim, every ACTIVE reservation of the execution is force-settled to `EXPIRED` by `BudgetGovernor.expire_orphaned_reservations`: the hold is released, the estimate is charged as consumed (same conservative rule as lease expiry, never double counted because a reservation leaves ACTIVE exactly once), the attempt is counted, and `metadata_json.recovered_by_epoch` is recorded. The old worker's `fence_token` can no longer settle it (`ReservationNotFoundError`). New attempts use new keys (`task:<id>:attempt:<n>`, n = attempts used).
3. **Retry-aware attempt numbering (F8 fix)**: dispatch passes the reserved `attempt_number` to the task; the retry loop runs `range(start_attempt, max_retries + 1)`. A task therefore never exceeds `max_retries + 1` provider attempts in total across restarts.
4. **Adoption (existing F5 logic)** completes tasks whose successful attempt was settled before the crash, using the reservation metadata, not the lost in-memory state.
5. **Task identity (F10 fix)**: task rows are created with `input_data = {"execution_id", "task_key"}` and matched on that, not on title. (No migration.)
6. **Approval resume guard**: `resume_pipeline` acts only on `WAITING_APPROVAL`; any other status is a no-op returning the execution (idempotent repeats, no FAILED to RUNNING).
7. **`OrchestrationRunner.recover_execution(db, execution_id, owner)`** is the new, explicit entry point: claim lease, expire orphaned reservations, verify the work directory (fail closed), re-enter the graph with the persisted `state_data`, heartbeat while running, release the lease at the end. It is **not** invoked automatically at API startup (a restart would otherwise start provider calls without an operator decision); `find_recoverable_executions` lists `RUNNING` executions with an expired or missing lease.

### 2.2 State-transition diagram
```
              start_pipeline (epoch 1)                        recover_execution (epoch n+1)
 PENDING ──► RUNNING ───────────────────────────┐       claim OK only if lease expired/NULL
               │ retrieve ► plan ► [SYNC#1]     │       ┌───────────────────────────────────┐
               ▼                                │       │ 1 claim (atomic UPDATE, epoch++)  │
          approval_check ──need approval──► WAITING_APPROVAL ──resume_pipeline (only here)──┐│
               │ ready wave                         ▲                                     ││
               ▼                                    │                                     ││
   dispatch: reserve wave (ACTIVE, token T) ──crash A,E──► orphan ACTIVE reservations     ││
        run providers ─ attempt k ──────────crash──► (provider done, not reconciled) B    ││
        settle: RECONCILED(success?) ───────crash──► reconciled, state lost  C,D,E        ││
               ▼                                                                          ││
            verify ► (remediation|replan|artifact) ► write files ──crash──► F             ││
               ▼                                                                          ││
         artifact [SYNC#2: tasks, artifacts, usage, status — fenced by epoch]             ││
               ▼ all tasks done                                                           ││
        ingest ► complete [SYNC#3] ──► COMPLETED (terminal, never reopened)               ││
        any failed task ──► FAILED (terminal, never reopened)                             ││
                                                                                          ││
  recovery: 2 expire orphaned ACTIVE reservations (charge estimate once, count attempt)   ││
            3 re-enter graph at retrieve_knowledge with persisted state_data ◄────────────┘│
              retrieve/plan: skip if state.plan exists │ approval_check: recompute wave     │
              dispatch: adopt valid reconciled attempt │ else reserve attempt n (limit kept)│
              verify/artifact: re-run (idempotent: same names, same registration key)      │
            4 release lease; terminal states untouched ◄───────────────────────────────────┘
```
Node safety on re-entry: `retrieve_knowledge`, `plan` (skip when plan persisted; else at-least-once planner call), `approval_check` (pure recompute), `dispatch_task` (reconcile persisted reservation state **before** performing work; this is the only node that may call a provider again), `verify` (re-run; at-least-once evaluator call), `artifact` (idempotent: same file names, registration upsert), `ingest_knowledge` (idempotent by operation token), `complete`.

### 2.3 Semantics that cannot be exactly-once (documented, not hidden)
- A provider call whose result was not durably settled before the crash is **invoked again** on recovery (at-least-once). Its estimated cost is charged once as consumed (the attempt counts).
- Planning, semantic verification and knowledge extraction may be repeated.
- Adopted output text comes from reservation metadata (capped at 4000 characters).
- Usage telemetry rows for adopted attempts are not recreated (F12).
- External side effects an agent performs inside the work directory are not rolled back.

## 3. Test design (real processes, real PostgreSQL)
- A separate throw-away database `astrava_m15_1c_<random>` on the existing PostgreSQL server (created and dropped by the test fixture; the dev database is never touched). Alembic upgraded to head in it.
- `tests/recovery/worker_main.py` is a subprocess entry point that runs the **real** `OrchestrationRunner` (`start` or `recover`). It installs only test doubles for the external model boundary (deterministic `ProviderFactory.get_provider`, `GoalDecomposer.decompose_goal`, `SemanticEvaluator.evaluate`) plus **failpoints** (wrapper that writes a marker file then sleeps) at: after provider returns / before reconcile, after reconcile / before state sync, inside artifact registration, between waves. The orchestrator process kills it with `SIGKILL` only after the marker file exists. No production code contains test hooks.
- Per scenario the parent records PIDs, DB rows before and after (executions, tasks, reservations, budget counters, artifacts, events) and the provider invocation log.
- Scenarios A-H as in the authorization, plus: two simultaneous recoverers (one must lose), repeated recovery idempotence, terminal execution never reopened, budget never double counted, retry limit preserved across restart.

## 4. Non-goals
No M1.5-2, no Docker for the API, no worker containers, no credential change, no billable call, no RBAC/multi-tenancy, no unrelated workflow rewrite. M1.5-1b residual debt stays open: worktree artifacts not retrievable, intermediate-directory TOCTOU, other repo-local git config, tracked-file-only dirty check.

## 5. Implementation notes (added after implementation)
- Orphan expiry charges runtime as min(timeout, elapsed since reservation) instead of the full timeout (a crash of a fast task must not consume the whole runtime budget); tokens and cost keep the full estimate.
- The execution semaphore is acquired before creating/claiming (start) and before claiming (recover); `resume_pipeline` already held it.
- `PENDING -> RUNNING` and the first lease are one atomic claim; the complete initial state is checkpointed before the first node.
- Added `app/orchestrator/recovery_cli.py` for operator-run recovery. Results: `docs/V1_5_M1_5_1C_ACCEPTANCE_REPORT.md`.
