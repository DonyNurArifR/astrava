# ASTRAVA Autonomous Execution State

## Baseline & Execution Context
- **Current Accepted Baseline:** `V1.4 Complete & Frozen`
- **Current Milestone:** M1.4-8 — Final V1.4 End-to-End Acceptance & Delivery Freeze (COMPLETED)
- **Current Phase:** V1.4 Fully Delivered & Baseline Frozen
- **Required Model:** `claude-haiku-5-5` (confirmed as the code default in `models/task.py`, `schemas/task.py`, `semantic_evaluator.py`, `agent_service.py`; live API availability was not re-checked during V1.5 planning)
- **Active Branch:** `main`
- **Alembic Head:** `6db676dd20fd`
- **Latest Verified Commit:** `ed08f15` (M1.4-8, authored by the operator identity; confirmed as HEAD of `main` with a clean working tree before V1.5 planning began; test results below are as recorded at M1.4-8 and were not re-run during V1.5 planning)
- **Current Blockers:** None for V1.4 as delivered. **Carried V1.4 security debt SD-01..SD-08 is open** and gates V1.5 (see `docs/V1_5_TECHNICAL_RISKS.md` section 6): 16 of 33 mutating API routes unauthenticated; artifact provenance/ownership not validated; full runner/LangGraph recovery untested; merge-target, path-prefix and fail-open worktree defects; host-side execution of agent-written code.

## Milestone Status Overview
- **Completed Milestones:** M0, M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, V1.1, V1.2, V1.2.1, V1.3, V1.4-M1, V1.4-M2, V1.4-M2.2, V1.4-M2.2.2, V1.4-M2.2.3, V1.4-M3, V1.4-M4, V1.4-M5, V1.4-M6, V1.4-M7, V1.4-M8 (ALL COMPLETED, VERIFIED & FROZEN)
- **Active Milestone:** None — All V1.4 milestones completed and accepted.
- **Next Milestone:** V1.5 Containerized Worker Sandboxing — PLANNING ONLY. Operator approved the direction; planning docs `docs/V1_5_*.md` drafted; implementation NOT approved or started. See `docs/V1_5_ROADMAP.md`.

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
- Implementation status: **NOT APPROVED / NOT STARTED.**

## Release Verdict
**ASTRAVA V1.4 ACCEPTED & VERIFIED — BASELINE FROZEN.**
