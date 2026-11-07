# ASTRAVA V1.5 — Threat Model: Containerized Worker Sandboxing

**Status:** Target Planning Specification (V1.5)  
**Baseline:** V1.4 Frozen (`ed08f15`, Alembic head `6db676dd20fd`)  
**Scope:** Control Plane, Worker Plane, Sandbox Runtime, Supply Chain, and Execution Boundaries  

---

## 1. System Assets

1. **Host Infrastructure & Credentials:** Developer workstation OS, host filesystem, home directory (`~/.ssh`, `~/.aws`, `~/.gitconfig`, `~/.claude`), Docker socket (`/var/run/docker.sock`), and host environment variables.
2. **API & LLM Credentials:** Anthropic API keys, OAuth session tokens, and credit/quota budgets.
3. **Repository Integrity:** Host Git repository, primary branch (`main`), commit history, Git configuration, and Git hooks.
4. **Control Plane State & Database:** PostgreSQL 16 database, Alembic schema, `BudgetGovernor` reservation tables, `project_memories`, and `workflow_executions`.
5. **Execution Deliverables:** Generated source code, artifacts registered in `storage/artifacts`, and audit logs.

---

## 2. Trust Boundaries & Architecture

```
+-----------------------------------------------------------------------------------------+
| HOST / CONTROL PLANE BOUNDARY (Trusted Operator Domain)                                 |
|                                                                                         |
|  [Operator UI / CLI]  <--->  [FastAPI API Gateway] (app/core/auth.py)                   |
|                                     |                                                   |
|                        +------------+------------+                                      |
|                        |                         |                                      |
|            [PostgreSQL 16 DB (5433)]     [BudgetGovernor & Runner]                      |
|            (Reservations, Audits)         (Host Git & Artifact Store)                   |
|                                                  |                                      |
+--------------------------------------------------|--------------------------------------+
           |                                       | (Container Lifecycle: Docker CLI/API)
           | Hard Isolation Wall                   v (No Docker Socket Mounted)
+-----------------------------------------------------------------------------------------+
| WORKER RUNTIME BOUNDARY (Untrusted Sandbox Domain - Ephemeral Container)                |
|                                                                                         |
|   +---------------------------------------------------------------------------------+   |
|   | Container Sandbox: Non-root (uid 10001), Read-only Rootfs, Cap-Drop ALL, --init  |   |
|   |                                                                                 |   |
|   |  [Task Workdir (tmpfs)] <--- Read/Write Isolated Working Tree                   |   |
|   |           |                                                                     |   |
|   |  [Claude Code CLI / Subprocess]                                                 |   |
|   |           |                                                                     |   |
|   |  [Isolated Git Repo Snapshot] (Hooks disabled, no host .git)                    |   |
|   +-----------|---------------------------------------------------------------------+   |
|               |                                                                         |
|               v (Controlled Egress via HTTP Proxy Only)                                 |
|      [Allowlisting Proxy] ---> Outbound to https://api.anthropic.com ONLY               |
|      (Blocks arbitrary web, host LAN, and cloud metadata 169.254.169.254)               |
+-----------------------------------------------------------------------------------------+
| VERIFICATION BOUNDARY (Zero-Network Container)                                          |
|                                                                                         |
|   [Pytest & Linters] ---> --network none, Read-only Deliverables Mount                  |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Adversary Profiles

1. **Malicious Repository Content:** Repository containing weaponized `.git/hooks`, malicious `setup.py`, toxic `.env` files, or malicious fixtures designed to trigger execution on clone/inspect.
2. **Prompt-Injected / Hallucinating Agent:** Agent coaxed by poisoned task context or web content into executing arbitrary shell commands, destructive file operations, or data exfiltration.
3. **Compromised Dependency:** Upstream package pulled during build/test phases executing hostile post-install scripts or reverse shells.
4. **Malicious Artifact Content:** Deliverables containing path-traversal sequences, binary bombs, or disguised executables attempting control plane compromise.
5. **Local Unprivileged User / Process:** Local process attempting to hijack the API server or intercept unencrypted DB traffic on port 5433.
6. **Stale / Zombie Worker:** Orphaned container from a previous crashed run attempting to write results or reconcile reservations past its lease lifetime.

---

## 4. STRIDE Threat Analysis

| Threat (STRIDE) | Target Asset | Attack Vector | Baseline Exposure | V1.5 Mitigation |
|---|---|---|---|---|
| **Spoofing** | Operator / Verifier | Any caller when `OPERATOR_API_KEY` is unset; client-supplied `X-ASTRAVA-ACTOR-NAME` is trusted for attribution. | `app/core/auth.py:79` grants operator and verifier rights to every caller when `OPERATOR_API_KEY` is unset (the default). | Enforce mandatory token authentication and cryptographically signed worker attempt tokens. |
| **Tampering** | Host Git History | Worker modifies host `.git` via worktree pointer. | `worktree_manager.py` `create_worktree()` creates worktree whose `.git` file points to host `.git`. | Standalone snapshot clone; host `.git` never mounted into container. Results imported via hardened `git fetch` with hooks disabled. |
| **Repudiation** | Audit Log | Attributed actions modified or deleted. | `BudgetAuditLog` is documented as immutable, but there is no hash-chained or externally anchored audit trail for worker runs. | Extend the immutable `budget_audit_logs` pattern to a new `worker_runs` audit record and workflow events; hash chaining is optional. |
| **Information Disclosure** | Host Credentials | Agent shell reads `~/.ssh`, `~/.aws`, or env vars. | `claude_code.py:87` passes real host `$HOME` and environment. | Empty container `$HOME`, no host directory mounts, credential-free worker environment. |
| **Denial of Service** | Host Compute / Quota | Fork bomb, infinite loops, or runaway LLM queries. | `engine.py` `verify_task()` runs pytest with a 30s timeout and `engine.py:79` calls `proc.kill()` on the direct child only (grandchildren survive); no host PID/memory bounds. | `--pids-limit 256`, `--memory 4g`, `--cpus 2.0`, `--init` process reaping, `BudgetGovernor` ceiling. |
| **Elevation of Privilege** | Host Kernel | Container breakout via root execution or capabilities. | Agent runs as host user with host OS privileges (`claude_code.py` `execute()`). | Rootless execution (`uid 10001`), `cap-drop ALL`, `no-new-privileges`, read-only rootfs. |

---

## 5. Security Invariants (Testable)

1. **INV-01 (Mount Isolation):** No worker container shall mount any host directory outside its designated ephemeral execution directory.
2. **INV-02 (Rootless Execution):** Every process inside a worker container shall run with non-root UID/GID (`>= 10000`) and `no-new-privileges:true`.
3. **INV-03 (Capability Revocation):** All Linux capabilities shall be dropped (`cap-drop ALL`).
4. **INV-04 (Read-Only Rootfs):** The container root filesystem shall be mounted read-only; writes are permitted only in bounded tmpfs/ephemeral workdirs.
5. **INV-05 (Host Git Inviolability):** The host repository `.git` directory shall never be accessible to any container runtime.
6. **INV-06 (Network Egress Bounding):** Worker task containers shall only connect to the Anthropic API via an allowlisting proxy; verification containers shall run with `--network none`.
7. **INV-07 (Process Containment):** Every container shall execute with an init process (`--init`) and hard PID limit (`pids-limit <= 256`).
8. **INV-08 (No Control Plane Ingress):** Containers shall not possess network routes or credentials to access the control plane API or database directly.
9. **INV-09 (Fencing Token Exclusivity):** Results submitted from any container must validate against active `BudgetGovernor` lease and fencing token.
10. **INV-10 (Artifact Path Containment):** All artifact paths extracted from workers must satisfy `target.is_relative_to(base_dir)`.
11. **INV-11 (Authenticated Mutation):** Every state-changing route requires operator authentication whenever the server is non-loopback, and the server refuses to start non-loopback without a valid `OPERATOR_API_KEY`. Proven by a route-inventory test over `app.routes`.
12. **INV-12 (No Host Execution Path):** In the production execution path, agent processes and verification commands run only inside workers. If the runtime, image, workspace or security configuration is unavailable the task fails; no flag, setting or environment variable enables host execution. Proven by a static test plus a runtime-unavailable test.
13. **INV-13 (Server-Derived Audit Identity):** Audit `actor_id` comes only from authenticated server-side context; client-supplied actor names are never trusted.
14. **INV-14 (No Paid or Host Credential in Workers):** No `ANTHROPIC_API_KEY`, no host `~/.claude`, no keychain material and no git credentials exist in any worker.

---

## 6. Comprehensive Threat Analysis (18 Security Topics)

### Topic 1: Container Privilege Escalation
- **Threat:** Malicious payload exploits setuid binaries or Linux capabilities to gain root inside container.
- **Current-State Exposure:** `app/providers/claude_code.py` `execute()` executes directly on host under the host user account.
- **Mitigation:** Launch containers with `--security-opt no-new-privileges:true`, `--cap-drop ALL`, and explicit `--user 10001:10001`.
- **Residual Risk:** Kernel vulnerability in container runtime (runC/cgroups).
- **Test:** Run setuid binary test inside container; verify `EPERM` on privilege escalation attempt.

### Topic 2: Docker Socket Exposure
- **Threat:** Container mounts `/var/run/docker.sock`, granting full root control over the host Docker daemon.
- **Current-State Exposure:** Host executes Docker commands directly; no container isolation currently in place.
- **Mitigation:** Strictly forbid mounting `/var/run/docker.sock` in worker containers. Validate container launch specs in `WorkerRuntime`.
- **Residual Risk:** Host API server compromise exposing daemon socket.
- **Test:** Verify `/var/run/docker.sock` does not exist inside worker container filesystem.

### Topic 3: Host Filesystem Access
- **Threat:** Agent traverses file paths to read `/etc/passwd`, `/var/log`, or host user documents.
- **Current-State Exposure:** `claude_code.py` `execute()` has full read/write access to host filesystem paths accessible by host user.
- **Mitigation:** Dedicated rootless container with read-only rootfs (`--read-only`) and ephemeral tmpfs volume for task work.
- **Residual Risk:** Filesystem leaks via host volume mount misconfiguration.
- **Test:** Attempt to read `/etc/shadow` or host `/Users` paths from inside container; verify `ENOENT` or `EACCES`.

### Topic 4: Host Home-Directory Access
- **Threat:** Agent inspects `$HOME` to steal SSH keys (`~/.ssh`), AWS credentials (`~/.aws`), or browser history.
- **Current-State Exposure:** `claude_code.py:87` explicitly passes host `HOME` to `_build_clean_environment`.
- **Mitigation:** Set container `HOME=/home/worker` on a size-limited tmpfs (see Target Architecture section 6); do not mount host `$HOME`.
- **Residual Risk:** Operator explicitly mounting host home via configuration mistake.
- **Test:** Assert `ls ~/.ssh` returns empty or not found inside container environment.

### Topic 5: Repository / Worktree Isolation
- **Threat:** Agent modifies `.git` config, rewrites git history, or poisons git hooks in the primary repository.
- **Current-State Exposure:** `worktree_manager.py` `create_worktree()` creates worktree whose `.git` file points directly into host repo `.git/worktrees`.
- **Mitigation:** Export repository as a standalone snapshot clone (`git clone --depth 1 file://...`). Control plane imports changes via `git fetch` with `core.hooksPath=/dev/null`.
- **Residual Risk:** Malicious `.gitattributes` or `.gitignore` altering host checkout behavior.
- **Test:** Commit change inside container; verify host `.git` reflog and commit history remain untouched until explicit operator merge.

### Topic 6: Git Credential Exposure
- **Threat:** Agent extracts SSH deploy keys or GitHub PAT tokens to push malicious code to upstream remotes.
- **Current-State Exposure:** Agent running on host inherits user's `ssh-agent` socket and git credential helpers.
- **Mitigation:** Zero git credentials mounted into worker container. No SSH agent socket forwarding; no `.git-credentials` file.
- **Residual Risk:** Git remote URLs embedding plaintext tokens in repository files.
- **Test:** Execute `git push origin main` inside container; verify immediate failure due to missing credentials.

### Topic 7: Claude Code CLI Authentication
- **Threat:** Agent or malicious script exfiltrates host Anthropic subscription token or API key.
- **Current-State Exposure:** CLI runs with host `~/.claude` session or host environment variables.
- **Mitigation:** Workers run credential-free; outbound traffic routes through a control-plane egress proxy that injects the auth token or worker uses short-lived task-scoped credentials.
- **Residual Risk:** Prompt injection inducing the CLI to print raw session tokens to logs before redaction.
- **Test:** Inspect container environment and filesystem; verify absence of static `ANTHROPIC_API_KEY` or `~/.claude/session`.

### Topic 8: Environment Variable Leakage
- **Threat:** Sensitive host environment variables (database passwords, API keys) leak into agent process.
- **Current-State Exposure:** `claude_code.py:87` filters basic variables but passes host user environment.
- **Mitigation:** Container launched with explicit, minimal static environment (`PATH`, `TERM`, `LANG`, `ASTRAVA_TASK_ID`).
- **Residual Risk:** Leakage through user-defined `env_overrides`.
- **Test:** Inspect `/proc/1/environ` inside container; verify zero host secrets present.

### Topic 9: Network Restrictions
- **Threat:** Agent initiates port scans, accesses internal cloud metadata (`169.254.169.254`), or opens reverse shells to attacker C2.
- **Current-State Exposure:** Host processes have unrestricted network access (`claude_code.py` `execute()`).
- **Mitigation:** Worker containers restricted via egress allowlisting proxy to Anthropic API endpoints only. Verification containers run with `--network none`.
- **Residual Risk:** SSRF via allowed Anthropic API subdomains or DNS rebinding.
- **Test:** Attempt `curl http://169.254.169.254` and `curl https://google.com` inside container; verify connection refused or blocked by proxy.

### Topic 10: CPU, Memory, Disk, and Process Limits
- **Threat:** Resource exhaustion via fork bomb, memory allocation spike, or disk filling causing host crash.
- **Current-State Exposure:** Host processes run without cgroup limits.
- **Mitigation:** Enforce `--cpus 2.0`, `--memory 4g`, `--memory-swap 4g`, `--pids-limit 256`, and bounded tmpfs storage (max 2GB).
- **Residual Risk:** Slow degradation when multiple containers reach max allocations simultaneously.
- **Test:** Run `:(){ :|:& };:` inside worker container; verify pids limit triggers cleanly and host remains responsive.

### Topic 11: Execution Timeouts
- **Threat:** Deadlocked process or infinite agent loop holds resources indefinitely.
- **Current-State Exposure:** Pytest has a 30s timeout (`engine.py` `verify_task()`); Claude CLI default is 180s (`config.py` `CLAUDE_EXECUTION_TIMEOUT_SECONDS`; `ProviderRequest.timeout_seconds`), but orphaned child processes persist.
- **Mitigation:** Control plane supervisor enforces hard timeout via `docker stop -t 5 <container_id>` bound to `BudgetGovernor.expires_at`.
- **Residual Risk:** Unresponsive Docker daemon blocking container stop command.
- **Test:** Launch container with `sleep 9999`; verify supervisor issues stop signal at timeout deadline.

### Topic 12: Orphaned Subprocesses
- **Threat:** Grandchild processes spawned by agent or pytest continue running after parent exits.
- **Current-State Exposure:** `engine.py:79` calls `proc.kill()` on the direct child only, leaving grandchildren running.
- **Mitigation:** Run container with `--init` (tini). Terminating the container instantly tears down the entire PID namespace.
- **Residual Risk:** Zombie process entries inside the container prior to cleanup.
- **Test:** Spawn background daemon inside container and terminate container; verify no lingering processes on host OS.

### Topic 13: Container Cleanup
- **Threat:** Accumulated stopped containers and dangling volumes exhaust host disk space.
- **Current-State Exposure:** Ephemeral worktrees cleaned up on success but can leak on crash (`worktree_manager.py` `cleanup_worktree()`).
- **Mitigation:** Launch with `--rm` flag or control plane `finally` block executing `docker rm -f`. Startup recovery sweep removes orphaned ASTRAVA containers.
- **Residual Risk:** Host crash leaving container records in Docker state store.
- **Test:** Simulate worker crash; run startup recovery and assert all `astrava-worker-*` containers are removed.

### Topic 14: Malicious Repository Content
- **Threat:** Toxic repository executes arbitrary code via Git hooks (`.git/hooks/post-checkout`) or malicious project configs.
- **Current-State Exposure:** Host git commands executed in user repo directory (`worktree_manager.py` `_run_git()`).
- **Mitigation:** Clone with `--config core.hooksPath=/dev/null` and `--no-local`. Strip executable permissions on untrusted repo configuration files.
- **Residual Risk:** Parsing vulnerabilities in Git binary (e.g. CVE-2024-32002).
- **Test:** Place weaponized `post-checkout` hook in test repo; verify hook does not execute during snapshot creation.

### Topic 15: Dependency Installation Risks
- **Threat:** `npm install` or `pip install` executes hostile install scripts (`postinstall`, `setup.py`) with access to agent secrets.
- **Current-State Exposure:** Pytest and agent commands run directly on host with access to host tools.
- **Mitigation:** Two-phase execution: (1) Prepare phase: installs dependencies in an unprivileged container with no API credentials, (2) Execution phase: mounts cached dependencies read-only.
- **Residual Risk:** Compromised dependency poisoning runtime behavior of verified application.
- **Test:** Verify environment during dependency install phase contains zero API tokens or provider secrets.

### Topic 16: Artifact and Log Sanitization
- **Threat:** Agent outputs malicious escape sequences, path-traversal strings, or exfiltrated data into artifacts or logs.
- **Current-State Exposure:** `artifact_service.py:18` uses flawed string prefix check; `redact_secrets` only operates on stdout.
- **Mitigation:** Fix `sanitize_path` using `Path.is_relative_to`. Redact secrets across artifact content, diff text, and persisted database logs.
- **Residual Risk:** Non-regex encoded credentials bypassing redaction patterns.
- **Test:** Attempt artifact registration with `artifacts_evil/hack.txt`; verify `ValueError` path traversal rejection.

### Topic 17: Worker-to-Control-Plane Authentication
- **Threat:** Compromised worker makes rogue API calls to control plane to modify other executions or promote fake memories.
- **Current-State Exposure:** `app/core/auth.py` trusts all requests when `OPERATOR_API_KEY` is unset; no worker identity exists.
- **Mitigation:** No inbound control plane network port exposed to workers (unidirectional result collection via stdout/volume file). If API is enabled, mandate HMAC tokens bound to `(execution_id, task_id, attempt, fence_token)`.
- **Residual Risk:** Shared loopback network exposure in local development setups.
- **Test:** Attempt HTTP connection from worker container to control plane port (8000/5433); verify connection refused.

### Topic 18: Container Escape Threat Model
- **Threat:** Zero-day or unpatched vulnerability in Linux kernel or runC allows arbitrary host code execution.
- **Current-State Exposure:** Full direct host execution; no barrier exists today.
- **Mitigation:** Defense in depth: rootless container, seccomp filtering, cap-drop ALL, and read-only rootfs. On macOS, execution is bounded inside the Docker Desktop Linux VM (Hypervisor.framework), preventing direct macOS host compromise. (Future roadmap: gVisor/Kata microVMs).
- **Residual Risk:** Hypervisor escape or Docker Desktop file-sharing exploit.
- **Test:** Validate seccomp profile blocks unauthorized syscalls (e.g., `clone3`, `keyctl`, `process_vm_writev`).

---

## 7. Sandbox Limitations & Residual Risk Statement

Containerization via standard Docker significantly shrinks the attack surface, but **Docker alone does not guarantee absolute containment**:
1. **Shared Linux Kernel:** On bare-metal Linux, containers share the host kernel. A kernel privilege escalation vulnerability (e.g., Dirty COW, io_uring flaws) allows container escape.
2. **macOS Hypervisor Boundary:** On macOS, Docker Desktop runs inside a lightweight Linux VM via Hypervisor.framework. A container breakout compromises only the Linux VM, not the host macOS directly, provided file-sharing mounts (`/Users/...`) are strictly isolated.
3. **VirtioFS / gRPC Mount Exploits:** Flaws in filesystem translation between the VM and macOS host could permit directory traversal if host mounts are improperly scoped.
4. **Conclusion:** Hardened container options (`cap-drop ALL`, rootless, read-only rootfs, no socket) reduce the practical attack surface; no percentage is claimed. True multi-tenant untrusted execution will ultimately require hardware-isolated microVMs (Kata Containers or Firecracker).

---

## 8. Orchestrator Review Notes (Sonnet, independent review of the Antigravity draft)

Open items that must be resolved in M1 before this model is treated as final:

1. **Line citations.** The first draft cited several wrong line numbers; those were corrected against source. Re-verify all citations at implementation time because the code will change.
2. **Credential injection vs TLS (Topics 7 and 9; also Risks R-05/R-12).** An allowlisting `CONNECT`/SNI proxy cannot also inject credentials, because injection requires terminating TLS or pointing the CLI at a plain internal gateway via a base-URL setting. Whether the CLI supports that for the operator's login type (subscription OAuth vs API key) is **UNVERIFIED** and is Open Decision D1. Until verified, treat "worker holds no credential" as a goal, not a guarantee, and keep the fallback: a single-use, revocable credential file scoped to one attempt.
3. **Working-tree storage.** The draft places the task workdir on tmpfs. tmpfs counts against the memory limit (`--memory 4g`) so a large repository plus build output can OOM the worker. A size-limited named volume inside the Docker VM is the alternative. Decide with the M1 benchmark, not by assumption.
4. **Seccomp expectations (Topic 18).** The claim that the default profile blocks `clone3`/`keyctl`/`process_vm_writev` is **UNVERIFIED**; Docker's default profile allows some of these depending on version and capabilities. The test must assert observed behavior, and a custom profile may be required.
5. **"Rootless".** Docker Desktop is not rootless Docker. INV-02 means a non-root user inside the container; it is not a claim about the daemon.
6. **Verification is a first-class threat.** pytest on agent-written code runs on the host today (Assessment G2). Moving it into the zero-network container is a P0 deliverable, not an enhancement.
7. **Not covered by the draft:** symlink and hardlink escape in imported snapshots, `.git`-metadata/submodule smuggling in agent commits, log injection into the UI (terminal/HTML escapes), and API-side authN when `APP_HOST=0.0.0.0` (Decision D6).
8. **Added after the D6 route audit:** 16 of 33 mutating routes are unauthenticated even with a key set, including `/orchestrator/execute` (starts agents), `PATCH /projects/{id}` (sets `repo_path` to any host path) and `PUT /agents/{id}`. The Spoofing and Elevation rows in section 4 understate the baseline until this is fixed; M1.5-1a is a hard prerequisite for any milestone that gives the API process Docker access (see `V1_5_TECHNICAL_RISKS.md` section 6, R-16 to R-19).
9. **Docker daemon reachability.** On this host the control-plane user already has full access to the Docker Desktop daemon. Workers must never receive that socket, and the `WorkerRuntime` launch-spec validator is a security control, not just a convenience.
