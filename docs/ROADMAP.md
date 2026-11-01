# ASTRAVA Development Roadmap
**Version:** 1.0.0
**Product:** ASTRAVA — AI Creation and Orchestration Platform ("From vision to execution.")
**Current Phase:** M0 (Environment & Repository Inspection) -> M1 (Project Foundation)

---

## Milestones Summary

| Milestone | Title | Status | Description |
|---|---|---|---|
| **M0** | Environment & Repository Inspection | **COMPLETE** | Inspect environment, verify CLIs, test Claude Haiku 5.5, configure Git/GitHub identity & origin, establish docs. |
| **M1** | Project Foundation | **IN PROGRESS** | Backend (FastAPI, Python 3.12, uv, Pydantic v2), Frontend (React, Vite, TS, Tailwind CSS), Docker Compose, Postgres, Logging, Health checks. |
| **M2** | Domain & Database Schema | NOT STARTED | Workspaces, Projects, Tasks, Workflows, Executions, Approvals, Artifacts, Usage Records; SQLAlchemy 2.0 + Alembic migrations. |
| **M3** | Provider Integrations | NOT STARTED | Provider abstraction, Claude Code CLI adapter (`claude --model haiku`), subprocess execution safety, timeouts, structured output parsing. |
| **M4** | Orchestration Engine | NOT STARTED | LangGraph stateful graph execution, task scheduling, dependency resolution, checkpointing, pause/resume, retry policies. |
| **M5** | Approval & Verification | NOT STARTED | Human-in-the-loop interrupt/resume, deterministic verification engine (Ruff, pytest, typecheck, build, git diff). |
| **M6** | Artifact Management | NOT STARTED | Filesystem artifact storage, metadata registry, file preview, download API, path sandboxing. |
| **M7** | ASTRAVA Enterprise Dashboard | NOT STARTED | Overview, Command Center, Projects, Executions, Artifacts, Approvals, Intelligence, Settings (Light & Dark themes, Inter + JetBrains Mono). |
| **M8** | SaaS & Media Studios | NOT STARTED | Studio selection, studio-specific workflow & project templates (PRD, Competitor analysis vs Scriptwriting, Storyboards). |
| **M9** | End-to-End Integration & Proof | NOT STARTED | Full lifecycle test: Objective -> Plan -> Approval -> Haiku Execution -> Verification -> Diff & Artifacts -> Persistent history. Failure mode testing. |
| **M10** | Documentation & Delivery | NOT STARTED | README, Architecture, Setup Guide, Environment variables, Docker instructions, API reference, Security verification. |

---

## Detailed Task Breakdown

### M0 — Environment & Repository Inspection
- [x] M0-T1: Verify Git status, configure branch `main`, remote origin `https://github.com/DonyNurArifR/astrava.git`.
- [x] M0-T2: Configure local Git identity (`user.name "Abstract"`, `user.email "61998277+DonyNurArifR@users.noreply.github.com"`).
- [x] M0-T3: Verify GitHub authentication via `gh auth status` and user ID 61998277.
- [x] M0-T4: Inspect Python (3.12 via uv), Node (v22), Docker.
- [x] M0-T5: Inspect and test Claude Code CLI (`--model haiku` -> `claude-haiku-5-5` verification).
- [x] M0-T6: Initialize documentation (`docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/PROGRESS.md`, `docs/EXECUTION_LOG.md`).

### M1 — Project Foundation
- [ ] M1-T1: Setup `.gitignore` excluding secrets, `.env`, caches, local database files.
- [ ] M1-T2: Setup backend workspace structure with `uv` (FastAPI, SQLAlchemy 2, Pydantic v2, Alembic, Ruff).
- [ ] M1-T3: Setup frontend workspace structure with Vite + React + TypeScript + Tailwind CSS.
- [ ] M1-T4: Setup Docker Compose for local PostgreSQL and Redis/storage services.
- [ ] M1-T5: Implement backend configuration (`pydantic-settings`), structured logging, health check endpoints (`/healthz`, `/readyz`).
- [ ] M1-T6: Setup initial test harness (pytest, frontend test runner) and verify clean pass.
- [ ] M1-T7: Git commit initial verified foundation and push to origin `main`.

### M2 — Domain & Database Schema
- [ ] M2-T1: Design SQLAlchemy 2.0 declarative models (Workspaces, Projects, Tasks, Workflows, WorkflowExecutions, ExecutionEvents, Approvals, Artifacts, UsageRecords).
- [ ] M2-T2: Configure Alembic migrations and generate initial migration.
- [ ] M2-T3: Implement Repository and Service layer with CRUD operations.
- [ ] M2-T4: Write unit and integration tests for database operations.

### M3 — Provider Integrations
- [ ] M3-T1: Define abstract Provider interface (`BaseProvider`, execution request/response schemas).
- [ ] M3-T2: Implement `ClaudeCodeCLIProvider` supporting Haiku 5.5, argument arrays, timeout, working dir restriction, secret redaction, and output parsing.
- [ ] M3-T3: Implement token and execution duration tracking.
- [ ] M3-T4: Write tests for provider adapter with mock and live validation.

### M4 — Orchestration Engine
- [ ] M4-T1: Implement structured plan generation and validation schemas.
- [ ] M4-T2: Implement LangGraph workflow graph definition with task node dependencies.
- [ ] M4-T3: Implement checkpointing and state persistence in PostgreSQL.
- [ ] M4-T4: Implement retry logic and failure handling.
- [ ] M4-T5: Verify workflow execution, state transitions, and persistence.

### M5 — Approval & Verification Engine
- [ ] M5-T1: Implement Human-in-the-loop interrupt and resume mechanics in workflow.
- [ ] M5-T2: Implement deterministic verification runner (lint, test, build, diff capture).
- [ ] M5-T3: Implement Approval API endpoints (request, approve, reject).
- [ ] M5-T4: Write verification tests and approval flow tests.

### M6 — Artifact Management
- [ ] M6-T1: Implement local storage manager with strict path sandboxing.
- [ ] M6-T2: Implement Artifact registration service and API endpoints (list, get, preview, download).
- [ ] M6-T3: Test artifact persistence and boundary enforcement.

### M7 — ASTRAVA Enterprise Dashboard
- [ ] M7-T1: Build enterprise UI foundation (Inter & JetBrains Mono, Midnight Navy / Slate Blue / Electric Blue theme, Dark/Light modes).
- [ ] M7-T2: Implement SVG letter A monogram brand logo.
- [ ] M7-T3: Build layout with navigation (Overview, Command Center, Projects, Executions, Artifacts, Approvals, Intelligence, Settings).
- [ ] M7-T4: Connect all views to live backend API endpoints.
- [ ] M7-T5: Test UI build and verify no mock data is used.

### M8 — SaaS & Media Studios
- [ ] M8-T1: Implement studio selection and project templates for SaaS Studio (PRD, architecture, QA).
- [ ] M8-T2: Implement studio selection and project templates for Media Studio (Content strategy, scripts, storyboards).
- [ ] M8-T3: Expose studio endpoints and test end-to-end studio flows.

### M9 — End-to-End Integration & Proof
- [ ] M9-T1: Execute full lifecycle test (Objective -> Plan -> Approval -> Haiku Execution -> Verification -> Diff & Artifacts -> History).
- [ ] M9-T2: Test negative failure modes and resilience.

### M10 — Documentation & Delivery
- [ ] M10-T1: Create comprehensive README.md, ARCHITECTURE.md, setup guides, and API docs.
- [ ] M10-T2: Final verification, clean git tree, push to origin `main`, output delivery report.
