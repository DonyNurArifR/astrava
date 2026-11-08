# M1.5-2a — Acceptance report (Worker broker contract, fake runtime, recovery integration)

Base `5cfdea5`. Spec: `V1_5_M1_5_2A_SPEC.md`. **No Docker, container, image, SDK, credential or network/host change exists in 2a.** 2b and 2c are not started.

## 1. Quality gates (operator list F1-F10)
| # | Gate | Result | Evidence |
|---|---|---|---|
| 1 | Independent security review | **ACCEPT WITH CHANGES** (Agy, Gemini Flash; no Critical/High/Medium; L-01 state dir mode, L-02 Unicode look-alikes in manifest paths), both fixed and tested. All five operator gates marked VERIFIED | Review file in the orchestrator scratchpad; `test_preexisting_state_dir_is_tightened_to_0700`, 5 added hostile manifest paths |
| 2 | API cannot access Docker directly | Met | `test_m1_5_2a_static_guards.py` (AST/text scans over `app/` and `astrava_broker/`: no container-client import, no socket/CLI reference, no container-CLI spawn, API may import only `contract`/`profiles`, broker never imports `app` or DB drivers, broker spawns no processes and uses no `eval/exec`) |
| 3 | Contract rejects arbitrary container configuration | Met | 142 contract tests: 30 smuggling keys x (arguments, envelope), enumerated aliases/profiles, kind/profile/alias coherence, bounds, strict ints, SHA-only `base_ref`, MAC/replay/timestamp; closed set of nine operations |
| 4 | Runtime interface replaceable | Met | Same 8-test conformance suite passes against `FakeWorkerRuntime` and `BrokerWorkerRuntime`; `WorkerRunService` suite runs against both; the orchestrator depends only on `WorkerRuntime` |
| 5 | Lease, fencing, recovery correct | Met | Order test observes workers already `cleaned` at the instant `expire_orphaned_reservations` runs; fail-closed tests (broker down, misconfigured, cleanup failure); M1.5-1c suites unchanged and green |
| 6 | Process-level crash tests, idempotent recovery | Met | `tests/recovery/test_j_workers.py` (4 scenarios, real broker process, real runner, SIGKILL/SIGSTOP/SIGCONT, throw-away PostgreSQL) |
| 7 | Tests, lint, types, migration | Met | Backend **1075 passed** (834 before; +241), 0 skipped/xfail; `ruff check` and `ruff format --check` clean (162 files); `mypy` (ephemeral `uv tool run`, not added to the project) clean on the new modules (the 15 pre-existing mypy findings in `runner.py` are unchanged); `alembic check` shows no drift; upgrade/downgrade/upgrade verified |
| 8 | No regressions / unexplained skips | Met | Full suite run twice; no skips |
| 9 | Docs | Met | Spec, this report, SECURITY.md section 12, roadmap Amendment A4, reassessment section 18, broker README, AGENT_STATE (CP-009), EXECUTION_LOG |
| 10 | Commit/push only verified work | Pending operator acceptance |

## 2. Process-level scenarios (J1-J4)
- **J1** API runner SIGKILLed with two workers RUNNING and one ACTIVE reservation: recovery reaps both workers (broker `cleaned`, rows `cleaned`), then expires the reservation, completes the execution at epoch 2; a second recovery is a no-op (no broker calls, rows unchanged).
- **J2** Runner and broker both SIGKILLed: recovery fails closed (`WorkerReconcileError`, `recovery_blocked`, reservation still ACTIVE, no provider call, lease released); after the broker restarts from its persisted state the same recovery succeeds.
- **J3** Runner SIGSTOPped (frozen, not dead), recovered by another process, then SIGCONTed: the stale runner exits with `StaleWorkerError`; a stale-epoch probe is refused by the PostgreSQL fence and by the broker fence; nothing changes.
- **J4** Three workers: exactly three terminate and three cleanup calls, all rows `cleaned`.

## 3. Mutation testing (40 mutants over contract, service, state, config, server, client, bookkeeping, runner)
First run: 33 killed, survivors M16 (redundant layer: authorize epoch check shadowed by the broker high-water mark), M27 (streamed body cap shadowed by Content-Length check), M29 (`_advance` fence shadowed by callers), M33 (explicit terminate shadowed by the reaper), **M38 (reconcile-after-expiry; genuine ordering gap)**, M40 (misconfiguration swallowed), M17 (invalid pattern). New tests: epoch-table-wiped defense in depth, chunked oversize body, `_advance` own fence, explicit-terminate assertion, an ordering spy at the moment of expiry, misconfigured runtime without rows. Re-run: **all 7 killed; 0 survivors**. Two real defects were found by tests along the way and fixed: the SQLite ledger kept a write lock after a replayed nonce (rollback missing) and uvicorn re-chmodded the Unix socket to 0666 (the broker now binds the socket itself, 0600).

## 4. Limitations (unchanged or new, stated plainly)
- Fake backend only: no isolation exists; timing, kill latency, cleanup failure and disk behaviour are untested until 2b. Host agent execution is unchanged.
- Tier A is development only and not a boundary against same-user code; tier B is not implemented. Host settings (Docker file sharing, PostgreSQL binding) untouched; proposals reported separately.
- Open and unresolved: worktree artifact retrieval limitation, intermediate-directory TOCTOU, other repo-local Git configuration, tracked-files-only dirty check, host-side repository parsing, D1 (blocked), D5 (unverified), SD-07, M1.5-1c at-least-once provider invocation and its residuals.
- Workers are not yet created by graph dispatch; 2a delivers the control plane and recovery contract they will use (the process tests drive it through the real service under the real epoch).
