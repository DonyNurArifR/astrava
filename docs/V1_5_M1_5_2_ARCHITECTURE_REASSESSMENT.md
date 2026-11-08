# ASTRAVA V1.5 — M1.5-2 Architecture Reassessment (privilege-separated worker runtime)

**Status:** PLANNING ONLY. Proposed for operator approval. Nothing here is implemented, authorized or started: no source, migration, dependency, image build, container, Docker access grant, credential experiment, billing or deployment.
**Date:** 2026-11-08. **Base:** `28eea99` (M1.5-1c accepted with limitations).
**Relationship to the planning baseline:** `V1_5_TARGET_ARCHITECTURE.md`, `V1_5_THREAT_MODEL.md`, `V1_5_ROADMAP.md` (+A1, A2) and `V1_5_M1_5_0_DECISION_RECORD.md` are preserved unchanged. This document **amends** them where stated in section 12 (a one-line Amendment A3 is appended to the roadmap that points here). Accepted milestone history is not rewritten.
**Operator constraint driving this document:** the API process must not have Docker daemon access, must not be able to submit arbitrary Docker commands or container configuration, and no generic Docker proxy may be built.

## 1. Executive summary
1. The baseline plan had the API process (`WorkerSupervisor` inside the control plane) drive Docker. That is rejected: access to the Docker daemon is root-equivalent inside the Docker VM and, through file sharing, reaches the operator's files.
2. **Proposal:** a small **Worker Broker** is the *only* component that talks to Docker. The API speaks to it through a closed, versioned, typed contract (nine operations) over a Unix domain socket. There is no field in the contract that can carry an image name, command, mount, network, capability, environment variable or Docker option; the broker builds every container from constants plus enumerated, bounded parameters.
3. **Honest limit found by inspection of this host:** the Docker socket (`~/.docker/run/docker.sock`, `/var/run/docker.sock` symlinks to it) is owned by the operator's macOS user (`abstract`). A broker running as the *same* macOS user as the API **does not defend against code execution in the API process**: such code can open the same socket. A same-user broker removes the *confused-deputy* path (API bugs and prompt-injected API requests can no longer produce arbitrary containers) and keeps Docker out of the API code base, which is a real but smaller benefit. A hard boundary needs a different OS principal (section 5.3, tier B).
4. **Docker Desktop on macOS is not a complete sandbox.** It is a useful hardening layer for a single operator running semi-trusted agents on their own repositories (strictly better than today's direct host execution), and it is not a boundary against a determined attacker who owns a container-escape exploit (sections 7 and 8).
5. **Containers alone fix less than the plan implied.** Several debts are only closed by the *design* choices below (tree export, raw object snapshotting, artifact copy-out), not by "moving processes into containers" (section 9).
6. **Proposed sequence:** split M1.5-2 into 2a (contract, broker skeleton, fake runtime; no Docker), 2b (broker Docker backend, hardened spec, harmless test workload; Docker access for the broker only, separate approval), 2c (workspace transfer and artifact copy-out). Verification containerization can ship before the credential decision D1 is solved (section 13).

## 2. Verified facts about this host (read-only checks, 2026-11-08)
| Fact | Value | Consequence |
|---|---|---|
| Runtime | Docker Desktop 29.8.0, `linux/arm64`, kernel `7.0.12-linuxkit`, cgroup v2, runtime `runc` only | No gVisor/Kata/Firecracker on this host; "stronger runtime later" is a Linux-host option, not available here |
| Daemon socket | `~/.docker/run/docker.sock` owned by `abstract`, mode `srwxr-xr-x`; `/var/run/docker.sock` is a symlink to it (owner `root`, link only) | Any process of the operator's user can use the daemon; by the mode bits other macOS users cannot connect (connecting to a Unix socket needs write permission); not tested with a second account |
| OS users | one human account (`abstract`) plus system accounts | Tier B (separate API user) needs the operator to create a user; it does not exist today |
| Other containers | `astrava-postgres` published on `0.0.0.0:5433`, unrelated `bl-pg` on `0.0.0.0:55432` | Pre-existing: the control-plane database is reachable on all host interfaces with a development password, and from containers through the host gateway. Recommend binding to `127.0.0.1` (operator action; **not performed**) |
| VM sharing | Docker Desktop settings file has no file-sharing keys, so defaults apply (VirtioFS sharing of user directories) | Any bind mount or VM-root compromise reaches shared host paths as the operator. File-sharing scope cannot be enforced from code; the design therefore forbids bind mounts entirely |
| Resources | about 12 CPUs, about 8.3 GB VM memory shared by all containers | Global caps must stay well under the VM size; exhaustion affects unrelated projects in the same VM |

## 3. Components
| # | Component | Trust | Responsibility | Must never |
|---|---|---|---|---|
| 1 | **API / control plane** (FastAPI, runner, `BudgetGovernor`, lease/epoch from M1.5-1c) | Trusted but assumed *compromisable* | Orchestration, budgets, approvals, `worker_runs` persistence, result validation, artifact registration, audit | Import a Docker client, open any Docker socket, name an image/command/mount/network, hold the model credential |
| 2 | **WorkerRuntime** (Python protocol inside the API) | Part of API | Narrow interface the runner calls; implementations: `BrokerWorkerRuntime` (production), `FakeWorkerRuntime` (tests) | Expose Docker types |
| 3 | **Worker Broker** (separate process, new package, no DB credentials, no model credential) | Privileged, small, security-critical | Authenticate the caller, validate every request against the closed contract, build the container from constants, enforce limits and global caps, own the Docker connection, run the deadline reaper, audit every request | Forward arbitrary Engine API calls (no generic proxy), accept paths/images/commands/mounts from the caller |
| 4 | **Agent container** (ephemeral, per task attempt) | Untrusted | Run one agent invocation inside the workspace volume | See Docker, the host, the control plane, other workers, credentials beyond the single approved model credential (D1) |
| 5 | **Verification container** (ephemeral, per verification run, separate from agent) | Untrusted | Run deterministic checks on a read-only copy of the deliverable, `--network none` | Reach any network, write to the deliverable |
| 6 | **Egress proxy** (only if/when D1 provides a model path) | Semi-trusted | Allowlist the model API host only | Terminate TLS for credential injection unless D1 decides so; reach private ranges |
| 7 | **Image supply chain** | Trusted by pinning | Pinned-digest minimal images built outside the API by a recorded build step | Be built or pulled from within a task |

## 4. Trust-boundary diagram
```
 Z0 OPERATOR (browser/CLI) ───HTTPS/loopback, key+cookie+CSRF (M1.5-1a)───┐
                                                                         ▼
 ┌──────────────────────────── Z1 CONTROL PLANE (host, OS principal P_api) ─────────────────────┐
 │  FastAPI + runner + BudgetGovernor + lease/epoch (M1.5-1c)   PostgreSQL (worker_runs,        │
 │  holds: DB credentials, operator key.  Holds NO docker socket, NO model credential.          │
 │  Allowed outbound to Z2 only: BrokerWorkerRuntime (typed requests)                           │
 └───────────────┬──────────────────────────────────────────────────────────────────────────────┘
   TRUST BOUNDARY 1 │ Unix domain socket (dir mode 0700, peer-credential check, signed requests)
                    ▼ closed contract, strict schema, no passthrough fields
 ┌──────────────────────────── Z2 WORKER BROKER (host, OS principal P_broker) ──────────────────┐
 │  validates → builds container spec from CONSTANTS + enums → audits → talks to Docker         │
 │  holds: Docker socket, broker config (repo allowlist, image digests, profiles), audit log.   │
 │  Reads host repos (read-only, hardened git plumbing) to build snapshots. Writes NO host repo.│
 └───────────────┬──────────────────────────────────────────────────────────────────────────────┘
   TRUST BOUNDARY 2 │ Docker Engine API over the Docker Desktop socket (broker only)
                    ▼
 ┌──────────────────────────── Z3 DOCKER DESKTOP LINUX VM (shared, one per host) ───────────────┐
 │  dockerd (root in VM) · VirtioFS shares of host dirs (default scope!) · other projects' containers
 │  ┌─────────── TRUST BOUNDARY 3 (namespaces, cgroups, seccomp, caps, no-new-privileges) ──────┐│
 │  │ Z4 WORKERS (untrusted)                                                                    ││
 │  │  agent container     : no mounts but its own volume, rootfs ro, internal net (or none)    ││
 │  │  verification cont.  : read-only input volume, --network none                              ││
 │  │  egress proxy (opt.) : allowlist to model API host only                                    ││
 │  └────────────────────────────────────────────────────────────────────────────────────────────┘│
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
 Data crossing 2→1 (results, logs, exported tree) is ADVERSARIAL OUTPUT: size-bounded and validated
 by the broker, then validated again and redacted by the API before any persistence or display.
```
Boundary 1 is only a *hard* boundary in tier B (different OS principal). In tier A it is a confused-deputy and code-hygiene boundary (section 5.3).

## 5. Privilege separation design
### 5.1 Why a broker and not a Docker proxy
A proxy that filters Engine API calls must understand the whole Docker API surface (create options, exec, copy, build, plugins, swarm, events) and any gap is a bypass. The broker has **nine typed operations** and *constructs* containers; it never relays requests. Anything not in the contract does not exist. This is the single most important property and it is testable (section 14).

### 5.2 Contract design rules
1. Closed set of operations (section 6). Unknown operation, unknown field, wrong type, out-of-range number: rejected (`422`-style error), logged, no side effect.
2. The caller names **logical aliases** only: `image_alias` in a broker-config enum, `profile` in a broker-config enum, `repo_id` registered in broker config. The caller never supplies a filesystem path, image reference, command, argument, environment, mount, network, capability, user, device, port, label or Docker option.
3. Free-form *data* the caller may send is limited to: the agent prompt / job payload (bytes, size-capped, written into the workspace volume as a file, never interpreted by the broker) and a base ref validated with the existing `validate_ref_name` rules.
4. Every request carries `request_id`, `worker_run_id` (idempotency key), `execution_id`, `lease_epoch`. Replays of the same `request_id` return the first result. The broker keeps a small append-only request ledger in its private directory so replay protection and idempotency survive a broker restart (a replay older than the nonce window is rejected outright).
5. Limits come from the **profile**; the caller can only pick a profile or request values **lower** than the profile (bounded below by broker minima).
6. Every request and decision (including rejections) is appended to a broker-owned audit log with the spec hash. The audit log is not writable by the API principal.

### 5.3 Authentication and authorization between API and broker
| Layer | Mechanism | Tier A (same macOS user, today's single-user host) | Tier B (hardened) |
|---|---|---|---|
| Transport | Unix domain socket only (no TCP listener). Socket in a directory created `0700` by the broker | Same user can open it | Directory ACL grants only `P_api`; kernel peer credentials (`LOCAL_PEERCRED`/`getpeereid`) checked on every connection |
| Message authentication | HMAC-SHA256 over canonical request + timestamp + nonce, key in a file readable only by the two principals | **No real separation**: same-user code can read the key | Real: other principals cannot read the key or connect |
| Authorization | Per-operation allowlist; a worker can be acted on only via the `worker_run_id` the broker created for that `execution_id`; global/per-execution caps; no operation lists or touches containers without the `astrava.managed` label | Same | Same |
| Docker access | Broker only. API code and process have no Docker client import and no socket path configured (static test, section 14) | Same user could still open the socket directly: **accepted residual in tier A** | `P_api` cannot connect to the Docker socket at all |
| Meaning | | Eliminates confused-deputy and injection-driven arbitrary containers; does **not** stop code execution inside the API | Stops a compromised API from reaching Docker |
Tier B requires the operator to create a separate macOS user for the API (and keep `~/.claude`, SSH keys, Docker Desktop and the broker under the operator's own user). That is an operator action; it is not performed here. The software must be identical for both tiers. A startup check in the broker reports which tier is in effect (compares peer uid with its own) and the audit log and documentation state it plainly. **Recommendation:** run tier A only for loopback single-operator development, and require tier B before any exposure beyond loopback or any use on repositories whose content you do not control.

### 5.4 Broker hardening
No database credential, no model credential, no operator key; minimal dependency set; runs under its own process; resource-limited; its Docker calls are a fixed small set (create container/volume/network, start, inspect, kill, remove, logs, archive get for the bounded export); refuses to start if the configured image digests are not present locally (`--pull never`; no registry access at runtime); refuses to create anything when the VM disk/memory headroom check fails.

## 6. API-to-broker contract (wire-level, v1)
Transport: length-prefixed JSON over UDS. All requests: `{v:1, op, request_id, worker_run_id, execution_id, lease_epoch, ts, nonce, mac, args}`. Responses: `{ok, code, worker_state?, result?}`; error codes are an enum (`invalid`, `denied`, `capacity`, `conflict`, `not_found`, `timeout`, `runtime_unavailable`, `internal`). **`runtime_unavailable` always fails closed; no host fallback.**
| Op | Args (all closed, bounded) | Effect | Returns |
|---|---|---|---|
| `create_worker` | `kind` ∈ {agent, verify, prepare*}, `image_alias`, `profile`, `repo_id`, `base_ref`, `task_id`, `attempt`, `wall_timeout_s` (≤ profile cap), `job` (≤ 256 KiB bytes), `input_ref` (verify only: an earlier worker_run_id; the broker resolves it **only inside the same `execution_id`** through its quarantine directory naming and rejects any mismatch), optional `credential_handle` (D1; absent until decided) | Admission checks, build snapshot into a new volume, create (not start) container. Idempotent on `worker_run_id` | `worker_id`, state `CREATED` |
| `start_worker` | none | Start; broker records deadline = now + `wall_timeout_s` | state `RUNNING` |
| `get_status` | none | Inspect | state, exit code, reason, started/finished, resource peaks |
| `collect_output` | `max_bytes` ≤ cap | Bounded log ring buffer (stdout/stderr), plus `result.json` (≤ 256 KiB) if present | log bytes, result bytes, truncation flags (adversarial; API redacts) |
| `export_artifacts` | `max_files`, `max_bytes` ≤ caps | **Precondition: worker state is EXITED, KILLED or TIMED_OUT** (never while running, so files cannot change mid-archive). Broker computes the **changed-path set against the baseline manifest it recorded at snapshot time**, applies the strict filter of section 9.2 to those paths only, extracts them into a quarantine directory bound to `<execution_id>/<worker_run_id>`, returns a manifest and a sha256-addressed stream of validated regular files | manifest + file stream |
| `terminate_worker` | `grace_s` ≤ 30 | `kill` then wait; idempotent | state `KILLED`/`EXITED` |
| `cleanup_worker` | none | Remove container, volume, network attachments **and the host quarantine directory** of this worker; idempotent; refuses if still running | state `CLEANED` |
| `list_workers` | optional `execution_id` | Reconciliation view built from labels the broker itself set (`astrava.managed`, `worker_run_id`, `execution_id`, `lease_epoch`, `deadline`) | list of worker summaries |
| `health` | none | Daemon reachability, capacity, tier, config digests | status |
\*`prepare` (dependency install) is reserved for M1.5-3b and not enabled in 2a-2c.
Explicitly **absent**: exec, attach, copy-in of arbitrary paths, build, pull, push, network/volume/image management, events, inspect-arbitrary, privileged anything.

## 7. Threat model (additions and re-evaluation; baseline topics 1-18 remain valid)
Ratings are qualitative; no percentage is claimed.
| # | Threat | Vector | Controls (design) | Residual risk | Test |
|---|---|---|---|---|---|
| T1 | Docker socket / daemon compromise | Code in API gets the socket; worker gets the socket | API has no Docker client/socket config (static guard); broker only; socket never mounted into any container (spec has no mounts except its own volume); tier B OS separation | Tier A: same-user code in the API process can open the socket. Tier B: broker compromise = daemon control | Static import/path guard; golden spec has no `docker.sock`; probe from inside worker finds no socket |
| T2 | Host filesystem exposure | Bind mount, Docker Desktop VirtioFS shares, snapshot code reading outside the repo | **No bind mounts, ever** (named volume + tmpfs only); broker builds snapshot via plumbing from a registered repo root (reuses `path_security` rules, `ALLOWED_REPO_ROOTS` equivalent in broker config the API cannot edit); no host `HOME` | VM-root compromise still sees shared host paths (default scope) as the operator; operator should narrow Docker Desktop file sharing | Escape-attempt suite reads `/Users`-style paths from inside; fails |
| T3 | Container escape (kernel/runc/VM) | Kernel or runc bug | cap-drop ALL, no-new-privileges, default+explicit seccomp, rootfs ro, non-root, PID/mem limits, no host namespaces; Linux VM boundary (hypervisor-based; implementation not verified) | **Unfixable by design here**: shared VM kernel, `runc` only; VM runs as the operator, so an escape yields operator-level, not root-level, host control. Not a boundary against a determined exploit owner | Seccomp behavior asserted by observation, not assumption |
| T4 | Malicious repository content | Hooks, `.gitattributes` filters, symlinks, hardlinks, submodules, huge/deep trees, `.git` metadata smuggling, fsmonitor/pager/sshCommand in repo config | Snapshot built only with plumbing (`ls-tree`/`cat-file --batch`, no checkout, no filters/attributes); refuse repos whose `.git/config` contains denied keys; symlinks/submodules/gitlinks not copied as live links; path rules from `path_security`; caps on count/size/depth | Parsers of git objects on the host remain a hostile-input surface (smaller than today) | Hostile-repo fixtures (as in M1.5-1b), tar/zip-slip fixtures |
| T5 | Malicious agent commands | Prompt injection making the agent run `rm -rf`, fork bombs, miners | Everything runs in an ephemeral container with its own volume; limits; wall-clock kill by broker; nothing persists except the validated export | Damage to the workspace copy itself (intended); CPU burn bounded by limits | Fork/memory/disk bomb tests hit limits and are killed |
| T6 | Credential exfiltration | Agent reads env/files, sends out | No host credentials mounted; workers have no `HOME` from host; env from constants; only a single model credential if D1 ever allows (not designed or claimed here); network egress none/allowlist | D1 unresolved: if a model credential exists in the worker, a prompt-injected agent can read it and send it to the model host or encode it in model-bound traffic | Env/file inventory test inside worker; DNS/HTTP egress negative tests |
| T7 | Network exfiltration / lateral movement | Agent calls out, scans host gateway, reaches Postgres/API/other containers, `host.docker.internal` | Worker networks are `--internal` (no gateway) or `none`; egress only via the allowlist proxy, which must deny RFC1918/link-local/loopback targets; broker never attaches workers to bridge/host networks | Proxy misconfiguration; DNS tunnelling through the proxy resolver; Docker Desktop host-gateway behavior must be **verified**, not assumed | Probes to gateway, `host.docker.internal:5433/8000`, `169.254.169.254`, DNS exfil |
| T8 | Privileged container creation | A forged or buggy request asks for privileged/host-PID/caps/devices | Contract has no field for them; spec builder is the only call site; golden test pins `Privileged=false`, `CapDrop=[ALL]`, `PidMode`/`IpcMode`/`UTSMode`/`UsernsMode` default, no `Binds`, no `Devices` | A bug in the broker spec builder; mitigated by golden + mutation tests | Golden HostConfig test, mutation of each field |
| T9 | Host namespace access | `--pid=host`, `--net=host`, userns host | Same as T8; labels used to ignore foreign containers | Same as T8 | Golden test |
| T10 | Resource exhaustion | CPU/mem/PID/disk/log/FD, many workers, VM-wide exhaustion hurting unrelated containers | Per-profile cgroup limits, ulimits, volume/tmpfs sizes, log ring buffer, export caps, global concurrency and disk caps below VM capacity, headroom check, admission control with `capacity` errors | Docker Desktop VM is shared: a runaway can still degrade other projects before the reaper acts | Limit tests for each dimension, concurrency cap test |
| T11 | Stale workers and cleanup failures | API/broker/daemon crash, late results, leaked volumes | Broker deadline reaper independent of the API; labels carry `lease_epoch`; API recovery (M1.5-1c) terminates stale-epoch workers *before* expiring their reservations; late results discarded by fencing; cleanup retried and flagged `CLEANUP_FAILED`; age-based GC; start-up reconciliation | Cleanup of the Docker VM itself can fail silently; operator alerts needed | Crash tests extending M1.5-1c (SIGKILL API/broker mid-run) |
| T12 | Compromised API-to-broker channel | Local process connects/injects, replay, MITM on the socket | UDS only, private directory, peer credentials (tier B), HMAC with nonce+timestamp window, strict schema, idempotency; no network listener | Tier A: same-user attacker bypasses all of it | Unauthorized/replayed/malformed request tests |
| T13 | Broker authn/authz failures | Missing checks, confused deputy | Deny by default; operations bound to worker/execution; rejections audited | Broker bug | Negative test per operation |
| T14 | Supply chain (worker images, tooling) | Poisoned base image, npm/pip packages, unpinned CLI | Digest-pinned minimal base, no `latest`, recorded reproducible build outside the API, SBOM and vulnerability scan as a build step, broker allowlists image digests and uses `--pull never`, install of the agent CLI pinned with integrity hash, no secrets at build time | Upstream compromise before pinning; scanners find only known issues | Digest check test; image content inventory test |
| T15 | Output injection | Logs/results with terminal escapes, HTML, secrets | Bounded buffers, redaction, escaping on display (baseline §8) | Redaction patterns incomplete | Fixture suite |

## 8. Does Docker Desktop on macOS provide the intended boundary?
**Verdict: partial.** What it gives: a Linux VM (a hypervisor-based VM; the exact VM implementation was not verified on this host) between workers and macOS, namespace/cgroup isolation inside the VM, no shared PID/IPC/UTS/network with the host, and easy ephemeral lifecycle. What it does **not** give, and what the design must not rely on:
1. **Not rootless Docker.** `dockerd` is root in the VM; VM-root can reach host paths shared by VirtioFS. Default sharing is broad. Mitigation: no bind mounts in our spec; the operator narrows file sharing; residual remains after an escape.
2. **The VM runs as the operator**, so even a perfect escape is operator-level code execution on macOS (including `~/.claude`, SSH keys, Keychain access paths that are unlocked), not root. That is the realistic ceiling of harm and equals today's exposure from running agents directly on the host, but today it requires no exploit at all.
3. **One shared VM and kernel** for every project's containers; no per-worker VM; `runc` only. No gVisor/Kata/Firecracker on macOS. Enhanced Container Isolation is a paid feature and is not assumed.
4. **Host gateway reachability** (`host.docker.internal`, host-published ports such as Postgres `5433`) is a Docker Desktop behavior that must be verified at implementation time; the plan uses `--internal` networks and an explicit negative test rather than trusting documentation.
5. **Limits enforcement is cgroup v2 inside the VM**; the VM's total memory (about 8.3 GB) is the real ceiling.
6. **Fit:** acceptable for a single operator, semi-trusted agents on the operator's own repositories, loopback API, tier B recommended. Not acceptable as the boundary for multi-tenant execution, hostile-code-at-scale, or any scenario needing a stronger isolation claim; those need a dedicated Linux host with rootless runtime/microVMs, reachable through the same `WorkerRuntime`/broker contract.

## 9. Workspace and artifact transfer design
### 9.1 Snapshot-in (host → worker)
1. The caller sends `repo_id` + `base_ref`. The broker maps `repo_id` to a root in **its own** config (not editable by the API principal) and re-applies the M1.5-1b repository checks.
2. The broker resolves `base_ref` to a commit with `rev-parse --verify` and reads the tree with **plumbing only**: `ls-tree -r -z` and `cat-file --batch`. No checkout, no working-tree access, no clean/smudge filters, no `.gitattributes`, no hooks, no `export-subst`. Git runs with the hardened environment from M1.5-1b and with a scan that refuses repositories whose `.git/config` contains denied keys (`include*`, `filter.*`, `core.fsmonitor`, `core.hooksPath`, `core.sshCommand`, `core.pager`, `diff.external`, `credential.*`, `url.*.insteadOf` …).
3. Entries are copied by policy: regular files and directories only; symlinks, gitlinks/submodules, special modes are recorded in a manifest but **not** materialized; path rules from `path_security` (component ban of `.git`, control/format/NFKC look-alikes, depth, count and size caps).
4. The tree is streamed into a **new named volume inside the Docker VM** (no host bind mount) and a fresh `git init` baseline commit is made *inside* the container image's entrypoint with an inert identity. The host repository, its `.git`, hooks and config are never mounted.
### 9.2 Export-out (worker → host): tree export, not git objects
The baseline plan imported agent-authored git bundles. This reassessment **replaces that with tree export** (amendment, section 12) because it removes a whole parser attack surface (pack/index/object/ref parsing, hooks, config smuggling, submodules, `.gitmodules`, replace refs) from the privileged side:
1. At collection (worker already stopped) the broker diffs the volume against the baseline manifest recorded at snapshot time and streams only **changed, added and deleted paths** through a strict filter (deletions are reported in the manifest, never applied by the broker): only regular files and directories; no symlinks or hardlinks (rejected, not followed); no device/fifo/socket nodes; no setuid/setgid/sticky; `.git` anywhere in the path is dropped (agent-created git state is never exported); path rules from `path_security`; limits on file count, depth, per-file and total bytes; NFKC and case-collision checks.
2. Extraction into the broker-private quarantine uses descriptor-relative creation with `O_NOFOLLOW`/`O_EXCL` into a directory that **no worker and no API process can write**. Because no hostile process runs concurrently on the host side, the intermediate-directory TOCTOU window of M1.5-1b does not exist on this path.
3. The broker returns a manifest of `{path, size, sha256, mode}` and the file stream. The API re-validates, stores each deliverable in the **artifact store addressed by sha256**, and registers it with `ArtifactService` (ownership, provenance `source="worker"`, `registered_by` the run). Artifacts therefore no longer depend on a worktree that is later removed.
4. A change set against the base tree is computed on the control-plane side; **the commit is created by the control plane**, with a fixed identity, in a control-plane-owned worktree or integration branch through the hardened git path. Agent-authored commits, refs and objects are never imported.
### 9.3 Verification containers
A verification container receives the exported tree as a **read-only** input volume (a copy produced by the broker from the validated quarantine), `--network none`, its own writable tmpfs, strict limits; it returns a structured report (bounded) through `collect_output`. It never sees the agent's writable volume and cannot alter the deliverable.

## 10. Worker lifecycle, persistence and recovery
### 10.1 Lifecycle (broker view, mirrored in `worker_runs`)
`REQUESTED → ADMITTED (capacity + budget reservation exists) → CREATED (snapshot volume + container, not started) → RUNNING → {EXITED | KILLED | TIMED_OUT | LOST} → COLLECTED → CLEANED`, plus `CLEANUP_FAILED` (retry, alert). Every transition is persisted by the **API** in `worker_runs` (new table, a migration in M1.5-2a) together with the reservation id, fence-token hash, `lease_epoch`, image digest, applied limits, container id; the broker keeps only labels and its own audit log (no database access).
### 10.2 Recovery (builds on M1.5-1c)
1. **Broker-local safety net:** every worker has a deadline label; the broker reaps overdue or unlabeled-epoch-stale workers even when the API is dead, and refuses new work when the daemon is unavailable.
2. **API recovery order** inside `recover_execution`: claim the execution lease → `list_workers(execution_id)` → terminate and clean every worker whose `lease_epoch` is older than the new epoch → **only then** expire orphaned reservations (so no live worker is consuming a reservation that is being force-settled) → re-enter the graph. A late result from a stale-epoch worker is discarded by the existing fencing (fence token + epoch) and its export is never registered.
3. **Broker restart:** reconstructs from labels, resumes deadline enforcement, never starts anything.
4. **Daemon unavailable:** `runtime_unavailable` → task fails closed (DR-06/DR-07). No host fallback, no flag.
5. **At-least-once semantics are unchanged:** a model call that was in flight in a killed worker may be repeated; the design neither adds nor claims exactly-once.
### 10.3 Cleanup failures
Idempotent `cleanup_worker` with backoff; leftover volumes and containers are found by label and garbage-collected by age; a global disk quota check blocks new creation; `CLEANUP_FAILED` is surfaced in health and audit.

## 11. Network, credentials, resource limits
### 11.1 Network and credential design
- Verification and (until D1) agent containers: `--network none`. Agent containers use a deterministic stub entrypoint in M1.5-2 testing, so no model access and no credential is needed.
- When D1 is resolved by the operator: agent containers join an `--internal` network whose only peer is the allowlist egress proxy. The proxy denies private, loopback and link-local destinations and resolves DNS itself. How the model credential reaches the worker is **not designed here**: D1 stays BLOCKED, subscription credential injection stays prohibited (Consumer Terms section 3.7, DR-11), no API billing without separate approval (DR-12). The contract keeps an optional `credential_handle` slot that the broker rejects until D1 has an approved arrangement.
- Control-plane secrets (DB URL, operator key) never exist in broker or worker environments. Worker env is a constant allowlist. No Git credentials, no remote, no push.
### 11.2 Resource limits (broker-enforced profiles; initial values to be validated by a benchmark in 2b)
| | Agent profile | Verify profile | Global |
|---|---|---|---|
| CPU | 2 | 2 | worker count cap default 2 |
| Memory (no swap) | 4 GiB | 2 GiB | total workers ≤ 50% of VM memory |
| PIDs | 256 | 128 | |
| Wall clock | 600 s (cap 1800 s) | 300 s | broker-enforced kill |
| Writable disk | 2 GiB volume (cap 5) | 512 MiB tmpfs `noexec` | total volumes ≤ configured quota |
| Logs | 1 MiB ring | 1 MiB | |
| Result / export | `result.json` ≤ 256 KiB; **changed/new** files only: ≤ 5000 files, ≤ 100 MiB (baseline size is not capped by this; a separate baseline snapshot cap applies at create) | report ≤ 256 KiB | |
| Other | `nofile` 1024, core dumps off, rootfs read-only, user ≥ 10000, `--init`, no-new-privileges, cap-drop ALL, explicit seccomp profile | same | |
Size-limited volumes: whether the Docker Desktop storage driver can enforce a quota is **unverified**; fallback is broker polling with kill on overrun. Decided by the 2b benchmark, not assumed.

## 12. Amendments to the baseline documents (traceable)
| Baseline statement | Amendment |
|---|---|
| Target Architecture §3 item 2: `WorkerSupervisor` in the control plane drives Docker | Superseded: supervision logic lives in the **Worker Broker**; the API holds only `BrokerWorkerRuntime` and the `worker_runs` records |
| Target Architecture §5: results come out as a git bundle imported into a quarantine ref | Superseded by **tree export + control-plane commit** (section 9.2) |
| Target Architecture §5: workspace snapshot as standalone clone | Refined: raw-object snapshot via plumbing, no clone/checkout on the host, no agent-visible git history |
| Decision record DR-02: Docker is the initial `WorkerRuntime` target | Unchanged, but Docker is reachable only from the broker; "gVisor later" noted as unavailable on this host |
| Roadmap M1.5-2 "gives the API process Docker access" | **Withdrawn.** The API never gets Docker access (operator directive) |
| Roadmap M1.5-3 (snapshot + hardened git import) | Largely absorbed into 2c; remainder re-scoped in section 13 |
| Threat model §6 topic 17 (worker-to-control-plane auth) | Unchanged (no worker→API channel); new trust boundary API→broker added (T12, T13) |
The original files are not edited. Appended: Amendment A3 in `V1_5_ROADMAP.md` pointing here, ADR-028 (Proposed) in `DECISIONS.md`.

## 13. Existing security debt: what the design actually addresses
| Debt | Does the design address it? | How / when |
|---|---|---|
| Worktree artifacts not retrievable through the artifact API | **Yes, by design** | Artifacts are copied out at `export_artifacts`, validated, stored in the sha256-addressed artifact store and registered (2c). Container use alone would not fix it. |
| Intermediate-directory TOCTOU | **Yes for the worker path**, not for the legacy host path | No hostile process writes to the host quarantine while it is populated (2c). Stays open for host-executed agents until the agent cutover. |
| Other repo-local Git configuration | **Partly** | Plumbing-only snapshot plus denied-key scan of repository config (2c); agent-authored git state is never imported. The merge into the operator's repository still uses the host repo's config → handled when the merge path is reworked (M1.5-3), residual until then. |
| Tracked-files-only dirty check | **No** | Containers do not touch it. Scheduled into M1.5-3 (merge path): check tracked **and** untracked collisions before merge. Remains open until then. |
| Host-side repository parsing and verification (SD-07) | **Not by M1.5-2**; yes at cutover | `RepoScanner` and verification move into containers at the verification cutover (4v) and agent cutover (4). Open until then. Git object parsing on the host shrinks to plumbing reads. |
| Subscription credential restriction | **Preserved, unsolved** | D1 BLOCKED; no mechanism designed or claimed; the contract rejects `credential_handle` until approved. |
| Unverified model availability (D5) | **Preserved** | M1.5-2a-2c use a deterministic stub workload; no model call, no live check. |
| M1.5-1c at-least-once provider invocation | **Preserved** | See 10.2 item 5. |
| M1.5-1c stale agent file side effects | **Improved at cutover** | Worker volumes are removed with the container; shared host work directory no longer exists for worker-executed tasks. |
| M1.5-1a residual risks (shared key, in-memory revocation, …) | **Unchanged** | Out of scope. |
New findings recorded: Postgres published on all interfaces with a development password (recommend `127.0.0.1` binding, operator action); Docker Desktop file sharing defaults; same-user broker is not a boundary against API code execution.

## 14. Testing strategy
1. **Contract tests (no Docker):** schema accept/reject matrix; unknown fields and operations rejected; limits above profile rejected; idempotency; replay/nonce/timestamp rejection; authorization per `worker_run_id`; **no passthrough** property test (fuzz arbitrary keys: none may reach the spec builder).
2. **Static guards:** the `app` package contains no import of any Docker client and no reference to a Docker socket path; the broker package imports no `app.db`/settings secrets; the spec builder is the only function constructing container configuration.
3. **Golden spec tests:** the complete generated container spec for each profile is pinned; mutation tests flip each hardening field (privileged, caps, binds, network mode, pid/ipc/uts/userns, read-only rootfs, user, limits) and the suite must fail for every flip.
4. **Fake-runtime orchestration tests:** lifecycle, retries, recovery ordering, fencing with `FakeWorkerRuntime`, extending the M1.5-1c real-process SIGKILL harness to SIGKILL the API and the broker mid-worker.
5. **Docker-backed tests (opt-in marker, operator-approved milestone only):** harmless test image; limits (fork bomb, memory bomb, disk fill, log flood, FD exhaustion); escape-attempt probes from inside the worker: Docker socket paths, host paths, environment and file inventory, `host.docker.internal`/Postgres/API/metadata reachability, DNS and HTTP egress, privilege and capability checks, seccomp observations; cleanup and orphan tests (kill daemon connection, kill broker, restart).
6. **Transfer tests:** hostile trees (symlink, hardlink, device, setuid, `.git`, Unicode look-alike, deep/huge, case-collision) in both directions; tar-slip style fixtures; artifact registration with ownership checks.
7. **Mutation testing** on validators, fencing and the recovery ordering, as in M1.5-1b/1c.
8. **Independent review** by Agy of every milestone, and an adversarial review of the contract before any Docker code exists.

## 15. Residual risks (stated plainly)
1. Tier A is not a boundary against code execution in the API process; tier B needs an operator-created OS user.
2. Docker Desktop shares one VM and kernel; escape yields operator-level control of the Mac; default file sharing is broad.
3. The broker is a new privileged component: a bug in its spec builder or snapshot reader is a direct risk. Mitigated by size, golden/mutation tests and review, not eliminated.
4. Git object parsing remains a host-side hostile-input surface (plumbing reads).
5. At-least-once model invocation; no exactly-once claim.
6. D1 and D5 unresolved; agents cannot be containerized for real work until D1 is decided by the operator.
7. DNS or covert-channel exfiltration through an allowlisted proxy is reduced, not eliminated.
8. Resource exhaustion of the shared VM can hurt unrelated projects before the reaper reacts.
9. Operator-side configuration (file-sharing scope, Postgres binding, tier B user) is outside what code can enforce.

## 16. Revised milestone dependency graph and proposed implementation sequence
Original IDs stay traceable; sub-milestones refine, they do not rename history.
```
M1.5-0   reduced decision record ........................ DONE (a4c1d1e)
M1.5-1a  operator authentication + audit identity ........ ACCEPTED (02edb00)
M1.5-1b  containment, provenance, fail-closed setup ...... ACCEPTED (552165c)
M1.5-1c  recovery, lease/epoch fencing, retry attempts ... ACCEPTED WITH LIMITATIONS (28eea99)
   │
M1.5-2a  contract + broker skeleton + FakeWorkerRuntime + worker_runs
         (NO Docker; migration; static guards) ........... needs 1c        — proposed
   │
M1.5-2b  broker Docker backend: hardened spec builder, Engine API client over UDS,
         pinned harmless test image, limits + escape-probe suite
         (Docker access for the BROKER only; image build) . needs 2a + explicit operator approval for Docker/image build
   │
M1.5-2c  workspace transfer: raw-object snapshot-in, tree export-out, artifact store
         copy-out, quarantine, hostile-tree suite ......... needs 2b           (absorbs most of original M1.5-3)
   ├─► M1.5-3   merge-path rework: control-plane commit, tracked+untracked dirty check,
   │            repo-config handling for merge ............. needs 2c
   ├─► M1.5-3b  controlled dependency preparation .......... needs 2c (reads lockfiles from the repo snapshot)
   ├─► M1.5-4v  verification cutover: RepoScanner + VerificationEngine into
   │            --network none containers; host verification removed
   │            (closes the verification half of SD-07; does NOT need D1) ... needs 2c, 3b optional
   └─► M1.5-4a  credential strategy ........................ BLOCKED by D1 (unchanged)
M1.5-4   agent cutover to containers (host agent path removed) .. needs 1c, 2c, 3, 4v, 4a  → BLOCKED via 4a
M1.5-5   integration, UI, leases, recovery ................. needs 4, 3b
M1.5-6   adversarial acceptance and freeze ................. needs 5
```
**Proposed implementation sequence for approval (nothing starts until you approve a step):**
1. **Step 0 (operator decisions, no code):** accept tier A for development / require tier B before exposure; narrow Docker Desktop file sharing; rebind Postgres to `127.0.0.1`; confirm that the broker may be a separate Python process in this repository; decide whether to create a separate macOS user for tier B.
2. **M1.5-2a** (authorize first): contract schemas, broker skeleton with a fake backend, `BrokerWorkerRuntime`, `FakeWorkerRuntime`, `worker_runs` migration, recovery-order integration, static guards, contract/mutation/SIGKILL tests, Agy design and implementation review. No Docker, no image, no container.
3. **M1.5-2b** (separate approval, includes Docker access for the broker and the first image build): hardened backend and probes against a harmless image; benchmark for volume quotas and `--internal` network behavior; seccomp observation.
4. **M1.5-2c** (separate approval): transfer design, artifact copy-out, hostile-tree suite.
5. Then 3 / 3b / 4v in dependency order, each separately authorized. 4a/4/5/6 stay blocked by D1.
Host quarantine directories are purged by `cleanup_worker` and by the age-based GC. Tree export squashes an attempt to its final changed paths: intermediate agent commits and `.gitattributes` effects are intentionally not preserved.
Each step ends with the standard evidence report, independent review and a STOP.

## 16a. Independent review record
Agy architecture review: no Critical findings; **ACCEPT WITH CHANGES**. Adopted: H-01 (export only changed paths, separate caps), H-02 (3b needs 2c), M-01 (export only after the worker stopped), M-02 (cross-execution `input_ref` bound by quarantine naming), M-03 (quarantine purge), L-01 (persistent request ledger). Agy's review confirmed the host facts in section 2 and found section 13 honestly classified; it could not verify Docker Desktop internals beyond what was inspected.

## 17. Open questions for the operator
1. Tier A (dev only) acceptable now, with tier B required before non-loopback use?
2. May 2a introduce a migration (`worker_runs`) and a new top-level package for the broker?
3. Dependency policy for the broker: prefer the standard library plus the already-present `httpx` over a Unix socket instead of adding the Docker SDK. Acceptable?
4. Is verification-first (4v before D1 is resolved) the desired order?
5. Image build authorization and who runs vulnerability scanning (tool availability is unverified).
6. Docker file-sharing narrowing and Postgres binding: will you perform them?
