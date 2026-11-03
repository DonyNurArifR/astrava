# ASTRAVA Development Execution Log

## [2026-11-01] M0: Environment & Repository Inspection
- **Task ID:** M0-T1 to M0-T6
- **Milestone:** M0
- **Executor:** Antigravity / Gemini Planner
- **Model:** Gemini 3.8 Flash
- **Actions Taken:**
  1. Inspected git status: empty repository. Set default branch to `main`. Configured remote `origin` to `https://github.com/DonyNurArifR/astrava.git`.
  2. Configured local Git identity:
     - `user.name`: "Abstract"
     - `user.email`: "61998277+DonyNurArifR@users.noreply.github.com"
  3. Verified GitHub authentication via `gh auth status` and `gh api user` (login: DonyNurArifR, name: Abstract, id: 61998277).
  4. Inspected development tools:
     - `uv` 0.12.x / python 3.12 verified.
     - `node` v22.22.3 verified.
     - `docker` 29.8.0 verified.
     - `agy` 1.4.12 verified.
     - `claude` 2.1.314 verified.
  5. Tested Claude Code CLI with Haiku model:
     - Command: `claude --model haiku -p --output-format json "echo 'test'"`
     - Exit code: 0
     - Response resolved to canonical model: `claude-haiku-5-5`.
     - Output captured with usage metrics (tokens, duration, cost).
  6. Created initial documentation structure under `docs/`:
     - `ROADMAP.md`
     - `ARCHITECTURE.md`
     - `DECISIONS.md`
     - `PROGRESS.md`
     - `EXECUTION_LOG.md`
- **Status:** COMPLETE
- **Next Task:** M1-T1 (.gitignore setup) and M1-T2 (Backend skeleton with uv).

## [2026-11-01] M1: Project Foundation Complete
- **Task ID:** M1-T1 to M1-T6
- **Milestone:** M1
- **Executor:** Antigravity / Gemini Planner
- **Model:** Gemini 3.8 Flash
- **Actions Taken:**
  1. Created `.gitignore` excluding secrets, credentials, environment files, local caches, `.venv`, `node_modules`, and local artifacts.
  2. Initialized backend workspace with Python 3.12 via `uv`. Installed FastAPI, uvicorn, Pydantic v2, pydantic-settings, SQLAlchemy 2.0, Alembic, asyncpg, psycopg2-binary, LangGraph, LangChain-core, pytest, and ruff.
  3. Scaffolding frontend with Vite, React, TypeScript, Tailwind CSS v4, Lucide icons, TanStack Query, and React Router. Verified clean production build with `npm run build`.
  4. Configured `docker-compose.yml` for PostgreSQL 16 Alpine with persistent volume and health check.
  5. Implemented backend configuration (`Settings`), structured logging (`StructuredFormatter`), and health check endpoints (`/healthz`, `/readyz`).
  6. Verified backend linting (`ruff check`) and tests (`pytest` 3/3 passed).
- **Status:** VERIFIED
- **Next Task:** M1-T7: Git commit initial verified foundation and push to origin `main`.

## [2026-11-01] M2: Domain Models, Alembic Migrations & REST API Complete
- **Task ID:** M2-T1 to M2-T4
- **Milestone:** M2
- **Executor:** Antigravity / Gemini Planner
- **Model:** Gemini 3.8 Flash
- **Actions Taken:**
  1. Started PostgreSQL 16 Alpine container on port 5433 via Docker Compose (avoiding conflicts with existing host services).
  2. Implemented SQLAlchemy 2.0 async domain models: `Workspace`, `Project`, `Task`, `Workflow`, `WorkflowExecution`, `ExecutionEvent`, `Approval`, `Artifact`, `ModelExecution`.
  3. Configured Alembic with `env.py`, generated initial migration `a229466e8dae_initial_astrava_domain_schema.py`, and applied it cleanly.
  4. Implemented Pydantic v2 schemas and asynchronous Service layer for each domain with validation and path sandboxing.
  5. Built API endpoints under `/api/v1/` for projects, tasks, workflows, executions, approvals, artifacts, and intelligence.
  6. Verified through automated tests (`tests/test_domain_api.py`) and Ruff linting (all checks passed, 6/6 tests passing).
- **Status:** VERIFIED
- **Next Task:** M3: Provider Integrations (Claude Code CLI Haiku 5.5 Adapter).

## [2026-11-01] M3: Provider Integrations Complete
- **Task ID:** M3-T1 to M3-T4
- **Milestone:** M3
- **Executor:** Antigravity / Gemini Planner
- **Model:** Gemini 3.8 Flash
- **Actions Taken:**
  1. Defined `BaseProvider`, `ProviderRequest`, and `ProviderResponse` with structured Pydantic v2 schemas.
  2. Implemented `ClaudeCodeCLIProvider` utilizing `claude --model haiku -p --output-format json` with:
     - Subprocess argument array execution (`asyncio.create_subprocess_exec`, `shell=False`).
     - Secret redaction for API keys and GitHub tokens (`gho_`, `sk-`, `Bearer`).
     - Path resolution, directory creation, clean environment variable isolation.
     - Timeout handling with safe process termination (`proc.kill()`, `proc.wait()`).
     - JSON output parsing for tokens (input, output, cache read/creation), session ID, duration, and cost calculation.
  3. Created `ProviderFactory` singleton pattern.
  4. Tested with unit tests (`tests/test_providers.py`) and live non-destructive invocation.
  5. Live execution verified: Exit code 0, canonical model `claude-haiku-5-5`, tokens: 4 in / 288 out, duration: 6763ms, cost: $0.00366.
- **Status:** VERIFIED
- **Next Task:** M4: Orchestration Engine (Structured Planning, LangGraph Workflow, Checkpointing).

## [2026-11-01] M4, M5, M6: Orchestration Engine, Approvals, Verification & Artifacts Complete
- **Task ID:** M4-T1 to M6-T1
- **Milestone:** M4, M5, M6
- **Executor:** Antigravity / Gemini Planner
- **Model:** Gemini 3.8 Flash
- **Actions Taken:**
  1. Implemented structured planner (`PlannerService`) with strict Pydantic v2 validation (`StructuredPlan`, `PlannedTask`) tailored for SaaS Studio and Media Studio production pipelines.
  2. Implemented LangGraph state graph (`build_orchestrator_graph`) with typed state `OrchestrationState`, connecting `plan`, `approval_check`, `dispatch_task`, `verify`, `artifact`, and `complete` nodes with conditional routing.
  3. Integrated deterministic verification engine (`VerificationEngine`) capturing syntax checks, test execution, and workspace Git diffs.
  4. Implemented human-in-the-loop approval interrupt and resumption mechanism in `OrchestrationRunner`.
  5. Implemented artifact storage management with strict path traversal validation (`ArtifactService.sanitize_path`) and file preview/download endpoints.
  6. Verified through automated test suite (`tests/test_orchestrator.py`), confirming that tasks requiring approval properly transition execution state to `waiting_approval` and resume seamlessly to `completed` upon human approval.
  7. All 14 tests passing, zero lint errors.
- **Status:** VERIFIED
- **Next Task:** M7: ASTRAVA Enterprise Dashboard & M8: SaaS & Media Studios frontend views.

## [2026-11-01] M7, M8, M9, M10: Dashboard, Studios, End-to-End Proof & Delivery Complete
- **Task ID:** M7-T1 to M10-T1
- **Milestone:** M7, M8, M9, M10
- **Executor:** Antigravity / Gemini Planner
- **Model:** Gemini 3.8 Flash
- **Actions Taken:**
  1. Built the complete ASTRAVA Enterprise Dashboard using React 19, TypeScript, Tailwind CSS v4, Lucide icons, and TanStack Query.
  2. Crafted custom geometric SVG letter A monogram logo and dual light/dark theme system adhering to brand palette (Midnight Navy, Slate Blue, Electric Blue, Cloud White).
  3. Created 8 full functional pages connecting to live backend endpoints:
     - Overview (real-time platform statistics, project counts, token usage, pending approvals banner).
     - Command Center (interactive pipeline launcher, objective input, SaaS vs Media studio selection, structured plan preview, and real-time execution event streamer).
     - Projects (project CRUD, studio filtering, target objectives list, deletion).
     - Executions (pipeline run monitor, step transitions, interactive pause & resume controls, event timeline drawer).
     - Artifacts (sandboxed file directory browser, search, type filters, preview modal with copy, direct download).
     - Approvals (human-in-the-loop governance interface with risk indicators, decision reasoning input, authorize/reject actions, and audit history).
     - Intelligence (telemetry metrics, token consumption, compute duration, cost calculations, model execution logs).
     - Settings (CLI provider adapter verification, database state, sandboxed storage directory, and governance policies).
  4. Executed comprehensive end-to-end integration and resilience test suite (`tests/test_e2e_resilience.py`), verifying full lifecycle execution, path traversal security protection, operator rejection handling, and state checkpoint preservation.
  5. Verified 16/16 backend tests passing, 0 Ruff lint errors, and frontend production build compiling cleanly in 92ms.
  6. Generated complete technical documentation: `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `PROGRESS.md`, `EXECUTION_LOG.md`, `API.md`, and `PROVIDERS.md`.
- **Status:** COMPLETE & DELIVERED
- **Final Result:** ASTRAVA V1 is fully functional, tested, locally deployable, and ready.

---

## 2026-11-01: ASTRAVA V1.1 — Independent Audit, Reliability & Security Hardening

### Phase 0: Independent Baseline Verification
- Verified Git remote (`git@github.com:DonyNurArifR/astrava.git`), branch `main`, author identity (`Abstract <61998277+DonyNurArifR@users.noreply.github.com>`).
- Verified Claude CLI (`2.1.316`) invocation resolves to canonical model `claude-haiku-5-5`.
- Verified PostgreSQL 16 Alpine container active on port `5433`.
- Discovered 7 prioritized findings documented in `docs/V1_1_AUDIT.md`:
  - F-01 (Critical): Duplicate task, artifact, and telemetry creation upon pipeline resumption.
  - F-02 (High): Unbounded subprocess concurrency.
  - F-03 (High): Incomplete secret redaction patterns.
  - F-04 (High): Subprocess leak risk and orphaned child process tree on timeout/exit.
  - F-05 (Medium): Missing input boundaries on API objectives and project models.
  - F-06 (Medium): Missing automated frontend test runner.
  - F-07 (Low): 8 Oxlint hook and Fast Refresh warnings.

### Phase 1: Implementation of Hardening Measures
1. **Relational Data Integrity (F-01):**
   - Added task DB ID tracking in `OrchestrationState` and project-level title matching in `_sync_state_to_db`.
   - Enhanced `ArtifactService.register_artifact` with duplicate prevention by execution ID and relative path.
   - Sliced telemetry synchronization with `synced_usage_count` offset.
2. **Concurrency Semaphore (F-02):**
   - Enforced `asyncio.Semaphore(settings.MAX_CONCURRENT_EXECUTIONS)` across `start_pipeline` and `resume_pipeline`.
3. **Secret Redaction & Subprocess Safety (F-03, F-04):**
   - Added regex coverage for Anthropic API keys (`sk-ant-...`), GitHub PATs (`github_pat_...`), AWS keys (`AKIA...`), database connection passwords (`postgres://...:...@`), and private keys.
   - Configured `start_new_session=True` on subprocess launch; added `os.killpg` on timeout.
   - Created `terminate_all_active_processes()` and integrated into FastAPI `lifespan` shutdown handler.
   - Extracted `canonicalModel` from CLI JSON `modelUsage` and propagated to `ProviderResponse`.
4. **Pydantic v2 Input Boundaries (F-05):**
   - Added bounded string length validators and whitespace stripping on `PlanRequest`, `ExecutePipelineRequest`, `ProjectCreate`, `ProjectUpdate`, `TaskCreate`, `TaskUpdate`, and `ApprovalDecisionRequest`.
5. **Frontend Testing & Linter Hygiene (F-06, F-07):**
   - Installed Vitest, `@testing-library/react`, `@testing-library/jest-dom`, and `jsdom`.
   - Created 4 test suites: `ThemeContext.test.tsx`, `Sidebar.test.tsx`, `CommandCenter.test.tsx`, `App.test.tsx`.
   - Refactored `useTheme` into separate file, isolated context definition for Fast Refresh, wrapped data fetchers in `useCallback`.
   - Achieved 0 Oxlint warnings across 24 frontend files.

### Phase 2: Acceptance & Regression Verification
- **Backend Tests:** 20/20 passed in 1.42s.
- **Backend Linting:** Ruff clean, 54 files formatted.
- **Frontend Tests:** 4/4 passed in 542ms.
- **Frontend Build:** `tsc -b && vite build` completed in 94ms.
- **Live Haiku CLI:** Successfully invoked and verified `canonicalModel: claude-haiku-5-5`.
- **Database Durability:** `test_pipeline_state_recovery_across_engine_restart` verified checkpoint survival across engine connection pool disposal.
- **Final Result:** ASTRAVA V1.1 is fully audited, hardened, verified, and ready for release.

---

## 2026-11-01: ASTRAVA V1.1.1 — Post-Release Acceptance Verification

### Controlled Crash Recovery Verification
- Executed `scratch/test_real_crash_recovery.py` spawning a dedicated Uvicorn backend process (PID 53879) on port 8009.
- Ran live Media Studio pipeline with real Claude Code CLI (`claude-haiku-5-5`) tasks 1 and 2 and deterministic verification.
- Execution reached checkpoint: `WAITING_APPROVAL` with 3 tasks recorded in PostgreSQL.
- Abruptly killed Process 1 with `kill -9` (`killpg 53879`).
- Confirmed process termination (`kill -0` confirmed dead).
- Spawned a brand-new Uvicorn process (PID 54535) on port 8009.
- Verified `/healthz` on the new process.
- Retrieved execution `8c4a8a70-...` on the new process: confirmed checkpoint state restored with `waiting_approval` status and preserved plan.
- Resumed execution with approval on the new process.
- Process 2 loaded state, preserved plan, and dispatched Task 3 using live Claude Code CLI with `claude-haiku-5-5`.
- Workflow reached `COMPLETED`.
- Post-recovery DB check: exactly 3 tasks (pre-crash: 3, 0 duplicate tasks), 4 artifacts registered.
- Status: VERIFIED.

### Concurrency & Idempotency Hardening
- Added in-semaphore state re-check in `runner.py:resume_pipeline` to serialize concurrent resume requests and eliminate race conditions.
- Implemented `test_simultaneous_resumes_and_concurrency_resilience`: 3 simultaneous resume requests fired via `asyncio.gather` all succeeded with HTTP 200, execution completed with zero duplicate tasks, and semaphore capacity restored (`_value == 1`).
- Documented single-process concurrency limitation of `asyncio.Semaphore`.

### Provider Failure Routing & Persistence
- Added conditional edge `route_after_dispatch` in `workflow_graph.py` to route failed/timed-out tasks immediately to `END`.
- Updated `runner._sync_state_to_db` to record failed tasks with `TaskStatus.FAILED` and transition `WorkflowExecution` to `ExecutionStatus.FAILED` with error details.
- Verified with `test_provider_failure_and_persistence`: execution and task transitioned to FAILED, error details persisted, backend remained healthy.

### Frontend Acceptance Suites
- Expanded Vitest suites from 4 to 7 test suites: added `ApprovalsPage.test.tsx`, `ArtifactsPage.test.tsx`, and `ExecutionsPage.test.tsx`.
- All 7 test suites passing in 800ms.
- Oxlint: 0 warnings, 0 errors across 27 files.
- Vite build: clean in 202ms.

### Final Assessment & Recommendation
- Comprehensive report generated in `docs/V1_1_1_ACCEPTANCE_REPORT.md`.
- Executive Assessment: **B. Release accepted with documented limitations.**
- Recommendation: **Freeze V1.1 / V1.1.1 as the verified stable baseline for the next product-development phase.**

---

## 2026-11-01: ASTRAVA V1.2 — Agent Intelligence & Workflow Engine

### Phase 1: Reusable Agent Domain Model & Registry
- Created SQLAlchemy model `Agent` (`backend/app/models/agent.py`) with fields: `slug`, `name`, `description`, `studio_type`, `capabilities`, `instructions`, `input_schema`, `output_schema`, `available_tools`, `model_config_data`, `execution_config`, `verification_requirements`, `version`, `is_enabled`.
- Added `tasks.assigned_agent_slug` foreign reference column.
- Generated and executed Alembic migration `6b136f812cca_add_agent_registry_and_task_agent_slug.py`.
- Defined default seed data in `AgentService.seed_default_agents`:
  - 7 SaaS Studio agents: `product-researcher`, `competitor-analyst`, `product-strategist`, `product-manager`, `solution-architect`, `developer`, `qa-engineer`.
  - 9 Media Studio agents: `content-researcher`, `audience-analyst`, `content-strategist`, `content-calendar-planner`, `scriptwriter`, `storyboard-designer`, `production-assistant`, `seo-analyst`, `content-quality-reviewer`.
- Implemented API router `backend/app/api/v1/agents.py` (`GET /agents`, `POST /agents/seed`, `GET /agents/{id}`, `POST /agents`, `PATCH /agents/{id}/status`, `PUT /agents/{id}`).

### Phase 2: Semantic Objective Understanding
- Created `IntelligenceService.understand_objective` (`backend/app/services/intelligence_service.py`):
  - Prompts configured Claude Haiku CLI for structured JSON analysis.
  - Extracts intended outcome, studio classification, required capabilities, expected deliverables, complexity, ambiguities, missing information, potential risks, and clarification questions.
  - Enforces deterministic Pydantic schema validation (`ObjectiveUnderstandingResponse`) with fallback for test and offline environments.
- Added API endpoint `POST /api/v1/orchestrator/understand`.

### Phase 3: Dynamic DAG Planning & Parallel Execution Stages
- Upgraded `PlannerService` (`backend/app/orchestrator/planner.py`):
  - Formulates multi-agent execution plans with assigned agents and explicit dependencies.
  - Cycle detection using Kahn's algorithm; raises `ValueError` on circular dependencies.
  - Computes parallel execution stages (`execution_stages`): groups independent tasks into concurrent waves.
  - SaaS pipeline features concurrent research & competitor analysis (Stage 1), strategic synthesis (Stage 2), PRD (Stage 3), architecture (Stage 4), modular code implementation (Stage 5), and deterministic QA (Stage 6).
  - Media pipeline features concurrent content & audience research (Stage 1), narrative strategy (Stage 2), scriptwriting (Stage 3), concurrent storyboard & SEO optimization (Stage 4), production manifest (Stage 5), and quality review with human approval gate (Stage 6).

### Phase 4: Dependency-Aware Multi-Agent Execution Engine
- Refactored `workflow_graph.py` and `runner.py`:
  - `approval_check_node`: identifies ready tasks whose dependencies are satisfied; pauses for human approval if any ready task requires it.
  - `dispatch_task_node`: executes ready tasks in parallel using `asyncio.gather` up to concurrency bounds.
  - Injects agent role, system instructions, and preceding task deliverables as context into downstream prompts.
  - `verify_node`: deterministic verification for completed task batches.
  - `artifact_node`: registers generated deliverables with producing agent slug.

### Phase 5: Frontend Agent Registry & DAG Visualization
- Implemented `AgentsPage.tsx` (`/agents`):
  - Agent cards with studio badges, capabilities tags, model config, and enable/disable toggle.
  - Inspector modal displaying system instructions, JSON output schemas, and verification criteria.
- Upgraded `CommandCenterPage.tsx`:
  - "Understand Objective" button triggers semantic interpretation card.
  - "Generate Multi-Agent Plan" triggers interactive DAG stage preview with assigned agent tags and dependency pills.
  - Real-time multi-agent execution progress monitoring.
- Updated `Sidebar.tsx` and `App.tsx` routing.

### Phase 6: Verification & Live Claude Haiku Proof
- **Backend Tests:** 27/27 tests passed in 2.45s (added `tests/test_agents.py`).
- **Backend Linting:** Ruff clean, 61 files formatted.
- **Frontend Tests:** 8/8 Vitest suites passed (10 tests) in 883ms (added `AgentsPage.test.tsx`).
- **Frontend Linting:** Oxlint 0 warnings, 0 errors across 29 files.
- **Frontend Build:** Vite production bundle built in 92ms.
- **Live Integration:** `scratch/test_v1_2_live_agent_run.py` executed live with Claude Haiku 5.5 CLI:
  - Objective: "Build an autonomous invoice validation and fraud audit system with webhook alerts".
  - Semantic understanding: High complexity, 15 capabilities, 4 deliverables, clarification requested.
  - DAG plan: 7 tasks across 6 stages with Stage 1 parallel execution.
  - Task 1 dispatched to `product-researcher`: 6,588 tokens generated in 41.1s via `claude-haiku-5-5`, cost $0.006196. Status: 100% SUCCESS.

---

## 2026-11-01: ASTRAVA V1.2.1 — Multi-Agent Reliability & Quality Assurance

### Phase 0: Baseline Audit & Vulnerability Discovery
- Performed rigorous static analysis and concurrency tracing across the V1.2 orchestrator, DAG planner, and agent subsystem.
- Identified and documented 7 prioritized findings in `docs/V1_2_1_AUDIT.md`:
  - AUD-01 (High): Duplicate task ID misdiagnosis in DAG validation.
  - AUD-02 (Critical): Concurrency wave partial failure unpersisted sibling completion.
  - AUD-03 (High): Missing bounded retry policy for transient provider timeouts.
  - AUD-04 (Medium): Blind context slicing and failure output contamination.
  - AUD-05 (High): QA Verification lacking dynamic test suite execution runner.
  - AUD-06 (Medium): Agent configuration mutable inflight during active workflows.
  - AUD-07 (Medium): Lack of granular execution state and concurrency wave visibility in UI.

### Phase 1: Architectural Hardening & Implementation
1. **DAG Validation Deduplication (AUD-01):**
   - Modified `backend/app/orchestrator/planner.py`: added explicit `seen_ids` duplicate validation before graph construction, raising `ValueError: Duplicate task identifier detected: '<id>'`.
2. **Partial Wave Isolation & Sibling Completion Persistence (AUD-02):**
   - Modified `backend/app/orchestrator/workflow_graph.py`: structured concurrent execution to capture outputs of all tasks in a wave; `verify_node` and `artifact_node` process and register all completed sibling tasks to disk and database before `route_after_artifact` terminates pipeline on failure.
3. **Autonomous Bounded Retries (AUD-03):**
   - Modified `_execute_single_task` with exponential backoff retry loop (`attempt 1/1`) and `retry_count` tracking.
4. **Context Traceability & Filtering (AUD-04):**
   - Structured prerequisite deliverables passing strictly from completed dependencies (`dep_id in completed_ids`), bounded to 3500 chars with truncation notices, and tagged with `used_context_sources`.
5. **Dynamic QA Deterministic Test Runner (AUD-05):**
   - Enhanced `VerificationEngine.verify_task` to discover and execute project test suites (`pytest`), validate JSON deliverable schemas, capture stdout/stderr, and return process exit codes.
6. **Immutable Agent Snapshots (AUD-06):**
   - Captured immutable `agent_snapshots` inside `initial_state` at execution start in `runner.py`, preventing inflight configuration drift.
7. **Real-Time Per-Wave Database Commits:**
   - Modified `OrchestrationRunner` to stream LangGraph execution via `graph.astream(...)` and commit completed tasks, artifacts, and state to PostgreSQL immediately upon completion of each wave.
8. **Frontend Execution Lifecycle Badges (AUD-07):**
   - Updated `CommandCenterPage.tsx` and `ExecutionsPage.tsx` with granular task badges (`Running (Parallel Wave)`, `Completed`, `Failed`, `Awaiting Approval`, `Blocked`) and context source chips.

### Phase 2: Verification, Controlled Crash Recovery & Live Proofs
- **Automated Backend Resilience Suite:** Added `tests/test_multi_agent_resilience.py` with 6 dedicated tests. Total test suite: 33/33 tests passing in 6.97s.
- **Frontend Verification:** Vitest 8/8 suites passing (10 tests) in 851ms, Oxlint 0 warnings / 0 errors across 29 files, Vite production bundle compiled in 172ms.
- **Controlled Real Process Crash Recovery (`scratch/test_real_parallel_recovery.py`):**
  - Process 1 (PID 79771) executed 7 tasks across 2 parallel waves until `WAITING_APPROVAL`.
  - Process 1 abruptly terminated with OS-level `killpg(SIGKILL)`. Confirmed dead: True.
  - Process 2 (PID 83554) booted on port 8011, restored checkpoint, approved resume, executed final quality review task, and finished with status `completed`.
  - Verified post-recovery task count in PostgreSQL: 8 pre-crash == 8 post-recovery (ZERO DUPLICATE TASKS).
  - Verified 8 persisted deliverables/artifacts.
- **Live Multi-Agent Proofs:** Real invocations using canonical `claude-haiku-5-5` via non-interactive Claude Code CLI across Media Studio (Scenario B) and SaaS Studio (Scenario A).
- **Release Documentation:** Authored `docs/V1_2_1_AUDIT.md` and `docs/V1_2_1_RELEASE_REPORT.md`.

---

## 2026-11-01: ASTRAVA V1.3 — Persistent Project Intelligence

### Phase 0: Baseline Verification & Architecture Assessment
- Verified Git baseline commit `f3aa9b95ec01d8882c57f04a4a7abf34180fb8d5`, branch `main`, author `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`.
- Verified non-interactive Claude Code CLI (`2.1.316`), canonical model `claude-haiku-5-5`, zero paid external API keys.
- Audited existing models, services, LangGraph workflow graph, and frontend pages.
- Authored comprehensive `docs/V1_3_ARCHITECTURE_ASSESSMENT.md` detailing:
  - 10-category Project Memory model (`objective`, `requirement`, `constraint`, `decision`, `discovery`, `preference`, `open_question`, `risk`, `milestone`, `rejected_approach`).
  - 4-tier provenance model (`user_provided`, `verified_finding`, `agent_conclusion`, `assumption`) with confidence scores.
  - Conflict detection engine preventing silent overwrites of architectural decisions.
  - Artifact intelligence graph (versioning, parent-child lineage, supersession).
  - Native PostgreSQL 16 Full-Text Search (`tsvector`/`tsquery`) with strict context budgeting (max 4,000 characters).
  - LangGraph pre-execution retrieval and post-execution memory ingestion nodes.
  - Interactive Project Intelligence frontend experience.
- Formulated 8 verifiable implementation milestones (M1.3-1 to M1.3-8).

### Milestone M1.3-2: Database Models & Alembic Migration
- **Model Implementations:**
  - `backend/app/models/memory.py`:
    - `ProjectMemory`: 10 memory categories (`MemoryCategory`), 4 provenance types (`MemoryProvenanceType`: `user_provided`, `verified_finding`, `agent_conclusion`, `assumption`), status (`MemoryStatus`: `proposed`, `active`, `superseded`, `rejected`, `archived`), conflict status (`MemoryConflictStatus`: `none`, `detected`, `resolved`).
    - Database check constraints: `ck_project_memories_confidence_range` (0.0 to 1.0), `ck_project_memories_revision_positive` (revision >= 1), `ck_project_memories_no_self_revision` (prev_id != id), `ck_project_memories_no_self_conflict` (conflict_id != id).
    - `MemoryAuditLog`: append-only audit trail capturing memory mutations (`MemoryAuditAction`), actor types, actor IDs, previous/new states, reason, and timestamps.
  - `backend/app/models/artifact.py`:
    - Added lineage and versioning columns: `version` (int, default 1), `parent_artifact_id` (UUID foreign key), `superseded_by_id` (UUID foreign key), `verification_status` (`ArtifactVerificationStatus`: `unverified`, `verified`, `failed`), `verification_details` (JSON).
    - Added check constraints: `ck_artifacts_no_self_parent`, `ck_artifacts_no_self_supersede`, `ck_artifacts_version_positive`.
  - `backend/app/models/__init__.py`:
    - Cleanly re-exported all new models and enums.
- **Alembic Migration:**
  - Created migration `f8d6aac5883a_add_persistent_project_memory_and_.py` chained from `6b136f812cca`.
  - Added explicit foreign key names (`fk_artifacts_superseded_by_id`, `fk_artifacts_parent_artifact_id`) and check constraints for safe two-way migration.
  - Tested `alembic upgrade head` on live PostgreSQL 16 (port 5433).
  - Tested `alembic downgrade 6b136f812cca` and re-upgrade to `f8d6aac5883a` with zero errors.
- **Verification & Test Harness:**
  - Created `backend/tests/test_memory_models.py` with 7 dedicated integration tests covering:
    - 4 provenance types and policy weight separation from verification flags.
    - Check constraints on confidence scores, revisions, self-revisions, and self-conflicts.
    - Revision chains and audit log consistency.
    - Artifact derivation, parent-child relationships, versioning, and supersession.
    - Artifact self-referential check constraints (self-parenting and self-supersession rejection).
    - Project isolation and cascade deletion.
  - Test results: 7/7 memory model tests passing (0.34s).
  - Full backend regression suite: 40/40 tests passing (7.13s).
  - Ruff check & format: 100% clean across all 64 backend files.
  - Frontend verification: 8/8 test suites passing (10 tests), 0 Oxlint warnings, production bundle clean.

### Milestone M1.3-3: Core Memory & Artifact Intelligence Services
- **Service Implementations:**
  - `backend/app/services/memory_audit_service.py`:
    - Append-only audit logger flushing within callers' transactions (`record_action`).
    - Immutability guards raising `PermissionError` on `update()`, `update_log()`, `delete()`, and `delete_log()`.
    - Project-scoped query methods: `list_by_memory` (chronological order) and `list_by_project` (reverse chronological).
  - `backend/app/services/memory_service.py`:
    - Full CRUD with strict project isolation.
    - Policy weights: `user_provided` (1.0), `verified_finding` (0.95), `agent_conclusion` (0.70), `assumption` (0.50).
    - Concurrency protection: `expected_revision` optimistic concurrency check paired with `SELECT ... FOR UPDATE` row locks to prevent simultaneous read-modify-write race conditions.
    - Immutable revision chains: `revision + 1` linked via `previous_revision_id`, marking current row `SUPERSEDED`. Automatic verification invalidation upon text modification.
    - Duplicate detection (re-activates or returns matching active row) and conflict detection (identical summary with divergent content flagged `conflict_status = DETECTED`).
    - Deterministic conflict resolution: `supersede`, `reject`, and `merge` strategies.
    - Verification workflow (`verify_memory`) upgrading conclusions to findings with actor attribution.
    - Soft-delete (`archive_memory`/`restore_memory`) and hard-delete (`delete_memory(hard_delete=True)`) preserving audit trail.
  - `backend/app/services/artifact_intelligence_service.py`:
    - Project-scoped artifact retrieval and manipulation (`get_artifact`, `_require_artifact`).
    - Multi-hop ancestry cycle prevention in `set_parent` via visited set graph traversal.
    - Cross-project boundary rejection (`ValueError("Cross-project artifact lineage is prohibited")`).
    - Supersession version progression validation (`target.version > artifact.version`) and cycle detection in `set_superseded_by`.
    - Comprehensive lineage traversal (`get_lineage` returning ancestors, descendants via BFS, superseding and superseded artifacts).
    - Verification state updates (`update_verification_status`).
- **Testing & Quality Assurance:**
  - `backend/tests/test_memory_services.py`: 7 integration tests covering CRUD, provenance scoring, optimistic concurrency, concurrent race conditions, conflict resolution, audit immutability, and lifecycle transitions.
  - `backend/tests/test_artifact_intelligence.py`: 6 integration tests covering project scoping, lineage traversal, self/multi-hop cycle rejection, cross-project rejection, version progression, and verification updates.
  - Test results: 13/13 new service tests passing (1.02s). Full regression: 53/53 tests passing (7.23s).
  - Code hygiene: `ruff check` and `ruff format` 100% clean across all 69 backend files.
  - Frontend: 8/8 test suites (10 tests) passing, 0 Oxlint warnings/errors, clean Vite build.
- **Documentation:**
  - Authored `docs/V1_3_M3_RELEASE_REPORT.md`.
  - Updated `docs/PROGRESS.md` and `docs/EXECUTION_LOG.md`.

### Milestone M1.3-4: Modular Knowledge Retrieval Engine Complete
- **Architecture & Assessment:**
  - Audited existing relational models, database session patterns, and migration state.
  - Selected PostgreSQL 16 Full-Text Search with GIN expression indexes as the dependable baseline.
  - Evaluated and rejected premature external vector databases and unpopulated pgvector embeddings (ADR-008).
- **Database & Migration:**
  - Generated and applied Alembic migration `07d25c09fdde_add_gin_full_text_indexes_for_retrieval.py`.
  - Added GIN expression indexes: `ix_project_memories_tsv` on `project_memories` and `ix_artifacts_tsv` on `artifacts`.
  - Verified migration upgrade, rollback (`downgrade f8d6aac5883a`), and re-upgrade with 0 errors. Verified `alembic check` clean.
- **Engine Components Implemented (`backend/app/services/retrieval/`):**
  - `schemas.py`: `RetrievalQuery`, `MemoryRetrievalFilter`, `ArtifactRetrievalFilter`, `ScoredMemory`, `ScoredArtifact`, `ContextAssemblySummary`, `RetrievalResult`.
  - `query_processor.py`: validates query bounds (max 500 chars), rejects null bytes, normalizes whitespace, extracts alphanumeric search tokens.
  - `metadata_filter.py`: constructs parameter-safe SQLAlchemy binary expressions enforcing mandatory `project_id` matching, enum validation, and lifecycle filters.
  - `ranker.py`: deterministic multi-signal ranking incorporating PostgreSQL text relevance (`ts_rank_cd`), provenance weights (`user_provided: 1.0`, `verified_finding: 0.95`, `agent_conclusion: 0.70`, `assumption: 0.50`), verification boost, 30-day half-life recency decay, lifecycle weighting, and stable tie-breaking (`-composite_score, -created_at, id`).
  - `memory_retriever.py`: database-side full-text search (`tsvector` & `tsquery`) and metadata filtering with bounded candidate fetching.
  - `artifact_retriever.py`: project-scoped artifact search with lineage context enrichment reusing `ArtifactIntelligenceService`.
  - `context_assembler.py`: formats structured Markdown prompt context strictly bounded by character budget (default 4,000 chars), preserving complete item boundaries and reporting omitted counts.
  - `service.py`: `RetrievalService` public interface providing explainable search, ID lookups, and context packaging.
- **Testing & Quality Assurance:**
  - Added `backend/tests/test_retrieval_engine.py` with 10 real PostgreSQL integration tests.
  - Backend regression: 63/63 tests passing (8.14s).
  - Code hygiene: `ruff check` and `ruff format` 100% clean across all 79 backend files.
  - Frontend: 8/8 test suites (10 tests) passing, 0 Oxlint warnings, production bundle clean.
- **Documentation:**
  - Updated `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (ADR-008), `docs/PROGRESS.md`, `docs/EXECUTION_LOG.md`.
  - Authored `docs/V1_3_M4_RELEASE_REPORT.md`.

### Milestone M1.3-5: LangGraph Workflow Memory Integration Complete
- **Architecture & Assessment:**
  - Formulated ADR-009 ("LangGraph Workflow Memory Integration with Idempotent Ingestion & Pre-Planning Retrieval").
  - Extended `OrchestrationState` with 9 typed fields: `retrieved_memories`, `retrieved_artifacts`, `retrieval_context`, `retrieval_metadata`, `retrieval_error`, `knowledge_candidates`, `ingestion_status`, `ingested_memory_ids`, `ingestion_errors`.
- **Pre-Planning Retrieval Integration:**
  - Added `retrieve_knowledge_node` as entry point before `plan_node` in `backend/app/orchestrator/workflow_graph.py`.
  - Configured graceful error tolerance: failures log warnings and fall back to clean empty state without halting execution.
  - Enhanced `QueryProcessor`, `MemoryRetriever`, and `ArtifactRetriever` with OR-based `websearch_to_tsquery` across significant tokens and token ILIKE checks to support multi-word natural language objectives while preserving ranking fidelity.
  - Updated `PlannerService.generate_plan` and `StructuredPlan` to accept and incorporate bounded `retrieval_context`.
  - Updated `_execute_single_task` to inject bounded project intelligence into downstream agent execution prompts.
- **Post-Execution Knowledge Extraction & Ingestion:**
  - Implemented `KnowledgeExtractor` (`backend/app/orchestrator/knowledge_extraction.py`): extracts milestones, architectural decisions, constraints, and discoveries.
  - Enforced strict provenance rules: tasks backed by passing deterministic QA verification get `AGENT_VERIFIED` (`confidence_score=0.95`, `is_verified=True`); unverified agent assertions get `AGENT_CONCLUSION` (`confidence_score=0.70`, `is_verified=False`).
  - Added `ingest_knowledge_node` executed after all task waves complete (`route_after_artifact` -> `ingest_knowledge` -> `complete_node` -> `END`).
  - Idempotency & crash recovery: checks `source_execution_id` against PostgreSQL `project_memories` prior to insertion to prevent duplicate records upon retry or recovery.
  - Foreign key safety: verified `WorkflowExecution` row existence before persisting foreign key references.
  - Synced runner state transitions and recorded `pipeline_memories_ingested` event in `WorkflowExecution.events`.
- **Testing & Quality Assurance:**
  - Created `backend/tests/test_workflow_memory_integration.py` with 8 integration tests covering pre-planning retrieval, error tolerance, prompt injection, verified provenance, unverified conclusions, failed pipeline bypass, retry idempotency, and approval pause/resume context preservation.
  - Full backend regression suite: 71/71 tests passing (12.64s).
  - Code hygiene: `ruff check` and `ruff format` 100% clean across all 81 backend files.
  - Frontend: 8/8 test suites (10 tests) passing, 0 Oxlint warnings, production bundle clean.
- **Documentation:**
  - Documented Section 6.4 in `docs/ARCHITECTURE.md`.
  - Documented ADR-009 in `docs/DECISIONS.md`.
  - Updated `docs/PROGRESS.md` (M1.3-5 marked COMPLETE).
  - Authored `docs/V1_3_M5_RELEASE_REPORT.md`.

### Milestone M1.3-6: REST APIs & Schemas for Project Intelligence Complete
- **API Architecture & Design:**
  - Designed REST API suite exposing project memories under `/api/v1/projects/{project_id}/memories` and artifact lineage under `/api/v1/projects/{project_id}/artifacts/{artifact_id}/lineage`.
  - Maintained thin routers delegating all business logic to `MemoryService`, `MemoryAuditService`, and `ArtifactIntelligenceService`.
  - Strict project boundary enforcement: verifies project existence on every endpoint, rejecting cross-project and non-existent queries with 404.
- **Pydantic Schemas Implemented:**
  - `backend/app/schemas/memory.py`: `MemoryCreateRequest` (with whitespace validators), `MemoryUpdateRequest` (`expected_revision`), `MemoryActionRequest`, `MemoryVerifyRequest`, `MemoryConflictResolveRequest`, `MemoryRead`, `MemoryConflictItem`, `MemoryAuditLogRead`, generic `PaginatedResponse[T]`.
  - `backend/app/schemas/artifact.py`: updated `ArtifactRead` with lineage fields (`version`, `parent_artifact_id`, `superseded_by_id`, `verification_status`, `verification_details`).
  - `backend/app/schemas/lineage.py`: `ArtifactLineageResponse`.
- **Service Layer Extensions:**
  - `MemoryService.list_and_count_memories`: database-side filtering (category, provenance, status, verification, conflict, search query, date bounds), pagination, deterministic sorting, and total count. Excludes superseded/archived records by default.
  - `MemoryService.list_conflicts`: queries detected conflicts with partner memory details and pagination.
  - `MemoryAuditService.list_by_memory_paginated`: paginated read-only access to immutable memory audit trails.
- **Router Implementation:**
  - Created `backend/app/api/v1/memories.py`: 10 distinct endpoints (list/filter, create, conflicts, detail, revision update with 409 Conflict protection, archive, restore, explicit verify, conflict resolve, audit trail).
  - Enhanced `backend/app/api/v1/artifacts.py`: added `GET /projects/{project_id}/artifacts/{artifact_id}/lineage` and `GET /artifacts/{artifact_id}/lineage`.
  - Registered routers in `backend/app/main.py`.
- **Testing & Quality Assurance:**
  - Created `backend/tests/test_memory_api.py` with 9 comprehensive FastAPI integration tests exercising real PostgreSQL transactions.
  - Full backend regression suite: 80/80 tests passing (14.83s).
  - Code hygiene: `ruff check` and `ruff format` 100% clean across all 85 backend files.
  - Frontend: 8/8 test suites (10 tests) passing, 0 Oxlint warnings, production bundle clean.
- **Documentation:**
  - Documented Section 6.5 in `docs/ARCHITECTURE.md`.
  - Updated `docs/PROGRESS.md` (M1.3-6 marked COMPLETE).
  - Authored `docs/V1_3_M6_RELEASE_REPORT.md`.

## 2026-11-02 — V1.3-M7: Frontend Project Intelligence Experience (Memory Bank UI)
- **Role Alignment:** Lead AI Architect & Technical Lead. Executor: Claude Haiku 5.5 (`claude-haiku-5-5`).
- **Backend API Additions & Audit:**
  - Added `MemoryStatsResponse` schema in `backend/app/schemas/memory.py`.
  - Implemented `MemoryService.get_memory_stats(db, project_id)` executing single-query SQL aggregation across active, verified, conclusion, assumption, conflict, and archived counts.
  - Added `GET /api/v1/projects/{project_id}/memories/stats` endpoint in `backend/app/api/v1/memories.py`.
  - Added `GET /api/v1/projects/{project_id}/memories/{memory_id}/revisions` endpoint calling `MemoryService.get_revision_history`.
  - Restricted `GET /api/v1/projects/{project_id}/artifacts/{artifact_id}/lineage` strictly to project scope for project boundary isolation.
- **Frontend Type Definitions & API Client:**
  - Updated `frontend/src/types/api.ts`: Added types for `MemoryCategory`, `MemoryProvenanceType`, `MemoryStatus`, `MemoryConflictStatus`, `MemoryAuditAction`, `ProjectMemory`, `MemoryConflictItem`, `MemoryAuditLog`, `MemoryStats`, `ArtifactLineage`, `PaginatedResponse<T>`, and lineage fields to `Artifact`.
  - Updated `frontend/src/api/client.ts`: Added client methods for `getMemoryStats`, `getMemories`, `getMemory`, `createMemory`, `updateMemory`, `archiveMemory`, `restoreMemory`, `verifyMemory`, `getConflicts`, `resolveConflict`, `getMemoryRevisions`, `getMemoryAudit`, `getArtifactLineage`.
- **UI Components Implemented:**
  - `frontend/src/components/intelligence/ProvenanceBadge.tsx`: Visual badges across the 4 provenance classifications (`user_provided`, `verified_finding`, `agent_conclusion`, `assumption`) with calibrated score indicators.
  - `frontend/src/components/intelligence/VerificationBadge.tsx`: Independent indicator decoupled from provenance, showing operator verification with verifier identity and date tooltip.
  - `frontend/src/components/intelligence/MemoryFormModal.tsx`: Creation and edit modal with character counters, category/provenance selectors, and optimistic concurrency conflict handling (`expected_revision` HTTP 409 handling).
  - `frontend/src/components/intelligence/MemoryDetailModal.tsx`: Comprehensive inspector with Overview, immutable Revision History, and immutable Audit Trail tabs, plus in-place verification and archive/restore actions.
  - `frontend/src/components/intelligence/ConflictWorkbench.tsx`: Side-by-side contradiction resolution interface with list of colliding memory pairs, comparison pane, and `supersede`, `reject`, and `merge` transactional resolution flows.
  - `frontend/src/components/intelligence/ArtifactLineageExplorer.tsx`: Tree explorer rendering complete ancestry chains, direct parents, current artifact focus, derived descendants, and supersession alerts.
  - Updated `frontend/src/pages/IntelligencePage.tsx`: Added project selector, 4 tabs (`Memory Bank`, `Conflict Workbench`, `Artifact Lineage`, `Model Telemetry`), KPI cards, live search, multi-filter toolbar, and server pagination.
- **Testing & Verification:**
  - Authored `frontend/src/__tests__/IntelligencePage.test.tsx` (6 comprehensive test suites covering header, project selector, memory stats, search/filtering, Conflict Workbench, Artifact Lineage, Model Telemetry, Detail Modal, and Creation Modal).
  - Vitest test suite: 9/9 test files, 16/16 tests passing in 1.20s.
  - Vite build: `tsc -b && vite build` completed in 148ms with 0 errors.
  - Oxlint: 0 errors across 35 files.
  - Backend regression: 80/80 tests passing in 13.51s. Ruff check & format: 100% clean across all 85 backend files.
- **Documentation:**
  - Added Section 6.6 (Memory Bank UI Architecture) in `docs/ARCHITECTURE.md`.
  - Updated `docs/PROGRESS.md` (marked M1.3-7 COMPLETE).
  - Authored `docs/V1_3_M7_RELEASE_REPORT.md`.

## 2026-11-03 — V1.3-M8: End-to-End Integration, Reliability, and V1.3 Acceptance
- **Role Alignment:** Lead AI Architect & Independent Reviewer: Gemini. Executor: Claude Haiku 5.5 (`claude-haiku-5-5`).
- **Architectural Findings & Hardening Implemented:**
  - **AF-1 (Decoupled Verification Semantics):** Refactored `backend/app/orchestrator/knowledge_extraction.py` to classify all agent extractions strictly as `MemoryProvenanceType.AGENT_CONCLUSION` with `confidence_score = 0.70` and `is_verified = False`. QA test success is recorded in `metadata_json["qa_tests_passed"] = True` without self-verifying. Added field validator on `MemoryVerifyRequest.verified_by` in `backend/app/schemas/memory.py` rejecting blank/whitespace strings (HTTP 422). Updated `MemoryService.verify_memory` to promote `PROPOSED` to `ACTIVE` upon explicit authorized verification.
  - **AF-2 (Ingestion Idempotency Granularity):** Replaced coarse execution-level blanket skip in `backend/app/orchestrator/workflow_graph.py` with candidate signature tracking `(category, summary, source_task_id)`. Prevents duplicate memory creation on retries while allowing new candidate batches in the same execution.
  - **AF-3 (Audit Log Hard Deletion Survival):** Updated `backend/app/services/memory_audit_service.py` to locate audit entries via foreign key or JSON snapshot examination (`previous_state->>'id'` / `new_state->>'id'`), ensuring audit records remain queryable after memory hard deletion (`ondelete="SET NULL"`).
  - **AF-4 (Crash Boundary Ingestion Recovery):** Tested process crash immediately following database memory commit before LangGraph checkpoint persistence with real OS-level `SIGKILL` (Process 1: PID 70068, Process 2: PID 70138). Verified 0 duplicate memories (6 -> 6), 0 duplicate audit logs (6 -> 6), and clean workflow completion.
- **Cross-Execution Intelligence Verification (`backend/tests/test_cross_execution_intelligence.py`):**
  - **Execution A:** Establishes durable project knowledge (architecture decisions, milestones, artifact v1). Explicit operator verification promotes decision to `VERIFIED_FINDING`.
  - **Execution B:** Retrieves verified architectural decision before planning; LangGraph pre-planning retrieval populates prompt context budget. Creates derived artifact v2 linked to v1 with supersession. Project isolation verified (unrelated project retrieves 0 items).
  - **Execution C:** Introduces conflicting security proposal under identical summary. Detects conflict status `DETECTED` bidirectionally. Resolves conflict via `MERGE` into unified dual-layer policy (`MemoryStatus.ACTIVE`, `MemoryConflictStatus.RESOLVED`). Full audit trail verified.
- **Empirical Performance Benchmarks (`scratch/benchmark_retrieval_performance.py`):**
  - Seeded 1,000 realistic project memories in PostgreSQL 16 (0.13s).
  - Ran 100 retrieval queries via `RetrievalService.search` (top_k=5):
    - Min: 30.14 ms
    - p50: 34.00 ms
    - p90: 38.69 ms
    - p95: 39.64 ms
    - p99: 41.43 ms
    - Max: 43.16 ms
  - 100% of context packages strictly honored the 4,000 character prompt budget.
  - Zero leftover rows after automated cleanup.
- **Verification & Acceptance:**
  - Backend regression: 88/88 pytest tests passing in 14.07s.
  - Frontend test suite: 9/9 test files (16 tests) passing in 1.46s.
  - Frontend build & lint: `npm run lint` (0 errors), `npm run build` (170ms) clean.
  - Code hygiene: `ruff check` and `ruff format` 100% clean across all 87 backend files.
- **Documentation & Reporting:**
  - Added Section 6.7 in `docs/ARCHITECTURE.md`.
  - Added ADR-010 and ADR-011 in `docs/DECISIONS.md`.
  - Updated `docs/ROADMAP.md` and `docs/PROGRESS.md` marking V1.3 COMPLETE.
  - Authored comprehensive `docs/V1_3_FINAL_ACCEPTANCE_REPORT.md`.

## 2026-11-03 — V1.4-M1: Security & Concurrency Hardening
- **Role Alignment:** Lead AI Architect & Independent Reviewer: Gemini. Executor: Claude Haiku 5.5 (`claude-haiku-5-5`).
- **Milestone Scope:** Security hardening of verifier identity (TR-01) and durable concurrency & idempotency hardening of knowledge ingestion (TR-02).
- **Security Hardening (TR-01 / R1):**
  - Created `backend/app/core/auth.py` defining `OperatorContext`, `get_operator_context`, and `require_authorized_verifier`.
  - Added configuration settings `DEFAULT_OPERATOR_NAME = "Abstract"` and `OPERATOR_API_KEY = None` (with API key enforcement when configured via `X-ASTRAVA-API-KEY` or Bearer token).
  - Updated `backend/app/schemas/memory.py`: `MemoryVerifyRequest.verified_by` made optional (`None`).
  - Updated `backend/app/api/v1/memories.py`: Endpoint `POST /projects/{project_id}/memories/{memory_id}/verify` uses `require_authorized_verifier`. Explicit verifier impersonation attempts are rejected with HTTP 403 Forbidden. Authentic operator identity is propagated to `MemoryService.verify_memory` and logged into `MemoryAuditLog` with authentic `actor_id` and `actor_type`.
  - Updated `frontend/src/api/client.ts`: `verifyMemory` sends `X-ASTRAVA-ACTOR-NAME: data.verified_by` header so UI-entered names match operator context.
  - Authored `backend/tests/test_v1_4_security.py` covering all 19 security scenarios (19/19 passed).
- **Concurrency & Idempotency Hardening (TR-02 / R2):**
  - Updated `backend/app/models/memory.py`: Added `IngestionOperationStatus` enum, `IngestionOperation` model (unique constraint on `project_id, operation_token`), `fingerprint` column and `ingestion_operation_id` foreign key on `ProjectMemory`, and partial unique index `uq_project_memories_fingerprint` on `(project_id, fingerprint)` where `fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED')`.
  - Authored Alembic migration `backend/alembic/versions/7a8e1b2c3d4e_add_ingestion_operations_and_memory_fingerprint.py`. Tested upgrade, downgrade, and re-upgrade against live PostgreSQL container.
  - Implemented `compute_candidate_fingerprint` in `backend/app/orchestrator/knowledge_extraction.py` (SHA-256 over `project_id:category:summary:source_task_id`).
  - Updated `MemoryService.create_memory` to accept and persist `fingerprint` and `ingestion_operation_id`.
  - Redesigned `ingest_knowledge_node` in `backend/app/orchestrator/workflow_graph.py`:
    - Generates stable `operation_token`.
    - Short-circuits immediately if operation is already `COMPLETED`.
    - Handles concurrent operation races: losing workers poll the winner via fresh database sessions and return the completed memory IDs.
    - Uses SQLAlchemy nested savepoints (`async with session.begin_nested():`) for per-candidate insert isolation, preventing session corruption if a single candidate collides or fails.
    - Prevents clobbering completed status in error handlers.
  - Authored `backend/tests/test_v1_4_concurrency_idempotency.py` covering all 11 concurrency scenarios (11/11 passed).
- **Verification & Acceptance:**
  - Backend pytest regression: **118/118 tests passed** in 17.65s (from 88 to 118 tests, +30 new tests).
  - Code hygiene: `ruff check` and `ruff format` 100% clean across all 90 backend files.
  - Frontend: 9/9 test suites (16 tests) passed in 1.20s; `npm run lint` 0 errors; `npm run build` completed cleanly in 207ms.
  - Database schema: current migration head `7a8e1b2c3d4e`.
- **Documentation & Reporting:**
  - Added Section 7 in `docs/ARCHITECTURE.md`.
  - Added ADR-012 and ADR-013 in `docs/DECISIONS.md`.
  - Updated `docs/PROGRESS.md` with M1.4-1 tasks marked COMPLETE.
  - Updated `docs/V1_4_TECHNICAL_RISKS.md` marking TR-01 and TR-02 RESOLVED.
  - Authored `docs/V1_4_M1_RELEASE_REPORT.md`.


