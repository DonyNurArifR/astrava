# ASTRAVA Security Model — Operator Authentication and Audit Identity

**Introduced:** V1.5 milestone M1.5-1a. **Scope:** the API surface only. Worker isolation, credential brokerage and RBAC are separate, unstarted milestones.

## 1. Threat summary
ASTRAVA's API can start agent executions, change which host path a project reads, edit agent configuration, approve risky actions and merge code. Before M1.5-1a, 16 of 33 mutating routes were unauthenticated, GET routes were open, the server defaulted to `0.0.0.0` with `DEBUG=true`, and the audit actor could come from a client header. This milestone closes SD-01, SD-05 and SD-08 (see `V1_5_TECHNICAL_RISKS.md` section 6).

## 2. Authentication modes
Decided per request by `OPERATOR_API_KEY`.

| Mode | Condition | Who is served |
|---|---|---|
| **Keyed** | `OPERATOR_API_KEY` set (>= 32 chars) | Requests with `Authorization: Bearer <key>`, `X-ASTRAVA-OPERATOR-KEY: <key>`, or a valid signed session cookie. Everything else: `401`. |
| **Local development** | key unset | Only loopback peers, with an allowlisted `Host`, and no forwarding headers. Everything else: `403`. |
| **Misconfigured** | key set but blank/short | The process refuses to start. A blank key that slips through still fails closed (`401`). |

There is **no default key and no hardcoded credential.** Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Default-deny
Authentication is a global FastAPI dependency (`authenticate_request`). Every route, including routes added later, requires authentication unless its endpoint is explicitly marked `@public_route`. The public set is exactly:

`GET /`, `GET /api/v1/healthz`, `GET /api/v1/readyz`, `POST /api/v1/auth/login`, `GET /api/v1/auth/session`, `POST /api/v1/auth/logout`.

This is enforced by tests, including a probe that registers new unmarked routes at runtime and requires `401`.

### Request guard (`SecurityGuardMiddleware`)
A pure-ASGI middleware runs inside CORS for every HTTP request, in every mode:
- `Host` must parse (port stripped, IPv6 brackets handled) to a name in `ALLOWED_HOSTS` (defends against DNS rebinding and Host-header attacks). Duplicate or malformed `Host` values are rejected.
- In local-dev mode the peer must be loopback (a missing peer is treated as non-loopback) and none of `Forwarded`, `X-Forwarded-*`, `X-Real-IP`, `Via`, `CF-Connecting-IP`, `True-Client-IP`, `X-Client-IP`, `X-Cluster-Client-IP`, `X-Original-Forwarded-For`, `Fastly-Client-IP`, `X-Envoy-External-Address` may be present, so a reverse proxy cannot silently turn a loopback bind into public unauthenticated access.
- For `POST/PUT/PATCH/DELETE`: an `Origin` header, if present, must be a configured CORS origin or the request's own origin; `Origin: null` is rejected. `form`, `multipart` and `text/plain` bodies are rejected (`415`) so cross-site "simple request" tricks cannot reach JSON endpoints.
The same checks are repeated inside `get_operator_context` as defense in depth.

## 3. Browser sessions and CSRF
- `POST /api/v1/auth/login {api_key}` verifies the key (constant-time), then sets cookie `astrava_session`: `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age=SESSION_TTL_SECONDS` (default 8 h), and `Secure` over HTTPS or whenever `APP_HOST` is non-loopback (override with `COOKIE_SECURE`).
- The cookie is a stateless signed token: `v1.<payload>.<HMAC-SHA256>`. The signing key is derived from the operator key, so **rotating the operator key invalidates every session.**
- **The operator key never reaches frontend JavaScript, local storage, the Vite bundle or any runtime config.** The login form posts it once; the browser keeps only the HttpOnly cookie. The CSRF token returned by login/`GET /auth/session` is not a credential on its own and is held in memory only.
- Cookie-authenticated `POST/PUT/PATCH/DELETE` must send `X-CSRF-Token` equal to the session's token (HMAC bound to the session id), else `403`. Bearer/key-header clients carry no ambient credential and are exempt.
- Failed logins are rate limited per peer (5 per 300 s, then `429` with `Retry-After`); the tracker is bounded (1024 peers), self-purging, and evicts unlocked peers before locked-out ones. The submitted value is never logged or echoed.
- `POST /auth/logout` clears the cookie and revokes the session id in process memory.

## 4. Audit identity
Identity is derived only from authenticated server-side context:
- `actor_id` = `display_name` = server setting `DEFAULT_OPERATOR_NAME`.
- `actor_type` = `operator` (key/session) or `operator_local_dev` (unauthenticated local development), so audit rows distinguish the two.
- `X-ASTRAVA-ACTOR-NAME` was removed and is ignored. Legacy body fields (`decided_by` on approvals, `actor_id` on conflict resolution, `verified_by` on memory verification) are optional; a value that differs from the server identity is rejected with `403`, and the server value is what is recorded. Orchestrator resume passes the server-derived approver to the runner.

## 5. Startup and secure defaults
`validate_security_configuration` runs in the application lifespan; a violation aborts startup:
- `OPERATOR_API_KEY` set but blank or shorter than 32 characters;
- non-loopback `APP_HOST` without a key, or with `DEBUG=true`, or with `COOKIE_SECURE=false`;
- `*` in `CORS_ORIGINS` or `ALLOWED_HOSTS`.
Defaults are now `APP_HOST=127.0.0.1` and `DEBUG=false`. OpenAPI/Swagger/ReDoc exist only when `DEBUG=true`, which is refused on non-loopback hosts. Supported entrypoint: `uv run python -m app.serve` (validates, then serves on `APP_HOST:APP_PORT`). Because uvicorn's own `--host` flag is invisible to the app, the request-time local-dev guard is the binding defense if someone binds wider than configured.

## 6. Local development
1. Leave `OPERATOR_API_KEY` **unset** (do not set it to an empty string; blank is rejected).
2. Run `uv run python -m app.serve` or `uv run uvicorn app.main:app --host 127.0.0.1`.
3. Use the Vite dev server (`npm run dev`); its proxy talks to `localhost:8000` from loopback and works without login. The UI shows no login screen.
4. Audit rows are tagged `operator_local_dev`.
To exercise the real auth flow locally, set `OPERATOR_API_KEY` to a 32+ character value and sign in through the UI.

## 7. Deploying beyond loopback
Set a strong `OPERATOR_API_KEY`, `APP_HOST`, `ALLOWED_HOSTS` (the public hostname), `CORS_ORIGINS` (exact origin), keep `DEBUG=false`, and terminate TLS in front (cookies are `Secure`). The login and mutation paths work only over HTTPS then. **Behind a TLS-terminating proxy the backend sees `http://`, so list the public `https://` origin in `CORS_ORIGINS`; otherwise browser mutations are rejected with `403` (fail closed). The app logs a startup warning when a non-loopback deployment has no public origin configured.** A single operator is assumed; this is not multi-tenant RBAC.

## 8. Accepted residual risks
- Revoked session ids are held in memory; a restart forgets them until the cookie expires (max 8 h). Single-process deployment assumed.
- Unmatched paths/methods return `404/405` before authentication, so route existence is observable.
- Free-text `reason` fields are stored verbatim in audit rows (content, not identity).
- The worktree commit author is still hard-coded in `workspace/worktree_manager.py` (not client-controlled; handled in later milestones).
- In DEBUG mode (loopback only) the docs routes are unauthenticated.
- One shared operator key; no per-user identity or role separation.

## 9. Test evidence
`backend/tests/test_m1_5_1a_core.py` and `backend/tests/test_m1_5_1a_operator_auth.py` cover the route inventory (all routes, default-deny), the 401 matrix over every non-public route, session/CSRF/Origin/Host/forwarding/content-type guards, rate limiting, key non-leakage, spoofed identity, startup validation and secure defaults. Frontend tests cover the CSRF header, the 401 event, the login form and absence of key storage.

## 10. Path containment and fail-closed execution setup (M1.5-1b)
- **Canonical containment.** All locations that come from an API client, a planner/LLM output or a stored database value pass through `app/workspace/path_security.py`: `is_within`/`safe_join` resolve symlinks and use `Path.is_relative_to` (never string prefixes). Rejected: traversal, absolute and drive/UNC forms, backslashes, control/format/private-use Unicode and fullwidth look-alikes (NFKC-normalized check), any `.git` component (case, trailing-dot and look-alike variants), over-long names, and symlinks that leave the root or point at a sibling such as `<root>_evil`.
- **Artifacts.** Registration verifies ownership (project, execution, task key) and that the file lies in the project's own artifact directory; provenance is written by the server. `artifact_node` and artifact adoption skip hostile names and write with `write_text_contained` (re-validation, parent resolution, `O_NOFOLLOW` on the final component). `PlannedTask.expected_output_artifacts` rejects unsafe names at plan time (the template plan is the fallback).
- **Repositories.** `repo_path` must sit inside `ALLOWED_REPO_ROOTS` (default empty = fail closed), be a git work-tree top level, and not overlap storage. Configure `ALLOWED_REPO_ROOTS` as a JSON list of absolute directories; `/` and your home directory are refused.
- **Merge target.** `merge_worktree` merges only when the repository's checked-out branch equals the intended target and tracked files are clean; it never switches branches in your repository, accepts only `astrava/exec-*` branches, and uses full `refs/heads/...` names.
- **Git hardening.** Every git call made by ASTRAVA runs with a sanitized environment (inherited `GIT_*` variables dropped, `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`) and `-c core.hooksPath=/dev/null`, so hooks planted in a repository or worktree do not run during ASTRAVA's add/commit/merge/worktree operations.
- **No host fallback.** The work-directory fallback to the project's artifact directory was removed. A repo-bound execution whose repository, base branch or worktree is missing, rejected or deleted ends `FAILED` (`execution_setup_failed`); no provider or task runs. Projects without `repo_path` are unchanged. A failed setup leaves no budget or reservation (the budget is created after setup succeeds); `GET /executions/{id}/budget` returns 404 for such an execution.
- **Residual risks (documented, not solved):** (1) until M1.5-4, agents still run on the host, so an agent can race an intermediate directory between a containment check and a write (TOCTOU); `O_NOFOLLOW` only protects the final component. (2) Verification and `RepoScanner` still parse and run repository content on the host (SD-07). (3) ASTRAVA's own git calls disable hooks, `core.fsmonitor`, external diff drivers and textconv, but other repository-local git configuration that git honors in an allowlisted repository is not individually neutralized; allowlist only repositories you trust. (4) Artifacts produced inside an isolated worktree are registered under `<project_id>/<name>` although the files live in the worktree: provenance records the worktree file's sha256 and `location: "worktree"`, but preview/download of such artifacts returns 404 (pre-existing; tracked debt, resolved when worker snapshots land). (5) Existing projects with a stored `repo_path` stop executing until `ALLOWED_REPO_ROOTS` includes them (intended, fail closed).


## 11. Execution ownership and recovery (M1.5-1c)
- **Single writer.** Running, resuming or recovering an execution requires its lease (`workflow_executions.run_epoch/lease_owner/lease_expires_at`). A claim is one atomic database update; state writes are fenced on the epoch, so a superseded ("stale") worker cannot overwrite a newer owner, and it cancels its own run when its heartbeat detects the loss.
- **Finished executions stay finished.** `COMPLETED`, `FAILED` and `CANCELLED` cannot be reopened or flipped (service guard, 409 on pause/resume). The resume endpoint only undoes a manual pause; approvals go through the orchestrator resume.
- **Reservations.** A crash cannot leave a permanent hold: recovery force-settles orphaned reservations once, and their old fence tokens stop working.
- **Recovery is operator-run** (`python -m app.orchestrator.recovery_cli`), never automatic, because it can invoke the provider again.
- **Residual:** at-least-once provider invocation after a crash; file-system side effects of a stale agent are not fenced until containerised workers exist. See `docs/V1_5_M1_5_1C_ACCEPTANCE_REPORT.md` section 5.
