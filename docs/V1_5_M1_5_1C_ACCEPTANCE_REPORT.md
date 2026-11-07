# M1.5-1c Acceptance Report — Orchestration Recovery and Retry Correctness

Base: `552165c` (M1.5-1b). Closes **SD-03** (full `OrchestrationRunner` crash/restart recovery) and **SD-04** (retry-aware recovery and reservation reconciliation). Design and verified architecture facts: `docs/V1_5_M1_5_1C_SPEC.md`.

## 1. What exists now (recovery architecture)
Recovery is **database-based**. There is no LangGraph checkpointer (verified: `workflow.compile()` without one); this milestone does not add one.
- **Execution lease + epoch** (migration `b7c1d2e3f4a5`: `run_epoch`, `lease_owner`, `lease_expires_at`). `claim` is one atomic `UPDATE` (free-or-expired lease and eligible status, `run_epoch+1`). A background heartbeat renews it; if the epoch is superseded or the database is unreachable longer than the TTL, the run is cancelled (`StaleWorkerError`). Every state write is fenced: it locks the execution row and compares the epoch first.
- **Orphan reservation settlement** (`BudgetGovernor.expire_orphaned_reservations`): on recovery every ACTIVE reservation of the dead epoch leaves ACTIVE exactly once (tokens/cost estimate charged once, attempt counted, runtime charged as min(timeout, elapsed)). The old fence token can no longer settle it.
- **Retry-aware attempt numbering**: the dispatcher's reserved attempt number seeds the retry loop (it used to restart at 0, colliding with the existing reservation key and allowing more than `max_retries+1` attempts).
- **Adoption** (pre-existing logic, now proven end to end): a task is completed after a crash only from a RECONCILED attempt with `success=True`, non-empty output and its deliverables present and fresh.
- **Checkpoints**: complete initial state is persisted before the first node; remediation and replan results are checkpointed (status stays RUNNING). Dispatch and verify are deliberately not checkpointed because their result is rebuilt from settled reservations.
- **Guards**: terminal executions are never reopened (`update_execution_status` raises, pause/resume API returns 409, resume endpoint only unpauses PAUSED); `resume_pipeline` acts only on WAITING_APPROVAL through an atomic status+epoch claim; task rows are matched on `(execution_id, task_key)` instead of by title across the project.
- **Entry point**: `OrchestrationRunner.recover_execution` / `find_recoverable_executions`, operator-run via `python -m app.orchestrator.recovery_cli --list | <execution_id>`. It is **not** started automatically because it can call the provider again.

### State-transition diagram
See `docs/V1_5_M1_5_1C_SPEC.md` section 2.2 (unchanged by implementation, except that the semaphore is now taken before the claim).

## 2. Crash scenarios and test evidence (real PostgreSQL, separate OS processes, `SIGKILL`)
Each test creates a throw-away database `astrava_m15_1c_<id>` (migrated to head, dropped afterwards), spawns `tests/recovery/worker_main.py` (real runner; only provider/planner/evaluator are deterministic doubles; failpoints stop the process at an exact point), kills it with `SIGKILL` and recovers in a second process.
| Scenario | Test | Result |
|---|---|---|
| A provider call in flight | `test_a_provider_crash.py` | orphan ACTIVE -> EXPIRED once; task re-run as attempt 1; COMPLETED; repeat recovery is a no-op |
| B provider finished, not reconciled | `test_b_...::test_b` | unsettled result not trusted; estimate charged once; provider re-invoked (at-least-once) |
| C attempt 0 failed, attempt 1 ok, state lost | `::test_c` | adopted from the successful attempt; no new provider call; failed attempt never counts |
| D reconciled but state interrupted | `::test_d` | with deliverable: adopted; without deliverable: re-run (reconciled alone is not completion) |
| E parallel wave partial | `::test_e` | siblings p1/p2 survive (one invocation each); only p3 re-invoked |
| F artifact written, registration interrupted | `::test_f` | adopted; each artifact registered exactly once |
| G stale worker returns | `test_g_h_concurrency.py::test_g` | `SIGSTOP`, successor claims epoch 2 and completes, `SIGCONT`: stale worker exits 4 and changes nothing |
| H repeated/simultaneous resume and recovery | `::test_h_*` | two simultaneous recoverers: one claim (epoch 2), one `pipeline_recovered`; two simultaneous approval resumes: task runs once |
| Invariants 12/13 | `::test_failed_execution_is_never_reopened...`, `::test_retry_limit...`, `::test_failed_reconciled_attempt...` | FAILED never reopened; at most `max_retries+1` provider attempts across restarts; a failed reconciled attempt is never adopted |
| Remediation | `::test_remediation_state_survives...` | `remediation_cycles` persisted; the turn is not recounted |
| Initial checkpoint | `::test_crash_before_first_sync...` | recovery works from a crash before the first sync |
| Fencing atomics | `tests/test_m1_5_1c_fencing.py` (21 tests) | 8 simultaneous claims -> 1 winner; stale epoch cannot heartbeat/write/release; stale fence token rejected; second expiry is a no-op; terminal guard; task identity |

### Process and database evidence (scenario E, run of `scratchpad/evidence.py`)
- Start process pid 68296 killed by SIGKILL (return code -9). A recovery attempted while the dead owner's lease was live was refused (exit 3). After the TTL, recovery process pid 68309 exited 0; a third process (pid 68311) recovering again exited 0 without changes.
- Before kill: `RUNNING epoch=1`, reservations `p1 RECONCILED, p2 RECONCILED, p3 ACTIVE`, budget active=1 attempts=2, tasks all PENDING, artifacts 0.
- After recovery: `COMPLETED epoch=2`, reservations `p1 R, p2 R, p3:0 EXPIRED, p3:1 R`, budget active=0 attempts=4 (est cost 0.010000 charged once, actual 0.003000), 3 tasks COMPLETED, 3 artifacts. After the repeat recovery: byte-identical.
- Provider invocation log: Par One/Par Two once each (pid 68296); Par Three ordinal 0 (pid 68296, never finished) and ordinal 1 (pid 68309).
- Duplication checks in every test: one task row per task, one artifact row per file, one reservation row per key, `active_reservations_count == 0`, `total_agent_attempts` equals the number of attempts.

## 3. Verification
- Backend: **834 passed** (796 before; +38). `ruff check` and `ruff format --check` clean (136 files). Alembic head `b7c1d2e3f4a5`; downgrade/upgrade round trip verified.
- Frontend: unaffected (no frontend, dependency or infrastructure change); not re-run.
- Mutation testing of 13 guards: 12 killed. First round had 4 survivors; 3 were real test gaps (retry-loop numbering, adoption of a failed attempt, initial checkpoint) and were closed with new tests then re-killed; **M8** (status pre-check in `resume_pipeline`) is a redundant layer, because the atomic claim already refuses non-waiting executions, and is kept as defense in depth. M13 (heartbeat cancellation) is killed by the stale-worker test.
- Test processes and databases were cleaned up (no `astrava_m15%` database remains).

## 4. Independent review (Agy, Gemini Flash)
- Design review: F1-F13 confirmed; adopted: resume must claim the lease; background heartbeat; checkpointing remediation/replan. Dispatch-time attempt cap check already existed.
- Implementation review: **ACCEPT WITH FIXES**, no Critical/High. M-01 (claim before semaphore) fixed by taking the semaphore first in `start_pipeline` and `recover_execution`; M-03 (RUNNING-without-owner window) fixed by claiming PENDING->RUNNING atomically; M-02 (rollback on a cancelled session) fixed by a guarded rollback; L-01 (resume endpoint could skip an approval) fixed, only PAUSED may be resumed there; L-02 partly adopted (CLI no-op and not-found tests added; a real-provider CLI recovery is not driven in tests).

## 5. Semantics that remain at-least-once or lossy (not hidden)
1. A provider call whose result was not durably settled is **invoked again**. Its estimate is charged once; the real call is not exactly-once.
2. Planning, semantic verification and knowledge extraction are provider calls and may repeat.
3. Adopted output text is limited to the 4000 characters stored in reservation metadata.
4. Usage rows (`ModelExecution`) for adopted attempts are not recreated; budget consumption is correct.
5. Remediation/replan counters are committed before their checkpoint: a crash between them can over-count one turn (conservative, never under).
6. A stale agent process can still write files in the shared work directory until its heartbeat cancels it; file side effects are not fenced (closes only with containerised workers, M1.5-2+).
7. Heartbeat/lease timing assumes PostgreSQL time and an honest clock-independent TTL; a process frozen longer than the TTL is treated as dead.
8. `recover_execution` is explicit, not automatic at startup.

## 6. Remaining debt
M1.5-1b residuals unchanged and **not** resolved: worktree artifacts not retrievable through the artifact API; intermediate-directory TOCTOU; other repo-local git configuration; tracked-file-only dirty check. M1.5-1a residuals unchanged. SD-07 (M1.5-4). D1 blocked, D5 unverified. New: the `get_execution` pause/resume API can pause a running execution without stopping its runner (pre-existing; the runner overwrites the status on its next sync).
