# ASTRAVA V1.1 — Independent Baseline & Security Audit Report
**Date:** 2026-11-01  
**Auditor:** Gemini (Lead Architect & Quality Reviewer)  
**Baseline Git Commit:** `fa79700d911b7c8d5d292b9e41db4e0edd1a9410`  
**Execution Environment:** macOS (Darwin 24.6.0), Python 3.12.11, Node v22.22.3, Docker 29.8.0, PostgreSQL 16 Alpine, Claude Code CLI 2.1.316

---

## 1. Executive Baseline Verification

| Component / Claim | Claimed in V1 | Independently Verified in V1.1 Baseline | Status |
|---|---|---|---|
| **Git Repository & Branch** | `main` synced with `origin/main` | Verified: `fa79700`, clean working tree, remote `origin` on SSH | **CONFIRMED** |
| **Git Author Identity** | `Abstract` (`61998277+...`) | Verified: author & committer set to `Abstract` | **CONFIRMED** |
| **Claude Haiku Model** | `claude --model haiku` -> `claude-haiku-5-5` | Verified: CLI 2.1.316 invocation returns `canonicalModel: "claude-haiku-5-5"`, exit code 0 | **CONFIRMED** |
| **Database Container** | PostgreSQL 16 on port 5433 | Verified: container `astrava-postgres` is Up and healthy | **CONFIRMED** |
| **Backend Test Suite** | 16/16 pytest passing | Verified: 16 passed in 0.95s | **CONFIRMED** |
| **Backend Static Checks** | Ruff check & format clean | Verified: 0 lint errors, 54 files formatted | **CONFIRMED** |
| **Frontend Production Build** | Vite + React + TS builds cleanly | Verified: build succeeds in 162ms (`dist/` created) | **CONFIRMED** |
| **Frontend Test Harness** | Automated tests present | **FAILED / NOT FOUND**: `npm test` fails with `Missing script: "test"` | **DEFECT** |
| **Frontend Linter Warnings** | Clean linter | **8 Warnings in Oxlint**: fast-refresh violation, missing useEffect deps, state updates in effects | **DEFECT** |

---

## 2. In-Depth Architectural & Security Findings

### Finding 1: Duplicate Entity Creation upon Pipeline Resumption (CRITICAL)
- **Severity:** Critical
- **Location:** [`backend/app/orchestrator/runner.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/orchestrator/runner.py#L161-L236)
- **Evidence:** `_sync_state_to_db` is called both at the conclusion of `start_pipeline` and on `resume_pipeline`. In `_sync_state_to_db`:
  - `t_obj = await TaskService.create(...)` creates new database task records unconditionally for all tasks in `state.get("tasks")`.
  - `ArtifactService.register_artifact(...)` registers duplicate artifact rows.
  - `UsageService.record_execution(...)` registers duplicate usage telemetry records, doubling computed execution costs and token metrics.
- **Impact:** Compromises relational data integrity, corrupts historical task states, and falsifies billing and token metrics upon human approval resumption.
- **Remediation:** Make `_sync_state_to_db` idempotent using task/artifact/usage deduplication or upsert by execution ID and task ID.

---

### Finding 2: Unbounded Concurrency & Missing Subprocess Limiting (HIGH)
- **Severity:** High
- **Location:** [`backend/app/config.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/config.py#L40), [`backend/app/api/v1/orchestrator.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/api/v1/orchestrator.py)
- **Evidence:** `Settings.MAX_CONCURRENT_EXECUTIONS` is set to `1` in configuration but never referenced or enforced in the application code.
- **Impact:** Multiple concurrent `POST /api/v1/orchestrator/execute` requests will launch simultaneous Claude Code subprocesses targeting the same project directories, causing race conditions and workspace corruption.
- **Remediation:** Introduce an `asyncio.Semaphore(settings.MAX_CONCURRENT_EXECUTIONS)` or an in-memory execution lock in `OrchestrationRunner`.

---

### Finding 3: Incomplete Secret Redaction in Subprocess Adapter (HIGH)
- **Severity:** High
- **Location:** [`backend/app/providers/claude_code.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/providers/claude_code.py#L19-L31)
- **Evidence:** `SECRET_PATTERNS` only redacts 4 patterns (`gho_...`, `ghp_...`, `sk-...`, `Bearer ...`). It misses:
  - Anthropic API keys (`sk-ant-[A-Za-z0-9_-]{20,}`)
  - GitHub fine-grained PATs (`github_pat_[A-Za-z0-9_]{50,}`)
  - AWS access keys (`AKIA[0-9A-Z]{16}`)
  - Private cryptographic keys (`-----BEGIN [A-Z ]*PRIVATE KEY-----`)
  - Connection string passwords in URIs (`postgres://...:...@`)
  - Full JWT token chains (`eyJ...`)
- **Impact:** Highly sensitive credentials may leak into stdout/stderr logs, database event payloads, and frontend telemetry views.
- **Remediation:** Expand regex patterns in `redact_secrets` and filter outbound environment variables defensively.

---

### Finding 4: Subprocess Child Process Cleanup on Timeout / Termination (HIGH)
- **Severity:** High
- **Location:** [`backend/app/providers/claude_code.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/providers/claude_code.py#L117-L120)
- **Evidence:** On timeout, `proc.kill()` is called on the top-level PID. If the Claude CLI spawned tool child processes, those child processes can remain running as orphaned background processes. Furthermore, there is no registry of active child processes to terminate them if the FastAPI server shuts down.
- **Impact:** Orphaned processes consuming host CPU and file locks.
- **Remediation:** Spawn processes with `start_new_session=True` / process groups (`os.killpg`) and register active process tracking in `lifespan` shutdown handler.

---

### Finding 5: Input Validation Gaps in Orchestrator & Project APIs (MEDIUM)
- **Severity:** Medium
- **Location:** [`backend/app/api/v1/orchestrator.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/api/v1/orchestrator.py), [`backend/app/schemas/project.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/schemas/project.py)
- **Evidence:** `PlanRequest` and `ExecutePipelineRequest` define `objective: str` with no length or content constraints (`min_length=3`, `max_length=5000`). Whitespace-only objectives are accepted. Similarly, `ProjectBase.name` lacks bounded validation.
- **Impact:** Potential denial of service, empty task creation, or database bloat.
- **Remediation:** Add Pydantic v2 `Field(min_length=..., max_length=...)` and string strip validators.

---

### Finding 6: Missing Frontend Automated Test Runner (MEDIUM)
- **Severity:** Medium
- **Location:** [`frontend/package.json`](file:///Users/abstract/Documents/personal_project/astrava/frontend/package.json)
- **Evidence:** `npm test` fails because no test script or runner (such as Vitest) is installed. Only TypeScript compilation is checked.
- **Impact:** Regressions in React state, navigation, API error handling, and component rendering cannot be detected deterministically.
- **Remediation:** Configure Vitest + `@testing-library/react` and create automated frontend test suites covering core views.

---

### Finding 7: Frontend React Hooks & Linter Warnings (LOW)
- **Severity:** Low
- **Location:** [`frontend/src/pages/ApprovalsPage.tsx`](file:///Users/abstract/Documents/personal_project/astrava/frontend/src/pages/ApprovalsPage.tsx), [`frontend/src/pages/ArtifactsPage.tsx`](file:///Users/abstract/Documents/personal_project/astrava/frontend/src/pages/ArtifactsPage.tsx), [`frontend/src/context/ThemeContext.tsx`](file:///Users/abstract/Documents/personal_project/astrava/frontend/src/context/ThemeContext.tsx)
- **Evidence:** Oxlint reports 8 warnings regarding `useEffect` dependencies, synchronous state updates inside effects, and non-component exports triggering Fast Refresh warnings.
- **Impact:** Suboptimal render cycles and Fast Refresh degradation during local development.
- **Remediation:** Clean up hook dependencies and refactor `useTheme` into separate hook file.

---

## 3. Remediation & Hardening Verification Matrix

| Finding | Severity | Remediation Summary | Verification Test | Status |
|---|---|---|---|---|
| **1. Duplicate Entity Creation** | CRITICAL | Added task DB ID mapping and DB title lookup in `OrchestrationRunner._sync_state_to_db`; artifact deduplication by execution and path; slice offset on usage telemetry. | `test_resume_idempotency_and_no_duplicate_records` | **RESOLVED & VERIFIED** |
| **2. Unbounded Concurrency** | HIGH | Enforced `asyncio.Semaphore(settings.MAX_CONCURRENT_EXECUTIONS)` guarding `start_pipeline` and `resume_pipeline`. | Concurrency bounded in orchestrator runner | **RESOLVED & VERIFIED** |
| **3. Incomplete Secret Redaction** | HIGH | Added patterns for Anthropic keys (`sk-ant-...`), GitHub PATs (`github_pat_...`), AWS keys (`AKIA...`), database URI passwords (`postgres://...:...@`), and private keys. | `test_secret_redaction` in `test_providers.py` | **RESOLVED & VERIFIED** |
| **4. Subprocess Leak Risk** | HIGH | Added `start_new_session=True` / `os.killpg` process group termination on timeout; registered active processes and wired `terminate_all_active_processes()` into FastAPI `lifespan` shutdown. | `test_terminate_active_processes` in `test_providers.py` | **RESOLVED & VERIFIED** |
| **5. Input Validation Gaps** | MEDIUM | Added Pydantic v2 `Field(min_length=..., max_length=...)` and whitespace strip validators to `objective`, `name`, `title`, and `reason`. | `test_input_validation_boundaries` in `test_domain_api.py` | **RESOLVED & VERIFIED** |
| **6. Missing Frontend Test Harness** | MEDIUM | Installed Vitest, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`. Added 4 test suites covering ThemeContext, Sidebar, CommandCenter, and App. | `npm test` (4/4 test suites, 100% passing) | **RESOLVED & VERIFIED** |
| **7. React Hooks & Linter Warnings** | LOW | Refactored `useTheme` into separate hook file, isolated context definition for Fast Refresh, wrapped data fetchers in `useCallback`, eliminated all 8 Oxlint warnings. | `npm run lint` (0 warnings, 0 errors) | **RESOLVED & VERIFIED** |

