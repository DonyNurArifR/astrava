# ASTRAVA Autonomous Execution State

## Baseline & Execution Context
- **Current Accepted Baseline:** `V1.4 Complete & Frozen` plus V1.5 milestone M1.5-1a (operator authentication and audit identity) delivered in commit `02edb00`
- **Current Milestone:** V1.5 M1.5-1a accepted (`02edb00`); reduced M1.5-0 complete (`a4c1d1e`); **M1.5-1b (artifact ownership, canonical path containment, merge target, fail-closed execution setup) implemented, independently reviewed and accepted** (see `docs/V1_5_M1_5_1B_ACCEPTANCE_REPORT.md`; closes SD-02 and SD-06). **M1.5-1c needs separate operator authorization;** M1.5-2 onward is not approved.
- **Current Phase:** V1.4 delivered and frozen; V1.5 containerized-worker-sandboxing programme in progress (planning committed, M1.5-1a delivered, remaining milestones awaiting operator approval)
- **Required Model:** `claude-haiku-5-5` (confirmed as the code default in `models/task.py`, `schemas/task.py`, `semantic_evaluator.py`, `agent_service.py`; live API availability was not re-checked during V1.5 planning)
- **Active Branch:** `main`
- **Alembic Head:** `6db676dd20fd`
- **Latest Verified Commit:** `02edb00` (M1.5-1a). Previous: `3623d43` (V1.5 planning), `ed08f15` (V1.4 freeze). The authoritative live commit is recorded in `AGENT_STATE.md`.
- **Current Blockers:** None for V1.4 as delivered. **M1.5-1a (operator authentication and audit identity) is COMPLETE and verified: SD-01, SD-05 and SD-08 are CLOSED** (see `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`). **Remaining carried V1.4 security debt (SD-03, SD-04, SD-07) is open; SD-02 and SD-06 were closed by M1.5-1b** and gates V1.5 (see `docs/V1_5_M1_5_0_DECISION_RECORD.md` section 4): full runner/LangGraph recovery untested (M1.5-1c); host-side execution of agent-written code until the M1.5-4 cutover.

## Milestone Status Overview
- **Completed Milestones:** M0, M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, V1.1, V1.2, V1.2.1, V1.3, V1.4-M1, V1.4-M2, V1.4-M2.2, V1.4-M2.2.2, V1.4-M2.2.3, V1.4-M3, V1.4-M4, V1.4-M5, V1.4-M6, V1.4-M7, V1.4-M8 (ALL COMPLETED, VERIFIED & FROZEN)
- **Active Milestone:** None — all V1.4 milestones and V1.5 M1.5-1a are complete; the next milestone needs explicit operator approval.
- **Next Milestone:** V1.5 remaining milestones per `docs/V1_5_ROADMAP.md` (M1.5-0, M1.5-1b, M1.5-1c, M1.5-2 ...). **None is approved or started.** Live recovery state: `AGENT_STATE.md` at the repository root.

## Delivered Capabilities in V1.4 (M1.4-1 through M1.4-8)
- [x] M1.4-1: Operator identity context, verifier authorization with 403 impersonation prevention, SHA-256 memory fingerprinting, partial unique index, savepoints.
- [x] M1.4-2: Centralized `BudgetGovernor`, atomic two-phase reservations (`SELECT ... FOR UPDATE`), hold lease tracking, 6-dimension bounding.
- [x] M1.4-2.2 / M1.4-2.2.2 / M1.4-2.2.3: Verifier-authorized budget increases, dynamic reservations, mandatory fencing tokens, operator mutation auth, multi-process crash proof.
- [x] M1.4-3: Two-tier verification (Tier 1 bounded diagnostics $\le 2500$ chars, Tier 2 Claude Haiku 5.5 `SemanticEvaluator`), closed-loop `remediation_node`, 3-cycle cap, `remediation_history_json`.
- [x] M1.4-4: Adaptive goal planning (`GoalDecomposer`), Kahn's algorithm topological DAG validation, `DAGModifier` with immutable completed tasks invariant, `replan_node`, 2-replan ceiling, `project_goals` table.
- [x] M1.4-5: Structural repo scanner (`RepoScanner`), ephemeral Git worktree sandboxing (`GitWorktreeManager`), diff inspection, operator merge, zero working tree contamination.
- [x] M1.4-6: Formal task capability schema (`required_capabilities`), heuristic `CapabilityMatcher`, `AgentMetricsService` performance aggregation, REST observability endpoints, UI KPI cards.
- [x] M1.4-7: Strategic Goals dashboard (`GoalsPage.tsx`), `/goals` route, worktree sandboxing card with interactive git diff viewer, operator merge trigger, expanded Vitest suite.
- [x] M1.4-8: Full autonomous mission lifecycle verification, budget exhaust ceiling proof, multiprocess lease reclamation proof, concurrent deduplication proof, comprehensive regression and delivery freeze.

## Verification Evidence
*Current (re-run at checkpoint CP-001, HEAD `02edb00`):* backend **522 passed**, frontend **50 passed** (13 files), ruff clean, Alembic head `6db676dd20fd`.
*V1.4 freeze record (historical):*
- Backend Pytest: **191/191 passing** in 33.09s (100% pass rate).
- Frontend Vitest: **20/20 passing** across 10 test files in 1.32s (100% pass rate).
- Frontend Production Build: Clean build in 206ms (`tsc -b && vite build`).
- Code Hygiene: Ruff check & format 100% clean across all 110 backend Python files.
- Alembic Migration Head: `6db676dd20fd` (clean, verified against PostgreSQL 16).

## V1.5 Planning Decisions (recorded, not implemented)
- D1 credentials: investigated, mechanism NOT verified; no paid API credential; potential blocker (see `V1_5_TARGET_ARCHITECTURE.md` section 11).
- D2 runtime: Docker Desktop 29.8.0 verified operational; no other runtime installed; `WorkerRuntime` abstraction preserved.
- D3 dependencies: pinned baseline image; no package-index access for task workers; controlled prepare job.
- D4 fail-closed: isolation mandatory; no host fallback; no unsafe flag in the production path.
- D5 model: live check withheld pending proof it cannot incur API/overage charges.
- D6 auth: mandatory operator key on non-loopback; central enforcement; server-derived audit identity; key never in frontend JavaScript.
- Implementation status: **M1.5-1a COMPLETE (operator auth, CSRF, server-derived audit identity, secure defaults; 522 backend / 50 frontend tests passing).** M1.5-1b, M1.5-1c, M1.5-2 and later: **NOT APPROVED / NOT STARTED.**
- D1 credentials: Anthropic Consumer Terms section 3.7 restricts automated/non-human access except through an API key or where explicitly permitted; no `CLAUDE_CODE_OAUTH_TOKEN` minting, subscription credential injection or OAuth proxy will be built. Open architectural decision, separate from M1.5-1a.

## M1.5-0 Reduced Decision Record (documentation only)
See `docs/V1_5_M1_5_0_DECISION_RECORD.md`. Docker Desktop operational and the initial `WorkerRuntime` target; pinned images; controlled dependency preparation; no package-index access from task workers; mandatory fail-closed, no host fallback, **no unsafe mode**; no Docker socket, host HOME or credential mounts in workers; subscription OAuth injection prohibited; no billable API calls without separate authorization. **D1 blocked, D5 unverified.** M1.5-1a residual risks preserved (in-memory session revocation, shared operator key, failed logins logged not stored as audit rows, `is_authorized_verifier` always true for an authenticated operator, 404/405 route disclosure, DEBUG docs routes on loopback). Because D1 is blocked, M1.5-4a and through it M1.5-4/5/6 are blocked.

## Release Verdict
**ASTRAVA V1.4 ACCEPTED & VERIFIED — BASELINE FROZEN.**
