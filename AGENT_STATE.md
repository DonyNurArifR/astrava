# ASTRAVA Agent State (authoritative recovery snapshot)

**Owner:** Claude orchestrator (`astrava_orchestrator`). Agy writes only between the `AGY-CHECKPOINT` markers in section 13.
**Schema:** 1 · **Checkpoint:** CP-001 · **Written:** 2026-11-07 17:49 +0700 (final CP-001 after Agy review) · **Recovery mission:** recovery-system bootstrap (docs only)
**Checkpoint commit:** `02edb00462d9ef6a98a4eb168dedb253f924b29d` (`main`). **If `git rev-parse HEAD` differs, this file is STALE unless every commit since the checkpoint touches only recovery files (protocol section 6.3): run `AGENT_PROTOCOL.md` section 6 before acting.**

## 1. Git state (verified at CP-001)
- Branch: `main`. HEAD: `02edb00` "feat(v1.5): m1.5-1a operator authentication and audit identity". `origin/main` equals HEAD at the time of writing (pushed).
- Recent history: `02edb00` M1.5-1a (17:33) · `3623d43` V1.5 planning docs (15:51) · `ed08f15` V1.4 freeze (15:01) · `45a295d` M1.4-7 · `37cd500` M1.4-6 (all 2026-11-07, +0700).
- Identity: repo-local `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`. `.claude/` is gitignored; `graphify-out/` is gitignored.

## 2. Current development milestone
- **V1.5 — Containerized Worker Sandboxing.** Direction approved by the operator. **M1.5-1a (operator authentication and audit identity) is COMPLETE, verified and pushed.**
- **No further implementation milestone is approved or started.** The operator must explicitly approve the next one. This recovery mission is documentation-only and implements no product feature.

## 3. Completed features and verified behavior
| Area | Delivered | Evidence |
|---|---|---|
| M0-M10, V1.1-V1.3 | Platform foundation, multi-agent DAG, persistent project intelligence | `docs/ROADMAP.md`, release reports |
| V1.4 (M1-M8) | Security/concurrency hardening, budget governor with fencing tokens, semantic evaluator and remediation loop, adaptive planner, git-worktree sandbox (host-side), capability matching, goals UI, acceptance freeze | `docs/V1_4_FINAL_ACCEPTANCE_REPORT.md`, commit `ed08f15` |
| V1.5 planning | Assessment, target architecture, threat model, roadmap, risk register, D1-D6 decisions | `docs/V1_5_*.md`, commit `3623d43` |
| **V1.5 M1.5-1a** | Default-deny auth on all 74 routes (6 explicit public), mandatory 32+ char key for non-loopback with fail-closed startup, HttpOnly SameSite=Strict signed session cookie, CSRF, Host/Origin/forwarded-header guards, server-derived audit identity, secure defaults (`APP_HOST=127.0.0.1`, `DEBUG=false`), login UI | `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`, `docs/SECURITY.md`, commit `02edb00` |

**Re-verified by the orchestrator at CP-001 (2026-11-07 ~17:45, HEAD `02edb00`):** backend `pytest` 522 passed; `ruff check` clean; frontend `vitest` 50 passed (13 files); `alembic current` = `6db676dd20fd (head)`. Not re-run at CP-001: ruff format check, oxlint, `npm run build` (last verified at commit time: 118 files formatted, oxlint 0 errors and 14 warnings identical to the pre-M1.5-1a baseline, clean build).

## 4. In-progress implementation
- **None.** No product code is in flight. Only recovery documentation is being established (uncommitted, section 11).

## 5. Pending milestones (all awaiting operator approval; none started)
Source of truth: `docs/V1_5_ROADMAP.md` (gate matrix). Do not start a milestone before its prerequisites are closed.
| Milestone | Purpose | Prerequisites |
|---|---|---|
| M1.5-0 | Decision record and operator-gated experiments (D1 credential mechanism, D5 model availability) | Operator action; D1 is **blocked** by the Anthropic Consumer Terms section 3.7 restriction (see section 10) |
| M1.5-1b | Artifact provenance/ownership, `merge_worktree` target fix, `sanitize_path` fix, fail-closed worktree setup, `repo_path` allowlist (SD-02, SD-06) | M1.5-0 (per roadmap) |
| M1.5-1c | Full `OrchestrationRunner` and compiled-graph recovery characterization tests (SD-03, SD-04) | M1.5-0 |
| M1.5-2 | `WorkerRuntime`, pinned worker image, `worker_runs` migration, supervisor | M1.5-1a (done) |
| M1.5-3 / 3b / 4a | Snapshot + hardened git import / controlled dependency provisioning / egress + credential strategy | 2 (3 also needs 1a, 1b); 4a also needs D1 outcome |
| M1.5-4 | Atomic cutover to containerized agent and verification (removes host execution) | 1a, 1b, 1c, 3, 4a |
| M1.5-5 | Orchestrator integration, leases, recovery, UI | 4, 3b |
| M1.5-6 | Adversarial acceptance and freeze | 5 |

## 6. Responsibilities
- **Claude orchestrator** (`astrava_orchestrator`): execution, integration, testing, delivery, git (with approval), authoritative `AGENT_STATE.md`, reconciliation and verification of all delegated work.
- **Agy / Antigravity** (`astrava_planner`): planning, architecture research, independent review; reports directly to Claude through Herdr; writes only what an assignment names.
- **Claude Code executor** (`astrava_executor`, Haiku 5.5 on the Claude Pro subscription): bounded implementation tasks only; no git; no new dependencies; no model switching.
- **Operator:** approvals for milestones, commits, pushes, credentials, spend.

## 7. Agent status (Herdr, workspace w7; verified at CP-001)
| Name | Pane | Kind | Status | Session / conversation ID | Restore |
|---|---|---|---|---|---|
| `astrava_orchestrator` | `w7:p1` | claude (Sonnet 5.5) | working (this session) | `b5b5d691-dbb6-4a98-8b15-22da1dddb4c6` | `claude --resume <id>` or `claude --continue` |
| `astrava_planner` | `w7:p2` | agy (Antigravity CLI, Gemini Flash) | idle; edit mode reset to prompt mode at operator instruction (see EXECUTION_LOG) | `5e5b2338-3e68-494f-9c65-06861b3c074b` (store: `~/.gemini/antigravity-cli/conversations/<id>.db`) | `agy --conversation <id>` or `agy --continue` |
| `astrava_executor` | `w7:p6` | claude Code, `--model claude-haiku-5-5` | idle, holds context of tasks H1-H4 only | `a51fa219-9129-4eca-ad09-ea0b2432aa6e` | start fresh and re-send the recorded task |
Other panes in the Herdr session belong to a different project (`zenar_*`); do not touch them. A first executor pane (`w7:p5`) vanished mid-session for an unknown reason and was recreated.
**Agy context:** in its live session Agy reports it remembers this thread; in any fresh invocation it has no memory beyond files. Treat Agy as stateless unless it explicitly confirms recovery.
**Standing approval policy** (operator, this conversation): Claude may approve Agy's read-only permission prompts and its writes to files the assignment names. See `AGENT_PROTOCOL.md` section 5.

## 8. Subsystem status
- **API / backend:** FastAPI app (`backend/app/main.py`, title string still reports version `1.3.0`, cosmetic defect). 74 routes; all authenticated except six explicit public routes. Auth core in `app/core/{auth,guard,session,security_config}.py`; supported entrypoint `uv run python -m app.serve`. Concurrency: `MAX_CONCURRENT_EXECUTIONS=1` (in-process semaphore).
- **Database:** PostgreSQL 16 (`astrava-postgres`, port 5433, healthy), Alembic head `6db676dd20fd`, no migration added by V1.5 so far. A second unrelated container `bl-pg` shares Docker.
- **Retrieval:** modular knowledge-retrieval engine (`backend/app/services/retrieval/`) using PostgreSQL full-text search, multi-signal ranking and a bounded context assembler (budget about 4000 characters); persistent project memory with provenance, lineage and conflict governance (V1.3).
- **Orchestration:** LangGraph workflow (`backend/app/orchestrator/workflow_graph.py`): `retrieve_knowledge → plan → approval_check → dispatch_task → verify → {remediation | replan} → artifact → ingest_knowledge → complete`. Budget governance via `BudgetGovernor` (reservations, `fence_token`, lease expiry). Recovery is DB-based; there is **no LangGraph checkpointer** and the runner/graph resume path is not fully tested (SD-03). Git-worktree sandboxing is host-side.
- **Evaluation:** `VerificationEngine` tier 1 (deterministic py_compile/pytest/JSON checks, bounded diagnostics) and tier 2 `SemanticEvaluator` (`claude-haiku-5-5`), 3-cycle remediation cap, 2-replan ceiling. Verification currently runs agent-written code **on the host** (SD-07, closes at M1.5-4).
- **Frontend:** React 19 + Vite + Tailwind; login/session gate active only when the server requires it; Vite dev proxy to `localhost:8000`.
- **Model / auth:** product model `claude-haiku-5-5`; the CLI uses the operator's Claude Pro login. Availability of the model for this account has **not** been live-checked (no billable or quota calls permitted without approval).

## 9. Test results and known defects
- Tests at CP-001: backend 522 passed, frontend 50 passed, ruff clean (see section 3 for what was re-run).
- **Open security debt (V1.5):** SD-02 artifact provenance/ownership (M1.5-1b); SD-03 runner and graph recovery tests, SD-04 retry-aware recovery closure evidence (M1.5-1c); SD-06 merge target ignored, `sanitize_path` prefix check, fail-open worktree fallback (M1.5-1b); SD-07 host-side execution of agent-written code and `RepoScanner` (M1.5-4). Closed: SD-01, SD-05, SD-08 (M1.5-1a).
- **Accepted residual risks (M1.5-1a, `docs/SECURITY.md` section 8):** in-memory session revocation; 404/405 reveal route existence; single shared operator key, no RBAC; docs routes open under DEBUG on loopback; worktree commit author hard-coded.
- **Minor defects:** FastAPI app version string `1.3.0`; pre-existing oxlint warnings (14, in `IntelligencePage`, `GoalsPage`, `MemoryDetailModal`, `ConflictWorkbench`); during the login-screen session check the app may fire protected calls that 401 before the sign-in screen appears.
- **Stale documents (record only; fix needs operator approval unless listed in section 11):** `docs/V1_5_ROADMAP.md` line 3 still says "no implementation approved or started" (M1.5-1a is delivered); `docs/V1_5_TECHNICAL_RISKS.md` section 6 still lists SD-01/05/08 as OPEN (closed by M1.5-1a); `docs/PROGRESS.md` and `docs/ROADMAP.md` carry 191/20 test figures in older rows (historical).
- **Scratch material:** the M1.5-1a spec and executor prompts lived in the Claude scratchpad under `/private/tmp/...` and may be gone; their substance is in `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`.

## 10. Open operator decisions
- Which milestone is next (recommended: **M1.5-1b**, then **M1.5-1c**, both independent of D1).
- **D1:** credential mechanism for workers is unresolved and constrained by Anthropic Consumer Terms section 3.7 (automated access only via API key or explicit permission). No OAuth-token minting, subscription-credential injection or OAuth proxy will be built. Alternatives need explicit operator approval.
- **D5:** live model availability check withheld (cannot prove it avoids API/overage charges).
- Whether any further M1.5-1a hardening is wanted beyond the delivered scope.

## 11. Recovery documents (CP-001) — operator approved committing these eight files
**Status:** committed and pushed in the docs-only recovery commit that follows `02edb00` (its hash is in `EXECUTION_LOG.md`); the working tree is clean afterwards. Anything `git status` shows later is new work.
Purpose: establish the recovery system (documentation only). Author: Claude orchestrator unless noted.
- New: `AGENT_STATE.md`, `AGENT_PROTOCOL.md`, `EXECUTION_LOG.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` (repo root).
- Edited (stale-state reconciliation only, no behavior): `docs/AUTONOMOUS_EXECUTION_STATE.md` (milestone/commit/test fields), `docs/ROADMAP.md` (header status).
- Agy's contribution to this checkpoint is confined to section 13 and one appended `EXECUTION_LOG.md` entry. **Verified by diff against pre-delegation copies:** only the marker region and that single log entry changed; `AGENT_PROTOCOL.md` untouched.
- Reported by Agy but not verifiable by Claude: that `AGENTS.md` and `GEMINI.md` at the repo root are auto-loaded by the Antigravity CLI into its session rules. Both files exist, so the claim is harmless if false; the protocol does not depend on it (the orchestrator also points Agy at the protocol in every assignment).
No product source, test, migration or dependency file is modified. Verify with `git status --short`.

## 12. Next actions (exact)
- **Operator:** (a) decide whether any further M1.5-1a hardening is wanted (see section 9: failed-login attempts are logged, not written as audit rows); (b) approve the next milestone (M1.5-1b or M1.5-1c are dependency-ready); (c) decide D1 direction. Agy edit mode was reset from `accept-edits` to prompt mode on the operator's instruction (verified in the log).
- **Claude orchestrator:** (1) on approval, stage the section-11 files by name, review the staged diff, commit with a docs-only message, then push; (2) do **not** start any milestone until approved; (3) on approval of M1.5-1b, write the task spec into this file first, delegate bounded implementation to `astrava_executor`, request an Agy design review before and an independent review after, verify everything locally, then update this file; (4) fix the minor stale-doc items only if approved.
- **Agy:** (1) keep the section 13 Agy checkpoint current; (2) when asked, review the M1.5-1b scope and acceptance criteria against `docs/V1_5_ROADMAP.md` and the source (read-only); (3) investigate options for D1 that comply with the terms restriction and report them with evidence (no implementation).
- **Executor (`astrava_executor`):** idle. Do nothing until given a recorded, scoped task by the orchestrator.

## 13. Agy checkpoint (Agy-owned section; Claude does not edit between the markers)
<!-- AGY-CHECKPOINT:BEGIN -->
- **Status:** ACTIVE (Planning & Independent Review). Recovery bootstrap reviewed; first checkpoint written.
- **Recovered context (live session memory vs inferred):**
  - *Live session memory:* I actively recall the turns in this live thread: baseline review, drafting `V1_5_THREAT_MODEL.md` (235 lines) and `V1_5_TECHNICAL_RISKS.md` (159 lines), VirtioFS/tmpfs latency analysis, M1.5-1a design critique (host port parsing, 415 simple-request block), and M1.5-1a security review (ACCEPT WITH FIXES).
  - *Inferred from files:* All past project history prior to this conversation (M0–V1.4 delivery freeze at `ed08f15`, M1.5-1a commit `02edb00`, and earlier milestones) is derived 100% from repository files and git logs. In any fresh CLI invocation without conversation ID resumption, I have zero intrinsic memory.
- **In-progress review:**
  - Evaluated `AGENT_PROTOCOL.md` and `AGENT_STATE.md` (CP-001). Cross-references, section numbering, single-writer rules, and commit-SHA staleness checks are consistent and sound.
  - Confirmed: `AGENTS.md` and `GEMINI.md` at repo root are automatically discovered and loaded as active user rules by Antigravity CLI.
  - Minor gaps noted: `AGENT_STATE.md` line 62 has minor path abbreviation `orchestrator/workflow_graph.py`; section 11 lists uncommitted filenames but not diff hashes.
- **Evidence pointers:**
  - Git HEAD: `02edb00` (`main`). Working tree: docs-only uncommitted files (`git status -s`).
  - Auto-load proof: `AGENTS.md` and `GEMINI.md` loaded into Antigravity session `<user_rules>`.
  - Verified baseline: backend 522 passed, frontend 50 passed, Alembic head `6db676dd20fd`.
<!-- AGY-CHECKPOINT:END -->
