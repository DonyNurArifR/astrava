# ASTRAVA V1.5 — Architecture Assessment (Containerized Worker Sandboxing)

**Status:** Planning only. No implementation started.
**Baseline:** V1.4 frozen at `ed08f15` on `main` (Alembic head `6db676dd20fd`).
**Method:** Every claim below was checked against source in this session, not copied from earlier reports. Each fact cites `file:line`-level locations. Items I could not verify are marked **UNVERIFIED**.

## 1. Verified current execution architecture

### 1.1 Everything agent-driven runs as a host process of the API server
| Surface | Location | Fact |
|---|---|---|
| Agent execution | `app/providers/claude_code.py` `execute()` | `asyncio.create_subprocess_exec(claude --model M -p --output-format json … prompt)`, `cwd` = task work dir, `start_new_session=True`. Runs as the same OS user as the API server. |
| Verification | `app/verification/engine.py` `verify_task()` | Runs `python3 -m py_compile` and **`pytest -v` on agent-written test files, on the host**, via `create_subprocess_exec`. Timeout 30s on pytest. No process-group kill (`proc.kill()` only), so grandchildren can survive. |
| Git operations | `app/workspace/worktree_manager.py` | Host `git` for worktree add/remove, diff, `add -A`, `commit`, `merge`. Commit author is hard-coded (`Abstract <…noreply…>`). |
| Deterministic tasks | `workflow_graph.py:~417` | `executor_type == DETERMINISTIC` calls `verify_task` directly, so host pytest execution happens even without the LLM. |

### 1.2 Environment and credentials
- `_build_clean_environment` allowlists only `PATH, HOME, USER, LANG, TERM` plus `env_overrides`. This is good hygiene, **but it passes the real `HOME`**. The Claude CLI authenticates from `~/.claude` under that HOME, and any child process (including agent-spawned shells) can read the rest of the home directory (`~/.ssh`, `~/.aws`, `~/.gitconfig`, browser data, and so on). This is the largest host-exposure gap.
- The `claude` CLI is invoked with **no** `--permission-mode`, `--allowedTools`, or `--disallowedTools`. What the CLI permits non-interactively in `-p` mode is **UNVERIFIED** and must be pinned and tested explicitly in V1.5 (it is a security-relevant default that can change between CLI versions; installed CLI is 2.1.319).
- Authentication is whatever the host CLI session uses (subscription login vs `ANTHROPIC_API_KEY`) — **UNVERIFIED which one is in use here.** This decides the billing risk of any credential strategy (see Technical Risks R-03).
- Secret redaction is regex-based on stdout/stderr only (`redact_secrets`); file artifacts and diffs are not redacted.

### 1.3 Repository and worktree handling
- Worktrees are created at `storage/worktrees/<execution_id>` via `git worktree add -b astrava/exec-<id>`; the worktree's `.git` is a file pointing at the **host repo's** `.git/worktrees/<id>`. A container that mounts only the worktree would have a broken git; a container that also mounts the repo `.git` can rewrite the host repo's history, hooks and config. This is the central design constraint (see Target Architecture §5).
- `merge_worktree()` runs `git merge --no-ff <branch>` **in `repo_path` against whatever branch is currently checked out**. The `target_branch` argument is accepted but never used in the command, so the merge target is not enforced. (Pre-existing defect, independent of V1.5; flagged for fix before sandboxing relies on it.)
- `create_worktree` deletes any existing branch/worktree of the same name (`branch -D`, `worktree remove --force`, `rmtree`) as "crash cleanup" — destructive operations on a user repo keyed only by execution id.
- Failed worktree creation is swallowed (`logger.warning`) and execution proceeds in `project_work_dir` — **fail-open to the non-isolated directory** (`runner.py:~120`).
- `repo_path` is an arbitrary operator-supplied host path; no allowlist of roots was found.

### 1.4 Artifacts
- `ArtifactService.sanitize_path` checks `str(target).startswith(str(base_dir))`. This is a **prefix check, not a path-component check**: a sibling like `…/artifacts_evil/x` passes. Fix with `Path.is_relative_to` before workers are allowed to produce artifact paths.
- Artifacts are written by the control plane (`register_artifact`) from content it holds; they are read back as text (`read_text`).

### 1.5 Concurrency, budgets, recovery
- `MAX_CONCURRENT_EXECUTIONS = 1` (semaphore in `runner.py`). Within an execution, independent tasks run in-process via `asyncio.gather` (`workflow_graph.py:~822`).
- `BudgetGovernor` implements two-phase reservations with a `fence_token`, `expires_at` lease and reclamation of expired holds (`budget_governor.py`). This is **already the right primitive for worker leases**; V1.5 should reuse it, not invent a second lease system.
- No LangGraph checkpointer (`PostgresSaver`/`MemorySaver`) was found in `app/`; recovery is DB-state based (reservations, task rows, `resume_pipeline`). Worker crash recovery therefore must reconcile via the existing reservation/lease tables.
- Shutdown hook `terminate_all_active_processes()` kills tracked process groups with SIGKILL. It tracks only provider processes (not verification or git children) and is lost entirely if the API process is SIGKILLed, so orphans are possible.

### 1.6 Auth to the control plane
- `app/core/auth.py`: if `OPERATOR_API_KEY` is **unset (the default)**, every request is trusted and `is_authorized_verifier=True` for all callers. With the key set, a single shared secret authenticates a single operator; actor name is a client-supplied header (`X-ASTRAVA-ACTOR-NAME`) and is used as the audit `actor_id`.
- **Route audit (AST scan of `app/api/v1`, this session):** of 33 mutating routes, 16 have **no authentication dependency even when the key is set**: `orchestrator` `/execute`, `/resume/{id}`, `/executions/{id}/resume`, `/plan`, `/understand`; `projects` POST/PATCH/DELETE; `agents` `/seed`, POST, PUT, PATCH status; `tasks` POST/PATCH; `workflows` POST; `artifacts` POST. All 36 GET routes counted on the main routers are unauthenticated (diffs, artifact contents, memories). `/orchestrator/execute` starts agent execution, `PATCH /projects/{id}` can set `repo_path` to any host path, and `PUT /agents/{id}` can change agent configuration. There is no memory-deletion endpoint. `APP_HOST` defaults to `0.0.0.0` with `DEBUG=True`.
- There is **no worker identity** in the system. Nothing authenticates a worker to the control plane because workers do not exist as a separate principal.

### 1.7 Infrastructure
- `docker-compose.yml` defines only Postgres 16 (published on host port 5433, default dev password in compose and in `config.py`). There is no API, frontend or worker service; no container runtime integration exists in code. `backend/` has no Dockerfile.

## 2. Gap summary against the V1.5 objective
| # | Gap | Severity |
|---|---|---|
| G1 | Agent CLI runs with full host user privileges and real `$HOME` | Critical |
| G2 | Verification (pytest on agent-written code) runs on host, unsandboxed | Critical |
| G3 | Worktree `.git` linkage forces a choice between broken git and repo-writable mount | High (design) |
| G4 | Worktree creation failure falls back to running in the non-isolated work dir | High |
| G5 | `merge_worktree` ignores `target_branch`; merges into current HEAD of host repo | High (pre-existing bug) |
| G6 | `sanitize_path` prefix check | Medium (pre-existing bug) |
| G7 | No worker principal / worker-to-control-plane auth; default-open operator auth | High |
| G8 | Process cleanup covers only provider children; no guarantee after hard crash | Medium |
| G9 | Redaction only on stdout/stderr, not artifacts/diffs/logs persisted elsewhere | Medium |
| G10 | CLI permission posture in headless mode unpinned and unverified | Medium (unknown) |
| G11 | 16 mutating routes unauthenticated even with a key set; all GETs unauthenticated; audit actor taken from a client header | Critical |
| G12 | `POST /artifacts` does not check that `execution_id`/`task_id` belong to `project_id` and can register pre-existing files under the artifact root | High |
| G13 | Recovery tests drive `dispatch_task_node` directly; no test restarts `OrchestrationRunner` and resumes the compiled graph; no LangGraph checkpointer | High (assurance gap) |

## 3. Things deliberately not assumed
- That `claude-haiku-5-5` is currently available to the operator's account. The code defaults to it everywhere (`models/task.py`, `schemas/task.py`, `semantic_evaluator.py`, `agent_service.py`), but verifying availability requires a real CLI/API call that consumes quota or money. **Not done; requires operator approval.** No model substitution is proposed anywhere in V1.5.
- That Docker is installed or the right runtime for the operator's host. Not checked in this document; the roadmap's first milestone is a runtime-selection spike.

## 4. Verified host facts (D2/D1/D5, this session)
- Container runtime: Docker Desktop 29.8.0 on macOS 27.0.1 (arm64), operational; VM 12 CPUs / about 8.3 GB; cgroup v2; `runc` 1.4.3 only; built-in seccomp; overlayfs. No other runtime installed. Existing containers (`astrava-postgres`, `bl-pg`, others' images) share the VM. No worker image exists.
- Claude CLI 2.1.319; subscription login (`claude.ai`, plan `pro`); credentials stored in `~/.claude/.credentials.json` (not read); no API-key environment variables in the inspected session. `--bare` ignores OAuth; `claude setup-token` and `claude gateway` exist; `--fallback-model` exists. See Target Architecture section 11 for the D1 analysis.
- Git: `ed08f15` is HEAD of `main`, working tree was clean before the V1.5 documents were added.
