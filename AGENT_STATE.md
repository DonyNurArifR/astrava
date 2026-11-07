# ASTRAVA Agent State (authoritative recovery snapshot)

**Owner:** Claude orchestrator (`astrava_orchestrator`). Agy writes only between the `AGY-CHECKPOINT` markers in section 13.
**Schema:** 1 · **Checkpoint:** CP-003 · **Written:** 2026-11-07 19:07 +0700 · **Recovery mission:** recovery-system bootstrap (docs only)
**Checkpoint commit:** `a55c73989f794be1e1e73ef9cbcc58da1bf7e5db` (`main`; a docs-only descendant of `02edb00462d9ef6a98a4eb168dedb253f924b29d`, the last commit that changed product code). **If `git rev-parse HEAD` differs, this file is STALE unless every commit since the checkpoint touches only recovery files (protocol section 6.3): run `AGENT_PROTOCOL.md` section 6 before acting.**

## 1. Git state (verified at CP-001)
- Branch: `main`. HEAD: `a55c739` "docs(recovery): checkpoint CP-002 ..." (docs only; before it `2fb864b` recovery docs). `origin/main` equals HEAD (pushed). Product code is unchanged since `02edb00` "feat(v1.5): m1.5-1a operator authentication and audit identity".
- Recent history: `a55c739` CP-002 · `2fb864b` recovery docs · `02edb00` M1.5-1a (17:33) · `3623d43` V1.5 planning docs (15:51) · `ed08f15` V1.4 freeze (15:01) · `45a295d` M1.4-7 · `37cd500` M1.4-6 (all 2026-11-07, +0700).
- Identity: repo-local `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`. `.claude/` is gitignored; `graphify-out/` is gitignored.

## 2. Current development milestone
- **V1.5 — Containerized Worker Sandboxing.** Accepted: **M1.5-1a** at implementation commit `02edb00462d9ef6a98a4eb168dedb253f924b29d` (operator acceptance; not reimplemented). Complete (documentation only): **reduced M1.5-0** decision record, `docs/V1_5_M1_5_0_DECISION_RECORD.md`, with Amendment A1 appended to `docs/V1_5_ROADMAP.md` and ADR-025.
- **Authorized next milestone: M1.5-1b only** (artifact ownership and project/execution/task validation, worktree target-branch correctness, canonical path containment, removal of the unsafe host-execution fallback, plus regression and adversarial tests). Starts after the M1.5-0 commit is verified.
- **Not authorized:** M1.5-1c (needs separate authorization after M1.5-1b is independently accepted), M1.5-2 and everything later. No Docker access for the API process, no credential injection, no API billing, no deployment.

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
- **M1.5-0 reduced decision record:** written and Agy-reviewed (all 14 required items and six preserved residual risks MET); commit pending in this checkpoint.
- **M1.5-1b:** authorized, **not started**. Next step is source inspection and a recorded spec (written into this file as CP-004 *before* any delegation).

## 5. Pending milestones
Source of truth: `docs/V1_5_ROADMAP.md` plus Amendment A1 and `docs/V1_5_M1_5_0_DECISION_RECORD.md` section 4. Do not start a milestone before its prerequisites are closed and the operator authorizes it.
| Milestone | Purpose | Status / prerequisites |
|---|---|---|
| M1.5-0 (reduced) | Docs-only decision record | **Done** when committed (no experiments performed) |
| M1.5-1a | Operator authentication and audit identity | **Accepted** (`02edb00`) |
| **M1.5-1b** | Artifact provenance/ownership, `merge_worktree` target fix, canonical path containment, remove fail-open worktree fallback, `repo_path` containment (SD-02, SD-06) | **Authorized** |
| M1.5-1c | Real `OrchestrationRunner` + persistent workflow recovery validation, retry-aware recovery, stale-worker behavior (SD-03, SD-04) | Needs **separate authorization** after 1b is accepted |
| M1.5-2 | `WorkerRuntime` (Docker initial target), pinned image, `worker_runs`, supervisor | Prerequisite 1a met; **not authorized**; introduces Docker access for the API process |
| M1.5-3 / 3b | Snapshot + hardened git import / controlled dependency preparation | After 2 (3 also needs 1b); not authorized |
| M1.5-4a | Credential strategy | **BLOCKED by D1** |
| M1.5-4 / 5 / 6 | Cutover to containerized agent execution / integration / acceptance | **Blocked through 4a (D1)** |

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
- **Open security debt (V1.5):** SD-02 artifact provenance/ownership (M1.5-1b); SD-03 runner and graph recovery tests, SD-04 retry-aware recovery closure evidence (M1.5-1c); SD-06 merge target ignored, `sanitize_path` prefix check, fail-open worktree fallback (M1.5-1b); SD-07 host-side execution of agent-written code and `RepoScanner` (M1.5-4). Closed: SD-01, SD-05, SD-08 (M1.5-1a).
- **Accepted residual risks (M1.5-1a, `docs/SECURITY.md` section 8):** in-memory session revocation; 404/405 reveal route existence; single shared operator key, no RBAC; docs routes open under DEBUG on loopback; worktree commit author hard-coded.
- **Observations on M1.5-1a (not defects against the operator's requirements, but roadmap-text items):** failed logins are rate-limited and logged (`logger.warning`, peer IP only) but not persisted as audit rows (a DB record would need a migration, or a dedicated security-event logger could be added without one); `is_authorized_verifier` is still always true for an authenticated caller (single-operator model, covered by a unit test with a constructed unauthorized context); per-request auth overhead was not measured.
- **Minor defects:** FastAPI app version string `1.3.0`; pre-existing oxlint warnings (14, in `IntelligencePage`, `GoalsPage`, `MemoryDetailModal`, `ConflictWorkbench`); during the login-screen session check the app may fire protected calls that 401 before the sign-in screen appears.
- **Stale documents (record only; fix needs operator approval unless listed in section 11):** `docs/V1_5_ROADMAP.md` line 3 still says "no implementation approved or started" (M1.5-1a is delivered); `docs/V1_5_TECHNICAL_RISKS.md` section 6 still lists SD-01/05/08 as OPEN (closed by M1.5-1a); `docs/PROGRESS.md` and `docs/ROADMAP.md` carry 191/20 test figures in older rows (historical).
- **Scratch material:** the M1.5-1a spec and executor prompts lived in the Claude scratchpad under `/private/tmp/...` and may be gone; their substance is in `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`.

## 10. Open operator decisions and constraints
- **D1 BLOCKED:** needs an approved provider authentication arrangement for workers. Anthropic Consumer Terms section 3.7 (operator-cited) restricts automated access; no OAuth-token minting, subscription-credential injection or OAuth proxy; subscription authentication is **not** claimed feasible. Blocks M1.5-4a and, through it, M1.5-4/5/6.
- **D5 UNVERIFIED:** no live model or availability check authorized; no billable API calls without separate authorization.
- **No unsafe mode** of any kind (DR-08); no host-execution fallback (DR-07).
- Authorization for M1.5-1c, M1.5-2 and later milestones is pending.
- Accepted M1.5-1a residual risks (kept open, not solved): in-memory session revocation; shared operator key; failed logins logged not stored as audit rows; `is_authorized_verifier` true for every authenticated operator; 404/405 route-existence disclosure; DEBUG docs-route exposure on loopback; TLS-proxy origin must be listed in `CORS_ORIGINS`; auth overhead not measured.

## 11. Uncommitted changes / commit history of recovery documents
- Committed: CP-001 recovery documents `2fb864b`; CP-002 `a55c739`.
- **Uncommitted at CP-003 (to be committed as the M1.5-0 docs-only commit, operator-authorized):** new `docs/V1_5_M1_5_0_DECISION_RECORD.md`; edited `docs/V1_5_ROADMAP.md` (appended Amendment A1 only; verified 11 added, 0 deleted lines), `docs/DECISIONS.md` (ADR-025), `docs/AUTONOMOUS_EXECUTION_STATE.md`, `docs/ROADMAP.md`, `AGENT_STATE.md`, `EXECUTION_LOG.md`. No source, test, migration or dependency file. After the commit anything `git status` shows is new work.

## 12. Next actions (exact)
- **Claude orchestrator:** (1) commit and push the M1.5-0 documentation (stage the listed files by name, verify HEAD = origin); (2) inspect the real source for M1.5-1b (artifact service/API, worktree manager, runner setup path, workflow_graph work-dir fallbacks, projects API/service) and write the spec into this file (CP-004) **before** delegating; (3) have Agy design-review the spec (read-only); (4) delegate bounded tasks to `astrava_executor` (Haiku 5.5), review every diff, run all checks, adversarial probes and mutation tests myself; (5) request Agy's independent review of the final diff, remediate, update the acceptance docs, commit and push M1.5-1b only; (6) stop and request authorization for M1.5-1c.
- **Agy:** idle in prompt mode (each permission is approved individually by the orchestrator). Design review of the M1.5-1b spec when asked, then independent review of the implementation. Read-only unless an assignment names files.
- **Executor (`astrava_executor`):** idle; no task until the orchestrator records and assigns one.
- **Operator:** review the M1.5-1b result when reported; decide authorization for M1.5-1c; D1 direction.

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
