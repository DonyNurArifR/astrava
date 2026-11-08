# ASTRAVA Architecture Decision Records (ADR)

## ADR-001: Modular Monolith Architecture
- **Status:** Accepted
- **Context:** ASTRAVA needs enterprise-grade stability, clear auditability, fast developer iteration, and straightforward deployment.
- **Decision:** Build ASTRAVA as a modular monolith with clear domain boundaries (API, Domain models, Orchestrator, Provider layer, Artifacts, Verification).
- **Consequences:** Low operational complexity, straightforward debugging, single repository, shared type contracts.

## ADR-002: Model Execution via Claude Code CLI (Haiku 5.5)
- **Status:** Accepted
- **Context:** The task requires executing implementation tasks using Claude Haiku 5.5 through Claude Code CLI under the active subscription.
- **Decision:** Use `claude --model haiku -p --output-format json` which maps to canonical model `claude-haiku-5-5`.
- **Consequences:** Subprocesses must be executed safely with argument vectors (`shell=False`), isolated per-project directories, strict timeouts, and detailed JSON response parsing (tokens, durations, session ID, tool calls).

## ADR-003: Stateful Workflows with LangGraph
- **Status:** Accepted
- **Context:** Multi-step planning, task dispatch, approval interrupts, and verification need state persistence and retry capabilities.
- **Decision:** Use LangGraph backed by PostgreSQL checkpoints for orchestration.
- **Consequences:** Workflows can pause for human approval, recover from backend restarts, and retain full execution history.

## ADR-004: Dual Frontend Theme & Enterprise Design System
- **Status:** Accepted
- **Context:** ASTRAVA's brand identity is enterprise, intelligent, reliable, and human-guided.
- **Decision:** Built with Tailwind CSS, supporting light (default) and dark modes using the specified palette (Midnight Navy `#101827`, Slate Blue `#253B59`, Electric Blue `#3B82F6`, Cloud White `#F8FAFC`). Typography uses Inter and JetBrains Mono.

## ADR-005: Reusable Agent Registry & Dynamic DAG Execution
- **Status:** Accepted
- **Context:** Hardcoded linear workflows limit multi-agent problem solving.
- **Decision:** Seeded 16 specialized agents in PostgreSQL and implemented dynamic Kahn's algorithm DAG planning with parallel stage partitioning.
- **Consequences:** Enables flexible workflows across SaaS and Media studios while keeping deterministic cycle detection.

## ADR-006: Autonomous Bounded Retries & Per-Stage Commit Durability
- **Status:** Accepted
- **Context:** Provider timeouts or transient errors should self-heal without abandoning completed sibling deliverables or crashing pipelines.
- **Decision:** LangGraph nodes execute bounded retries with exponential backoff; `OrchestrationRunner` streams events and commits DB state per wave.
- **Consequences:** Pipelines survive abrupt process kills (`SIGKILL`) with zero duplicate tasks and preserve sibling outputs under partial failures.

## ADR-007: Persistent Project Intelligence & PostgreSQL Full-Text Search
- **Status:** Accepted
- **Context:** Agents need long-term project memory across separate executions without premature external vector database infrastructure.
- **Decision:** Implement project-scoped persistent memories across 10 categories with a 4-tier provenance model (`user_provided`, `verified_finding`, `agent_conclusion`, `assumption`), conflict detection, and native PostgreSQL 16 Full-Text Search (`tsvector`/`tsquery`) with strict context budgeting (max 4,000 characters).
- **Consequences:** Zero external vector DB dependencies; deterministic, bounded prompt injections; traceable provenance; conflict preservation without silent overwrites.

## ADR-008: Modular Knowledge Retrieval Engine Architecture
- **Status:** Accepted
- **Context:** Agents and execution pipelines require relevant project memories and artifact lineage context before planning and task execution. We need project-isolated, explainable, bounded retrieval without introducing vector DB overhead or external API costs.
- **Decision:** Build a modular retrieval engine (`RetrievalService`, `MemoryRetriever`, `ArtifactRetriever`, `QueryProcessor`, `MetadataFilter`, `RetrievalRanker`, `ContextAssembler`) using PostgreSQL 16 Full-Text Search with GIN indexes, database-side metadata filtering, multi-signal ranking (text relevance, provenance policy weight, verification status, recency decay, and lifecycle status), lineage traversal reuse, and strict post-formatting context budgeting (default max 4,000 characters).
- **Alternatives Considered & Rejected:**
  1. *External Vector DB (Pinecone, Qdrant, Weaviate):* Rejected due to added infrastructure complexity, operational failure modes, synchronization overhead, and cost.
  2. *pgvector Embeddings:* Rejected for baseline M1.3-4 as embedding generation requires external API calls or heavyweight local models with no embeddings currently populated. Interface is decoupled so semantic vector retrieval can be added as a pluggable retriever.
  3. *Client-side Python Filtering:* Rejected to avoid loading unbounded tables into application memory; filtering and base scoring are pushed to PostgreSQL.
- **Consequences:** Deterministic, reproducible rankings; strict project isolation; zero external API dependencies; guaranteed prompt budget compliance.

## ADR-009: LangGraph Workflow Memory Integration with Idempotent Ingestion & Pre-Planning Retrieval
- **Status:** Accepted
- **Context:** Multi-agent workflows need to benefit from persistent project knowledge before formulating plans, and durable discoveries from completed pipelines must be captured without corrupting checkpoints or creating duplicate records across retries, pauses, or process crashes.
- **Decision:**
  1. *Pre-Planning Retrieval Node (`retrieve_knowledge`):* Set as graph entry point before `plan`. Queries `RetrievalService` with mandatory `project_id` and bounds context to $\le 4,000$ chars. Passes context to planner and injects it into downstream agent prompts.
  2. *Post-Execution Ingestion Node (`ingest_knowledge`):* Placed after all wave tasks and deterministic verification succeed. Only extracts durable knowledge (objectives, verified findings, architectural decisions) into typed Pydantic candidates.
  3. *Strict Provenance Classification:* Only findings with automated verification evidence receive `verified_finding`; unverified agent outputs remain `agent_conclusion`.
  4. *Two-Tier Idempotency Guard:* Ingestion checks in-memory `ingestion_status == "completed"` and checks PostgreSQL `ProjectMemory.source_execution_id == execution_id`. A crash between DB commit and checkpoint persistence does not create duplicate memories or audit records on restart.
- **Consequences:** Safe resumption across interrupts and process crashes; zero duplicate memories; seamless knowledge reuse across separate workflow executions.

## ADR-010: Decoupled Verification Semantics & Verifier Attribution
- **Status:** Accepted
- **Context:** Automated agents executing multi-step pipelines cannot self-certify their conclusions as `verified_finding` merely because automated QA tests passed on code artifacts. Self-attestation degrades memory trust and introduces circular confidence inflation.
- **Decision:**
  1. *Automated Ingestion Boundary:* Knowledge extraction from automated pipelines strictly assigns `MemoryProvenanceType.AGENT_CONCLUSION` with `confidence_score = 0.70` and `is_verified = False`. Passing QA tests are noted as metadata (`qa_tests_passed: true`) without altering provenance.
  2. *Explicit Verification Gate:* Promotion from `AGENT_CONCLUSION` to `VERIFIED_FINDING` (and activation from `PROPOSED` to `ACTIVE`) requires explicit invocation of `verify_memory` with mandatory non-empty verifier attribution (`verified_by`). Whitespace-only or missing verifier strings are rejected with HTTP 422.
- **Consequences:** Pristine audit trails; unambiguous provenance boundaries; prevents autonomous hallucination loops from contaminating the long-term project knowledge bank.

## ADR-011: Conflict Resolution Governance & Audit Survival on Hard Deletion
- **Status:** Accepted
- **Context:** Knowledge evolution produces contradictory proposals over time. Silent overwrites corrupt historical context, and accidental or deliberate memory deletion must not destroy the audit trail.
- **Decision:**
  1. *Transactional Conflict Resolution:* Colliding summaries trigger `conflict_status = DETECTED`. Resolution supports three deterministic strategies: `supersede` (marks one memory superseded, preserves both), `reject` (marks one memory rejected, leaves partner active), and `merge` (creates a synthesized active record, resolving the conflict).
  2. *Audit Trail Persistence on Hard Deletion:* `memory_audit_logs.memory_id` uses `ondelete="SET NULL"`. Audit queries match by foreign key or by querying JSON snapshots (`previous_state->>'id'` / `new_state->>'id'`).
- **Consequences:** Absolute historical auditability; zero data loss during memory lifecycle changes; compliance with enterprise security requirements.

## ADR-012: Trusted Operator Authentication Context & Verifier Identity Protection
- **Status:** Accepted
- **Context:** In V1.3, `POST /api/v1/projects/{project_id}/memories/{memory_id}/verify` accepted arbitrary unauthenticated `verified_by` strings from HTTP clients. This allowed any client or script to impersonate arbitrary verifiers or promote unverified agent conclusions under false identity, corrupting the forensic audit trail (V1.3 Risk R1 / TR-01).
- **Decision:**
  1. *Operator Context Dependency (`backend/app/core/auth.py`):* Implement `OperatorContext` and FastAPI dependency `get_operator_context` resolving authentic actor identity per request.
  2. *Single-User Local Mode & Secured Mode:* If `OPERATOR_API_KEY` is not set, authenticate as local default operator (`settings.DEFAULT_OPERATOR_NAME = "Abstract"`), with display name customizable via `X-ASTRAVA-ACTOR-NAME`. When `OPERATOR_API_KEY` is configured, enforce mandatory API key validation (`X-ASTRAVA-API-KEY` or Bearer token), rejecting unauthenticated calls with HTTP 401.
  3. *Enforced Verification Authorization:* Dependency `require_authorized_verifier` guards the memory verification route. Direct client impersonation (supplying a `verified_by` name that does not match the authenticated operator's display name) is strictly forbidden and rejected with HTTP 403 Forbidden.
  4. *Immutable Audit Attribution:* Derive `verified_by` directly from the authenticated `operator.display_name` if omitted, and log authentic `actor_id` (`operator.operator_id`) and `actor_type` (`operator.actor_type`) to `MemoryAuditLog`.
- **Consequences:** Verifier spoofing is completely eliminated; audit trails record authentic, non-repudiable operator attribution; backwards compatible with single-user local development while seamlessly locking down in secured deployments.

## ADR-013: Two-Tier Ingestion Idempotency, Operation Token Tracking & Partial Unique Index Deduplication
- **Status:** Accepted
- **Context:** V1.3 relied on Python-side pre-query deduplication before inserting extracted knowledge. Concurrent pipeline runs or workers racing for the same project/execution would both observe 0 rows and insert duplicates. Furthermore, transaction rollback on a single candidate error aborted preceding successful candidates in the session (V1.3 Risk R2 / TR-02).
- **Decision:**
  1. *Candidate Fingerprinting:* Compute deterministic SHA-256 fingerprint for every candidate based on `(project_id, category, summary, source_task_id)` and store in `ProjectMemory.fingerprint`.
  2. *Relational Partial Unique Index:* Enforce database-level uniqueness via PostgreSQL partial index:
     `CREATE UNIQUE INDEX uq_project_memories_fingerprint ON project_memories (project_id, fingerprint) WHERE fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED')`.
     Duplicate insertions under concurrency or retries are rejected at the database level.
  3. *Ingestion Operation Tracking (`IngestionOperation`):* Record pipeline ingestion attempts under a unique `(project_id, operation_token)` constraint. The state machine (`PENDING` -> `IN_PROGRESS` -> `COMPLETED` / `FAILED`) prevents duplicate pipeline ingestion.
  4. *Concurrent Race Polling:* In the event of concurrent execution races where losing workers hit an `IntegrityError` on the operation token, losers enter an async backoff polling loop using a fresh session to wait for the winner to complete, returning the winning result without failing or repeating work.
  5. *Nested Transaction Savepoints:* Wrap candidate inserts inside `async with session.begin_nested():`. If an individual candidate fails or collides with a concurrent insert, only that candidate's savepoint is rolled back, leaving preceding valid candidates intact.
- **Consequences:** Relational engine-level guarantee against duplicate memory creation; zero transaction corruption on candidate errors; seamless handling of concurrent pipeline execution races.

## ADR-014: Centralized Execution Budget Governance & Atomic Two-Phase Reservation
- **Status:** Accepted
- **Context:** Autonomous agents, dynamic replanning, and iterative remediation turns can consume unbounded tokens, API quotas, and runtime if not strictly governed. In-memory counters are vulnerable to process restarts, parallel wave races, and multi-worker double-spending (V1.4 TR-03).
- **Decision:**
  1. *Execution-Level Ownership:* Attach `ExecutionBudget` to `workflow_executions` (1-to-1) rather than individual tasks or ephemeral processes.
  2. *Two-Phase Reservation Protocol:* Enforce atomic reservation prior to agent dispatch using row-level database locks (`SELECT ... FOR UPDATE` on `execution_budgets`).
  3. *In-Flight Hold Tracking (`BudgetReservation`):* Record reservations with an expiration lease (`expires_at`). Overdue active reservations from crashed workers are reclaimed automatically.
  4. *Multi-Dimension Governance:* Enforce independent limits across cost ($1.00 USD), input/output tokens (250k/50k), agent/task attempts (10/3), remediation turns (5), replans (2), and runtime (600s). Distinguish actual provider-reported cost from estimated cost (`is_cost_estimated`).
  5. *Graceful Exhaustion & Resumption:* On limit exhaustion, transition to `EXHAUSTED`, record `exhaustion_reason`, preserve all completed work/artifacts, and halt new dispatches. Enable operators to resume executions by increasing limits via `POST /api/v1/executions/{id}/budget/increase`.
- **Consequences:** Guaranteed protection against runaway autonomous loops; deterministic concurrency safety across parallel waves; zero resource leakage on worker crashes; audit-ready budget accounting.

## ADR-015: Budget Governance Hardening & Resilient Resource Accounting (M1.4-2.2)
- **Status:** Accepted
- **Context:** The M1.4-2.1 independent acceptance audit identified six critical operational vulnerabilities in execution budget governance (F-01 through F-06): unauthenticated budget increase endpoint, retry attempts bypassing budget controls, missing provider metrics silently coerced to zero cost, lack of fencing tokens permitting stale workers to settle reservations, IEEE-754 binary floating-point drift violating check constraints, and crash resumption failures on already-reconciled reservations.
- **Decision:**
  1. *Authorized Budget Increases & Forensic Audit Logging (F-01):* Protect `POST /api/v1/executions/{execution_id}/budget/increase` with `OperatorContext` and `require_authorized_verifier`. Mandate justification `reason` ($\ge 5$ chars) and enforce system safety ceilings (`MAX_BUDGET_CEILINGS`). Atomically record every limit modification into `budget_audit_logs`.
  2. *Retry-Aware Dynamic Reservation (F-02):* Reserve budget per-attempt using key format `task:{task_id}:attempt:{attempt}`. Authorize each retry attempt dynamically with `BudgetGovernor.reserve()`. Halt retries immediately mid-task upon budget exhaustion. Record `total_agent_attempts += 1` per actual provider attempt.
  3. *Telemetry Metric Integrity (F-03):* When provider cost telemetry is missing or unavailable, preserve the reserved estimate as `consumed_estimated_cost_usd` rather than coercing to $0.00. Explicitly flag `cost_unavailable` and distinguish confirmed zero cost via `is_cost_zero_confirmed`.
  4. *Distributed Fencing Tokens (F-04):* Assign a cryptographically secure 64-character `fence_token` to each `BudgetReservation`. Require the token on all `reconcile` and `release` operations, raising `FencingTokenMismatchError` to reject stale or zombie worker reconciliations.
  5. *Fixed-Point Monetary Precision (F-05):* Migrate database schema from `Float` to `Numeric(12, 6)` and Python service layer to `Decimal`. Ensure zero arithmetic drift across high-frequency sub-cent cost increments.
  6. *Idempotent Resumption Recovery (F-06):* Inspect settled reservation state during worker restart. If attempt 0 was already reconciled prior to an abrupt crash, cleanly adopt the completed task output without raising unhandled reservation errors.
- **Consequences:** Eliminates unauthorized or unlogged budget inflation; guarantees bounded resource consumption across retries; ensures accurate financial accounting when provider metrics fluctuate; prevents distributed concurrency corruption from stale workers; provides crash-resilient execution resumption.

## ADR-016: Workflow Recovery & Endpoint Security Hardening (M1.4-2.2.2)
- **Status:** Accepted
- **Context:** The M1.4-2.2.1 independent acceptance audit identified operational and security vulnerabilities in workflow recovery and API mutations: AUD-M2.2-01 (partial-wave task index misalignment when pre-completed tasks exist), AUD-M2.2-02 (reservation reconciliation conflated with task completion on restart), AUD-M2.2-03 (optional fencing token parameter allowing unauthenticated settlement bypasses), and AUD-M2.2-04 (unauthenticated execution lifecycle endpoints: `/executions`, `/pause`, `/resume`).
- **Decision:**
  1. *Explicit 1-to-1 Task Identity Pairing (AUD-M2.2-01):* Replace positional index mapping (`results[i]`) with `zip(tasks_to_dispatch, results, strict=True)`. Map each result directly to its originating task identity via `task_map.get(task_id, task_dispatched)` to guarantee correctness in partial waves.
  2. *Decoupled Settlement & Verified Task Completion (AUD-M2.2-02):* Enforce that a `RECONCILED` reservation alone never establishes task completion. Resumed workflows must verify provider attempt success (`res_0.metadata_json["success"] is True`), presence of non-empty deliverables, and physical existence of expected artifact files on disk. Failed previous attempts are recognized, increment attempt counters, and permit dynamic retry reservation (`attempt:N`) if limits allow.
  3. *Mandatory Cryptographic Fencing Tokens (AUD-M2.2-03):* Enforce `fence_token: str` as a non-optional parameter across `BudgetGovernor.reconcile()` and `BudgetGovernor.release()`, raising `FencingTokenMismatchError` on any missing or mismatched token.
  4. *Execution Mutation Endpoint Authentication (AUD-M2.2-04):* Protect `POST /api/v1/executions`, `POST /api/v1/executions/{id}/pause`, and `POST /api/v1/executions/{id}/resume` with `OperatorContext = Depends(require_authorized_verifier)`. Record authenticated `actor_id` in execution telemetry events.
  5. *Multi-Process Crash Recovery Verification:* Verify true multi-process crash durability via OS subprocesses and `SIGKILL`, proving that resuming orchestrator processes successfully reclaim expired leases from killed workers and proceed to completion.
- **Consequences:** Eliminates state corruption during partial-wave dispatches; prevents incomplete or failed tasks from masquerading as completed during recovery; guarantees cryptographic fencing across all reservation lifecycles; seals unauthenticated execution mutation attack vectors; ensures verified fault tolerance across process boundaries.

## ADR-018: Two-Tier Semantic Evaluation & Closed-Loop Automated Remediation (M1.4-3)
- **Status:** Accepted
- **Context:** Blind retries in autonomous agent execution waste budget and fail to resolve root causes such as code syntax errors, unmet acceptance criteria, or malformed artifacts. Prior versions lacked a closed-loop feedback mechanism to inject verification diagnostics back into agent prompts.
- **Decision:**
  1. *Two-Tier Verification Architecture:* Tier 1 Deterministic Engine executes fast syntax compilation (`py_compile`), automated pytest runner, and JSON validation, extracting structured diagnostics (`StructuredDiagnostic` bounded to 2,500 characters). Tier 2 Semantic Evaluator (`SemanticEvaluator` / `SemanticEvaluationProvider`) evaluates deliverables against task-defined `acceptance_criteria` using Claude Haiku 5.5, computing compliance scores (0.0 - 1.0) and identifying unmet criteria.
  2. *Closed-Loop Remediation Graph Node (`remediation_node`):* Added a dedicated LangGraph node between `verify` and `dispatch_task`. Formats structured diagnostics, compiler lines, and unmet criteria into a high-priority prompt section (`=================== REMEDIATION REQUIRED ===================`) and routes back to `dispatch_task`.
  3. *Deterministic 3-Cycle Remediation Cap:* Strict bounding at 3 remediation cycles per task. Tasks failing verification after 3 cycles are permanently marked `failed` and halted from re-entering remediation, preventing infinite loops.
  4. *Centralized Budget Governance Integration:* Added `BudgetGovernor.record_remediation_turn(db, execution_id)` tracking against `max_remediation_turns`. Reaching the limit transitions budget to `EXHAUSTED` and cleanly terminates the pipeline without corruption.
  5. *Persistence & Audit Observability:* Added `remediation_history_json` to `tasks` table and `remediation_count` to `workflow_executions`. Exposed `GET /api/v1/executions/{id}/remediations` returning complete cycle history and diagnostics. Added frontend inspector badge and drawer in `ExecutionsPage.tsx`.
- **Consequences:** Intelligently self-correcting agent pipelines; eliminate blind retries; deterministic cycle and budget bounding; comprehensive auditability across all self-correction attempts.## ADR-019: Adaptive Goal Decomposition & Dynamic DAG Replanning (M1.4-4)
- **Status:** Accepted
- **Context:** Hardcoded 6-stage workflow templates constrain ASTRAVA to fixed execution topologies that cannot adapt to non-standard project objectives, dynamic real-world feedback, or mid-pipeline discoveries. Autonomous intelligence requires flexible goal decomposition and dynamic graph modification while safeguarding completed deliverables and resource limits.
- **Decision:**
  1. *Autonomous Goal Decomposition (`GoalDecomposer`):* Utilize Claude Haiku 5.5 to synthesize tailored execution DAGs from arbitrary natural-language project goals and studio types. Pass project retrieval context (memory) directly into the decomposition prompt. Validate all generated graphs using Kahn's topological sort algorithm (`PlannerService.validate_and_compute_stages`), falling back deterministically to the proven 6-stage template on syntax or acyclicity failures.
  2. *Runtime DAG Modification Invariants (`DAGModifier`):* Strictly preserve all tasks in `completed` status as immutable ground truth. When new plans are supplied, replace unexecuted tasks (`replace_unexecuted=True`) while verifying the composite graph remains a valid, cycle-free DAG before execution.
  3. *Closed-Loop Replanning Node (`replan_node`):* Integrate dynamic replanning as a first-class LangGraph node. When verification identifies structural impediments, route to `replan_node` to update remaining workflow tasks.
  4. *Budget Ceiling & Guardrails (2-Replan Limit):* Restrict executions to a strict maximum of 2 replan iterations enforced centrally via `BudgetGovernor.record_replan(db, execution_id)`. Exceeding this limit halts replanning and cleanly transitions the workflow to its terminal state.
  5. *Persistence & REST API:* Add `project_goals` table with progress tracking, link executions via `workflow_executions.goal_id`, and track iterations via `replan_count`. Expose goal CRUD endpoints (`/api/v1/projects/{project_id}/goals`), goal execution trigger (`/execute`), and an authenticated manual replanning endpoint (`/api/v1/executions/{execution_id}/replan`).
- **Consequences:** Eliminates static template limitations; supports arbitrary non-standard workflows; protects completed work from rollback or overwriting; prevents infinite replanning loops with strict budget bounding; provides comprehensive relational and API visibility for goal-driven pipelines.

## ADR-020: Repository Context & Git Worktree Sandboxing (M1.4-5)
- **Status:** Accepted
- **Context:** Prior versions executed agent tasks in arbitrary artifact storage directories disconnected from actual software repositories. Grounding agent development in real codebases requires scanning repository architectures and isolating file modifications to avoid contaminating the user's primary working tree.
- **Decision:**
  1. *Structural Repository Scanning (`RepoScanner`):* Implement a filesystem scanner that traverses repositories up to configurable depth while ignoring cache/vendor directories (`.git`, `node_modules`, `.venv`, `dist`, `storage`). Extract detected toolchains (Python, Node/TS, Rust, Go, Docker), entrypoints, and test directories into a compact markdown summary ($\le 1,500$ tokens) injected into planning prompts.
  2. *Ephemeral Git Worktree Isolation (`GitWorktreeManager`):* Create an isolated Git worktree under `storage/worktrees/<execution_id>` on branch `astrava/exec-<execution_id>` for each repository execution. Direct agent execution, deliverable writing, and deterministic verification tests into the worktree path.
  3. *Zero Working Tree Contamination:* Prevent changes from touching the main checkout. Provide auto-commit for completed tasks and generate standard git diffs and numstats against the project base branch.
  4. *Merge & Prune Lifecycle:* Expose an operator-authorized merge endpoint (`POST /executions/{id}/merge`) to integrate execution branches into base branches upon verification. Prune ephemeral worktrees cleanly via `git worktree remove --force` and `git worktree prune`.
  5. *Relational Persistence:* Add `repo_path` and `base_branch` to `projects` table; add `worktree_path` and `worktree_branch` to `workflow_executions` table via migration `6db676dd20fd`.
- **Consequences:** Eliminates scratch-directory disconnections; enables real-world codebase editing with full git provenance; guarantees complete isolation from developer workspaces; provides clean diff inspection and automated merge capabilities.

## ADR-021: Agent Capability Matching & Observability Metrics (M1.4-6)
- **Status:** Accepted
- **Context:** Prior versions hardcoded agent slug assignments in planning templates or relied on exact string matches. Autonomous intelligence requires matching dynamically synthesized tasks to the best-suited agent personas based on declared capabilities, along with observability into agent reliability, remediation frequency, and cost efficiency.
- **Decision:**
  1. *Task Capability Schema (`PlannedTask.required_capabilities`):* Enable tasks to declare required capability tags (e.g., `["database_migrations", "code_implementation"]`, `["automated_testing"]`).
  2. *Heuristic Capability Matcher (`CapabilityMatcher`):* Compute tag intersection and studio weighting between task requirements and the registered agent repository (`Agent.capabilities`). Dispatch tasks to the highest-scoring available agent with graceful fallback to defaults.
  3. *Agent Performance Observability (`AgentMetricsService`):* Query relational tables (`tasks`, `model_executions`) to aggregate per-agent success rates, remediation frequency, total tokens, financial cost, and average execution latency.
  4. *REST Endpoints & UI Visualization:* Expose `GET /api/v1/agents/metrics` and `GET /api/v1/agents/{slug}/metrics`. Render live performance KPI cards directly on `AgentsPage.tsx`.
- **Consequences:** Eliminates hardcoded agent bindings; routes tasks based on capabilities; enables data-driven agent selection and continuous performance observability.

## ADR-022: Frontend Autonomous Intelligence Experience (M1.4-7)
- **Status:** Accepted
- **Context:** Delivering end-to-end autonomous intelligence requires operators to formulate high-level project goals, monitor multi-wave dynamic executions, inspect ephemeral Git worktree modifications, and review unified diffs before merging.
- **Decision:**
  1. *Strategic Goals Dashboard (`GoalsPage.tsx`):* Provide a comprehensive interface for defining, tracking, and executing `ProjectGoal` entities. Render goal status badges (`pending`, `in_progress`, `achieved`, `paused`, `cancelled`), target acceptance criteria checklists, and visual progress meters. Trigger dynamic goal decomposition and execution with 1-click execution dispatch.
  2. *Navigation & Sidebar Integration:* Add `/goals` navigation item with `Target` icon across desktop and mobile menus.
  3. *Worktree Sandboxing & Git Diff Viewer (`ExecutionsPage.tsx`):* Add Worktree Sandboxing card to the execution drawer showing the active branch (`astrava/exec-<id>`) and worktree path. Provide an interactive "Inspect Git Diff" viewer rendering changed files, insertions/deletions stats, and unified patch syntax.
  4. *Operator Merge Trigger:* Enable authenticated operators to trigger `merge_worktree` directly from the UI, committing and merging changes cleanly into the project's base branch with real-time feedback.
  5. *Test Suite Expansion:* Add `frontend/src/__tests__/GoalsPage.test.tsx` verifying goal rendering, status filtering, modal creation, and execution triggers.
- **Consequences:** Unifies autonomous intelligence capabilities into an intuitive operator console; provides real-time visibility into goal progress and code changes; guarantees safe, sandboxed code modification with human operator merge control.

## ADR-023: V1.4 Next-Generation Autonomous Intelligence Baseline & Delivery Freeze (M1.4-8)
- **Status:** Accepted
- **Context:** Following completion of milestones M1.4-1 through M1.4-7, comprehensive end-to-end acceptance testing, regression suites, and multi-process crash verification were required to ensure the entire V1.4 Next-Generation Autonomous Intelligence platform operates with deterministic reliability, resource boundedness, and zero regressions.
- **Decision:**
  1. *End-to-End Acceptance Suite (`test_v1_4_e2e_acceptance.py`):* Implement full lifecycle empirical verification proving:
     - Real Git repository initialization, structural scan with toolchain discovery, project goal creation, autonomous goal execution, ephemeral worktree sandboxing (`astrava/exec-<id>`), initial defect detection, closed-loop remediation (`remediation_node`) with self-correction, worktree branch commit, SHA-256 fingerprint deduplication on knowledge ingestion, diff inspection (`diff_text`), operator merge to `main`, and goal progress reaching 100% `achieved`.
     - Bounded remediation turn limit (`max_remediation_turns`) halting runaway pipelines cleanly with `BudgetExhaustedError` and `status = 'exhausted'`.
     - Multi-process recovery and zombie lease reclamation: expired leases reclaimed upon resume; stale worker reconciliation rejected with `ReservationNotFoundError`; invalid fencing token rejected with `FencingTokenMismatchError`.
     - Concurrent memory fingerprint deduplication: PostgreSQL partial unique index `uix_project_memories_active_fingerprint` raises `IntegrityError` on concurrent duplicate active fingerprint ingestion.
  2. *Verification Evidence:* 191/191 backend pytest tests passing; 20/20 frontend vitest tests passing; zero TypeScript compilation errors; clean Vite production build.
  3. *Delivery Freeze:* Declare ASTRAVA V1.4 complete and freeze the repository baseline.
- **Consequences:** Formally delivers all V1.4 capabilities, resolves all architectural risks (TR-01 through TR-07), and establishes a certified, frozen baseline for production deployment and future development.

## ADR-024: V1.5 M1.5-1a Operator Authentication & Audit Identity
- **Status:** Accepted (implemented; see `docs/V1_5_M1_5_1A_ACCEPTANCE_REPORT.md`)
- **Context:** The V1.5 plan gives the API process access to a container runtime, which makes API compromise far more severe. At V1.4, 16 of 33 mutating routes and all GET routes were unauthenticated, an unset `OPERATOR_API_KEY` trusted every caller, the audit actor could come from a client header, and the server defaulted to `0.0.0.0` with `DEBUG=true` (SD-01, SD-05, SD-08).
- **Decision:**
  1. *Default-deny global dependency* instead of per-endpoint opt-in; six explicit public routes.
  2. *Two modes:* keyed (Bearer/key header/session cookie) and local-dev (key unset; loopback peer, allowlisted Host, no forwarding headers). No `APP_ENV`-based bypass; tests extend `ALLOWED_HOSTS` only.
  3. *Fail closed at startup* for blank/short keys, non-loopback bind without a key, DEBUG or wildcard origins/hosts on non-loopback; plus request-time guards because uvicorn's `--host` is invisible to the app.
  4. *Stateless signed session cookie* (HMAC key derived from the operator key; HttpOnly, SameSite=Strict, Secure by rule) with derived per-session CSRF tokens, Origin checks and JSON-only unsafe requests. Chosen over a DB-backed session table to avoid a migration in this milestone; in-memory revocation is a documented limitation.
  5. *Server-derived identity only;* `actor_type` distinguishes `operator` from `operator_local_dev`; legacy identity body fields must match the server or get `403`.
  6. *Secure defaults:* `APP_HOST=127.0.0.1`, `DEBUG=false`, docs only in DEBUG.
- **Consequences:** Closes SD-01, SD-05, SD-08 and unblocks M1.5-2 from the authentication standpoint. Existing clients must authenticate or run on loopback; the frontend gained a login flow. Single shared operator key remains (no RBAC). Residual risks are listed in `docs/SECURITY.md` section 8.

## ADR-025: V1.5 M1.5-0 Reduced Decision Record and M1.5-1a Acceptance
- **Status:** Accepted (documentation only)
- **Context:** M1.5-1a was delivered at `02edb00` and re-verified. The original M1.5-0 included credential and model-availability experiments that the operator has not authorized (Anthropic Consumer Terms section 3.7; no billable calls).
- **Decision:** (1) Accept M1.5-1a at `02edb00` and preserve its residual risks (in-memory session revocation, shared operator key, failed logins not audited as rows, `is_authorized_verifier` always true for an authenticated operator, 404/405 route disclosure, DEBUG docs routes on loopback). (2) Perform only the documentation part of M1.5-0: Docker Desktop installed and operational; Docker is the initial `WorkerRuntime` target behind the abstraction; pinned baseline worker images; controlled dependency preparation; no package-index access from task workers; mandatory fail-closed behavior with no host fallback and no unsafe mode; no Docker socket, host HOME or unrestricted credential mounts in workers; subscription OAuth injection prohibited; no billable API calls without separate authorization. (3) D1 stays blocked and D5 unverified; subscription authentication is not claimed to be feasible. (4) Update the dependency graph through an appended amendment instead of rewriting the planning baseline.
- **Consequences:** M1.5-4a, and through it M1.5-4/5/6, are blocked until an approved provider authentication arrangement exists; M1.5-1b, 1c, 2, 3 and 3b can proceed in dependency order with operator approval. Full record: `docs/V1_5_M1_5_0_DECISION_RECORD.md`.

## ADR-026: V1.5 M1.5-1b Path Containment, Artifact Ownership and Fail-Closed Execution Setup
- **Status:** Accepted (implemented; see `docs/V1_5_M1_5_1B_ACCEPTANCE_REPORT.md`)
- **Context:** Source inspection found that planner-supplied artifact names were written relative to the work directory without containment, repository binding was unvalidated, merges ignored the target branch, and every setup failure silently fell back to a non-isolated directory (SD-02, SD-06).
- **Decision:** (1) One path-security module with canonical symlink-resolving containment, a `.git` component ban and Unicode/NFKC hardening, used by every path that comes from a client, an LLM or the database. (2) Artifact registration checks project/execution/task ownership and confinement to the project's directory and writes provenance on the server. (3) `ALLOWED_REPO_ROOTS` allowlist, default empty (fail closed); ref names by allowlist; no `HEAD` fallback. (4) `merge_worktree` merges only into the checked-out target on a clean tree and never switches branches. (5) Execution setup fails closed: `ExecutionSetupError` ends the execution `FAILED` before any provider call, with no work-dir fallback and no leftover budget. (6) ASTRAVA's own git calls run with a sanitized environment, no hooks, no fsmonitor, no external diff or textconv. (7) Worktree artifacts are hashed and tagged `location: "worktree"` rather than copied.
- **Consequences:** Closes SD-02 and SD-06. Operators must configure `ALLOWED_REPO_ROOTS` before repositories execute. TOCTOU on intermediate directories and host-side repository parsing remain until sandboxing (M1.5-4).


## ADR-027: V1.5 M1.5-1c Execution Lease, Epoch Fencing and Database-Based Recovery
- **Status:** Accepted (implemented; see `docs/V1_5_M1_5_1C_ACCEPTANCE_REPORT.md`)
- **Context:** There is no LangGraph checkpointer and no recovery entry point; `resume_pipeline` only handled approvals. A killed process left the execution RUNNING forever, held reservations ACTIVE, reused the dead worker's fence token on re-reserve, and the retry loop mis-numbered attempts after a restart.
- **Decision:** (1) Per-execution lease with a monotonic `run_epoch` claimed by one atomic UPDATE, heartbeat from a background task, all state writes fenced on the epoch; (2) recovery force-expires the dead epoch's ACTIVE reservations exactly once; (3) retry loop continues from the dispatched attempt number; (4) terminal executions never reopen; (5) checkpoint initial state and remediation/replan, rebuild dispatch/verify from settled reservations; (6) recovery is explicit (CLI), not automatic; (7) no LangGraph checkpointer and no new infrastructure.
- **Consequences:** Closes SD-03 and SD-04. Provider invocation after a crash is at-least-once. One migration (3 columns). Lease TTL is configurable (`EXECUTION_LEASE_TTL_SECONDS`, default 60).

## ADR-028: V1.5 M1.5-2 Privilege-Separated Worker Broker (PROPOSED, not accepted)
- **Status:** Proposed (planning only; awaiting operator approval)
- **Context:** The baseline plan let the API process drive Docker. Docker daemon access is root-equivalent in the Docker VM and reaches shared host paths; the operator rejected unrestricted Docker access from the API. On this host the Docker socket is owned by the operator's own macOS user.
- **Decision (proposed):** (1) A separate Worker Broker is the only Docker client; (2) the API reaches it through a closed nine-operation typed contract over a Unix domain socket, with no field able to carry an image, command, mount, network, capability or Docker option, and no generic proxy; (3) containers are built from constants plus enumerated bounded profiles, with no bind mounts; (4) results leave workers as a strictly filtered tree export and the control plane creates the commit; (5) tier A (same user) is dev-only and not a boundary against API code execution, tier B (separate OS user) is required for any wider use; (6) sequence 2a (no Docker) -> 2b -> 2c, each separately authorized.
- **Consequences:** Closes the "API has Docker access" risk by construction in tier B and removes confused-deputy paths in tier A. Adds a privileged component to review. Docker Desktop on macOS remains a partial boundary. D1 and D5 are untouched. See `V1_5_M1_5_2_ARCHITECTURE_REASSESSMENT.md`.
