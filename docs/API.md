# ASTRAVA REST API Reference
**Base URL:** `http://localhost:8000/api/v1`

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
    "debug": true
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
Resumes an execution paused at a human approval checkpoint.
- **Request Body:**
  ```json
  {
    "decision": "approved",
    "reason": "Operator authorized high-risk step",
    "decided_by": "Abstract"
  }
  ```
- **Response `200`:** Updated execution record.

---

## 4. Human Governance Approvals (`/api/v1/approvals`)

### `GET /api/v1/approvals`
Lists approval records. Query parameter `pending_only=true` filters for pending actions.

### `POST /api/v1/approvals/{approval_id}/decide`
Submits decision (`approved` or `rejected`) with reasoning.

---

## 5. Artifacts (`/api/v1/artifacts`)

### `POST /api/v1/artifacts`
Registers a new artifact with path validation.

### `GET /api/v1/artifacts/project/{project_id}`
Lists all registered artifacts for a project.

### `GET /api/v1/artifacts/{artifact_id}/preview`
Returns text/markdown preview of artifact contents.

### `GET /api/v1/artifacts/{artifact_id}/download`
Downloads the file directly.

---

## 6. Intelligence & Telemetry (`/api/v1/intelligence`)

### `GET /api/v1/intelligence/summary`
Telemetry summary: total executions, total duration, token consumption, and cost estimates.

### `GET /api/v1/intelligence/usage`
Granular log of model execution events (provider, model, duration ms, input/output tokens, cache reads, exit code).
