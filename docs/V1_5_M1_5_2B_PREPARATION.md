# M1.5-2b — Preparation: host-change proposals and technical plan (NO implementation authorized)

Status: written 2026-11-08 after acceptance of M1.5-2a. **Updated by CP-010 (section 8 below): H2 was authorized and applied; H1 was declined for now; 2b remains NOT authorized.** Sections 1-7 are the original proposal text; where section 8 differs, section 8 governs. ADR-028 stays **Proposed**. D1 **BLOCKED**, D5 **UNVERIFIED**.

How this was gathered (all read-only; Docker was **not** contacted, no `docker` command was run, no image/container touched): file reads of `docker-compose.yml`, `~/Library/Group Containers/group.com.docker/settings-store.json`, Docker Desktop's own backend logs (a settings dump they contain), `~/.docker/{config,daemon}.json`; `lsof` on port 5433; `grep` of this repo and sibling projects; `socketfilterfw --getglobalstate`. Host: macOS 27.0.1 arm64, Docker Desktop app 4.91.0 (engine reported 29.8.0 in the earlier reassessment).

---
## 1. Proposal H1 — Docker Desktop file sharing

### 1.1 Current effective configuration
`settings-store.json` has **no** file-sharing keys (so product defaults apply). Docker Desktop's backend log (settings dump, the only place the effective list appears on disk) shows:

| Shared path | Source |
|---|---|
| `/Users` | default |
| `/Volumes` | default |
| `/private` | default |
| `/tmp` | default |
| `/var/folders` | default |

`allowedFileshares: []` (no admin/policy restriction). File sharing backend: VirtioFS/gRPC-FUSE flag `useGrpcfuse: true` appears in the same dump; the active file-sharing implementation was **not** independently verified. Caveat: this list comes from the log of the last captured settings dump, not from the live UI; confirm in **Settings → Resources → File sharing** before changing anything.

Consequence: any container started with a bind mount (or a VM-root compromise) can reach the entire home directory of the operator, including `~/.ssh`, `~/.claude`, `~/Library`, and all repositories.

### 1.2 What broker and workers actually require
**Nothing from the host filesystem.** The M1.5-2 design forbids bind mounts: the broker state, socket and key live on the host and are never mounted into a container; workers get their input as a tar stream written into a named volume/tmpfs through the Engine API, and results come back through the API. The existing Compose service (`astrava-postgres`) uses a **named volume** (`postgres_data`), not a bind mount.

### 1.3 Minimum proposed list
**Empty** (no shared directories), if Docker Desktop accepts an empty list on this version (unverified). Fallback if the UI insists on at least one entry: a single dedicated empty directory, e.g. `/Users/abstract/docker-share-empty`.

### 1.4 Exact change (to be done by the operator, or by me only after explicit approval)
1. Quit nothing yet; back up: `cp "$HOME/Library/Group Containers/group.com.docker/settings-store.json" "$HOME/docker-settings-store.json.bak-2026-11-08"`.
2. Docker Desktop → Settings → Resources → File sharing: remove `/Users`, `/Volumes`, `/private`, `/tmp`, `/var/folders` (or leave the fallback empty directory only). **Apply & restart**.
3. Editing `settings-store.json` by hand is **not** proposed (the key name, probably `FilesharingDirectories`, was inferred from log text, not verified; the UI is the supported path).

### 1.5 Impact on existing containers and services
- **Restart: yes.** Applying file-sharing changes restarts the Docker Desktop VM; every running container stops and those with a restart policy come back. `astrava-postgres` has `restart: unless-stopped` and a named volume, so it returns with data intact (downtime roughly tens of seconds). `bl-pg` (published on `0.0.0.0:55432`; its owning project was not found in `~/Documents/personal_project`) is affected the same way; its volume type is unknown.
- **Breaks anything that bind-mounts a path under the removed directories.** Found: `ohmic-api/docker-compose.yml` bind-mounts `./db/migrations:/migrations` (service `ohmic_migrate`). With `/Users` unshared it would fail to mount until `/Users/abstract/Documents/personal_project/ohmic-api` is shared again. `portofolio-ai-backend/docker-compose.yml` has no bind mount. Other projects outside `personal_project` were not scanned.
- `docker build` and `docker compose build` do not depend on file sharing (build context is sent by the client).
- `/tmp` and `/var/folders` are used by some tools (testcontainers, devcontainers, IDE helpers); unaffected here because ASTRAVA tests use the Compose Postgres through TCP.
- **Decision for the operator:** keep a narrow per-project share (e.g. only `.../ohmic-api`) or accept that ohmic-api's migrate step needs sharing re-enabled when used.

### 1.6 Verification after the change
Settings UI shows the new list; `astrava-postgres` healthy and `alembic current` works; the ohmic compose case above fails as predicted (confirms the change took effect) — do this only with the operator's consent.

### 1.7 Rollback
Docker Desktop → File sharing → re-add the five paths above → Apply & restart. If the UI is unusable: quit Docker Desktop, restore `settings-store.json` from the backup, relaunch.

---
## 2. Proposal H2 — PostgreSQL published on 127.0.0.1

### 2.1 Current configuration
`/Users/abstract/Documents/personal_project/astrava/docker-compose.yml`, service `postgres` (image `postgres:16-alpine`, container `astrava-postgres`), line 11:
```yaml
    ports:
      - "5433:5432"
```
No host address ⇒ published on all interfaces. Verified live: `lsof` shows `com.docker.backend` (PID owned by the operator) listening on `TCP *:5433` (IPv6 wildcard, dual-stack). The macOS Application Firewall is **disabled**. The Mac's `en0` has a LAN address (`192.168.0.x`), so the database (dev password `astrava_dev_password`, user `astrava`) is reachable by any device on that LAN. No established connections at inspection time.

### 2.2 Consumers (all found by repository grep; sibling projects have no reference — their only `5433` hits are hashes in `uv.lock`)
| Consumer | Reference | Connects via |
|---|---|---|
| `backend/app/config.py:41-42` | `localhost:5433` (async + sync URL defaults) | host loopback |
| `.env.example:28-29`, `README.md:116-117` | `localhost:5433` | host loopback |
| `backend/tests/recovery/harness.py:19` | `host="localhost", port=5433` (throw-away DB creation) | host loopback |
| Alembic (via `DATABASE_URL_SYNC`) | `localhost:5433` | host loopback |
| Docs only | reassessment, threat model, reports | — |

No consumer uses the LAN address, the hostname, or `host.docker.internal`. No remote service depends on the current `0.0.0.0` binding (as far as the repo shows; a person connecting from another device by hand cannot be detected).

### 2.3 Exact proposed change
`docker-compose.yml` line 11:
```yaml
      - "127.0.0.1:5433:5432"
```
Apply with `docker compose up -d postgres` from the repo root (a published-port change **recreates the container**; the named volume `postgres_data` is untouched). Backup first: `git stash`-free approach — the change is one line under git; also `docker exec astrava-postgres pg_dump -U astrava astrava > ~/astrava-pre-rebind.sql` (the dev DB holds only development data, but a dump is cheap).

### 2.4 Expected impact
- Downtime: seconds (recreate). `restart: unless-stopped` and healthcheck unchanged.
- `localhost` resolves to `::1` and `127.0.0.1`; the new binding is IPv4 only. asyncpg and libpq both try every resolved address, so `localhost` clients fall back to `127.0.0.1`. **Risk:** a small connect delay or, in a client that tries only `::1`, failure. Validation covers this; no code change is proposed (switching the defaults to `127.0.0.1` would be a source change and is out of scope here).
- LAN devices lose access (intended).
- **Not a worker isolation measure.** Containers reaching the host through `host.docker.internal` or the gateway may still arrive from the host's loopback side under Docker Desktop's port forwarding; whether a loopback-published port is reachable from another container is **unverified**. Worker protection stays `network: none` plus an explicit negative probe in 2b.

### 2.5 Validation
1. `lsof -nP -iTCP:5433 -sTCP:LISTEN` shows `127.0.0.1:5433` only.
2. `pg_isready -h 127.0.0.1 -p 5433` and `-h localhost -p 5433` both succeed.
3. From another LAN device (or `nc` to the Mac's `en0` address): connection refused.
4. Backend: `alembic current` = `c8a1f3d5e7b9`; one recovery-harness test and the full backend suite pass.
5. Row counts of a few tables equal the pre-change dump.

### 2.6 Rollback
Revert line 11 to `"5433:5432"`; `docker compose up -d postgres`. Data is in the named volume; restore from the dump only if the volume was damaged.

---
## 3. M1.5-2b technical implementation plan (security-focused)

Scope of 2b (when separately authorized): broker **Docker backend**, first **pinned image**, limits, cleanup, reconciliation, escape/hostile-repo probes. Not in 2b: export-out file stream and artifact filter (2c), real agent entrypoint, egress proxy, any credential (D1), host-side verification containers (4v), tier B build. The contract (nine operations, no new fields except as a reviewed contract change) is unchanged; nothing in the API or `worker_runtime` changes.

### 3.1 Broker Docker backend
- New module `astrava_broker/docker_backend.py` implementing the existing `WorkerBackend` protocol. **No Docker SDK** (not required: the Engine API is plain HTTP; `httpx` with a Unix-socket transport is already installed, as agreed). **No `docker` CLI and no subprocess** (CLI adds context/credential-helper behavior and argument-injection surface).
- A single `DockerEngineClient` with an **endpoint allowlist** (method + path template) of about 12 calls: `GET /_ping`, `GET /version`, `GET /images/{id}/json`, `POST /containers/create`, `POST /containers/{id}/start`, `POST /containers/{id}/kill`, `POST /containers/{id}/wait`, `GET /containers/{id}/json`, `GET /containers/{id}/logs`, `DELETE /containers/{id}`, `GET /containers/json` (label-filtered), `POST/DELETE /volumes…` (or tmpfs only, see 3.5), `PUT /containers/{id}/archive` (snapshot-in). Anything else raises before a request is made. **No** `exec`, `attach`, `build`, `commit`, `images/create` (pull), `networks/*`, `plugins`, `swarm`, `system/prune`, or `/containers/{id}/archive GET` in 2b.
- Container creation body is produced by **one function** from `Profile` constants plus broker-generated names and labels. Nothing a caller supplies reaches `Image`, `Cmd`, `Entrypoint`, `Env`, `HostConfig`, mounts, networks, devices or capabilities (the contract already has no such fields). A **golden-file test** pins the exact JSON; a static guard forbids the strings `Privileged`, `Binds`, `Devices`, `CapAdd`, `NetworkMode: host`, `PidMode`, `IpcMode`, `UsernsMode`, `docker.sock`.

### 3.2 Pinned minimal worker image, build and provenance
- **Stub image only in 2b** (deterministic entrypoint that reads `/work/input`, writes `/work/result.json`, and has switches to run hostile probes). No agent, no model client, no credential.
- Base: a minimal base referenced **by digest** (`name@sha256:…`), never a tag; candidate `python:3.12-slim-bookworm@sha256:…` or a distroless/static binary for the stub (smaller surface; probes need a shell, so a separate **probe image** with busybox is built only for tests and never mapped to an alias usable in production profiles).
- Dockerfile lives in the repo (`worker_images/`), non-root `USER 10001:10001`, no package manager at runtime, no `setuid` binaries (asserted by a test that walks the filesystem), `HEALTHCHECK NONE`.
- **Build and provenance:** built once by the operator-authorized step (`docker buildx build --provenance=mode=max --sbom=true`, network required to fetch the base — this is the first step that needs network and is a separate authorization point). Recorded in a committed `worker_images/images.lock`: base digest, Dockerfile sha256, built image ID (`sha256:…`), build date, SBOM digest, scanner results digest. The broker, at start-up and on every `create`, resolves the alias → image **ID** from `images.lock` and refuses if the local image ID differs (no tag trust, no pulling at runtime).
- Reproducibility is best-effort (base digest pinned; apt/pip layers are not bit-reproducible); stated, not claimed.

### 3.3 Container lifecycle and cleanup
- Names are deterministic (`astrava-w-<worker_id>`); `create` is idempotent: a 409 is resolved by inspecting labels (`astrava.broker`, `astrava.execution`, `astrava.worker`, `astrava.epoch`, `astrava.profile`, `astrava.created`) and accepting only an exact match.
- `AutoRemove=false` (exit status and logs must be collected before removal). States map onto the existing broker state machine: create → CREATED, start → RUNNING, `wait`/inspect → EXITED / KILLED / TIMED_OUT / LOST, collect (logs ≤ 1 MiB, `result.json` ≤ 256 KiB via API), cleanup removes the container and its volume.
- Terminate = `kill` (SIGKILL) → bounded `wait` → `remove -f`; cleanup is idempotent and retried; failure records `CLEANUP_FAILED` (already modelled) and blocks recovery (fail closed, as in 2a).
- Docker Desktop restart or VM crash kills containers: the broker reports `LOST`, the API treats it as a failed attempt, never as success.

### 3.4 Limits (profiles already carry the values; 2b validates them by benchmark)
Memory = MemorySwap (no swap), `NanoCpus`, `PidsLimit`, `Ulimits` (nofile 1024, core 0), wall-clock deadline enforced by the **broker reaper** (kill), log ring 1 MiB, global worker cap (default 2) and total memory ≤ 50% of the VM. Disk: see 3.5.

### 3.5 Filesystem
`ReadonlyRootfs=true`; writable locations only `/tmp` and `/work`, both **tmpfs** with explicit `size=` and `noexec,nosuid,nodev` (a tmpfs is the only quota I can enforce with certainty; its content counts against the container memory limit, so profiles must budget for it). Named volumes are avoided in 2b because per-volume size limits are not verified on Docker Desktop's storage driver; if 2b's benchmark shows tmpfs is too small for real repositories, the alternative (volume plus broker-side polling and kill) goes to a design review, not a silent switch. Snapshot-in is a tar stream via `PUT /containers/{id}/archive` into the tmpfs path of a created-not-started container; the broker validates every member (regular files and directories only, no symlinks/hardlinks/devices, no absolute or `..` paths, NFKC/Unicode rules from `validate_relative_path`, count and byte caps) **before** sending it.

### 3.6 User, capabilities, seccomp
`User=10001:10001`, `CapDrop=[ALL]`, no `CapAdd`, `SecurityOpt=["no-new-privileges:true", "seccomp=<inline JSON>"]` using an **explicit committed profile** (Docker's default allowlist as the starting point, with additional denies for `ptrace`, `keyctl`, `add_key`, `request_key`, `unshare`/`setns` of user namespaces, `bpf`, `perf_event_open`, `userfaultfd`, `mount`/`umount`, `open_by_handle_at`, `kexec`), `Init=true`, no `Privileged`, no devices, `IpcMode=private`, `PidMode` default, `UsernsMode` default, `CgroupnsMode=private`, `Runtime=runc` (only one available). The seccomp JSON is hashed in `images.lock`-style manifest and compared on every create.

### 3.7 Network and egress
`NetworkMode=none`, no `ExtraHosts`, no DNS settings, no port bindings. **Explicit egress policy in 2b: none.** The egress allowlist proxy and `--internal` network are designed in the reassessment (§11) but **not built**; they depend on D1. Test: only `lo`, no default route, DNS resolution fails, `host.docker.internal` and gateway unreachable.

### 3.8 Docker API access restrictions
Only the broker process opens the Docker socket; the API holds no path to it (existing static guards stay; a new guard asserts that only `astrava_broker/docker_backend.py` references the Engine API). Allowlisted endpoints (3.1), request bodies built from constants, response parsing with strict models, request timeouts, no redirects. **Limit:** on macOS tier A the socket is owned by the operator's user, so any same-user process can talk to Docker directly; the allowlist protects against mistakes and caller-controlled input, **not** against hostile same-user code.

### 3.9 Worker ownership, fencing, crash recovery
- Every container carries `epoch` and `execution` labels. The broker's persistent epoch high-water mark (2a) is the authority; a container whose epoch is below the mark is killed and removed by the reaper even with no API alive.
- **Broker start-up reconciliation:** list containers with label `astrava.broker=<instance-id>` → match against the ledger: known and consistent → adopt; labelled but unknown to the ledger → remove after a grace period (orphan); ledger says running but container missing → `LOST`. A foreign container (no label) is never touched.
- Docker daemon down → every operation returns `unavailable` (fail closed, recovery blocked, exit code 5 path unchanged).

### 3.10 Image vulnerability scanning and update policy
Scanner candidates (needs operator choice, see §7): Trivy or Grype (offline DB fetch needs network), Docker Scout (needs Docker login — **not** proposed). Gate: no fixable CRITICAL/HIGH in the shipped image; results stored with the lock file. Update policy: rebuild at least monthly or on a relevant CVE; new base digest and new lock file go through a reviewed commit; no automatic pulls.

### 3.11 Escape and hostile-repository tests (run only inside 2b after authorization)
Probes executed *inside* the worker (via the stub's probe mode, no `exec` API): attempt `mount`, `ptrace`, `unshare -U`, `mknod`, writing `/proc/sys`, `/sys`, `/proc/sysrq-trigger`, reading `/var/run/docker.sock`, `/etc/shadow`, host paths (`/Users`, `/host`), listing capabilities (`CapEff` must be 0), no-new-privileges flag set, running as uid 10001, writing to the root filesystem (must fail), writing/executing in `/tmp` (exec must fail), network (no interface but `lo`, DNS fails, `169.254.169.254`, `host.docker.internal`, gateway, port 5433/8000 all unreachable), resource bombs (memory → OOM-kill, fork bomb → PID limit, CPU spin → wall-clock kill, tmpfs fill → ENOSPC without host effect, log flood → ring cap, huge output → cap). Hostile-repo inputs fed through snapshot-in: symlink and hardlink escapes, `..` and absolute names, Unicode look-alike and bidi names, device nodes, setuid files, tar bombs (count/size), sparse files, deep nesting, 0-byte and 4 GiB claims, `.git` tricks (git is never run in the worker; hooks are inert). Cleanup audit after every test: zero leftover containers and volumes with the astrava label.

---
## 4. What Docker Desktop on macOS can and cannot enforce

| Protection | Enforced by Docker Desktop? | Notes |
|---|---|---|
| Namespaces (pid/net/ipc/mount/uts), no shared PID/IPC with host | **Yes**, inside the Linux VM | |
| cgroup v2 memory/CPU/PIDs | **Yes**, inside the VM | the VM total (about 8.3 GB, 12 CPUs) is the real ceiling and is shared with every project's containers |
| `cap-drop ALL`, `no-new-privileges`, seccomp, read-only rootfs, non-root user, tmpfs size | **Yes** (kernel-enforced in the VM) | verified by probes, not assumed |
| `network none` | **Yes** | |
| Wall-clock limit | **Broker-enforced**, not Docker | accuracy after Mac sleep / VM clock drift is unverified |
| Per-volume disk quota | **Cannot be guaranteed** | hence tmpfs |
| Host file exposure | **Only by the operator's file-sharing setting (H1)**; not controllable from code | |
| Escape containment | **No**: `dockerd` is VM-root, the VM runs as the operator; a kernel/runc escape yields operator-level code on macOS, with VirtioFS reaching shared paths | one shared VM, `runc` only, no gVisor/Kata, no rootless mode, Enhanced Container Isolation not assumed |
| Host-gateway behavior (`host.docker.internal`, loopback-published ports) | **Cannot be assumed** | probed, never trusted |
| Protection of the Docker socket from the API | **No (tier A)**: same macOS user can open it | tier B required |
| Reproducible image builds | **No** | pinned digests + provenance only |

**Tier A remains development-only.** A same-user broker does not protect against arbitrary code execution in the API process; the 2a/2b controls defend against caller-controlled input, bugs and stale owners, not against a compromised API running as the same user.

**Tier B and Docker Desktop (open design problem):** the Docker daemon socket is per macOS user. A separate broker user cannot use the operator's Docker Desktop VM (socket mode 755 prevents connect), so tier B requires either a second Docker runtime owned by the broker user (a second Docker Desktop login session, or Colima/Lima under that user) or a different host. This is not solved in 2b; it must be decided before any "tier B" claim.

---
## 5. Security limitations and unresolved risks
1. No hardware-level isolation; one shared kernel and VM; escape ⇒ operator-level code on the Mac.
2. Tier A is not a boundary; tier B needs a separate user *and* a separate Docker runtime (4, above).
3. File sharing stays broad until H1 is applied; narrowing is a host setting and cannot be verified by code.
4. Postgres stays LAN-reachable until H2 is applied; even after H2, container→host reachability is unverified.
5. Disk quota only via tmpfs (RAM-backed); real repositories may not fit.
6. Image supply chain: base digest pinned, but build needs network; scan results depend on an external vulnerability database.
7. Fake-backend timing and the reaper have not met a real daemon; kill latency, VM pressure, Docker Desktop restarts and sleep/wake are untested.
8. Orphaned containers if the broker crashes *and* the ledger is lost (reconciliation relies on labels).
9. Unchanged from earlier: worktree artifact retrieval limit; intermediate-directory TOCTOU; other repo-local Git config; tracked-files-only dirty check; host-side repository parsing/verification; D1 BLOCKED; D5 UNVERIFIED; SD-07; at-least-once provider invocation (M1.5-1c); host agent execution is still unfenced until the graph uses workers.

## 6. Proposed test and acceptance gates for 2b
1. Independent security review (Agy) of the Docker backend and container spec; findings fixed or recorded.
2. Golden-JSON test of the create body; static guards (endpoint allowlist, forbidden option strings, only `docker_backend.py` touches the Engine API, API still has no Docker access).
3. Recorded-request fake Engine API server in CI (no Docker needed) for all unit tests; real-Docker integration tests behind an explicit opt-in marker and run only during the authorized 2b session.
4. Same conformance suite as 2a passes against the Docker backend (replaceability).
5. Limit, escape, network and hostile-repo probes (3.11) all pass; every probe asserts the *negative* outcome and that no host effect occurred (marker files outside the sandbox untouched).
6. Process-level crash tests with a real daemon: SIGKILL broker mid-create/start/kill, restart + reconcile; SIGKILL API; stop Docker Desktop → fail closed; no leaked containers/volumes after each test.
7. Epoch fencing proven with real containers (stale-epoch worker killed by the reaper alone).
8. Image: digest-pinned, lock file verified at start, scan with no fixable CRITICAL/HIGH, SBOM and provenance recorded.
9. Mutation harness extended to the new backend; zero survivors.
10. All backend tests, ruff, mypy (new modules), `alembic check` pass; no unexplained skips (opt-in Docker tests are reported as *run*, not skipped, in the authorized session).
11. Docs, AGENT_STATE, EXECUTION_LOG, roadmap, reassessment updated; commit and push only after acceptance.

## 7. Decisions required from the operator
1. **H1:** approve the exact file-sharing change (empty list vs one empty fallback directory) and say how to treat `ohmic-api`'s bind mount (re-share its folder when needed, or keep a narrow share for it). Who applies it: you in the UI (recommended) or me?
2. **H2:** approve the one-line Compose change and the container recreate (and the pre-change dump).
3. **Network access for the first image build and scanner install:** authorize pulling the base image and installing a scanner (Trivy/Grype via Homebrew or a release binary), or provide a different source.
4. **Base image choice** (python slim vs distroless/static) and scanner choice.
5. **tmpfs-only workspace** for 2b (RAM-backed, size-capped) — accept, or require volumes with polling.
6. **Tier B path on Docker Desktop:** second user with its own Docker runtime vs a different host; needed before any non-dev use, not before 2b.
7. Explicit authorization of **M1.5-2b** itself (this document does not grant it), including permission to contact the Docker daemon.

Nothing in this document authorizes, and nothing was done to: Docker (any call), images, containers, Docker Desktop settings, PostgreSQL/Compose configuration, firewall/network, source code, dependencies, credentials, or deployment.

---
## 8. CP-010 operator decisions, results and refined plan (governs over sections 1-7)

### 8.1 M1.5-2a accepted
Recorded in `AGENT_STATE.md` / `EXECUTION_LOG.md` (CP-010). 2b is **not** authorized; nothing of 2b or 2c was started.

### 8.2 H1 — Docker Desktop file sharing: NOT changed (operator decision)
The setting is shared with other projects, so no change. Read-only inventory (Docker `ps`/`inspect`, no modification), 2026-11-08:

| Container | Compose project | State | Mounts | Notes |
|---|---|---|---|---|
| `astrava-postgres` | `astrava` | running | named volume `astrava_postgres_data` | no bind mount |
| `bl-pg` | none | running | anonymous volume | no bind mount; published on `0.0.0.0:55432`; owner project unknown; **not touched** |
| `keep-keep-frontend-dev-1` | `keep` | exited 7 weeks | bind `/Users/abstract/Documents/works/dana/keep/keep-ui -> /app` + 2 volumes | would fail to start if `/Users` were unshared |
| `keep-keep-backend-dev-1` | `keep` | exited 7 weeks | binds `.../dana/keep -> /app`, `.../dana/keep/state -> /state` | same |
| `keep-keep-websocket-server-1` | `keep` | exited 7 weeks | none | |

Also: `ohmic-api/docker-compose.yml` bind-mounts `./db/migrations` (no container exists now). Named volumes of other projects exist (`cvat_*`, `adsign-mcp-server_qdrant_data`, `garena_take_home_test_ollama_data`, `reporty-ai-agent-api_kafka_data`); their compose files are outside `personal_project` and were not inspected, so their mount types are unknown. **Conclusion:** narrowing is not safe to propose as "empty"; a future proposal would need a per-project list (at least `.../works/dana/keep`, `.../personal_project/ohmic-api`) after the operator confirms which projects are still used. ASTRAVA itself needs no shared path. H1 stays open and unscheduled.

### 8.3 H2 — PostgreSQL loopback binding: APPLIED
- Pre-checks: Compose project `astrava`, service `postgres`, container `astrava-postgres` (image `postgres:16-alpine`, PostgreSQL 16.15), volume `astrava_postgres_data` (created 2026-11-01), databases `astrava postgres template0 template1`, Alembic `c8a1f3d5e7b9`, no ASTRAVA API/Alembic/pytest process running, only listener `*:5433`.
- Backup: `pg_dump -Fc` to `~/astrava-backups/astrava-pre-rebind-20261108.dump` (68,179,267 bytes, mode 0600, sha256 `7425dfd358bdef910f69df80d2650c82be044848599d6996659b75c68a87a876`, outside the repo). Usability: restored into scratch database `astrava_restore_check`, all 19 public tables had identical row counts to the live database, Alembic version intact, scratch database dropped. (A first count attempt returned an empty list; it was discarded and redone with a shell loop.)
- Change (one line, `docker-compose.yml`): `"5433:5432"` -> `"127.0.0.1:5433:5432"`; applied with `docker compose up -d --no-deps postgres` (only this service recreated).
- Results: `lsof` shows only `127.0.0.1:5433`; container healthy; volume unchanged (same creation time); 19 tables' row counts identical before/after; asyncpg to `127.0.0.1` and `localhost` both work (about 11-16 ms); `::1:5433` refused; `localhost` resolves to `::1` then `127.0.0.1` and clients fall back immediately (no failure, no measurable delay); LAN address refused; `alembic current` = `c8a1f3d5e7b9 (head)`, `alembic check` clean; `bl-pg` unchanged (same container, `0.0.0.0:55432`, uptime 7 days); the three `keep-*` containers stay exited.
- **IPv6 behavior:** loopback-only IPv4 publication. `::1` is refused by design; tools that resolve `localhost` retry on `127.0.0.1`. No source change.
- Rollback: (1) `git checkout -- docker-compose.yml` (or edit line 11 back to `"5433:5432"`); (2) `docker compose up -d --no-deps postgres`; (3) check `docker ps` shows `0.0.0.0:5433->5432`. Data is in the named volume and is not touched by either step. Only if the volume is damaged: recreate the database and `pg_restore -U astrava -d astrava --clean --if-exists` from the dump above.
- Not changed: credentials, schema, other ports, any other container.
- Remaining caveat: loopback publication does not prove containers cannot reach the host's 5433 through Docker Desktop's gateway; workers use `network: none` and 2b contains a negative probe.

### 8.4 Final 2b image specification (planning; nothing built or pulled)
| Item | Decision |
|---|---|
| Base | `python:3.12-slim-bookworm`, referenced as `python@sha256:<digest>`; the digest is **resolved at the authorized build step** (resolving it needs registry access, which was not performed) and then recorded in `worker_images/images.lock` |
| Contents added | one stdlib-only stub (`worker_stub.py`) and nothing else: no pip packages, no apt packages, no Node, no compilers, no git, no shell tooling beyond what the base ships |
| Reductions | remove `pip`, `setuptools`, `wheel` and `ensurepip` from the image in the build (runtime never installs anything); remove package-manager caches/lists; no setuid/setgid files (test asserts it); `PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1`, `-I` isolated mode in the entrypoint |
| Runtime user | `USER 10001:10001`, no login shell, no home directory write access |
| Entrypoint | exec-form `["python","-I","/opt/astrava/worker_stub.py"]`; the broker, not the caller, chooses image and command |
| Probe image | a second alias `probe` from the same base plus `probe_stub.py` (stdlib `ctypes`/`socket`/`os` probes); mapped only in test profiles, never in production profiles |
| Labels | `org.opencontainers.image.*`, `astrava.image.alias`, lock-file hash |
| Provenance | digest-pinned base, Dockerfile hash, built image ID, build date, SBOM and scan-result digests in `images.lock` (committed); broker refuses an ID mismatch |
| Scan | Trivy, **proposed, not installed**: availability, checksum/signature of the release and database provenance must be verified when installation is authorized; gate = no fixable CRITICAL/HIGH |
| Not in the image | model SDKs, agent code, credentials, Git, project dependencies (see 8.6) |

### 8.5 Build-time network requirements (all need explicit approval at the time; none performed)
1. **Base image pull** from Docker Hub: registry and token endpoints (`registry-1.docker.io`, `auth.docker.io`) and the layer CDN (`production.cloudflare.docker.com`). One pull of `python:3.12-slim-bookworm` (by digest after resolving it).
2. **Trivy installation** (if approved): one release binary from GitHub Releases (`github.com`, `objects.githubusercontent.com`) with checksum verification, or Homebrew (`formulae.brew.sh`, `ghcr.io`); decide at that time.
3. **Trivy vulnerability database**: `ghcr.io/aquasecurity/trivy-db` (use `--skip-java-db-update`; Java DB not needed).
4. **No** `apt`, `pip`, `npm`, `git clone` or any other network access inside the Dockerfile. Patch level comes only from choosing a newer pinned base digest.
5. Runtime workers: **no network at all** (`network: none`).
After the pull and the DB download, the build and the scan run offline.

### 8.6 Providing project dependencies without worker network (design; not part of 2b)
2b ships **no** project dependencies (the stub uses the standard library only). Later designs, each needing its own authorization:
1. **Dependency preparation step** run by the broker side, separate from workers: lockfile-driven, hash-pinned (`pip download --require-hashes --only-binary=:all:`, or `npm ci --ignore-scripts`) in a throw-away prep container that has network but **no project source and no credentials**; only wheels (no sdist builds, which execute code); result is a content-addressed tar archive, scanned and size-capped, cached by lockfile hash.
2. **Delivery**: the archive is written into the worker's tmpfs (`/deps`) through the Engine archive API, like the input snapshot; no bind mount, no volume, no network. Pure extraction (`PYTHONPATH=/deps`), so `pip` is not needed at runtime. Cost: RAM-backed, counted in the worker memory budget.
3. **Fallback if egress is ever required** (D1 stays BLOCKED): allowlist proxy on an internal network, designed in the reassessment section 11, not built.
4. Dependencies that need compilation, post-install scripts or network at import time are **unsupported** in this design and fail closed.

### 8.7 Runtime security guarantees and limitations (2b, Docker Desktop, tier A)
Guaranteed (kernel-enforced inside the Docker Desktop Linux VM and verified by probes): no network; read-only root filesystem; writable space only in size-capped `noexec,nosuid,nodev` tmpfs; uid 10001; `CapEff` empty; `no-new-privileges`; explicit seccomp profile; no bind mounts, no Docker socket, no devices; CPU, memory (no swap), PID and `nofile` limits; broker-enforced wall-clock kill; Docker Engine API reachable only by the broker code path (the API process has no path to it); epoch fencing and label-based reconciliation after crashes; image identity checked by ID.
**Not guaranteed:** containment after a kernel/runc escape (VM runs as the operator; operator-level code on macOS); protection against a same-user hostile process (tier A is development-only and is not a boundary); per-volume disk quota; accuracy of the wall clock across sleep; behavior under VM memory pressure shared with other projects' containers; reproducible builds; protection of the host's published ports against workers beyond `network: none`.

### 8.8 Tier B infrastructure proposal (separate infrastructure milestone; tier A stays development-only)
- Per the operator: no attempt to expose the current Docker Desktop to another macOS user and no change to its socket permissions.
- **Direction:** a dedicated Linux VM or host (Debian/Ubuntu LTS, arm64 or amd64) with its own Docker daemon (preferably rootless, or rootful with `userns-remap`) owned by a dedicated `astrava-broker` account; optional `runsc` (gVisor) runtime, which is available on Linux and not on this Mac; no other workloads on the daemon.
- **Identity and transport:** the broker runs on that host as `astrava-broker`; the API host holds no Docker credentials. To keep the 2a contract unchanged, expose the broker's Unix socket to the API host through an SSH unix-socket forward with a dedicated restricted key (forward-only, no shell, no other forwards), and keep the HMAC envelope (key rotated and stored per host). A network-native transport (mTLS) would be a reviewed contract/transport change.
- **Host hardening:** default-deny firewall with only SSH from the API host inbound; default-deny egress except the explicitly approved image-preparation window; separate disk with XFS project quotas or a size-limited filesystem so disk limits are real; auditd/journal retention; unattended security updates for the host OS; the image preparation host path (8.5) lives here.
- **Gates for this milestone (outside 2b/2c):** independent review; re-run of the 2b escape/limit/probe suite on the target host; a negative test showing the API host cannot reach the daemon; failure tests for transport loss and host reboot; documented key rotation and break-glass procedure. It needs its own authorization and infrastructure decisions (where the VM lives, who administers it).

### 8.9 Refined 2b acceptance gates (additions to section 6)
12. Image build only from a digest-pinned base after explicit approval of the network steps in 8.5; `images.lock` produced and verified by the broker.
13. Trivy installation verified (checksum/signature) before it is trusted; scan result stored; if Trivy cannot be verified, a different scanner is chosen by the operator, never silently.
14. Evidence that the final image contains no pip/setuptools/wheel, no setuid files, no compilers, and only the stub files.
15. Probe results include host-gateway and `127.0.0.1:5433` reachability from inside a worker (must fail).
16. Leak audit: zero astrava-labelled containers/volumes/networks and no change to `bl-pg`, `keep-*` or other unrelated containers after the suite; Docker daemon state compared before/after.
17. No H1 change is assumed or required by any 2b test.
