# ASTRAVA REST API Reference
**Base URL:** `http://localhost:8000/api/v1`

## 0. Authentication (M1.5-1a)
Every endpoint requires operator authentication except the public set below. See [`SECURITY.md`](SECURITY.md) for the full model.
- **Keyed mode** (`OPERATOR_API_KEY` set): send `Authorization: Bearer <key>` or `X-ASTRAVA-OPERATOR-KEY: <key>`, **or** use the browser session cookie from `POST /auth/login`. Missing/invalid credentials return `401` with `WWW-Authenticate: Bearer`.
- **Local-development mode** (key unset): only loopback clients with an allowlisted `Host` and no forwarding headers are served; others get `403`.
- **CSRF:** cookie-authenticated `POST/PUT/PATCH/DELETE` must include `X-CSRF-Token` (returned by login and `GET /auth/session`). Key/Bearer clients are exempt. `form`, `multipart` and `text/plain` bodies are rejected with `415`; a cross-origin `Origin` on an unsafe request is rejected with `403`.
- **Identity** is always derived by the server. `X-ASTRAVA-ACTOR-NAME` is ignored. The legacy body fields `decided_by`, `actor_id` and `verified_by` are optional; a value that differs from the server's operator name is rejected with `403`.
- **Public endpoints:** `GET /`, `GET /healthz`, `GET /readyz`, `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`.

### `POST /api/v1/auth/login`
- **Request:** `{"api_key": "<operator key>"}` (max 512 chars).
- **Response `200`:** `{"authenticated": true, "auth_method": "session", "actor_id": "...", "csrf_token": "...", "expires_at": "..."}` and `Set-Cookie: astrava_session=...; HttpOnly; SameSite=Strict; Path=/` (`Secure` over HTTPS or non-loopback hosts).
- **Errors:** `401` invalid key; `429` too many failures (`Retry-After` header); `409` when no key is configured (local-dev mode needs no login).

### `GET /api/v1/auth/session`
Never returns `401`. `{"authenticated": bool, "auth_method": "session"|"local_dev"|null, "login_required": bool, "actor_id": str|null, "csrf_token": str|null}`. `csrf_token` is present only for a valid session cookie.

### `POST /api/v1/auth/logout`
Always `200 {"authenticated": false}`; clears the cookie and revokes the session id.

---

## 1. System & Health

### `GET /api/v1/healthz`
Basic liveness probe.
- **Response `200`:**
  ```json
  {
    "status": "healthy",
    "app": "ASTRAVA",
    "tagline": "From vision to execution.",
    "environment": "development",
    "debug": false
  }
  ```

### `GET /api/v1/readyz`
Readiness probe verifying storage directory and database connectivity.
- **Response `200`:**
  ```json
  {
    "status": "ready",
    "database": "connected",
    "storage": "available"
  }
  ```

---

## 2. Projects (`/api/v1/projects`)

### `POST /api/v1/projects`
Creates a new workspace production project.
- **Request Body:**
  ```json
  {
    "name": "MicroSaaS Billing Agent",
    "description": "Autonomous subscription billing and invoicing pipeline",
    "studio_type": "saas",
    "target_objectives": ["Automate invoice generation", "Stripe webhook handling"]
  }
  ```
- **Response `201`:** Project object.

### `GET /api/v1/projects`
Lists all projects. Supports query parameters `studio_type` (`saas` / `media`) and `status`.

### `GET /api/v1/projects/stats`
Aggregated counts: total projects, active projects, tasks, executions, and artifacts.

### `GET /api/v1/projects/{project_id}`
Returns details for a specific project.

### Repository binding (`POST /api/v1/projects`, `PATCH /api/v1/projects/{project_id}`)
`repo_path` must be an absolute path to the top level of a git work tree that lies inside one of `ALLOWED_REPO_ROOTS` (empty list = rejected) and does not overlap ASTRAVA's storage directories; it is stored in canonical (symlink-resolved) form. `base_branch` must be a plain git branch name (no leading `-`, no `..`, spaces or special characters). Violations return `422`. `GET /projects/{id}/scan` re-validates the stored path (`422`). An execution of a repo-bound project **fails closed**: if the repository is rejected, the base branch does not resolve or the worktree cannot be created, the execution ends `FAILED` with an `execution_setup_failed` event and no task or model call runs.

### `DELETE /api/v1/projects/{project_id}`
Deletes project and cascades to tasks, workflows, and artifacts.

---

## 3. Orchestration Engine (`/api/v1/orchestrator`)

### `POST /api/v1/orchestrator/plan`
Generates and validates a structured execution plan without executing tasks.
- **Request Body:**
  ```json
  {
    "project_id": "<UUID>",
    "objective": "Build automated customer feedback triage platform",
    "studio_type": "saas"
  }
  ```
- **Response `200`:** `StructuredPlan` with tasks, dependencies, assigned models, risk levels, and acceptance criteria.

### `POST /api/v1/orchestrator/execute`
Initiates stateful LangGraph autonomous pipeline execution.
- **Request Body:** Same as plan request.
- **Response `202 Accepted`:** Returns execution record with current status (`running` or `waiting_approval`).

### `POST /api/v1/orchestrator/resume/{execution_id}`
Resumes an execution paused at a human approval checkpoint. Only an execution in `waiting_approval` is acted on (atomic claim); any other status, including a repeated or simultaneous resume, returns the execution unchanged. The approver is the authenticated operator; an optional `decided_by` is rejected with `403` if it differs.
- **Request Body:**
  ```json
  {
    "decision": "approved",
    "reason": "Operator authorized high-risk step"
  }
  ```
- **Response `200`:** Updated execution record.

---

## 4. Human Governance Approvals (`/api/v1/approvals`)

### `GET /api/v1/approvals`
Lists approval records. Query parameter `pending_only=true` filters for pending actions.

### `POST /api/v1/approvals/{approval_id}/decide`
Submits decision (`approved` or `rejected`) with reasoning. The approver recorded is the authenticated operator; `decided_by` is optional and rejected with `403` if it differs.

---

## 5. Artifacts (`/api/v1/artifacts`)

### `POST /api/v1/artifacts`
Registers a new artifact (M1.5-1b ownership and containment rules).
- The project must exist (`404`); a given `execution_id` must exist (`404`) and belong to the project (`403`); a `task_id` requires an `execution_id` and must be one of that execution's task keys (`403`).
- `file_path` must resolve (symlinks followed) inside `<ARTIFACT_STORAGE_PATH>/<project_id>/`. Another project's directory is `403`; traversal, absolute paths, `.git` components, control or look-alike Unicode characters, and symlinks are `400`.
- The server writes `metadata_json.provenance` (`source`, `registered_by` = authenticated operator, `sha256` when the file exists and is at most 25 MB, `size_bytes`). A client-supplied `provenance` key is discarded.

### `GET /api/v1/artifacts/project/{project_id}`
Lists all registered artifacts for a project.

### `GET /api/v1/artifacts/{artifact_id}/preview`
Returns text/markdown preview of artifact contents.

### `GET /api/v1/artifacts/{artifact_id}/download`
Downloads the file directly. Preview and download return `404` unless the stored path resolves to a regular file inside artifact storage (symlinks and directories are refused).

---

## 6. Intelligence & Telemetry (`/api/v1/intelligence`)

### `GET /api/v1/intelligence/summary`
Telemetry summary: total executions, total duration, token consumption, and cost estimates.

### `GET /api/v1/intelligence/usage`
Granular log of model execution events (provider, model, duration ms, input/output tokens, cache reads, exit code).

### Execution pause/resume (`POST /api/v1/executions/{id}/pause|resume`)
Finished executions (`completed`, `failed`, `cancelled`) return `409`; `resume` additionally returns `409` unless the execution is `paused` (approvals use the orchestrator resume endpoint).
