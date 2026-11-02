# ASTRAVA V1.3 — Milestone M1.3-6 Release Report
## REST APIs & Schemas for Project Intelligence

**Release Date:** 2026-11-02  
**Milestone:** M1.3-6  
**Status:** VERIFIED & COMPLETE  
**Git Author:** `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`  
**Base Commit:** `e32b7cfab30a97cb9b08b9c615b4e8c5fdcfddc5`  
**AI Executor:** Canonical Claude Haiku 5.5 (`claude-haiku-5-5`) via non-interactive Claude Code CLI  

---

### 1. Executive Summary

Milestone M1.3-6 exposes ASTRAVA Project Intelligence through a comprehensive, secure, and production-grade REST API.

Prior to M1.3-6, project memory (M1.3-3), knowledge retrieval (M1.3-4), and workflow memory integration (M1.3-5) functioned strictly within the backend service and orchestrator layers. M1.3-6 opens these capabilities to HTTP clients, API consumers, and future UI components (M1.3-7) via thin routers that strictly preserve all underlying service invariants:

1. **Project-Scoped Memory CRUD & Filtering:** List with deterministic pagination, category/provenance/status filters, search queries, and date bounds.
2. **Immutable Revision Mechanics:** Update requests require an `expected_revision` optimistic concurrency token, producing an immutable revision row ($R_{n+1}$) while superseding the predecessor, returning HTTP 409 Conflict on revision collisions.
3. **Lifecycle Operations:** Endpoints for soft-archiving and restoring memories.
4. **Explicit Verification Workflow:** Promotes `AGENT_CONCLUSION` to `VERIFIED_FINDING` with verifier identity and structured evidence.
5. **Conflict Inspection & Resolution:** Project-scoped conflict listing and transactional resolution via `supersede`, `reject`, and `merge` strategies.
6. **Immutable Audit Trail:** Read-only paginated audit access; all mutation attempts to audit history are prohibited.
7. **Artifact Lineage Exploration:** Project-scoped traversal of artifact ancestry, children, and supersession links.

---

### 2. New Endpoint Inventory

All endpoints reside under the `/api/v1` namespace:

| Method | Path | Summary | Response | Key Status Codes |
|---|---|---|---|---|
| `GET` | `/projects/{project_id}/memories` | List and filter memories | `PaginatedResponse[MemoryRead]` | `200`, `400`, `404` |
| `POST` | `/projects/{project_id}/memories` | Create project memory | `MemoryRead` | `201`, `400`, `404`, `422` |
| `GET` | `/projects/{project_id}/memories/conflicts` | List detected conflicts | `PaginatedResponse[MemoryConflictItem]` | `200`, `404` |
| `GET` | `/projects/{project_id}/memories/{memory_id}` | Get memory detail | `MemoryRead` | `200`, `404` |
| `PATCH` | `/projects/{project_id}/memories/{memory_id}` | Create immutable revision | `MemoryRead` | `200`, `400`, `404`, `409` |
| `POST` | `/projects/{project_id}/memories/{memory_id}/archive` | Soft-archive memory | `MemoryRead` | `200`, `400`, `404` |
| `POST` | `/projects/{project_id}/memories/{memory_id}/restore` | Restore archived memory | `MemoryRead` | `200`, `400`, `404` |
| `POST` | `/projects/{project_id}/memories/{memory_id}/verify` | Mark memory verified | `MemoryRead` | `200`, `400`, `404` |
| `POST` | `/projects/{project_id}/memories/{memory_id}/resolve` | Resolve memory conflict | `MemoryRead` | `200`, `400`, `404` |
| `GET` | `/projects/{project_id}/memories/{memory_id}/audit` | Read immutable audit history | `PaginatedResponse[MemoryAuditLogRead]` | `200`, `404`, `405` |
| `GET` | `/projects/{project_id}/artifacts/{artifact_id}/lineage` | Traverses artifact lineage | `ArtifactLineageResponse` | `200`, `404` |
| `GET` | `/artifacts/{artifact_id}/lineage` | Traverses artifact lineage (global) | `ArtifactLineageResponse` | `200`, `404` |

---

### 3. Request & Response Schemas

Organized in [`backend/app/schemas/memory.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/schemas/memory.py) and [`backend/app/schemas/lineage.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/schemas/lineage.py):

- **`MemoryRead`:** Comprehensive Pydantic v2 model exposing all business fields without exposing raw ORM internals (`category`, `summary`, `content`, `provenance_type`, `confidence_score`, `is_verified`, `verified_at`, `status`, `revision`, `previous_revision_id`, `conflict_status`, `conflicting_memory_id`, `metadata_json`, timestamps).
- **`MemoryCreateRequest`:** Validates non-empty `summary` (max 500 chars) and `content`. Direct setting of `is_verified` is excluded from the schema to enforce provenance rules.
- **`MemoryUpdateRequest`:** Requires `expected_revision: int` (ge=1).
- **`MemoryVerifyRequest`:** Requires `verified_by: str` (min_length=1) and accepts structured `verification_details`.
- **`MemoryConflictResolveRequest`:** Validates `resolution` (`supersede`, `reject`, `merge`), mandatory `reason`, and requires `merged_summary` + `merged_content` when strategy is `merge`.
- **`PaginatedResponse[T]`:** Standardized pagination envelope (`items`, `total`, `page`, `page_size`, `total_pages`).
- **`ArtifactLineageResponse`:** Enriched lineage graph (`artifact`, `parent`, `ancestors`, `descendants`, `superseded_by`, `supersedes`).

---

### 4. Project Access & Security Behavior

- **Strict Project Boundary Scoping:** Every endpoint accepts `project_id: uuid.UUID` and invokes `_verify_project_exists(db, project_id)`. If the project does not exist, an immediate HTTP 404 is returned.
- **Cross-Project Access Prevention:** Requesting a resource belonging to Project A via Project B returns HTTP 404. Neither memory content, audit logs, nor artifact lineage are exposed across project boundaries.
- **SQL Injection Safety:** All filtering, counting, and sorting use parameterized SQLAlchemy 2.0 expressions. Whitelist validation regexes protect dynamic sort parameters (`^(created_at|updated_at|revision|confidence_score|summary)$`).
- **Audit Immutability:** Audit routes reject mutating methods (`POST`, `PUT`, `PATCH`, `DELETE`) with HTTP 405 Method Not Allowed.

---

### 5. Memory Lifecycle & Revision Semantics

- **Revision Progression:** Updating a memory does not mutate the existing row in place. `MemoryService.update_memory` inserts a new revision row with `revision = current.revision + 1`, copies attributes, resets `is_verified = False` on text changes, and transitions the prior revision to `SUPERSEDED`.
- **Optimistic Concurrency Control:** If two callers update a memory concurrently, the second update presents a stale `expected_revision` and is rejected with HTTP 409 Conflict (`"Revision conflict: expected 1, current is 2."`).
- **Lifecycle Guards:** Archived memories can be restored to `ACTIVE`. Terminal statuses (`SUPERSEDED`, `REJECTED`) reject archive, restore, and verify operations with HTTP 400 Bad Request.

---

### 6. Conflict Resolution Semantics

Detected conflicts (`conflict_status = DETECTED`) are inspected via `GET /projects/{project_id}/memories/conflicts` and resolved via `POST /projects/{project_id}/memories/{memory_id}/resolve`:
- **`supersede`:** The selected memory transitions to `ACTIVE`, while its partner transitions to `SUPERSEDED`. Both have `conflict_status = RESOLVED`.
- **`reject`:** The selected memory transitions to `REJECTED`, keeping the partner active. Both have `conflict_status = RESOLVED`.
- **`merge`:** Requires `merged_summary` and `merged_content`. Produces a new revision row ($R_{n+1}$) with the synthesized content marked `ACTIVE`. Both original conflicting rows are marked `SUPERSEDED` and `RESOLVED`.
- All conflict resolutions are fully transactional and record `CONFLICT_RESOLVED` audit events.

---

### 7. Verification Evidence Matrix

All 9 integration tests in [`backend/tests/test_memory_api.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/tests/test_memory_api.py) passed:

| Test ID | Test Name | Target Behavior | Result |
|---|---|---|---|
| API-01 | `test_memory_creation_and_validation` | Creation returns 201, auto-generates CREATED audit log, rejects whitespace-only summaries (422) and non-existent projects (404). | **PASS** (0.13s) |
| API-02 | `test_memory_listing_filtering_and_pagination` | Validates pagination envelope, category filtering, search queries, default exclusion of historical records, and 400 on invalid date ranges. | **PASS** (0.12s) |
| API-03 | `test_memory_get_and_cross_project_isolation` | Verifies cross-project memory access attempts return HTTP 404 without data leakage. | **PASS** (0.11s) |
| API-04 | `test_memory_update_optimistic_concurrency_and_immutability` | Verifies revision increment ($R_1 \rightarrow R_2$), verification invalidation, predecessor supersession, and 409 Conflict on stale revision. | **PASS** (0.13s) |
| API-05 | `test_memory_archive_and_restore_lifecycle` | Verifies soft-archive transitions status to ARCHIVED, restore returns to ACTIVE, audit events recorded. | **PASS** (0.11s) |
| API-06 | `test_memory_explicit_verification_endpoint` | Verifies POST /verify marks memory verified, records `verified_by`, and upgrades AGENT_CONCLUSION to VERIFIED_FINDING. | **PASS** (0.12s) |
| API-07 | `test_conflict_detection_and_resolution_api` | Verifies GET /conflicts, resolution via 'supersede' (target active, partner superseded), and conflict status updates. | **PASS** (0.13s) |
| API-08 | `test_memory_audit_history_read_only_endpoint` | Verifies GET /audit returns ordered event logs, pagination works, and mutation attempts (POST/DELETE) return 405. | **PASS** (0.11s) |
| API-09 | `test_artifact_lineage_api_exploration` | Verifies lineage API returns ancestors, parent, descendants, and supersession links; enforces cross-project 404 rejection. | **PASS** (0.12s) |

---

### 8. Regression & Quality Assurance Summary

- **Backend Pytest Suite:** **80 / 80 passed** (100% clean, 14.83s).
- **Code Hygiene (Ruff):** 100% clean (`ruff check backend/` — 0 errors; `ruff format --check backend/` — 85 files formatted).
- **Frontend Vitest Suite:** **8 / 8 test suites passed** (10 tests, 1.16s).
- **Frontend Linter (Oxlint):** 0 warnings, 0 errors across 29 files.
- **Frontend Build (Vite):** Clean production bundle generated in 172ms.
- **OpenAPI Schema Check:** Verified 46 distinct endpoints in `/docs` and `/openapi.json`.

---

### 9. Independent Review Findings & Fixes

1. **Whitespace Validation on Summary and Content:**
   - *Finding:* Pydantic's default `min_length=1` accepts `"   "` (whitespace-only strings), deferring rejection to `MemoryService` and returning HTTP 400 instead of HTTP 422.
   - *Fix:* Added `@field_validator` on `summary` and `content` in `MemoryCreateRequest` and `MemoryUpdateRequest` to strip whitespace, ensuring uniform 422 responses on invalid input.
2. **Revision Conflict Exception Translation:**
   - *Finding:* `MemoryService.update_memory` formats its revision mismatch as `"Revision conflict: expected X, current is Y."`. Initial router logic looked for `"Expected revision"`, causing a fallback to HTTP 400.
   - *Fix:* Broadened exception inspection to check for `"revision conflict"`, ensuring HTTP 409 Conflict is reliably returned.
3. **ArtifactType Enum Fidelity:**
   - *Finding:* Integration tests referenced `ArtifactType.DOCUMENT`, which does not exist on the schema (available: `PRD`, `RESEARCH`, `ARCHITECTURE`, etc.).
   - *Fix:* Updated tests to use `ArtifactType.ARCHITECTURE`.

---

### 10. Transition to Milestone M1.3-7

Milestone M1.3-6 is complete, verified, and ready for:
- **Milestone M1.3-7 (Frontend Project Intelligence Experience):**
  - Implement interactive Memory Bank page under `/intelligence`.
  - Visual provenance badges (`User Provided`, `Verified Finding`, `Agent Conclusion`, `Assumption`).
  - Revision history inspector and conflict resolution workbench.
  - Interactive artifact lineage graph visualization.
