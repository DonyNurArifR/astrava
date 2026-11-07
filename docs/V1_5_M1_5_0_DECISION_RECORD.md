# ASTRAVA V1.5 — M1.5-0 Decision Record (reduced, documentation only)

**Status:** Authorized by the operator as a *reduced* M1.5-0. Documentation only. **No credential experiment, no model-availability check, no Docker command that changes state, and no product code was run or changed for this record.**
**Relationship to the planning baseline:** `V1_5_ARCHITECTURE_ASSESSMENT.md`, `V1_5_TARGET_ARCHITECTURE.md`, `V1_5_THREAT_MODEL.md`, `V1_5_TECHNICAL_RISKS.md` and `V1_5_ROADMAP.md` (committed at `3623d43`) are preserved. This file is a separate amendment. The only edit to a baseline document is an appended "Amendment A1" at the end of `V1_5_ROADMAP.md` that carries the updated dependency graph and points here; nothing above it was rewritten.
**Date:** 2026-11-07. **Product code at record time:** `02edb00` (M1.5-1a). **Repository HEAD when written:** `a55c739`.

## 1. M1.5-1a acceptance
The operator **accepted M1.5-1a at implementation commit `02edb00462d9ef6a98a4eb168dedb253f924b29d`** after the re-verification recorded at checkpoint CP-002 (backend 522 passed, frontend 50 passed, ruff clean, oxlint 0 errors with 14 baseline warnings, clean build; Agy's R1-R11 / S1-S10 conformance check all MET and spot-checked by the orchestrator). It is not re-implemented.

Residual risks and observations that **remain open and are not claimed as solved**:
| # | Item | Status |
|---|---|---|
| RR-1 | Revoked session ids are held in process memory; a restart forgets them until cookie expiry (max 8 h). Single-process deployment assumed | Open, accepted |
| RR-2 | One shared operator key; no per-user identity or role separation (no RBAC) | Open, accepted |
| RR-3 | Failed login attempts are rate-limited and logged (peer address only) but **not stored as audit rows** | Open observation |
| RR-4 | `is_authorized_verifier` is true for every authenticated operator (single-operator model); the denial path is covered only by a unit test with a constructed context | Open observation |
| RR-5 | Unmatched paths/methods return 404/405 before authentication, so route existence is observable by unauthenticated peers | Open, accepted |
| RR-6 | With `DEBUG=true` (refused on non-loopback hosts) the OpenAPI/docs routes are unauthenticated on loopback | Open, accepted |
| RR-7 | Behind a TLS-terminating proxy the same-origin check sees `http://`; the public `https://` origin must be listed in `CORS_ORIGINS` (a startup warning is logged otherwise) | Open, documented |
| RR-8 | Per-request authentication overhead was not measured | Open observation |
Source: `docs/SECURITY.md` section 8 and `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`.

## 2. Decisions recorded
| ID | Decision | Notes |
|---|---|---|
| DR-01 | **Docker Desktop is installed and operational on the current host.** Verified read-only at record time: client and server 29.8.0, `linux/arm64`, 12 CPUs, about 8.3 GB VM memory, cgroup v2, `runc` as the only registered runtime. No other container runtime is installed | Nothing was installed, changed or started |
| DR-02 | **Docker is the initial `WorkerRuntime` implementation target.** The `WorkerRuntime` interface remains the coupling boundary: orchestration code must not import Docker types, so Docker-compatible or hardened alternatives (for example Podman, a gVisor runtime) can be added later without rewriting orchestration | Supersedes nothing; confirms Target Architecture sections 3-4 |
| DR-03 | **Pinned baseline worker images.** Worker images are referenced by content digest, built outside the running API by a recorded build step, and scanned. No image is built or pulled from within a task | Roadmap M1.5-2, M1.5-3b |
| DR-04 | **Controlled dependency preparation.** Dependencies for repositories that need them are provisioned by a separate control-plane-run prepare job into a read-only, lockfile-hash-keyed volume. Task workers mount it read-only | Roadmap M1.5-3b |
| DR-05 | **No unrestricted package-index access from task workers.** Task and verification workers have no package-index egress. Missing dependencies fail the task | Roadmap M1.5-3b, M1.5-4a |
| DR-06 | **Mandatory fail-closed behavior.** If the container runtime, worker image, workspace provisioning or security configuration is unavailable, the task fails | Governing rule 1 of `V1_5_ROADMAP.md` |
| DR-07 | **No host-execution fallback.** Host execution never substitutes for a sandbox, in any code path, setting or error handler | M1.5-1b removes the existing silent fallback in the orchestration setup path |
| DR-08 | **No unsafe mode.** No flag, setting or environment variable may enable host execution or weaken isolation. This tightens the earlier planning wording that allowed a separately reviewed development diagnostic: any such tool would need its own explicit, reviewed proposal and operator approval first | Operator instruction in this authorization |
| DR-09 | **No Docker socket inside workers.** Workers never receive the daemon socket or any daemon API access | Enforced by the launch-spec validator (M1.5-2) |
| DR-10 | **No host `HOME` and no unrestricted credential mounts.** Workers get an empty home and no mounts of host credential stores, `~/.claude`, `~/.ssh`, keychain material or similar | INV-14 in the threat model |
| DR-11 | **Subscription OAuth injection remains prohibited/unapproved.** No `CLAUDE_CODE_OAUTH_TOKEN` minting, no copying of subscription credentials into workers, no OAuth credential proxy | Anthropic Consumer Terms section 3.7 (operator-cited); unchanged |
| DR-12 | **No billable API calls without separate authorization.** No API-key billing, no live model call, no model substitution (`--fallback-model` is never passed) | Applies to all milestones |
| DR-13 | **D1 remains BLOCKED** pending an approved provider authentication arrangement for workers. This record does **not** claim that subscription authentication is technically feasible inside an isolated worker; the earlier hypotheses about `setup-token` and an environment variable are unverified third-party reports and are not a plan | See section 3 consequences |
| DR-14 | **D5 remains UNVERIFIED.** `claude-haiku-5-5` is the product's code default and the identifier the executor ran under on the operator's subscription, but account-level availability for product use has not been checked and no check is authorized | |

## 3. Status of D1-D6 after this record
| Decision | Status | Note |
|---|---|---|
| D1 worker credentials | **BLOCKED** | Needs an approved provider authentication arrangement. Alternatives are the operator's to approve; none is assumed |
| D2 container runtime | **Resolved** | DR-01, DR-02 |
| D3 dependency installation | **Resolved (design)** | DR-03, DR-04, DR-05 |
| D4 fail-closed | **Resolved** | DR-06 to DR-09 (stricter than the planning text: no unsafe mode) |
| D5 model availability | **Unverified** | DR-14 |
| D6 operator authentication | **Implemented and accepted** | M1.5-1a at `02edb00`, residual risks in section 1 |

**Consequence of D1 being blocked:** milestone M1.5-4a (credential strategy) cannot start, and M1.5-4 (cutover to containerized agent execution), M1.5-5 and M1.5-6 depend on it. M1.5-1b, M1.5-1c, M1.5-2, M1.5-3 and M1.5-3b do not need a worker credential and are not blocked by D1. Until D1 is resolved, containerized *agent* execution cannot be delivered; host execution must not be used as a substitute (DR-07).

## 4. Updated V1.5 status and dependency graph (supersedes the graph in `V1_5_ROADMAP.md` for status; milestone definitions there still apply)
```
M1.5-0   reduced decision record (this document) .......... DONE when committed
M1.5-1a  operator authentication + audit identity ......... ACCEPTED (02edb00)
   │
M1.5-1b  provenance, merge target, path containment,
         fail-closed worktree setup (SD-02, SD-06) ........ AUTHORIZED by the operator (next)
M1.5-1c  real OrchestrationRunner + persistent recovery
         validation (SD-03, SD-04) ........................ NOT started; needs separate authorization after 1b is accepted
   │
M1.5-2   WorkerRuntime + pinned image + worker_runs ....... needs 1a (met); not authorized yet; Docker access for the API process is introduced here
   ├─► M1.5-3   snapshot + hardened git import ........... needs 1a, 1b, 2
   ├─► M1.5-3b  controlled dependency preparation ........ needs 2
   └─► M1.5-4a  credential strategy ...................... BLOCKED by D1
M1.5-4   atomic cutover to containerized agent/verification  needs 1a, 1b, 1c, 3, 4a  -> BLOCKED by D1 (via 4a)
M1.5-5   integration, leases, recovery, UI ................. needs 4, 3b
M1.5-6   adversarial acceptance and freeze ................. needs 5
```
Security-debt status: SD-01, SD-05, SD-08 **closed** (M1.5-1a). SD-02, SD-06 open, targeted by M1.5-1b. SD-03, SD-04 open, targeted by M1.5-1c. SD-07 open until the M1.5-4 cutover. `V1_5_TECHNICAL_RISKS.md` section 6 still lists the first group as open; this table supersedes it.

## 5. What this record deliberately does not do
- No credential experiment (`claude setup-token` or otherwise), no OAuth token handling, no model call.
- No Docker image build, pull, container start, network or volume creation.
- No change to product code, tests, migrations, dependencies or infrastructure.
- No claim that any worker authentication mechanism is feasible.
