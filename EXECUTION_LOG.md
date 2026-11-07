# ASTRAVA Agent Execution Log (append-only)

Recovery-oriented event log shared by all agents. **Append only, newest last.** Never edit or delete past entries; add a correcting entry instead. Format and rules: `AGENT_PROTOCOL.md` section 4. Current snapshot: `AGENT_STATE.md`.
Historical product-delivery log (M0 to V1.4 and the M1.5-1a summary): `docs/EXECUTION_LOG.md`. Entries below that precede the recovery system were **reconstructed** from git history and the delivery reports; their evidence is stated, and exact times are given only where git records them. Times are +0700 on 2026-11-07.

### [15:01] CLAUDE — COMMIT: V1.4 frozen (`ed08f15`)
- **Evidence:** `git log`; `docs/V1_4_FINAL_ACCEPTANCE_REPORT.md` (191 backend / 20 frontend tests at freeze).
- **Next:** operator requested V1.5 planning.

### [time not recorded, between 15:01 and 15:51] CLAUDE+AGY — PLAN: V1.5 containerized worker sandboxing planning
- Orchestrator audited source (provider, worktree manager, verification engine, auth, artifacts, compose). Findings: agent CLI and pytest run on the host with the real `$HOME`; worktree `.git` links into the host repo; `merge_worktree` ignores `target_branch`; `sanitize_path` prefix bug; 16 of 33 mutating routes unauthenticated.
- Agy drafted `V1_5_THREAT_MODEL.md` and `V1_5_TECHNICAL_RISKS.md`; orchestrator corrected wrong line citations and unsupported claims; Agy then reviewed the architecture and roadmap and found a host-mount vs stream contradiction, which was resolved.
- **Evidence:** `docs/V1_5_*.md` (committed). **Result:** accepted.

### [time not recorded] OPERATOR — DECISION: D1-D6 directives
- D2 Docker Desktop verified operational; D3 baseline image and controlled dependency provisioning; D4 fail-closed isolation; D6 mandatory operator key on non-loopback; D1 and D5 constrained (no paid credential, no unverified live model call).
- **Evidence:** `docs/V1_5_TARGET_ARCHITECTURE.md` section 11.

### [15:51] CLAUDE — COMMIT+PUSH: V1.5 planning docs (`3623d43`)
- Docs only (5 planning documents plus state doc reconciliation). **Evidence:** `git show --stat 3623d43`.

### [time not recorded, between 15:51 and 17:33] OPERATOR — DECISION: authorize M1.5-1a only
- Operator also noted Anthropic Consumer Terms section 3.7: no OAuth-token minting, no subscription-credential injection, no OAuth proxy, no live model check.

### [time not recorded] CLAUDE+AGY+EXECUTOR — DELEGATE/RESULT: M1.5-1a implementation
- Orchestrator wrote the spec; Agy design review found Host-with-port parsing, `client=None`, bounded rate limiter and docs-route issues, all folded into the spec.
- `astrava_executor` (Haiku 5.5, Claude Pro) executed bounded tasks H1 backend core, H2 backend tests, H3 frontend, H4 review fixes. First executor pane vanished once (`INTERRUPT`); recreated and the task re-sent.
- Orchestrator reviewed each diff, re-ran all checks itself, ran an independent adversarial probe, real-uvicorn smoke tests and six mutation tests (all caught). Agy's security review: ACCEPT WITH FIXES, five findings, all remediated.
- **Evidence:** `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`; 522 backend / 50 frontend tests; ruff clean; oxlint 0 errors (14 baseline warnings); clean build.

### [17:33] CLAUDE — COMMIT+PUSH: M1.5-1a delivered (`02edb00`)
- Closed SD-01, SD-05, SD-08. Added `.claude/` to `.gitignore`. Code-only `graphify update` run (docs semantic refresh pending, `graphify-out/` ignored).
- **Evidence:** `git show --stat 02edb00`; `origin/main` equals HEAD.

### [17:44] CLAUDE — AUDIT: recovery-system mission started (operator request)
- Scope: create `AGENT_STATE.md`, `AGENT_PROTOCOL.md`, `EXECUTION_LOG.md`, and agent instruction files; documentation only; no commit or push without approval.
- Orchestrator audit: branch `main`, HEAD `02edb00`, tree clean, in sync with `origin/main`; Alembic head `6db676dd20fd`; re-ran backend `pytest` (522 passed), `ruff check` (clean), frontend `vitest` (50 passed); Docker containers `astrava-postgres` (healthy) and `bl-pg` up. No `CLAUDE.md`, `AGENTS.md` or `GEMINI.md` existed in the repo (only the user-level `~/.claude/CLAUDE.md`).

### [17:50] AGY — RESULT: independent status review (read-only), received and read in pane
- Agy independently reported: HEAD `02edb00`, tree clean; V1.4 frozen, V1.5 planning committed, M1.5-1a delivered, all other V1.5 milestones planned only; correct prerequisite chain; no instruction files in the repo; recommended recording the checkpoint commit SHA and halting on mismatch, plus failure modes of the two-agent handover.
- Agy identified stale statements: `docs/AUTONOMOUS_EXECUTION_STATE.md` lines 5, 6, 10, 15, 16 (still V1.4-only, commit `ed08f15`, "None" active milestone), `docs/ROADMAP.md` lines 2-4 (Version 1.4), `docs/V1_5_ROADMAP.md` line 3 ("no implementation approved or started").
- **Orchestrator verification:** all three claims reproduced by reading the files. Agy's memory claim: it says it remembers this thread in the live session but would have none in a fresh invocation (unverified; treated as stateless).
- **Reconciliation:** Claude and Agy agree on repository status. `AUTONOMOUS_EXECUTION_STATE.md` and `ROADMAP.md` were corrected (state fields only). `V1_5_ROADMAP.md` line 3 and `V1_5_TECHNICAL_RISKS.md` section 6 are planning-baseline documents and were **not** edited; they are recorded as known-stale in `AGENT_STATE.md` section 9 pending operator approval.

### [17:55] CLAUDE — IMPLEMENT: recovery documents created (uncommitted)
- Created `AGENT_PROTOCOL.md`, `AGENT_STATE.md` (checkpoint CP-001), this file, and root `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` pointing to the protocol; reconciled stale fields in `docs/AUTONOMOUS_EXECUTION_STATE.md` and `docs/ROADMAP.md`.
- **Evidence:** `git status --short` (documentation files only). **Next:** Agy review of the protocol and first Agy checkpoint; operator approval to commit.

### [17:58] AGY — VALIDATE: recovery system review and initial checkpoint (CP-001)
- **Evidence:** Inspected `AGENT_PROTOCOL.md`, `AGENT_STATE.md`, `EXECUTION_LOG.md`, `AGENTS.md`, `GEMINI.md`, and git status (`HEAD 02edb00`, clean code, uncommitted recovery docs only). Traced Antigravity CLI rule discovery injecting `AGENTS.md` and `GEMINI.md` into `<user_rules>`.
- **Result:** Factual consistency, section numbering, and staleness detection logic verified. Written initial Agy checkpoint in `AGENT_STATE.md` section 13.
- **Next:** Operator review and approval to commit recovery documentation bootstrap.

### [17:49] CLAUDE — VALIDATE: Agy checkpoint verified and recovery bootstrap finalized
- **Evidence:** `diff` of `AGENT_STATE.md` and `EXECUTION_LOG.md` against copies saved before the Agy run: Agy changed only the `AGY-CHECKPOINT` region (original lines 97-100) and appended one entry; `AGENT_PROTOCOL.md` byte-identical (`cmp`). `git status --short` shows only the documented documentation files.
- **Agy review points:** cross-references and numbering consistent (confirmed by Claude); relative path `orchestrator/workflow_graph.py` corrected to `backend/app/orchestrator/workflow_graph.py`; atomic-write rule clarified for Agy's in-place marker edits; "no diff hash for uncommitted files" accepted as a limitation (the file list plus `git status --short` is the check). Agy's claim that its CLI auto-loads `AGENTS.md`/`GEMINI.md` is recorded as reported-by-Agy, not Claude-verified.
- **Agy recovered-context statement (its own words, recorded for the record):** it recalls this live session's turns but has no intrinsic memory of earlier history in a fresh invocation, which it treats as inferred from files. Claude therefore treats Agy as stateless unless it explicitly confirms recovery.
- **Result:** CP-001 final. Nothing committed or pushed. **Next:** operator reviews and approves committing the section-11 files; no milestone is started.

### [18:55] OPERATOR — DECISION: approve committing the recovery documents; reset Agy edit mode; "resume M1.5-1a"
- Operator approved committing the eight files in `AGENT_STATE.md` section 11 and asked for Agy to be reset from `accept-edits` to prompt mode. The operator also asked to "resume M1.5-1a" on the premise that it was not implemented.
- **Claude finding (see next entries):** M1.5-1a was already implemented, independently reviewed, committed and pushed as `02edb00`. It will be re-verified, not re-implemented; no later milestone is started.
- Pre-commit change disclosed: protocol section 6.3 now treats a descendant commit that touches only recovery files as non-stale (a snapshot cannot contain the hash of the commit that stores it); `AGENT_STATE.md` sections 1, 11, 12 updated to match.

### [18:55] CLAUDE — COMMIT+PUSH: recovery documents (`2fb864b`)
- Operator-approved docs-only commit of exactly eight files (6 new at repo root, 2 edited in `docs/`). Verified before committing: branch `main`, HEAD equal to `origin/main`, file set equal to `AGENT_STATE.md` section 11, staged list and non-doc check, no secrets, five V1.5 planning baseline documents untouched (`git diff HEAD` empty). Stale line in `docs/AUTONOMOUS_EXECUTION_STATE.md` ("16 of 33 mutating routes unauthenticated") corrected before staging.
- **Evidence:** `git show --stat 2fb864b` (8 files, +335/−9); push `02edb00..2fb864b`; HEAD equals `origin/main`; working tree clean.

### [19:0x, written with CP-002] CLAUDE — IMPLEMENT: Agy reset from accept-edits to prompt mode
- Cycled the live Agy session with `shift+tab` (accept-edits → auto → plan → no label = default). No global configuration changed.
- **Evidence:** footer shows no mode label; functional probe: Agy asked to create `.agy_mode_probe.txt` and Herdr/Agy raised "Allow creation of this file?"; denied with `esc`; the file does not exist and `git status` is clean. Named-file assignments and single-writer rules are unchanged.

### [19:01] CLAUDE+AGY — VALIDATE: M1.5-1a re-verification (operator asked to "resume M1.5-1a")
- Finding: M1.5-1a is **already implemented, independently reviewed, committed and pushed** (`02edb00`). The operator's premise that it was not implemented was reconciled by re-verifying, not re-implementing; no later milestone started and nothing was added to the product.
- Claude re-ran every check at HEAD `2fb864b`: backend 522 passed, ruff check and format clean, Alembic head `6db676dd20fd`, frontend 50 passed, oxlint 0 errors / 14 baseline warnings, tsc + vite build clean, frontend source and bundle free of operator-key references.
- Agy (read-only, prompt mode, each read approved individually) checked R1-R11 and S1-S10 against the committed code: all MET. Claude spot-checked citations: conclusions confirmed, some line numbers approximate (e.g. cited `main.py:57` is the redoc line; the dependency is a few lines away).
- Observations (not defects): failed logins logged not persisted; `is_authorized_verifier` always true for an authenticated caller; auth overhead not measured. Left for the operator.
- Roadmap graph note: M1.5-1b and M1.5-1c list M1.5-0 as predecessor. Earlier statements calling them "dependency-ready" were loose; their content is independent of D1, but strictly they need M1.5-0 (docs-only decision record) or an operator waiver.

### [19:01] CLAUDE — HANDOVER: checkpoint CP-002 written (uncommitted)
- `AGENT_STATE.md` and this log updated; checkpoint commit `2fb864b` (docs-only descendant of `02edb00`). **Next:** operator approval to commit CP-002 and to choose the next milestone. No agent has work in flight.

### [19:07] OPERATOR — DECISION: accept M1.5-1a; authorize CP-002 commit, reduced M1.5-0 and M1.5-1b
- M1.5-1a accepted at `02edb00` (not reimplemented). CP-002 commit authorized (two files). Reduced M1.5-0 authorized (documentation only; no credential or model-availability experiments). M1.5-1b authorized; M1.5-1c requires separate authorization after M1.5-1b acceptance; no M1.5-2 or later.

### [19:03] CLAUDE — COMMIT+PUSH: CP-002 checkpoint (`a55c739`)
- Verified branch `main`, HEAD = origin, full diff reviewed (two files only, no source), secrets scan clean; entry timestamps corrected from git before staging; staged exactly `AGENT_STATE.md` and `EXECUTION_LOG.md`. **Evidence:** `git show --stat a55c739`; push `2fb864b..a55c739`; HEAD = origin/main; tree clean.

### [19:07] CLAUDE+AGY — VALIDATE: M1.5-0 reduced decision record
- Claude re-verified Docker read-only (29.8.0, linux/arm64, 12 CPUs, about 8.3 GB, cgroup v2, runc only; no other runtime). Wrote `docs/V1_5_M1_5_0_DECISION_RECORD.md` (DR-01..DR-14), appended Amendment A1 to `docs/V1_5_ROADMAP.md` (11 lines added, 0 deleted; other baseline documents untouched), added ADR-025, updated the state docs.
- Agy (read-only, each read approved individually): all 14 required items MET, six residual risks preserved as open, no feasibility claim for subscription authentication, the old "reviewed development diagnostic" wording is clearly withdrawn, dependency gating logic confirmed (D1 blocks 4a, hence 4/5/6). Claude spot-checked the diff-based claims (numstat, untouched baseline files).
- Not done by design: any credential experiment, model call, Docker state change or product-code change.

### [19:1x] CLAUDE — COMMIT+PUSH: M1.5-0 reduced decision record (`a4c1d1e`)
- Staged exactly seven documentation files (decision record, Amendment A1 appended to `V1_5_ROADMAP.md`, ADR-025, state docs, `AGENT_STATE.md`, `EXECUTION_LOG.md`); no source; secrets scan clean. **Evidence:** push `a55c739..a4c1d1e`; HEAD = origin/main; tree clean.

### [19:11] CLAUDE — PLAN: M1.5-1b source inspection and spec (checkpoint CP-004, before any delegation)
- Inspected artifact service/API, runner setup path, `workflow_graph` work-dir blocks, planner, worktree manager, projects/executions APIs. New finding: `artifact_node` writes planner-supplied filenames relative to the work dir without containment. Spec in `docs/V1_5_M1_5_1B_SPEC.md`. **Next:** Agy design review, then bounded executor tasks B1-B3.

### [20:18] CLAUDE+AGY+EXECUTOR — IMPLEMENT/VALIDATE: M1.5-1b (checkpoint CP-005)
- Spec `docs/V1_5_M1_5_1B_SPEC.md` written after source inspection; Agy design review adopted (`.git` component ban, `O_NOFOLLOW` leaf, sanitized git env and hooks off, budget consistency, extra tests). Executor (Haiku 5.5, Claude Pro) tasks B1 path-security + artifact ownership, B2 worktree/API hardening, B3 fail-closed runner/graph/planner, B4 Unicode fix, B5 review remediation. Orchestrator reviewed each diff and re-ran the suite after every task (689 -> 718 -> 786 -> 796 passed).
- Orchestrator findings: `artifact_node` wrote planner-supplied names outside the work dir; `safe_join` accepted invisible/format Unicode and fullwidth look-alikes (fixed in B4); first mutation round had two equivalent-mutant survivors (redundant guards), re-run against both layers: all caught.
- Agy independent review: ACCEPT WITH FIXES (F-01..F-04); F-02/F-03 fixed, F-01 mitigated (worktree sha256 + location, no file moves), F-04 unchanged; Agy re-check ACCEPT.
- **Evidence:** 796 backend tests, ruff clean, Alembic head unchanged, frontend 50 tests/0 lint errors/clean build, no frontend/migration/dependency change. Report `docs/V1_5_M1_5_1B_ACCEPTANCE_REPORT.md`.
- **Next:** commit and push M1.5-1b only; STOP; request authorization for M1.5-1c.


### [CP-006] OPERATOR+CLAUDE — AUTHORIZE+PLAN: M1.5-1c
- Operator authorized M1.5-1c only (SD-03, SD-04). Claude inspected runner, graph, governor, services. Findings F1-F13 in `docs/V1_5_M1_5_1C_SPEC.md`: no checkpointer; no recovery entry point for RUNNING executions; resume_pipeline unguarded; reserve() returns the old fence token; retry loop restarts at attempt 0 after restart; state writes unfenced; task rows matched by title across executions. **Next:** Agy design review, then implementation (lease+epoch migration, orphan reservation expiry, attempt numbering, recover_execution) and real-process SIGKILL tests on an isolated database.

### [CP-007] CLAUDE+AGY — IMPLEMENT/VALIDATE: M1.5-1c
- Implemented lease+epoch (migration b7c1d2e3f4a5), orphan reservation settlement, attempt-number fix, recover_execution + CLI, terminal-state guard, task identity, checkpoints. 38 new tests (real-process SIGKILL scenarios A-H on throw-away databases). Backend 834 passed, ruff clean. Mutation: 13 guards, 12 killed, 1 redundant layer; 3 initial survivors closed by new tests.
- Agy implementation review: ACCEPT WITH FIXES (no Critical/High); M-01..M-03, L-01 fixed. **Next:** commit and push M1.5-1c; STOP; await authorization for M1.5-2.
