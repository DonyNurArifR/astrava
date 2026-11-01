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
