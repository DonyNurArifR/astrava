# ASTRAVA V1.5 — M1.5-1a Acceptance Report
## Operator Authentication and Audit Identity

**Baseline:** `3623d43` (V1.5 planning, on top of frozen V1.4 `ed08f15`). **Scope:** M1.5-1a only. M1.5-1b, M1.5-1c, M1.5-2 and later were **not** started; the API process has **no** Docker access; no worker, credential-injection or credential-brokerage code exists.
**Roles:** Sonnet orchestrator (scope, design, review, verification, git); Antigravity (design critique and independent security review, read-only); Claude Code **Haiku 5.5** on the Claude Pro subscription (banner `Haiku 5.5 · Claude Pro`, started with `--model claude-haiku-5-5`; no fallback model, no API key) executed four bounded tasks H1-H4. No `CLAUDE_CODE_OAUTH_TOKEN` was minted, no subscription credential was moved into a container, no model-availability or other billable call was made by the orchestrator.

## 1. Before / after findings
| ID | Finding at baseline (verified in source) | After M1.5-1a |
|---|---|---|
| SD-01 | 16 of 33 mutating routes unauthenticated (orchestrator execute/resume/plan/understand, project create/update/delete, agents seed/create/update/status, tasks, workflows, artifacts register) | **Closed.** Global default-deny dependency; 0 unauthenticated mutating routes; new unmarked routes are denied automatically (proved with runtime-registered rogue routes) |
| SD-05 | Unset key trusted every caller; `is_authorized_verifier` always true; audit actor from `X-ASTRAVA-ACTOR-NAME`; client `decided_by`/`actor_id`/`verified_by` honored | **Closed.** Local-dev mode limited to loopback + allowlisted Host + no forwarding headers; header removed; identity server-derived only; mismatching legacy fields return 403; `actor_type` distinguishes `operator` / `operator_local_dev` |
| SD-08 | All GET routes open; `APP_HOST=0.0.0.0`, `DEBUG=true` defaults; docs always on | **Closed.** GETs authenticated by default; defaults `127.0.0.1` / `false`; docs only when DEBUG; fail-closed startup validation |

## 2. Complete route inventory and authentication coverage
Generated from the live application (`app.openapi()` with `DEBUG=true`, then cross-checked by the inventory tests). 74 routes: 35 mutating (33 pre-existing + `auth/login`, `auth/logout`), 6 explicitly public, 68 authenticated. 16 mutating routes were previously open (bold).

| Method | Path | Before (V1.4) | After (M1.5-1a) |
|---|---|---|---|
| Method | Path | Before (V1.4) | After (M1.5-1a) |
|---|---|---|---|
| GET | `/` | open | public (explicit) |
| GET | `/api/v1/agents` | open | operator auth (default-deny) |
| POST | `/api/v1/agents` | **open** | operator auth (default-deny) |
| GET | `/api/v1/agents/metrics` | open | operator auth (default-deny) |
| POST | `/api/v1/agents/seed` | **open** | operator auth (default-deny) |
| GET | `/api/v1/agents/{identifier}` | open | operator auth (default-deny) |
| PUT | `/api/v1/agents/{identifier}` | **open** | operator auth (default-deny) |
| GET | `/api/v1/agents/{identifier}/metrics` | open | operator auth (default-deny) |
| PATCH | `/api/v1/agents/{identifier}/status` | **open** | operator auth (default-deny) |
| GET | `/api/v1/approvals` | open | operator auth (default-deny) |
| GET | `/api/v1/approvals/pending` | open | operator auth (default-deny) |
| GET | `/api/v1/approvals/{approval_id}` | open | operator auth (default-deny) |
| POST | `/api/v1/approvals/{approval_id}/decide` | verifier-protected | operator auth (default-deny) |
| POST | `/api/v1/artifacts` | **open** | operator auth (default-deny) |
| GET | `/api/v1/artifacts/project/{project_id}` | open | operator auth (default-deny) |
| GET | `/api/v1/artifacts/{artifact_id}` | open | operator auth (default-deny) |
| GET | `/api/v1/artifacts/{artifact_id}/download` | open | operator auth (default-deny) |
| GET | `/api/v1/artifacts/{artifact_id}/preview` | open | operator auth (default-deny) |
| POST | `/api/v1/auth/login` | n/a (new) | public (explicit) |
| POST | `/api/v1/auth/logout` | n/a (new) | public (explicit) |
| GET | `/api/v1/auth/session` | open | public (explicit) |
| GET | `/api/v1/executions` | open | operator auth (default-deny) |
| POST | `/api/v1/executions` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/executions/{execution_id}` | open | operator auth (default-deny) |
| GET | `/api/v1/executions/{execution_id}/budget` | open | operator auth (default-deny) |
| POST | `/api/v1/executions/{execution_id}/budget/increase` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/executions/{execution_id}/diff` | open | operator auth (default-deny) |
| POST | `/api/v1/executions/{execution_id}/merge` | verifier-protected | operator auth (default-deny) |
| POST | `/api/v1/executions/{execution_id}/pause` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/executions/{execution_id}/remediations` | open | operator auth (default-deny) |
| POST | `/api/v1/executions/{execution_id}/replan` | verifier-protected | operator auth (default-deny) |
| POST | `/api/v1/executions/{execution_id}/resume` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/healthz` | open | public (explicit) |
| GET | `/api/v1/intelligence/summary` | open | operator auth (default-deny) |
| GET | `/api/v1/intelligence/usage` | open | operator auth (default-deny) |
| POST | `/api/v1/orchestrator/execute` | **open** | operator auth (default-deny) |
| POST | `/api/v1/orchestrator/executions/{execution_id}/resume` | **open** | operator auth (default-deny) |
| POST | `/api/v1/orchestrator/plan` | **open** | operator auth (default-deny) |
| POST | `/api/v1/orchestrator/resume/{execution_id}` | **open** | operator auth (default-deny) |
| POST | `/api/v1/orchestrator/understand` | **open** | operator auth (default-deny) |
| GET | `/api/v1/projects` | open | operator auth (default-deny) |
| POST | `/api/v1/projects` | **open** | operator auth (default-deny) |
| GET | `/api/v1/projects/stats` | open | operator auth (default-deny) |
| DELETE | `/api/v1/projects/{project_id}` | **open** | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}` | open | operator auth (default-deny) |
| PATCH | `/api/v1/projects/{project_id}` | **open** | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/artifacts/{artifact_id}/lineage` | open | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/goals` | open | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/goals` | verifier-protected | operator auth (default-deny) |
| DELETE | `/api/v1/projects/{project_id}/goals/{goal_id}` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/goals/{goal_id}` | open | operator auth (default-deny) |
| PATCH | `/api/v1/projects/{project_id}/goals/{goal_id}` | verifier-protected | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/goals/{goal_id}/execute` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/memories` | open | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/memories` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/memories/conflicts` | open | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/memories/stats` | open | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/memories/{memory_id}` | open | operator auth (default-deny) |
| PATCH | `/api/v1/projects/{project_id}/memories/{memory_id}` | verifier-protected | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/memories/{memory_id}/archive` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/memories/{memory_id}/audit` | open | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/memories/{memory_id}/resolve` | verifier-protected | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/memories/{memory_id}/restore` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/memories/{memory_id}/revisions` | open | operator auth (default-deny) |
| POST | `/api/v1/projects/{project_id}/memories/{memory_id}/verify` | verifier-protected | operator auth (default-deny) |
| GET | `/api/v1/projects/{project_id}/scan` | open | operator auth (default-deny) |
| GET | `/api/v1/readyz` | open | public (explicit) |
| POST | `/api/v1/tasks` | **open** | operator auth (default-deny) |
| GET | `/api/v1/tasks/project/{project_id}` | open | operator auth (default-deny) |
| GET | `/api/v1/tasks/{task_id}` | open | operator auth (default-deny) |
| PATCH | `/api/v1/tasks/{task_id}` | **open** | operator auth (default-deny) |
| POST | `/api/v1/workflows` | **open** | operator auth (default-deny) |
| GET | `/api/v1/workflows/project/{project_id}` | open | operator auth (default-deny) |
| GET | `/api/v1/workflows/{workflow_id}` | open | operator auth (default-deny) |

The public set is exactly `GET /`, `GET /healthz`, `GET /readyz`, `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`. With `DEBUG=true` (loopback only) four extra documentation routes exist (`/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`); they do not exist otherwise.

## 3. Verification results (run by the orchestrator, not copied from the executor)
| Check | Result |
|---|---|
| Backend `pytest` | **522 passed** (V1.4 baseline 191) in about 34 s |
| Backend `ruff check` / `ruff format --check` | clean / 118 files formatted |
| Frontend `vitest` | **50 passed**, 13 files (baseline 20 / 10) |
| Frontend `oxlint` | **0 errors, 14 warnings, identical to baseline** (all in files this milestone did not introduce; verified against a clean checkout of `3623d43`) |
| TypeScript + production build (`tsc -b && vite build`) | clean, 2075 modules |
| Alembic | no migration added; head unchanged `6db676dd20fd` |

### Authentication, CSRF and identity evidence
- **Route inventory tests** walk every route (including FastAPI's included-router wrappers) and require the public set above; a **401 matrix** runs over every non-public method/path with: no credential, wrong Bearer, wrong `X-ASTRAVA-OPERATOR-KEY`, empty-string configured key, tampered cookie.
- **Independent probe** (`scratchpad`, run by the orchestrator against the real app): rogue routes added after startup via `include_router` and `app.get` return 401; 9 path-normalization/redirect variants never leak; HEAD/OPTIONS do not bypass; `Basic`/`Token`/short-key authorization schemes rejected; cookie signed with another key rejected; session POST without/with wrong CSRF 403, with correct CSRF 200; evil `Origin` 403 even with a valid CSRF token; `text/plain` 415; local-dev: forwarded headers, evil/null `Origin`, public peer, missing client, suffix host (`localhost.evil.com`) all denied; `localhost:8000` and `[::1]:8000` allowed.
- **Real-process smoke tests** (actual uvicorn, loopback and `0.0.0.0` binds, the host's LAN address): dev mode serves loopback only; the same process reached from the LAN address returns 403 for every route including public ones; keyed mode returns 401/200/401 for none/Bearer/wrong; login sets `HttpOnly; SameSite=strict; Max-Age=28800; Path=/` and `Cache-Control: no-store`; cookie GET 200, cookie POST without CSRF 403, with CSRF reaches validation (422); the operator key appeared 0 times in server logs. `python -m app.serve` exits non-zero for: non-loopback without key, short key, blank key, non-loopback with DEBUG, non-loopback with `COOKIE_SECURE=false`, wildcard CORS; a valid non-loopback configuration starts.
- **Audit actor evidence:** tests show `X-ASTRAVA-ACTOR-NAME` ignored in both modes and audit rows (memory audit, budget audit, approvals, workflow events) recording the server operator; `decided_by`/`actor_id`/`verified_by` mismatches return 403 with no state change; `actor_type` cannot be injected. The V1.4 tests that asserted the old header or client-identity behavior were rewritten to assert the opposite (header value not recorded); no assertion was removed.
- **Mutation testing of the new tests (orchestrator):** removing the global dependency, the CSRF check, the Host allowlist, the forwarding-header guard, the identity check or the Origin check each makes the suite fail; originals restored byte-for-byte.

## 4. Independent reviews and remediation
Design review (Antigravity, before implementation) led to: Host parsing with ports and IPv6, `scope['client']=None` denied, bounded rate-limit store, 415 for simple content types, docs only in DEBUG, and updated existing tests.
Implementation review (Antigravity, after implementation): verdict **ACCEPT WITH FIXES**, no Critical or High findings. All findings were remediated in this milestone:
| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | Medium | Same-origin check uses the backend's scheme, so a TLS-terminating proxy causes false 403s unless the https origin is in `CORS_ORIGINS` | Kept strict (fail closed). Startup now logs a warning for non-loopback deployments without a public origin; documented in SECURITY.md section 7 |
| 2 | Low | Rate-limit LRU eviction could drop a locked-out peer | Eviction now prefers unlocked entries; test proves a locked peer survives a flood |
| 3 | Low | CDN/proxy client-IP headers missing from the forwarding guard | Seven headers added with tests |
| 4 | Low | Revocations are in memory and lost on restart | Accepted and documented (max 8 h; single process) |
| 5 | Low | Failed session lookup left the UI unable to reach sign-in after a 401 | Fixed in `AuthContext`; test added |
The orchestrator's own review additionally verified key leakage (logs, errors, frontend storage), constant-time comparisons, cookie flags and the middleware order (guard inside CORS).

## 5. Changed files
Backend: `app/config.py`, `app/main.py`, `app/serve.py` (new), `app/core/{auth,guard,session,security_config}.py` (auth rewritten; guard/session/security_config new), `app/api/v1/{auth,health,approvals,memories,orchestrator}.py`, `app/schemas/approval.py`; tests `conftest.py`, `test_m1_5_1a_core.py` (new), `test_m1_5_1a_operator_auth.py` (new), and updates to `test_v1_4_security.py`, `test_v1_4_budget_hardening.py`, `test_v1_4_workflow_recovery.py`, `test_memory_api.py`, `test_orchestrator.py`, `test_e2e_resilience.py`.
Frontend: `src/api/{client,session,login-error}.ts`, `src/context/{AuthContext.tsx,auth-types.ts,useAuth.ts}`, `src/pages/{LoginPage,ApprovalsPage}.tsx`, `src/App.tsx`, `src/components/Sidebar.tsx`, `src/components/intelligence/{ConflictWorkbench,MemoryDetailModal}.tsx`, `src/types/api.ts`, tests `AuthContext`, `LoginPage`, `client` (new) plus updates.
Docs/config: `README.md`, `.env.example`, `.gitignore` (adds `.claude/` per local policy), `docs/{SECURITY,API,ARCHITECTURE,DECISIONS,PROGRESS,ROADMAP,EXECUTION_LOG,AUTONOMOUS_EXECUTION_STATE,V1_5_M1_5_1A_ACCEPTANCE_REPORT}.md`. The `docs/V1_5_*.md` planning baseline was not modified.

## 6. Remaining security debt
- **Closed here:** SD-01, SD-05, SD-08.
- **Still open (not in scope):** SD-02 (artifact provenance/ownership) and SD-06 (merge target, path-prefix check, fail-open worktree) belong to **M1.5-1b**; SD-03/SD-04 (full runner and graph recovery tests) to **M1.5-1c**; SD-07 (host-side execution of agent-written code, `RepoScanner`) to **M1.5-4**.
- **New residual items (accepted, documented in `SECURITY.md` section 8):** in-memory session revocation; 404/405 reveal route existence; single shared operator key; unauthenticated docs in DEBUG on loopback; worktree commit author hard-coded; client free-text `reason` stored verbatim; the login screen is skipped during the brief session check, so protected calls may fire (and 401) before the sign-in screen appears in keyed mode.
- **Unchanged and out of scope:** D1 credential mechanism (Consumer Terms section 3.7 restriction acknowledged; no OAuth token, subscription credential injection or OAuth proxy was built).

## 7. Confirmations
M1.5-1b, M1.5-1c and M1.5-2 and later were not started. The API process was not given Docker access. No worker containers, credential injection or brokerage were implemented. The Claude authentication mechanism was not changed. No multi-tenancy or RBAC. No history rewrite or force-push.
