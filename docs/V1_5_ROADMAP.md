# ASTRAVA V1.5 — Roadmap: Containerized Worker Sandboxing

**Status:** Planning accepted in principle; **no implementation approved or started.** Each milestone starts only on explicit operator approval.
**Roles:** Operator = decisions and approvals. Sonnet orchestrator = independent reviewer, sign-off, git/test ownership. Antigravity = architecture/plan authoring and plan-conformance review. Claude Code executor = implementation, `claude-haiku-5-5` only; no model substitution (`--fallback-model` is never passed), and no paid API credential (Decisions D1/D5).
**Governing rules.**
1. **Isolation is mandatory (D4).** If the runtime, worker image, workspace provisioning or security configuration is unavailable, the task fails. There is no host-execution fallback and no flag, environment variable or setting that enables one in the production path. Any development diagnostic must live outside the execution path, be a separate tool, and require explicit opt-in per invocation.
2. **Security debt gates (see `V1_5_TECHNICAL_RISKS.md` section 6).** V1.4 carried findings SD-01..SD-08 are prerequisites, not follow-ups. No milestone may introduce a capability before its gating debt is closed (see gate matrix).
3. Every milestone ships with its security and recovery tests; one commit per milestone, authored by the operator identity, with no AI attribution.
4. **Rollback is by git revert/tag of the milestone commit plus additive-only migrations**, not by a runtime switch back to host execution.

## Dependency graph
```
M1.5-0  decisions record + operator-gated experiments (D1 credential, D5 model)
   │
M1.5-1a auth + audit identity (D6; SD-01, SD-05, SD-08) ──┐
M1.5-1b artifact provenance + merge/path/fail-closed fixes │ (1a,1b,1c are independent of each other)
        (SD-02, SD-06, SD-07)                              │
M1.5-1c full-runner/LangGraph recovery characterization    │
        tests (SD-03, SD-04)                               ┘
   │
M1.5-2  WorkerRuntime + pinned image + worker_runs        needs 1a        (adds Docker-launch capability to the API process)
   ├─► M1.5-3   snapshot + hardened git import            needs 1a,1b,2
   ├─► M1.5-3b  controlled dependency provisioning (D3)   needs 2
   └─► M1.5-4a  egress + credential strategy (D1)         needs 2, M1.5-0 D1 experiment result
M1.5-4  atomic cutover: containerized agent + verification  needs 1a,1b,1c,3,4a  (removes host agent/verification execution)
M1.5-5  orchestrator integration, leases, recovery, UI      needs 4,3b
M1.5-6  adversarial acceptance + freeze                     needs 5
```

### Gate matrix (no milestone bypasses a prerequisite)
| Capability introduced | Milestone | Must already be closed |
|---|---|---|
| API process can launch containers (Docker daemon access = high privilege) | M1.5-2 | 1a: every mutation authenticated; non-loopback requires key; audit identity server-derived |
| Untrusted git data crosses into the host repo | M1.5-3 | 1a, 1b (merge target enforced, path check fixed, artifact ownership), 2 |
| Package-index egress exists | M1.5-3b | 2; network policy tests from 2 |
| Model credential enters a worker | M1.5-4a | 1a, D1 experiment result recorded; credential never billable without approval |
| Host agent/verification execution is removed | M1.5-4 | 1c (characterization tests exist, so the cutover is regression-checked), 3, 4a |
| Parallel workers + leases | M1.5-5 | 4, 3b |

## M1.5-0 — Decision record and operator-gated experiments
**Description.** Record D1–D6 resolutions (Target Architecture section 11) in `DECISIONS.md`. Complete only the experiments that cannot create billing or expose secrets.
**Tasks.**
- Append the decision record to `DECISIONS.md`.
- **D1 experiments (operator-run, see Target Architecture section 6):** E1 mint a dedicated long-lived token with `claude setup-token`; E2 in a throwaway hardened container, set only that token and run `claude auth status` (no model call) to see whether it is recognised; E3 only if E2 passes **and** the operator confirms extra/overage usage is disabled on the subscription, run one `claude -p` call with `--model claude-haiku-5-5` and no fallback model.
- **D5:** same gate as E3; no live model call otherwise.
- Benchmark on the verified host (Docker Desktop): workdir latency for named volume vs tmpfs vs bind mount, container start time, clone timing.
**Dependencies.** Operator action for E1/E3.
**Acceptance.** Decision record merged; D1 outcome is either "mechanism verified" or "blocked with operator-approved alternative"; benchmark numbers recorded.
**Security tests.** Experiment containers run with the final hardening flags; no host `~/.claude` mounted or copied; token never written to a repo file or log.
**Recovery tests.** n/a. **Performance (proposed):** warm container start <= 3 s; workdir file-op throughput >= 0.8x native on a 2,000-file test; snapshot <= 5 s for a 100 MB repo.
**Rollback.** Delete spike artifacts and revoke the experiment token; no repo changes.

## M1.5-1 — Security prerequisites (V1.4 carried debt + D6)
### M1.5-1a — Operator authentication and audit identity (D6; SD-01, SD-05, SD-08)
**Tasks.**
- **Startup guard:** refuse to start if the configured bind host is non-loopback and `OPERATOR_API_KEY` is missing, empty or shorter than 32 characters. Also guard at request time: with no key configured, reject any request whose client address or `Host` header is non-loopback (also defeats DNS rebinding of a local dev server).
- **Central enforcement:** a router-level dependency requires operator authentication for every non-`GET` route, and for all `GET` routes when the server is non-loopback; only a minimal health route stays public. Remove per-endpoint opt-in as the mechanism (SD-01: 16 mutation routes are currently unauthenticated).
- **Route-inventory test:** enumerates `app.routes` and fails if any mutating route lacks the dependency, so new endpoints cannot regress.
- **Audit identity:** derive `actor_id` from the authenticated server-side context (configured operator identity), never from `X-ASTRAVA-ACTOR-NAME`. In loopback development mode, record `actor_id=local-dev` with `auth_mode=local_dev_unauthenticated`; the header may be stored only as an unauthenticated `claimed_name` note.
- **Browser access without exposing the key to JavaScript:** a login endpoint verifies the key once and sets an `HttpOnly`, `SameSite=Strict` (and `Secure` when not on plain-loopback) server-side session cookie plus a CSRF token required on mutating requests; the key is never stored in `localStorage`, embedded in the bundle, or sent by script. Non-browser clients keep `Authorization: Bearer`. Rate-limit and audit failed logins; constant-time comparison (already used).
- Distinguish permissions that are currently collapsed: `is_authorized_verifier` is hard-coded `True` for every authenticated caller; keep a single operator for now but make the check real and testable.
**Dependencies.** M1.5-0.
**Acceptance.** All mutating endpoints (executions create/pause/resume/replan/merge/budget-increase, approvals decide, goals, memories create/update/verify/resolve/archive/restore, agents, projects, tasks, workflows, artifacts, orchestrator execute/resume) return 401 without credentials in authenticated mode; server refuses to start insecurely; local dev on loopback still works with no key; existing V1.4 suites stay green.
**Security tests.** Route inventory; non-loopback + no key -> process exits; forged `Host` header rejected; spoofed actor-name header never appears as `actor_id`; cookie flags asserted; CSRF-less mutation rejected; key absent from every frontend asset and response.
**Recovery tests.** n/a. **Performance.** Auth overhead < 2 ms per request.
**Rollback.** Revert the commit; no migration (or an additive audit column only).

### M1.5-1b — Provenance, ownership and baseline defect fixes (SD-02, SD-06, SD-07)
**Tasks.**
- `ArtifactService.sanitize_path` uses `Path.is_relative_to` (R-10).
- `POST /artifacts` validates that `execution_id` and `task_id` belong to `project_id`, rejects registering pre-existing arbitrary files, requires the file to be inside that execution's artifact directory, and records provenance (producer, attempt, content hash).
- `merge_worktree` enforces `target_branch` without `git checkout` in the operator's repo (R-09).
- Fail closed on worktree/snapshot setup failure (R-11, D4).
- `projects.repo_path` allowlist of roots and validation on create/patch (a mutable arbitrary host path is a path-selection primitive).
- Interim: kill whole process groups in `VerificationEngine` and `_run_git`; extend `redact_secrets` patterns and apply them to artifacts, diffs and persisted logs.
**Dependencies.** M1.5-0 (independent of 1a, but both gate M1.5-3).
**Acceptance.** Each defect has a failing-then-passing regression test; V1.4 baseline (191 backend / 20 frontend) stays green.
**Security tests.** `artifacts_evil/x` rejected; cross-project execution/task id rejected; merge while repo is on another branch lands only on target or errors; simulated worktree failure -> execution `FAILED`, nothing ran; `repo_path` outside allowlist rejected.
**Recovery tests.** Verification timeout leaves no surviving grandchild. **Rollback.** Revert the commit.

### M1.5-1c — Full-runner and LangGraph recovery characterization (SD-03, SD-04)
**Tasks.** Add tests that drive `OrchestrationRunner.start_pipeline`/`resume_pipeline` and the compiled graph end to end (not only `dispatch_task_node`): crash at each node boundary (plan, approval, dispatch, verify, remediation, replan, artifact, ingest, complete), real process kill, restart, resume. Re-run the existing retry-aware recovery tests as the regression baseline. Decide and document whether a LangGraph checkpointer is needed (none exists today; recovery is DB-based).
**Dependencies.** M1.5-0.
**Acceptance.** Matrix of crash points x resume outcomes passes; no duplicated tasks, double settlements or lost reservations.
**Security tests.** Fence-token rejection after resume. **Recovery tests.** This milestone is the recovery test suite. **Performance.** Suite time added <= 90 s. **Rollback.** Tests only.

## M1.5-2 — `WorkerRuntime`, pinned worker image, `worker_runs`
**Tasks.**
- `WorkerRuntime` interface (`prepare/start/wait/kill/cleanup/inspect`) and `DockerWorkerRuntime`; **no Docker types leak into orchestration code**, so Podman/Colima/OrbStack/gVisor implementations can be added later.
- Launch-spec validator that **rejects** privileged mode, docker socket, host-home or arbitrary host mounts, host network, added capabilities, missing limits, and any non-digest image reference.
- Minimal worker image built by a separate build step (never by the running API), referenced by digest; CI vulnerability scan.
- Alembic migration: `worker_runs` (additive); `WorkerSupervisor` lifecycle state machine, wall-clock kill, `finally` cleanup, startup reaper by label.
- `CredentialProvider` slot; M1.5-2 ships only a no-credential implementation and asserts the worker env is secret-free.
- Preflight check in the health endpoint (runtime reachable, image present by digest, limits enforceable). The runtime is **not reachable from any execution path yet** (cutover happens in M1.5-4); there is no mode flag.
- Compatibility test: Node-based CLI, git and Python run under `--read-only` with the required tmpfs/volume overlays.
**Dependencies.** M1.5-1a; D2 (verified: Docker Desktop).
**Acceptance.** A no-op container runs under all hardening flags; validator matrix passes; every transition recorded; reaper removes labelled orphans.
**Security tests.** Launch-spec fuzz; inside the container: non-root, no capabilities, read-only rootfs, no docker socket, no host paths, empty home, minimal env; setuid escalation fails; fork bomb stopped by pids limit; memory hog OOM-killed without affecting the host or the other containers sharing the Docker VM.
**Recovery tests.** API killed mid-run -> reaper removes the container on restart; Docker daemon stopped -> start fails closed.
**Performance.** Warm start <= 3 s; supervisor overhead < 200 ms per attempt. **Rollback.** Revert commit; migration is additive.

## M1.5-3 — Snapshot delivery and hardened git import
**Tasks.** `WorkspaceSnapshotter` (standalone clone, hooks emptied, no alternates/worktree linkage); stream-in transport into a size-limited volume inside the runtime VM; results leave as git data (bundle/fetch), with strict extraction (reject absolute paths, `..`, escaping links, device nodes, setuid) for any file bytes; quarantine import with limits (objects, size, symlinks, `.git*`/submodule rules, path components); reference cache; snapshot GC.
**Dependencies.** M1.5-1a, 1b, 2.
**Acceptance.** Round trip (snapshot -> modify in container -> import -> operator diff/merge) works; host repo refs/reflog untouched until merge.
**Security tests.** Weaponized hooks, `core.fsmonitor`, filters and `.gitattributes` do not execute on the host; symlink/`..` escapes, huge objects and path-case attacks rejected; commits touching `.git` metadata or submodules rejected; `git push` from the worker fails.
**Recovery tests.** Crash between import and ref update leaves only the quarantine ref; re-run is idempotent.
**Performance.** Snapshot <= 5 s (100 MB repo); import <= 3 s typical. **Rollback.** Revert commit.

## M1.5-3b — Controlled dependency provisioning (D3)
**Principle.** Task workers never have package-index access. Images and dependencies are built/provisioned **outside** untrusted task execution.
**Tasks.**
- Baseline: a pinned, reproducible worker image (digest-referenced, built from a recorded Dockerfile and a locked package set) containing the CLI, git, Python and pytest.
- Repositories needing extra packages declare them via lockfile; a control-plane-run **prepare job** (separate container, no model credential, no repo secrets, no write access to the repo) resolves them with hash-checked, lockfile-pinned installs (for example `pip --require-hashes --only-binary=:all:`, `npm ci --ignore-scripts`), through an allowlisted package mirror/proxy, into a content-addressed, read-only `deps` volume keyed by lockfile hash.
- Install-time scripts are disabled by default; a package needing them requires explicit operator approval recorded in the audit log.
- Task and verification containers mount `deps` read-only and get `PYTHONPATH`/`NODE_PATH` set; they have no index access.
- A repository with unmet dependencies and no provisioned `deps` volume **fails the task** with a clear error; it never falls back to open networking.
**Dependencies.** M1.5-2. **Acceptance.** Reproducible volume hash for identical lockfiles; tasks succeed offline with a provisioned volume.
**Security tests.** Hostile `setup.py`/`postinstall` runs only in the prepare container with no secrets; task container cannot reach any index; tampered hash rejected; dependency confusion test.
**Recovery tests.** Prepare job killed mid-install leaves no partial volume that later tasks can mount. **Performance.** Cached prepare is a no-op (<1 s). **Rollback.** Revert commit.

## M1.5-4a — Egress and credential strategy (D1)
**Tasks.** Implement the mechanism that survived the M1.5-0 experiments (see Target Architecture section 6): scoped, revocable subscription token delivered for one attempt, or a credential-holding gateway **only if** verified to work with the subscription login; `EgressProxy` default-deny with a model-API allowlist; DNS, metadata and LAN blocking; redaction of the credential in all outputs. No paid API credential is ever used without operator approval.
**Dependencies.** M1.5-2; D1 experiment outcome; 1a. **If D1 is blocked,** this milestone does not start; the alternatives require explicit approval.
**Acceptance.** The worker reaches only the allowlisted host; the credential never appears in persisted data.
**Security tests.** `curl` to arbitrary hosts, `169.254.169.254`, the host LAN, the control-plane port and the Postgres port all fail; credential absent from `/proc/*/environ` of non-CLI processes where the mechanism allows, from the filesystem, logs and `worker_runs`; credential revoked/expired after the lease; billing guard: environment contains no `ANTHROPIC_API_KEY`.
**Recovery tests.** Proxy restart mid-run fails the attempt cleanly with no host fallback. **Performance.** Proxy adds < 50 ms per request. **Rollback.** Revert commit; revoke the token.

## M1.5-4 — Atomic cutover to containerized agent and verification
**Tasks.** `ClaudeCodeWorkerProvider` (same `BaseProvider` contract); pin CLI permission mode and tool allow/deny lists with a version-change guard test; forbid `--fallback-model` and `--dangerously-skip-permissions` outside the container; run `VerificationEngine` checks and deterministic tasks inside the zero-network verification container; **remove** host-side `pytest`/`py_compile`/agent execution in the same milestone; move `RepoScanner` into the container or reduce it to name/size metadata; strict tar/bundle extraction; sanitize ANSI/HTML escapes in streamed logs before UI display; bounded result schema; output redaction.
**Dependencies.** M1.5-1a, 1b, 1c, 3, 4a.
**Acceptance.** V1.4 end-to-end acceptance tests pass on the containerized path; a grep/static test proves no code path launches the agent or runs pytest on the host.
**Security tests.** Prompt-injection corpus (read `~/.ssh`, exfiltrate env, delete outside workdir, write `.git/hooks`, network beacons) has no host effect; malicious `conftest.py`/`setup.py` runs only in the zero-network container; oversize/malformed result, malicious tar/bundle and log escape sequences are rejected or rendered inert; runtime unavailable -> task `FAILED` with no execution.
**Recovery tests.** Worker killed mid-task -> retried per policy; late result from a stale worker discarded by fence token.
**Performance.** End-to-end task overhead <= 15 % or <= 8 s versus V1.4 (whichever is larger). **Rollback.** Revert the cutover commit (git/tag); no runtime flag.

## M1.5-5 — Orchestrator integration, leases, recovery, observability
**Tasks.** Bind each `worker_runs` row to a `BudgetGovernor` reservation and `fence_token`; heartbeat and expiry reclamation; admission control with global and per-execution caps (default 2, sized to the Docker VM's resources — currently 12 CPUs / about 8 GB shared with other containers); resource accounting in agent metrics; worker-run details in the Executions UI; startup reconciliation of reservations and containers.
**Dependencies.** M1.5-4, 3b.
**Acceptance.** Parallel DAG waves respect caps; the budget ceiling halts workers; the UI shows state, limits and exit reason.
**Security tests.** A worker cannot settle another attempt's reservation; stale fence token rejected.
**Recovery tests.** SIGKILL the API at each lifecycle state -> zero orphan containers, zero double-settled reservations, execution resumable (built on the 1c suite); Docker restart mid-run; disk-full during snapshot.
**Performance.** 2 parallel workers without starvation; reaper < 5 s with 50 stale rows. **Rollback.** Revert commit; additive schema.

## M1.5-6 — Adversarial acceptance and delivery freeze
**Tasks.** Full invariant matrix (Threat Model INV-01..INV-14); escape/chaos suite; soak (50 consecutive attempts, disk/container baseline returns); independent review by Antigravity and Sonnet; V1.5 acceptance report; update `ROADMAP.md`, `ARCHITECTURE.md`, `API.md`, state doc; baseline freeze.
**Dependencies.** M1.5-5. **Acceptance.** All invariants proven by automated tests; zero open Critical/High findings; residual risk accepted by the operator. **Rollback.** Tag-based revert.

## Cross-cutting
- **Testing without Docker in CI:** runtime-interface tests use a fake runtime; Docker-backed tests are marked and run only where the daemon exists.
- **Documentation:** each milestone updates `PROGRESS.md`, `DECISIONS.md`, `AUTONOMOUS_EXECUTION_STATE.md`.
- **Out of scope for V1.5:** RBAC/multi-tenancy, multi-repo, remote scheduling, remote git push, Kubernetes. The `WorkerRuntime` seam and `worker_runs` table accommodate them later.

---

## Amendment A1 (2026-11-07) — status and dependency update
*Appended after `3623d43`; nothing above this line was rewritten. Reviewed separately; full text in `V1_5_M1_5_0_DECISION_RECORD.md`.*
- **Status correction:** the header statement "no implementation approved or started" is superseded. M1.5-1a is **accepted** at `02edb00`; reduced M1.5-0 (documentation-only decision record) is complete; M1.5-1b is authorized; M1.5-1c requires separate authorization after M1.5-1b is accepted. No milestone from M1.5-2 onward is approved.
- **M1.5-0 scope reduced:** only the decision record was performed. The D1 credential experiments and the D5 model-availability check are **not** performed and are not authorized.
- **D1 is BLOCKED** pending an approved provider authentication arrangement. Consequently **M1.5-4a is blocked, and M1.5-4, M1.5-5 and M1.5-6 are blocked through it.** M1.5-1b, M1.5-1c, M1.5-2, M1.5-3 and M1.5-3b do not depend on a worker credential.
- **D4 tightened:** no unsafe mode of any kind (the planning text that allowed a separately reviewed development diagnostic is withdrawn pending a new reviewed proposal).
- **Security debt:** SD-01, SD-05, SD-08 are closed; the table in `V1_5_TECHNICAL_RISKS.md` section 6 is superseded by decision record section 4.

