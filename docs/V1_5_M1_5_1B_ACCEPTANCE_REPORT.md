# ASTRAVA V1.5 — M1.5-1b Acceptance Report
## Artifact Ownership, Canonical Path Containment, Merge Target and Fail-Closed Execution Setup

**Baseline:** `a4c1d1e` (docs) on product code `02edb00` (M1.5-1a). **Scope:** M1.5-1b only. M1.5-1c and M1.5-2 or later were **not** started; the API process has **no** Docker access; no worker, credential-injection or brokerage code; no migration; no frontend change.
**Roles:** Sonnet orchestrator (spec, review, verification, git); Antigravity (design review, independent security review, remediation re-check; prompt mode, each permission approved individually); Claude Code **Haiku 5.5** on the Claude Pro subscription executed bounded tasks B1-B5 (banner `Haiku 5.5 · Claude Pro`; no fallback model, no API key, no billable call).
**Spec:** `docs/V1_5_M1_5_1B_SPEC.md` (with post-review amendments).

## 1. Before / after
| ID | At baseline (verified in source) | After M1.5-1b |
|---|---|---|
| SD-02 | `POST /artifacts` accepted any execution/task for any project and any pre-existing file under storage; no provenance | **Closed.** Ownership (project, execution, task key), file confined to the project's own artifact directory, server-written provenance (source, registered_by, sha256, size, location), API registration requires an existing regular file, preview/download refuse non-regular files |
| SD-06a | `merge_worktree` ignored `target_branch` and merged into whatever branch was checked out | **Closed.** Merges only when the checked-out branch equals the target, tracked tree is clean, branch is `astrava/exec-*`, full `refs/heads/...` names, never switches branches; every refusal is `(False, message)` |
| SD-06b | `sanitize_path` used a string-prefix check | **Closed.** Canonical `safe_join`/`is_within` (symlinks resolved, `is_relative_to`) |
| SD-06c | Fail-open worktree setup: missing repo directory skipped isolation, creation errors were logged and execution continued in the project directory; five work-dir blocks silently fell back to the project directory | **Closed.** `resolve_execution_work_dir` has no fallback; setup failures end the execution `FAILED` with `execution_setup_failed` and no provider or task runs |
| New | `artifact_node` wrote `work_dir / <planner filename>` with no containment (host file write via `../`) | **Closed.** Plan-time validation, `safe_join`, and `write_text_contained` (`O_NOFOLLOW` leaf) |
| New | `repo_path` and `base_branch` unvalidated; silent `HEAD` fallback for a missing base; `cleanup_worktree`/`create_worktree(worktree_dir=)` accepted any path | **Closed.** `ALLOWED_REPO_ROOTS` (default empty = fail closed), ref allowlist, no HEAD fallback, worktree paths confined to storage |
| New | Git ran with the inherited environment and repository hooks | **Closed.** Sanitized env, `core.hooksPath=/dev/null`, `core.fsmonitor=false`, `--no-ext-diff --no-textconv` |

## 2. Verification (run by the orchestrator)
| Check | Result |
|---|---|
| Backend `pytest` | **796 passed** (M1.5-1a baseline 522; +274 across four new test files and adapted tests) |
| `ruff check` / `ruff format --check` | clean / 123 files formatted |
| Alembic | head `6db676dd20fd`, **no migration added** |
| Frontend | unchanged: 50 passed, oxlint 0 errors / 14 baseline warnings, clean build |
| Scope | no frontend, migration, dependency or infrastructure file changed |
**Mutation tests (orchestrator):** removing the traversal check, the `.git` rule (both layers), the repo allowlist, the merge branch check, hook disabling, execution ownership, the missing-worktree error, the runner's setup-failure handling, or the contained artifact write each makes the new tests fail (two first-round survivors were equivalent mutants caused by redundant guards and were re-run against both layers). **Own probe** of `safe_join` found invisible/format Unicode and fullwidth look-alikes accepted (CVE-2014-9390 class); fixed in B4 and re-probed.

## 3. Independent review and remediation
Design review (Antigravity, before code): adopted `.git` component rejection, `O_NOFOLLOW` leaf writes, sanitized git environment and hook disabling, budget consistency on setup failure, extra adversarial tests; judged macOS case folding a false-rejection issue only and declined an autouse allowlist fixture.
Implementation review (Antigravity): **ACCEPT WITH FIXES**, no Critical/High.
| # | Severity | Finding | Disposition |
|---|---|---|---|
| F-01 | Medium | Worktree artifacts are registered under storage paths that do not exist there (null hash, preview/download 404) | **Mitigated:** provenance records the worktree file's sha256 and `location`; no files moved. Retrieval gap carried as tracked debt (pre-existing; resolved with worker snapshots) |
| F-02 | Low | Resume failing closed left an ACTIVE budget and open reservations | **Fixed** with test |
| F-03 | Low | Client `file_size_bytes` trusted for a non-existent file | **Fixed**: API registration requires an existing regular file; size/hash from disk |
| F-04 | Low | Planned-but-unexecuted task ids accepted | **Not changed**: ownership means "belongs to this execution" |
Re-check (Antigravity): F-01 to F-03, the git additions and the Unicode fix CONFIRMED; dispositions of F-01 and F-04 accepted; no new issues; verdict **ACCEPT**.

## 4. Behavior changes operators will notice
- Repositories require `ALLOWED_REPO_ROOTS` (JSON list of absolute directories; empty rejects every repository). Existing projects with a stored `repo_path` fail closed at execution until their repository is under an allowed root.
- A missing or unresolvable `base_branch` now fails the execution instead of silently using `HEAD` (note: the default `base_branch` is `main`; a repository whose branch is `master` must set it).
- `POST /artifacts` returns `403` for ownership violations and `404` for unknown project/execution; registering a file that does not exist is `400`.
- A setup-failed execution has no budget; `GET /executions/{id}/budget` returns the existing `404` for it.

## 5. Changed files
Backend app: `workspace/path_security.py` (new), `workspace/{__init__,worktree_manager}.py`, `services/{artifact_service,project_service}.py`, `api/v1/{artifacts,projects,executions}.py`, `orchestrator/{runner,workflow_graph,planner}.py`, `verification/engine.py`, `config.py`, `core/security_config.py`.
Tests: `test_m1_5_1b_{containment,worktree,failclosed,review_fixes}.py` (new); `test_v1_4_git_worktrees.py`, `test_v1_4_e2e_acceptance.py` adapted through explicit fixtures only (every assertion kept).
Docs/config: `README.md`, `.env.example`, `docs/{API,SECURITY,DECISIONS,PROGRESS,ROADMAP,AUTONOMOUS_EXECUTION_STATE}.md`, `docs/V1_5_M1_5_1B_SPEC.md`, this report, `AGENT_STATE.md`, `EXECUTION_LOG.md`. The `docs/V1_5_*` planning baseline and Amendment A1 are untouched.

## 6. Remaining security debt after M1.5-1b
- **SD-03, SD-04:** M1.5-1c (needs separate authorization). Note from this work: `resume_pipeline` re-enters the graph at `retrieve_knowledge`, which M1.5-1c must characterize.
- **SD-07:** host-side execution of agent-written code and `RepoScanner` until the M1.5-4 cutover (blocked by D1).
- **Carried by M1.5-1b (documented in `docs/SECURITY.md` section 10):** TOCTOU on intermediate directories while agents run on the host; other repository-local git configuration is not individually neutralized (allowlist trusted repositories only); worktree artifacts not retrievable through the artifact API; tracked-file-only dirty check before merge (untracked files are ignored); task ownership does not require completion.
- **M1.5-1a residual risks** (in-memory session revocation, shared key, failed logins not stored, `is_authorized_verifier` always true, 404/405 disclosure, DEBUG docs routes) remain open as recorded in the decision record.
- **D1 blocked, D5 unverified** (unchanged).

## 7. Confirmations
No M1.5-1c, M1.5-2 or later work. No Docker access for the API process. No credential injection or brokerage. No billable API calls. No deployment. No history rewrite or force-push.
