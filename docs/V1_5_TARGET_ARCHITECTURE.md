# ASTRAVA V1.5 — Target Architecture: Control Plane / Worker Plane

**Status:** Proposed. Planning only. Requires operator approval before any implementation.
**Inputs:** `V1_5_ARCHITECTURE_ASSESSMENT.md` (verified facts), `V1_5_THREAT_MODEL.md`, `V1_5_TECHNICAL_RISKS.md`.
**Principle:** Docker is a *containment layer*, not a security proof. Every control below is paired with a test (see Roadmap) and a named residual risk (see Threat Model).

## 1. Goals and non-goals
**Goals.** Agents and verification run only inside isolated, resource-bounded, short-lived workers. A malicious repo, a prompt-injected agent or a compromised dependency must not be able to read host files, reach host credentials, damage the host repo, or outlive its lease.
**Non-goals (V1.5).** Multi-tenancy/RBAC, multi-repo, remote/cloud scheduling, Kubernetes, remote git push. The `WorkerRuntime` seam keeps these possible later.

## 2. Plane responsibilities
| Control plane (host, trusted) | Worker plane (container, untrusted) |
|---|---|
| Task orchestration (LangGraph), DAG, replanning | Run one Claude Code CLI invocation for one task attempt |
| Budget enforcement and reservations (`BudgetGovernor`) | Run verification commands (separate container) |
| Approval decisions, operator auth | Read the snapshot, write changes inside it |
| Worker provisioning, lifecycle, lease, kill, cleanup | Emit one structured result file |
| Execution tracking, audit history | Nothing else: no DB, no control-plane API, no host paths, no secrets beyond its model credential |
| Result validation, artifact registration, redaction | |
| Git import of worker output and operator-gated merge | |

The worker is treated as **adversarial output**: everything it returns (result JSON, files, git objects, logs) is validated and size-bounded before the control plane acts on it.

## 3. Components (new)
1. `WorkerRuntime` (interface): `prepare()`, `start()`, `wait()`, `kill()`, `cleanup()`, `inspect()`. First implementation `DockerWorkerRuntime`. Later: `GVisorRuntime`, `PodmanRuntime`, microVM.
2. `WorkerSupervisor`: owns a worker's lifecycle for one attempt; heartbeats the lease; enforces wall-clock timeout; guarantees `kill()+cleanup()` in `finally` and from a startup **reaper**.
3. `WorkspaceSnapshotter`: builds the standalone snapshot (see §5) and imports results.
4. `ClaudeCodeWorkerProvider`: implements the existing `BaseProvider.execute(ProviderRequest)` contract, so `workflow_graph.py` changes are minimal. At cutover (M1.5-4) the host `ClaudeCodeCLIProvider` execution path is **removed from the production path**; there is no flag that selects host execution (D4).
5. `EgressProxy` (sidecar or shared container): allowlist to the model API host only.
6. `worker-image/` (Dockerfile + pinned digest manifest): minimal base, `claude` CLI, git, python, pytest, non-root user. Built and scanned by CI, never by the running API.
7. `worker_runs` table (new, Alembic in the implementation phase): one row per attempt: execution/task/attempt ids, `reservation_id`, `fence_token` hash, container id, image digest, limits applied, state, timestamps, exit info, reaped flag. This is the audit and recovery record.

## 4. Key design decisions and recommendations
| Decision | Options | Recommendation | Rationale / trade-off |
|---|---|---|---|
| Granularity | per task vs per execution | **Per task attempt** | Maps 1:1 to the existing reservation/fence/lease and retry model; limits blast radius of a compromised agent; costs ~1–3 s startup per task (acceptable against 180 s task timeouts; target in Roadmap). Per-execution containers keep a compromised agent alive across tasks and complicate lease semantics. |
| Lifetime | ephemeral vs reusable | **Ephemeral, never reused** | No state carry-over between tasks or executions; cleanup is trivially "remove container". Reuse only for the *image*, never a container. |
| Repo delivery | bind-mount worktree vs snapshot | **Snapshot** (standalone clone, §5) | Mounting the existing worktree either breaks git or exposes the host repo `.git`. Snapshot costs a copy and an import step; gains hard host-repo isolation. |
| Images | shared vs per-task | **One shared pinned image**; per-project images deferred | Per-task images mean building untrusted Dockerfiles. Dependencies are handled by the prepare phase (§7), not by task-specific images. |
| Network | open vs restricted | **Restricted:** agent container egress = model API only; verification container = none | Prompt injection + open network = exfiltration. Dependency install happens in a separate secret-free prepare step. |
| Runtime | Docker, rootless Docker/Podman, gVisor, Kata, Firecracker | **Hardened Docker first**, behind `WorkerRuntime`; gVisor (Linux) as the first hardening step; microVM if a multi-tenant/cloud step ever comes | On macOS, Docker Desktop already adds a Linux VM boundary; gVisor/Kata/Firecracker are Linux-host technologies. Choosing hardened Docker avoids a platform rewrite; the interface avoids lock-in. **Runtime availability on the operator's host is unverified (spike in M1).** |
| Worker protocol | callback API vs supervised file | **Supervised; no worker→control-plane API in v1** | The supervisor starts the container, waits, then reads a single result file. There is no inbound path to authenticate or attack. If a callback is ever added: per-attempt token bound to `(execution, task, attempt, fence_token)`, short TTL, scoped to one endpoint, over a private socket/network. |
| Lease / recovery | new lease system vs reuse | **Reuse `BudgetGovernor` reservation + `fence_token` + `expires_at`** | Already crash-tested (M1.4-2.2.x). The `worker_runs` row references the reservation; a reaper reconciles expired leases by killing the container and releasing/settling the reservation with the fence token. |
| Parallelism | unlimited vs capped | **Global cap (default 2), per-execution cap, both configurable; admission control before provisioning** | `MAX_CONCURRENT_EXECUTIONS=1` today; tasks inside an execution use `asyncio.gather`. A container-count semaphore sits in `WorkerSupervisor`. |
| Resource accounting | none vs per-worker | **Record applied limits and observed peak (cpu/mem/pids/disk/wall)** in `worker_runs`; surface in existing agent metrics | Feeds the existing budget dimensions (runtime) and enables regression tests on limits. |

## 5. Repository and filesystem design
- **Host repo and its `.git` are never mounted into any container.**
- **Transport (resolves the host-mount vs stream contradiction found in review):** the workspace lives in a **size-limited named volume inside the container runtime's own filesystem** (on macOS: inside the Docker Desktop VM), not in a host bind mount and not on tmpfs. tmpfs is memory-backed and would compete with the worker memory limit on multi-GB repositories; host bind mounts add VirtioFS latency and UID/GID mismatch. The M1.5-0 benchmark confirms or revises this choice.
- `WorkspaceSnapshotter.create(execution)`: builds a standalone clone of the base ref (own `.git`, no alternates, no worktree linkage, hooks directory emptied, local `config` rewritten, `--depth` where history is not needed) and streams it **into** the volume. The host keeps only a control-plane-owned reference cache.
- **Results come out as git data, never as an extracted tarball.** The worker writes commits; the control plane retrieves a `git bundle`/fetch stream and imports it through the hardened path below. If any file bytes must be copied out (e.g. artifacts), the host extracts with Python `tarfile` `data` filter semantics (reject absolute paths, `..`, links escaping the root, device nodes, setuid bits) and size/count caps.
- Mounts into the worker: the workspace volume (rw), a size-limited `/tmp` tmpfs (`noexec`), optional `/inputs` (ro, upstream context). **Required tmpfs/volume overlays for a read-only root filesystem:** `/home/worker` and CLI cache/config directories; compatibility of the Node-based CLI with `--read-only` is an explicit M1.5-2 test. No other mounts. No host `$HOME`.
- **Import path (untrusted→trusted):** the control plane reads results using its own `git` with `-c core.hooksPath=/dev/null -c protocol.file.allow=user -c core.fsmonitor=false`, fetches the attempt's commits into a quarantine ref (`refs/astrava/quarantine/<exec>/<attempt>`) in the host repo, enforces limits (object count/size, path-component rules, no symlinks escaping the tree, no `.git*` metadata or submodule changes unless allowlisted), and only then advances `astrava/exec-<id>`. Merge into the base branch remains operator-gated and is fixed to merge **into the intended branch explicitly** (assessment G5).
- **Pre-existing fixes that gate this design (done early in M1/M2):** fail-closed on snapshot/worktree failure (G4), `merge_worktree` honoring `target_branch` (G5), `sanitize_path` using `Path.is_relative_to` (G6).

## 6. Credential strategy
| Credential | Strategy |
|---|---|
| Git credentials / SSH keys / `.gitconfig` | **Never enter a worker.** Workers cannot push; there is no remote. The commit identity is injected as inert config values by the supervisor. |
| Claude Code CLI authentication | **D1 is investigated but NOT yet verified (section 11).** No `ANTHROPIC_API_KEY` or other paid credential is ever injected. The host `~/.claude` directory, `.credentials.json` and keychain are never mounted or copied. Candidate mechanism: a dedicated, revocable long-lived subscription token (from `claude setup-token`) delivered for a single attempt through the narrowest channel the CLI supports; a credential-holding gateway is acceptable only if verified to work with the subscription login. If neither is verified, the worker milestone is blocked and the alternatives in section 11 need explicit operator approval. |
| Control-plane secrets (DB URL, `OPERATOR_API_KEY`) | Never in worker env. Worker env is built from an explicit allowlist (`LANG`, `TERM`, `HOME=/home/worker`, `PATH`, and the single model credential), not by inheriting. |
| Credential lifecycle | Created per attempt (or per execution), scoped, expires with the lease, absent from `worker_runs` (only a hash/identifier is stored), removed with the container. Redaction patterns extended and applied to **all** worker-derived text before persistence (§8). |
| Image build | No secrets at build time; no credentials baked into layers. |

## 7. Network, dependencies and malicious content
- **Agent container:** user-defined network with default-deny; egress only through `EgressProxy` to the model API host(s). DNS resolved by the proxy. Inter-container and host-network access blocked; `host.docker.internal`/metadata addresses blocked.
- **Verification container:** `--network none`.
- **Dependency installation:** a **prepare** container with package-index-only egress (via proxy allowlist), no model credential, no repo secrets, output written into a per-snapshot `deps/` directory the later containers mount read-only. Lockfile-pinned, hash-checked installs; install scripts treated as hostile (non-root, same limits). If the operator does not need installs in V1.5, prepare is disabled and verification runs on the stdlib+pytest baked into the image.
- **Malicious repository content:** assumed hostile. The repo is only ever opened by tools running inside a worker, or by the control plane's hardened git import (hooks/fsmonitor/filters disabled, `GIT_CONFIG_NOSYSTEM`, no `safe.directory` loosening). `RepoScanner` (host-side) is a host-side reader of hostile content: it moves into the verification/worker container or is limited to file-name/size metadata (explicit M1.5-4 task and test).
- **Prompt injection:** repo and web-derived text cannot widen privileges because privileges are fixed by the container, not by the prompt.

## 8. Output handling
- One result file `/workspace/.astrava/result.json` plus the git delta. Control plane enforces max sizes, schema validation, UTF-8, and path rules.
- stdout/stderr are streamed to a bounded ring buffer, redacted with an extended pattern set, then persisted. Redaction also applies to diffs and artifact text before storage and UI display; redaction failures fail closed (drop the field, record an audit event).
- Artifacts are registered by the control plane from validated paths inside the quarantined snapshot only.

## 9. Container lifecycle (state machine)
`REQUESTED → ADMITTED (budget reservation + capacity) → PREPARING (snapshot [+ deps]) → STARTING → RUNNING (lease heartbeats) → {COMPLETED | FAILED | TIMED_OUT | KILLED | LOST} → COLLECTING (validated import) → CLEANED`
Invariants: every transition recorded in `worker_runs` and the workflow event log; `CLEANED` is reached for every row that left `REQUESTED` (enforced by the reaper); a settle/release always carries the fence token.

## 10. Failure and recovery design
| Failure | Detection | Response |
|---|---|---|
| Worker exceeds wall time | Supervisor timer | `kill` (container-level, not process-level), reservation settled as timeout, retry per existing retry policy |
| Worker OOM / pids limit | exit info + cgroup events | classify FAILED(resource), count against budget, no automatic limit increase |
| Control plane crash mid-run | Startup reaper scans `worker_runs` in non-terminal states and Docker containers labelled `astrava.managed=true` | Kill+remove orphans, mark LOST, let `BudgetGovernor` reclaim expired holds, resume via existing recovery path |
| Docker daemon unavailable | `inspect()`/`start()` errors | **Fail closed:** the task fails/queues; **never fall back to host execution** (hard invariant) |
| Stale worker finishes late | fence token mismatch on settle | Rejected by existing `FencingTokenMismatchError`; output discarded |
| Orphaned processes inside container | container PID namespace + `--init` | `docker rm -f` kills the whole tree; no host PIDs involved |
| Disk exhaustion | size-limited tmpfs/snapshot quota + reaper | Fail attempt; reaper GC of old snapshots by age and by terminal state |
| Corrupt/oversized output | validation | Reject result, FAILED(invalid_output), full audit event |

## 11. Decision resolutions (D1–D6) and remaining open questions
Status key: RESOLVED = decided and designed; INVESTIGATED = facts gathered, mechanism not yet verified; BLOCKED = needs operator action or approval.

### D1 — Claude CLI credentials in the worker: **INVESTIGATED, NOT VERIFIED (potential blocker)**
Verified facts (read-only inspection of this host; no model call, no secret read):
- The CLI is 2.1.319, logged in with `authMethod: claude.ai` (subscription, plan `pro`), `apiProvider: firstParty`, login expiry 2026-11-26. Credentials are stored in `~/.claude/.credentials.json` (contents deliberately not read). No `ANTHROPIC_*` or API-key environment variables are set in the session environment.
- `claude --bare` explicitly **never reads OAuth or keychain** (auth strictly `ANTHROPIC_API_KEY` or `apiKeyHelper`) so `--bare` is incompatible with subscription auth and must not be used in workers.
- `claude setup-token` exists: "Set up a long-lived authentication token (requires Claude subscription)".
- `--fallback-model` exists (automatic model fallback); it is never passed, to prevent silent substitution.
- `claude gateway` exists ("enterprise auth/telemetry gateway"); its relevance to subscription auth is **unknown** and unexplored.
Unverified claims (third-party sources only, no official Anthropic page was found): the `setup-token` token is about one year long-lived, is consumed through a `CLAUDE_CODE_OAUTH_TOKEN` environment variable, takes precedence over stored credentials, does not refresh automatically, and can be used with `claude -p`. Treat all of this as hypothesis.
Mechanisms considered, in order of preference:
| # | Mechanism | Isolation quality | Status |
|---|---|---|---|
| A | Dedicated `setup-token` token injected for one attempt into the worker only | Medium: the agent process can read its own environment, so a prompt-injected agent could read the token; mitigated by egress allowlist (token is only useful against the model API), short lease, revocation, never persisted | Unverified; needs E1–E3 |
| B | Credential-holding gateway so the worker never sees a credential | High | Likely incompatible with subscription OAuth (CLI expects its own login); `claude gateway` unexplored; unverified |
| C | Copy or mount a subset of `~/.claude` | Low: exposes session state/history, long-lived refresh material | **Rejected** (violates the directive) |
| D | `--bare` + API key | n/a | **Rejected**: paid credential and `--bare` ignores OAuth |
Verification plan (operator-gated; none executed in this planning phase): E1 operator runs `claude setup-token` to mint a dedicated token (a credential-creating side effect, so it needs the operator); E2 in a hardened throwaway container set only that token and run `claude auth status` (no model call); E3 only if E2 recognises the token and the operator confirms extra/overage usage is disabled, one `claude -p` call. Also to confirm: Anthropic's terms permit this automated use of a subscription token (**unverified**).
**If A and B both fail:** D1 is a blocker. Alternatives that each need explicit operator approval: (1) a billed API key with a hard spend limit on a dedicated workspace; (2) run the CLI on the host under a dedicated low-privilege OS user with restricted filesystem access (weaker isolation, does not meet the container goal); (3) a cloud-provider model endpoint (billed). No alternative is adopted by default.

### D2 — Container runtime: **RESOLVED (host verified)**
Verified on this host: Docker Desktop 29.8.0 is installed and operational (daemon responds on contexts `default` -> `/var/run/docker.sock` and `desktop-linux`), macOS 27.0.1 on arm64, VM with 12 CPUs and about 8.3 GB memory, cgroup v2, `runc` 1.4.3 (the only registered runtime), built-in seccomp profile, overlayfs storage. Not installed: Podman, Colima, nerdctl, OrbStack, Lima, gVisor, Kata, Firecracker, Apple `container`. Other containers already share the VM (for example `astrava-postgres`, a second Postgres, other projects' images), so worker caps must leave headroom. No worker image exists yet. **No runtime is to be installed or replaced without operator approval.** The `WorkerRuntime` interface keeps orchestration independent of Docker. Note: because the control-plane process runs as the operator user, it will hold access to the Docker daemon; that is why authentication (M1.5-1a) gates M1.5-2.

### D3 — Dependency installation: **RESOLVED (design)**
Pinned reproducible baseline image; no task worker has package-index access; images and dependencies are built/provisioned by separate control-plane jobs (the prepare job, M1.5-3b) into a read-only, lockfile-hash-keyed `deps` volume. Missing dependencies fail the task. See Roadmap M1.5-3b.

### D4 — Fail-closed: **RESOLVED**
Isolation is mandatory. Runtime, image, workspace or security-configuration failure fails the task. No host fallback and no flag enabling one in the production path. Any development diagnostic is a separate tool outside the execution path with per-invocation opt-in.

### D5 — Model availability: **INVESTIGATED; live check WITHHELD**
`claude-haiku-5-5` is the code default and is the identifier published for the Claude 5 family in this environment's model list, so it is a plausible identifier; `--model` accepts an alias or a full name and the CLI has no model-listing command. Account-level availability is not verified. A live check was **not** made because it could not be established that overage ("extra usage") billing is off, even though auth is the subscription login. The check is part of D1 experiment E3, under the same gate. The model is never substituted and `--fallback-model` is never passed.

### D6 — Operator authentication: **RESOLVED (design); audit findings recorded**
Mandatory key on non-loopback (startup guard plus request-time guard), central enforcement, route-inventory test, server-derived audit identity, HttpOnly cookie session with CSRF so the key never reaches frontend JavaScript, and unchanged loopback development convenience. Audit result: 16 of 33 mutating routes currently have no authentication, and the 36 GET routes counted on the main routers are unauthenticated. Full table in `V1_5_TECHNICAL_RISKS.md` section 6. Scheduled in M1.5-1a.

### Remaining open technical questions
1. Does `CLAUDE_CODE_OAUTH_TOKEN` (or any supported mechanism) work with the subscription in a container, and with what revocation behaviour? (D1 E1–E3)
2. Is automated use of a subscription token within Anthropic's terms? (operator to confirm)
3. Is overage billing disabled on the subscription? (needed for any live model call)
4. What does `claude gateway` do, and can it broker subscription auth?
5. Does the CLI run correctly under `--read-only` with only the planned tmpfs/volume overlays?
6. Named volume vs tmpfs vs bind mount performance on this VM (M1.5-0 benchmark).
7. Does Docker Desktop's default seccomp profile block the syscalls the threat model assumes (`clone3`, `keyctl`, `process_vm_writev`)? A custom profile may be required.
8. Does a single-operator model remain sufficient, or must `is_authorized_verifier` become a real role before RBAC work?
