# M1.5-2a — Worker broker contract, fake runtime and recovery integration (spec)

Status: authorized by the operator (2026-11-08), **2a only**. Base commit `5cfdea5`. Design source: `V1_5_M1_5_2_ARCHITECTURE_REASSESSMENT.md` (section numbers below refer to it). ADR-028 stays **Proposed**.

## 1. Scope
In: typed broker contract + validation; broker skeleton with a **fake backend**; API-side `WorkerRuntime` interface with `BrokerWorkerRuntime` and `FakeWorkerRuntime`; `worker_runs` migration; integration with M1.5-1c recovery and epoch fencing; static security guards; process-level crash/recovery tests.

Out (prohibited and not done): Docker daemon access, Docker SDK, containers, image builds, credential injection or experiments, network or host privilege changes, deployment, anything of M1.5-2b / 2c. Nothing in 2a can start a process on behalf of a caller; the only backend is a deterministic simulation.

## 2. What was built
| Piece | Location | Notes |
|---|---|---|
| Contract (the only broker module the API may import, with `profiles`) | `backend/astrava_broker/contract.py`, `profiles.py` | Nine operations, `extra="forbid"` everywhere, bounded values, HMAC-SHA256 envelope, signed responses |
| Broker service | `astrava_broker/service.py` | Replay ledger, per-execution epoch high-water mark, worker↔execution binding, state machine, deadline/stale-epoch reaper, audit log |
| Backend interface + fake | `astrava_broker/backend.py` | `WorkerBackend` protocol; `FakeBackend` persists to SQLite so a broker restart reconstructs workers (stands in for container labels) |
| Server | `astrava_broker/server.py`, `__main__.py` | HTTP/1.1 over a Unix socket, **one route** `POST /v1/call`, socket 0600 in a 0700 directory, body cap, no docs/openapi |
| Config | `astrava_broker/config.py` | `ASTRAVA_BROKER_*` only; refuses any backend except `fake`; key file hygiene (regular file, owner, 0600, ≥32 bytes) |
| Runtime interface | `app/worker_runtime/base.py` | Nine abstract methods, error taxonomy, no Docker concept |
| Broker client | `app/worker_runtime/broker.py` | httpx over UDS; signs requests, authenticates and re-validates responses; transport failure → `RuntimeUnavailableError` (fail closed) |
| Fake runtime | `app/worker_runtime/fake.py` | Independent in-process implementation with fault injection |
| Selection | `app/worker_runtime/factory.py`, settings `WORKER_RUNTIME` (default `disabled`), `BROKER_SOCKET_PATH`, `BROKER_KEY_FILE` | No fallback to host execution |
| Persistence | `app/models/worker_run.py`, migration `c8a1f3d5e7b9` | `worker_runs`, state check constraint, unique `(execution, task, attempt, kind)` |
| Bookkeeping + recovery | `app/services/worker_run_service.py`, `OrchestrationRunner._reconcile_workers` | Fenced writes, forward-only states, reconcile before reservation expiry, fail closed |

## 3. Amendments to the reassessment (traceable; the reassessment text is unchanged)
1. **Wire transport:** HTTP/1.1 over a Unix socket (httpx, per the operator's dependency decision) instead of length-prefixed JSON. The envelope, MAC, nonce and error codes are as in section 6.
2. **`list_workers` is execution-scoped** (requires `execution_id` + `lease_epoch`; no global listing). Tighter than the reassessment's "optional execution_id".
3. **`credential_handle` is not in the contract at all** (D1 blocked). Adding it later is a contract change that needs its own review.
4. **`export_artifacts` returns a validated manifest only** in 2a (paths, sizes, sha256). The sha256-addressed file stream and the real filter arrive in 2c. The API re-validates every manifest path (broker output is untrusted).
5. **`ADMITTED` is not used in 2a rows** (REQUESTED → CREATED); it is introduced when workers are wired to the budget reservation in dispatch.
6. **Responses are signed** (domain-separated MAC bound to the `request_id`), so a process squatting on the socket path cannot spoof worker state to the API.
7. **Epoch fencing at the broker:** the broker keeps a persistent per-execution epoch high-water mark; any request with an older epoch is refused, `start/collect/export` require the worker's own epoch, and its reaper stops workers of superseded epochs even when no API process is alive.
8. **Profiles carry `network: "none"` for both kinds.** Provider egress for agents is undecided (D1) and is not enabled.

## 4. Security model in 2a (stated plainly)
- **Tier A only** (same macOS user). The socket mode, directory mode and MAC are the only controls; **they are not a security boundary against code running as the same user** (that code can read the key file and the socket). Tier B (separate OS user) is required before any broader use and is not implemented in 2a.
- What 2a *does* establish and test: the API holds no Docker capability (static guards: no container-client import, no Docker socket or CLI reference, no process spawning of container CLIs, and the broker imports nothing from `app`); the contract cannot express arbitrary container configuration; the runtime is replaceable; recovery fences stale owners at three layers (PostgreSQL epoch, broker epoch, reservation fence token).
- The fake backend interprets a `{"fake": {...}}` hint in `job` to script a simulated worker. That is fake-only behaviour; a real backend treats `job` as opaque bytes.

## 5. Recovery order (extends M1.5-1c)
`claim lease` → **`list_workers` (also raises the broker's epoch mark)** → terminate/clean every worker of an older epoch (DB rows to `CLEANED`) → **only then** `expire_orphaned_reservations` → re-enter the graph. A runtime that is unavailable, misconfigured or fails to clean a worker raises `WorkerReconcileError`: the event `recovery_blocked` is recorded, the lease is released, reservations are **not** settled and no provider call is made; the execution stays `RUNNING` and recoverable (`recovery_cli` exit code 5). Open worker rows with no configured runtime also block recovery.

## 6. Residual risks / not done in 2a
- No real isolation exists yet (no Docker backend); host agent execution is unchanged and still unfenced for file side effects until 2b/M1.5-4.
- Same-user tier A is not a boundary. Replay protection is persistent, but anyone holding the key can mint requests.
- Fake-backend timing is a pure function of timestamps; real backend behaviour (kill latency, cleanup failures, disk) is untested until 2b.
- Preserved, unresolved: worktree artifact retrieval limitation, intermediate-directory TOCTOU, other repo-local Git configuration, tracked-files-only dirty check, host-side repository parsing/verification, subscription credential restriction (D1), unverified model availability (D5), SD-07, M1.5-1c at-least-once provider invocation.
- Host settings (Docker Desktop file sharing, PostgreSQL bound to `0.0.0.0:5433`) are **unchanged**; proposals are reported separately.
