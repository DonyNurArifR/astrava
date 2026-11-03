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
