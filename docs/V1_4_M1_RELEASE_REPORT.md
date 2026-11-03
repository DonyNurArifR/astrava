# ASTRAVA V1.4 — Milestone M1.4-1 Release Report
## Security & Concurrency Hardening

**Release Date:** 2026-11-03  
**Milestone:** M1.4-1  
**Status:** VERIFIED & COMPLETE  
**Git Author:** `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`  
**Base Commit:** `08355ab5b18c92aa62c06dd7160f784ace964f93` (V1.3 Frozen Baseline)  
**AI Executor:** Canonical Claude Haiku 5.5 (`claude-haiku-5-5`) via non-interactive Claude Code CLI  
**Lead Architect & Reviewer:** Gemini  

---

### 1. Executive Summary

Milestone M1.4-1 delivers **Security & Concurrency Hardening**, formally resolving two primary operational risks identified during V1.3:
1. **TR-01 / R1 (Spoofed Verifier Identity):** Eliminates unauthenticated, client-supplied verifier attestation. Implements a trusted operator authentication context, validates verifier authorization, rejects impersonation attempts with HTTP 403 Forbidden, and records authentic actor identity and type into immutable audit logs.
2. **TR-02 / R2 (Concurrent Knowledge Ingestion Races & Transaction Corruption):** Resolves race conditions and partial rollback transaction failures in multi-worker pipeline runs. Implements deterministic SHA-256 candidate fingerprinting, a PostgreSQL partial unique index on active/proposed memories, an `IngestionOperation` lifecycle tracking model with concurrent winner/loser backoff polling, and SQLAlchemy nested savepoints preventing session corruption.

---

### 2. Core Architectural Deliverables

#### 2.1 Trusted Operator Identity & Authentication (`backend/app/core/auth.py`)
- **`OperatorContext`:** Typed dataclass encapsulating the authenticated actor: `operator_id`, `display_name`, `actor_type` (`"user"`, `"agent"`, or `"system"`), `is_authenticated`, and `roles`.
- **`get_operator_context`:** FastAPI dependency resolving actor identity per request:
  - *Local Single-User Mode:* When `OPERATOR_API_KEY` is not set (default), authenticates as the local operator (`settings.DEFAULT_OPERATOR_NAME = "Abstract"`), with optional override via header `X-ASTRAVA-ACTOR-NAME`.
  - *Secured Mode:* When `OPERATOR_API_KEY` is configured in environment/settings, enforces mandatory API key validation (`X-ASTRAVA-API-KEY` or `Authorization: Bearer <key>`), rejecting missing or invalid keys with HTTP 401 Unauthorized.
- **`require_authorized_verifier`:** Enforces verifier authorization for `POST /api/v1/projects/{project_id}/memories/{memory_id}/verify`:
  - Rejects any client attempt to supply a `verified_by` that differs from the authenticated operator's display name with HTTP 403 Forbidden.
  - Automatically derives `verified_by` from `operator.display_name` if omitted in the request.
  - Passes authentic operator ID (`operator.operator_id`) and actor type (`operator.actor_type`) to `MemoryService.verify_memory` for immutable audit log recording.

#### 2.2 Relational Ingestion Tracking & Fingerprint Indexing (`backend/app/models/memory.py`)
- **`IngestionOperation` Model:**
  - Tracks pipeline knowledge ingestion lifecycles with unique constraint `uq_ingestion_operations_project_token` on `(project_id, operation_token)`.
  - State machine: `PENDING` -> `IN_PROGRESS` -> `COMPLETED` / `FAILED`.
  - Stores `ingested_count`, `duplicate_count`, `error_message`, `started_at`, and `completed_at`.
- **Candidate Fingerprinting:**
  - `compute_candidate_fingerprint(project_id, category, summary, source_task_id)`: Deterministic SHA-256 hash.
  - Stored in `ProjectMemory.fingerprint` (String 64).
  - Linked to operation via foreign key `ProjectMemory.ingestion_operation_id`.
- **PostgreSQL Partial Unique Index:**
  - `uq_project_memories_fingerprint` on `(project_id, fingerprint)` where `fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED')`.
  - Database-level guarantee against duplicate memory records under any concurrency scenario.
- **Alembic Migration:**
  - Migration `7a8e1b2c3d4e_add_ingestion_operations_and_memory_fingerprint.py`. Verified clean upgrade, downgrade, and re-upgrade against live PostgreSQL 16 container.

#### 2.3 Resilient Orchestration Ingestion Node (`backend/app/orchestrator/workflow_graph.py`)
- Stable `operation_token` generation per execution attempt.
- Idempotent short-circuit if `operation.status == COMPLETED`.
- Multi-worker race handling: losing workers encountering an `IntegrityError` on the operation token poll the winner with backoff using fresh database sessions (`AsyncSessionLocal()`) and return the completed result without duplicate work or error.
- Per-candidate isolation: individual candidate creation is wrapped in `async with session.begin_nested():`. Duplicate collisions or validation errors roll back only the candidate savepoint, leaving preceding valid candidates intact.

#### 2.4 Frontend API Client Alignment (`frontend/src/api/client.ts`)
- Updated `verifyMemory` to pass header `X-ASTRAVA-ACTOR-NAME: data.verified_by` so explicit UI verifier entries match the authenticated operator context cleanly.

---

### 3. Verification & Testing Matrix

#### 3.1 Security Test Suite (`backend/tests/test_v1_4_security.py`)
- **19/19 tests passed (1.95s)**
- Tested:
  - Default local operator resolution (`Abstract`, `user`, authenticated).
  - Custom display name override via `X-ASTRAVA-ACTOR-NAME`.
  - API key enforcement in secured mode (valid key succeeds, missing/invalid key rejected with 401).
  - Impersonation prevention (mismatched `verified_by` rejected with 403 Forbidden).
  - Omitted `verified_by` cleanly derived from operator display name.
  - Matching explicit `verified_by` succeeds.
  - Authentic `actor_id` and `actor_type` recorded in `MemoryAuditLog`.
  - Cross-project verification rejected with 404.
  - Status promotion from `PROPOSED` to `ACTIVE` upon authorized verification.

#### 3.2 Concurrency & Idempotency Test Suite (`backend/tests/test_v1_4_concurrency_idempotency.py`)
- **11/11 tests passed (1.34s)**
- Tested:
  - Database-level partial unique index prevents duplicate active/proposed fingerprints.
  - Soft-archived / superseded memories with identical fingerprints can be replaced by new active memories.
  - Deterministic fingerprint computation across identical inputs and distinct fingerprints across different categories/tasks.
  - Single execution ingestion creates exactly 1 `IngestionOperation` row and links memories.
  - Repeated identical ingestion call is idempotent and creates 0 duplicate memories.
  - 10 simultaneous concurrent workers ingesting the same candidate batch create exactly 1 set of records and 0 duplicates.
  - Concurrent workers racing on separate operations with overlapping fingerprints resolve cleanly with 0 duplicates.
  - Retry after a failed operation succeeds without orphaned state.
  - Partial candidate failure in batch does not abort valid candidates (savepoint isolation).
  - Ingestion operation records accurate failure details and status.
  - Completed operation is never clobbered by retry attempts.

#### 3.3 Full Test Suite Regression
- **Backend (Pytest):** **118/118 tests passed** in 17.65s (all 15 test files passing).
- **Frontend (Vitest):** **16/16 tests passed** in 1.20s (all 9 test files passing).
- **Code Hygiene (Ruff):** `ruff check` and `ruff format` 100% clean across all 90 backend files.
- **Frontend Lint & Build:** `npm run lint` 0 errors, `npm run build` completed cleanly in 207ms.

---

### 4. Database Migration & Schema State

- **Current Alembic Head:** `7a8e1b2c3d4e` (`add_ingestion_operations_and_memory_fingerprint`).
- **PostgreSQL Version:** PostgreSQL 16 (container `astrava-postgres` on port 5433).
- **Schema Additions:**
  - Table: `ingestion_operations` (`id`, `project_id`, `execution_id`, `operation_token`, `status`, `ingested_count`, `duplicate_count`, `error_message`, `started_at`, `completed_at`, `created_at`, `updated_at`).
  - Constraint: `uq_ingestion_operations_project_token` on `(project_id, operation_token)`.
  - Column: `project_memories.fingerprint` (String 64, nullable).
  - Column: `project_memories.ingestion_operation_id` (UUID, foreign key to `ingestion_operations.id` with `SET NULL` on delete).
  - Index: `uq_project_memories_fingerprint` partial unique index on `(project_id, fingerprint)` where `fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED')`.

---

### 5. Risk Resolution Status

| Risk ID | Title | Previous Status | New Status |
|---|---|---|---|
| **TR-01** | Spoofed Verifier Identity & Audit Corruption | HIGH Risk (Unmitigated) | **RESOLVED** |
| **TR-02** | Concurrent Ingestion Race & Partial Rollback Corruption | HIGH Risk (Unmitigated) | **RESOLVED** |

---

### 6. Git Delivery Status

- **Branch:** `main`
- **Working Tree:** Clean (all files committed and pushed).
- **Stop Condition Enforced:** Milestone M1.4-1 complete. Do NOT proceed to M1.4-2 without explicit authorization.
