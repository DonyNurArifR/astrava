# ASTRAVA Agent State (authoritative recovery snapshot)

**Owner:** Claude orchestrator (`astrava_orchestrator`). Agy writes only between the `AGY-CHECKPOINT` markers in section 13.
**Schema:** 1 · **Checkpoint:** CP-007 · **Written:** 2026-11-07 +0700 · **Mission:** M1.5-1c
**Checkpoint commit (base):** `552165cd0320bf5d2e82626dd02001bf5ecd0bfb`. **Expected HEAD:** the single M1.5-1c milestone commit that follows it (subject `feat(v1.5): m1.5-1c ...`, contains this file). Verify with `git log --oneline 552165c..HEAD` (exactly that one commit, then a clean tree). Any other history means this file is STALE: run `AGENT_PROTOCOL.md` section 6.

## 1. Git state (CP-007)
- Branch: `main`. Base `552165c` (M1.5-1b). The M1.5-1c milestone commit is the next and only commit after it; `origin/main` equals HEAD after the push; tree clean.
- Product code last changed by that milestone commit (previous: `552165c`, M1.5-1b).
- Recent history: M1.5-1c · `552165c` M1.5-1b · `a4c1d1e` M1.5-0 · `a55c739` CP-002 · `2fb864b` recovery docs · `02edb00` M1.5-1a · `3623d43` V1.5 planning · `ed08f15` V1.4 freeze (2026-11-07, +0700).
- Identity: repo-local `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`; `.claude/` and `graphify-out/` are gitignored.

## 2. Current development milestone
- **V1.5 — Containerized Worker Sandboxing.** Accepted: **M1.5-1a** (`02edb00`), reduced **M1.5-0** (`a4c1d1e`), and **M1.5-1b** (this checkpoint's milestone commit; closes SD-02 and SD-06; 796 backend / 50 frontend tests).
- **M1.5-1c IMPLEMENTED and independently reviewed (Agy: ACCEPT WITH FIXES, fixes applied); awaiting commit approval/commit.** Report `docs/V1_5_M1_5_1C_ACCEPTANCE_REPORT.md`; 834 backend tests; SD-03/SD-04 closed; M1.5-2 not started. Previously: M1.5-1c authorization was pending (real `OrchestrationRunner` + persistent workflow recovery validation, retry-aware recovery, stale-worker behavior). **Not started.**
- **Not authorized:** M1.5-2 and everything later. No Docker access for the API process, no credential injection, no API billing, no deployment. D1 blocked, D5 unverified.

## 3. Completed features and verified behavior
| Area | Delivered | Evidence |
|---|---|---|
| M0-M10, V1.1-V1.3 | Platform foundation, multi-agent DAG, persistent project intelligence | `docs/ROADMAP.md`, release reports |
| V1.4 (M1-M8) | Security/concurrency hardening, budget governor with fencing tokens, semantic evaluator and remediation loop, adaptive planner, git-worktree sandbox (host-side), capability matching, goals UI, acceptance freeze | `docs/V1_4_FINAL_ACCEPTANCE_REPORT.md`, commit `ed08f15` |
| V1.5 planning | Assessment, target architecture, threat model, roadmap, risk register, D1-D6 decisions | `docs/V1_5_*.md`, commit `3623d43` |
| **V1.5 M1.5-1a** | Default-deny auth on all 74 routes (6 explicit public), mandatory 32+ char key for non-loopback with fail-closed startup, HttpOnly SameSite=Strict signed session cookie, CSRF, Host/Origin/forwarded-header guards, server-derived audit identity, secure defaults (`APP_HOST=127.0.0.1`, `DEBUG=false`), login UI | `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`, `docs/SECURITY.md`, commit `02edb00` |

**Re-verified by the orchestrator at CP-002 (2026-11-07, HEAD `2fb864b`, product code = `02edb00`):** backend `pytest` 522 passed; `ruff check` clean; `ruff format --check` 118 files formatted; frontend `vitest` 50 passed (13 files); `oxlint` 0 errors / 14 warnings (same as the pre-M1.5-1a baseline); `tsc -b && vite build` clean; `alembic current` = `6db676dd20fd (head)`. Frontend source and bundle contain no operator-key reference (`localStorage` is used only for the theme preference).
**M1.5-1a conformance re-check (operator request to "resume M1.5-1a"):** M1.5-1a was already implemented and pushed; the operator's premise that it was not implemented was reconciled by re-verification, not re-implementation. Agy independently checked the committed code against all eleven requirements (R1-R11) and ten security controls (S1-S10): all MET. Claude spot-checked its citations: conclusions confirmed, several line numbers approximate.

## 4. In-progress implementation
- **None.** M1.5-1b is implemented, independently reviewed (Agy: ACCEPT WITH FIXES, then ACCEPT after remediation) and committed. Report: `docs/V1_5_M1_5_1B_ACCEPTANCE_REPORT.md`; spec: `docs/V1_5_M1_5_1B_SPEC.md`.
- Executor tasks B1-B5 all completed and verified by the orchestrator; no delegation is in flight.

## 5. Pending milestones
Source of truth: `docs/V1_5_ROADMAP.md` + Amendment A1 + `docs/V1_5_M1_5_0_DECISION_RECORD.md` section 4. Nothing starts without operator authorization.
| Milestone | Purpose | Status / prerequisites |
|---|---|---|
| M1.5-0 (reduced), M1.5-1a, **M1.5-1b** | Decision record / operator auth / containment + ownership + fail-closed setup | **Accepted** |
| **M1.5-1c** | Execution lease/epoch recovery, retry-aware attempts (SD-03, SD-04) | **Implemented and reviewed; commit pending approval/just committed** (see `docs/V1_5_M1_5_1C_ACCEPTANCE_REPORT.md`) |
| M1.5-2 | `WorkerRuntime` (Docker initial target), pinned image, `worker_runs`, supervisor | Prerequisite 1a met; **not authorized**; gives the API process Docker access |
| M1.5-3 / 3b | Snapshot + hardened git import / controlled dependency preparation | After 2 (3 also needs 1b, now met); not authorized |
| M1.5-4a | Credential strategy | **BLOCKED by D1** |
| M1.5-4 / 5 / 6 | Cutover / integration / acceptance | **Blocked through 4a (D1)** |

## 6. Responsibilities
- **Claude orchestrator** (`astrava_orchestrator`): execution, integration, testing, delivery, git (with approval), authoritative `AGENT_STATE.md`, reconciliation and verification of all delegated work.
- **Agy / Antigravity** (`astrava_planner`): planning, architecture research, independent review; reports directly to Claude through Herdr; writes only what an assignment names.
- **Claude Code executor** (`astrava_executor`, Haiku 5.5 on the Claude Pro subscription): bounded implementation tasks only; no git; no new dependencies; no model switching.
- **Operator:** approvals for milestones, commits, pushes, credentials, spend.

## 7. Agent status (Herdr, workspace w7; verified at CP-001)
| Name | Pane | Kind | Status | Session / conversation ID | Restore |
|---|---|---|---|---|---|
| `astrava_orchestrator` | `w7:p1` | claude (Sonnet 5.5) | working (this session) | `b5b5d691-dbb6-4a98-8b15-22da1dddb4c6` | `claude --resume <id>` or `claude --continue` |
| `astrava_planner` | `w7:p2` | agy (Antigravity CLI, Gemini Flash) | idle; **prompt mode verified** (footer shows no mode label; a probe request produced an "Allow creation of this file?" dialog, was denied, and no file was created) | `5e5b2338-3e68-494f-9c65-06861b3c074b` (store: `~/.gemini/antigravity-cli/conversations/<id>.db`) | `agy --conversation <id>` or `agy --continue` |
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
- **Open security debt (V1.5):** SD-07 host-side execution of agent-written code and `RepoScanner` (M1.5-4). **Closed:** SD-01, SD-05, SD-08 (1a); SD-02, SD-06 (1b); SD-03, SD-04 (1c). **Tracked debt:** M1.5-1b residuals (worktree artifacts not retrievable, intermediate-directory TOCTOU, repo-local git config, tracked-only dirty check) and 1c residuals (at-least-once provider invocation after crash, unfenced stale-agent file side effects; see 1c report section 5).
- **Accepted residual risks (M1.5-1a, `docs/SECURITY.md` section 8):** in-memory session revocation; 404/405 reveal route existence; single shared operator key, no RBAC; docs routes open under DEBUG on loopback; worktree commit author hard-coded.
- **Observations on M1.5-1a (not defects against the operator's requirements, but roadmap-text items):** failed logins are rate-limited and logged (`logger.warning`, peer IP only) but not persisted as audit rows (a DB record would need a migration, or a dedicated security-event logger could be added without one); `is_authorized_verifier` is still always true for an authenticated caller (single-operator model, covered by a unit test with a constructed unauthorized context); per-request auth overhead was not measured.
- **Minor defects:** FastAPI app version string `1.3.0`; pre-existing oxlint warnings (14, in `IntelligencePage`, `GoalsPage`, `MemoryDetailModal`, `ConflictWorkbench`); during the login-screen session check the app may fire protected calls that 401 before the sign-in screen appears.
- **Stale documents (record only; fix needs operator approval unless listed in section 11):** `docs/V1_5_ROADMAP.md` line 3 still says "no implementation approved or started" (M1.5-1a is delivered); `docs/V1_5_TECHNICAL_RISKS.md` section 6 still lists SD-01/05/08 as OPEN (closed by M1.5-1a); `docs/PROGRESS.md` and `docs/ROADMAP.md` carry 191/20 test figures in older rows (historical).
- **Scratch material:** the M1.5-1a spec and executor prompts lived in the Claude scratchpad under `/private/tmp/...` and may be gone; their substance is in `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`.

## 10. Open operator decisions and constraints
- **D1 BLOCKED:** needs an approved provider authentication arrangement for workers. Anthropic Consumer Terms section 3.7 (operator-cited) restricts automated access; no OAuth-token minting, subscription-credential injection or OAuth proxy; subscription authentication is **not** claimed feasible. Blocks M1.5-4a and, through it, M1.5-4/5/6.
- **D5 UNVERIFIED:** no live model or availability check authorized; no billable API calls without separate authorization.
- **No unsafe mode** of any kind (DR-08); no host-execution fallback (DR-07).
- Authorization for M1.5-2 and later milestones is pending; M1.5-1c needs only the commit.
- Accepted M1.5-1a residual risks (kept open, not solved): in-memory session revocation; shared operator key; failed logins logged not stored as audit rows; `is_authorized_verifier` true for every authenticated operator; 404/405 route-existence disclosure; DEBUG docs-route exposure on loopback; TLS-proxy origin must be listed in `CORS_ORIGINS`; auth overhead not measured.

## 11. Uncommitted changes / commit history of recovery documents
- Committed: CP-001 `2fb864b`, CP-002 `a55c739`, CP-003 with M1.5-0 `a4c1d1e`. CP-005 (this file and the log) ships inside the M1.5-1b milestone commit by operator authorization of that milestone. After the push the tree is clean; anything `git status` shows later is new work.

## 12. Next actions (exact)
- **Operator:** (a) review the M1.5-1c acceptance report; (b) decide whether to authorize **M1.5-2** (WorkerRuntime; gives the API process Docker access); D1 remains blocked, D5 unverified.
- **Claude orchestrator:** STOPPED after M1.5-1b acceptance. On M1.5-1c authorization: inspect the real runner/graph resume path first, write the spec into this file (CP-006) before delegating, have Agy design-review it, delegate bounded tasks to `astrava_executor`, verify everything locally, request Agy's independent review, then commit/push only after acceptance. Do not start M1.5-2.
- **Agy:** idle in prompt mode. On request: design-review the M1.5-1c spec, then independent review.
- **Executor (`astrava_executor`):** idle; no task until the orchestrator records and assigns one.

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
