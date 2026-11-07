# ASTRAVA

> **"From vision to execution."**

ASTRAVA is an enterprise-grade AI creation and orchestration platform engineered to transform high-level objectives into functioning digital products, software businesses, and high-impact media content.

---

## Key Capabilities

- **Two Core Production Studios:**
  - **ASTRAVA SaaS:** Market research, PRD generation, modular system architecture, database design, software development, deterministic QA, and deployment preparation.
  - **ASTRAVA Media:** Content strategy, audience persona research, scene-by-scene scriptwriting, visual storyboards, SEO optimization, and publishing manifests.
- **Stateful Workflow Engine:** LangGraph-powered execution with PostgreSQL checkpoint persistence, multi-step dependency graphs, and human-in-the-loop governance.
- **Provider Adapters:** Subprocess execution adapter for **Claude Code CLI** using **Claude Haiku 5.5** (`claude-haiku-5-5`), with argument array safety, secret redaction, isolated project sandboxes, and granular token/cost audit logs.
- **Deterministic Verification Engine:** Python syntax checks, linting, automated unit tests, and workspace Git diff collection before registering deliverables.
- **Controlled Artifact Management:** Filesystem storage sandboxed per project with path traversal protection, syntax preview, and direct download capabilities.
- **Enterprise Visual Identity:** Clean letter A geometric SVG monogram, light/dark themes, Inter & JetBrains Mono typography, Midnight Navy, Slate Blue, and Electric Blue palette.

---

## System Architecture

```mermaid
flowchart TD
    User["Operator / User"] --> UI["ASTRAVA Enterprise Dashboard (React 19, TypeScript, Tailwind v4)"]
    UI --> API["FastAPI Modular Monolith (Python 3.12, Pydantic v2)"]

    subgraph Core Engine ["ASTRAVA Core Engine"]
        API --> Orchestrator["Orchestration Engine (LangGraph)"]
        API --> ApprovalEngine["Human Governance Engine"]
        API --> VerificationEngine["Deterministic Verification Engine"]
        API --> ArtifactManager["Sandboxed Artifact Manager"]
        API --> UsageTracker["Telemetry & Audit Tracker"]

        Orchestrator --> TaskDispatcher["Task Dispatcher"]
        Orchestrator --> StateStore[(PostgreSQL 16 Persistence)]
    end

    subgraph Provider Layer ["Execution Layer"]
        TaskDispatcher --> ClaudeCLI["Claude Code CLI (claude-haiku-5-5)"]
        TaskDispatcher --> AgyCLI["Antigravity CLI (Gemini)"]
    end

    subgraph Storage ["Persistent Storage"]
        ArtifactManager --> LocalStorage["storage/artifacts/<project_id>/"]
    end
```

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **Backend** | Python 3.12, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2.0 (asyncio), Alembic, LangGraph, asyncpg, psycopg, Ruff, Pytest |
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS v4, Lucide Icons, TanStack Query |
| **AI Providers** | Claude Code CLI 2.1.314 (`claude --model haiku`), Antigravity CLI 1.4.12 |
| **Database** | PostgreSQL 16 Alpine via Docker Compose (Port 5433) |
| **Storage** | Sandboxed local filesystem (`storage/artifacts/`) with traversal protection |

---

## Local Setup & Quickstart

### Prerequisites
- Python 3.12+ (installed or managed via `uv`)
- Node.js 20+ and npm 10+
- Docker & Docker Compose
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) authenticated via `claude auth`

### 1. Start Persistent Database
```bash
docker compose up -d
```
*Note: Exposes PostgreSQL on port `5433` to prevent any conflict with existing host services.*

### 2. Backend Setup & Startup
```bash
cd backend
uv sync
uv run alembic upgrade head
uv run pytest
uv run python -m app.serve        # validates security config, binds APP_HOST:APP_PORT (127.0.0.1:8000)
# or, for hot reload during development (keep the host on loopback):
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Interactive API docs (`http://localhost:8000/docs`) exist only when `DEBUG=true`.

**Authentication (M1.5-1a).** Leave `OPERATOR_API_KEY` unset for local development: the API serves only loopback clients and the UI needs no login. To require sign-in (or to bind beyond loopback) set a 32+ character `OPERATOR_API_KEY`; the dashboard then shows a login screen and uses an HttpOnly session cookie. The key is never exposed to frontend JavaScript. Full model, deployment rules and residual risks: [`docs/SECURITY.md`](docs/SECURITY.md).

### 3. Frontend Setup & Startup
```bash
cd frontend
npm install
npm run build
npm run dev
```
Dashboard is accessible at: `http://localhost:3000` (or `http://localhost:5173`)

---

## Environment Variables Reference

| Variable | Default Value | Description |
|---|---|---|
| `APP_NAME` | `ASTRAVA` | Application name |
| `APP_ENV` | `development` | Runtime environment (`development`, `test`, `production`) |
| `APP_HOST` | `127.0.0.1` | Bind host. Non-loopback requires `OPERATOR_API_KEY` and `DEBUG=false` |
| `DEBUG` | `false` | Enables OpenAPI docs and verbose logging (refused on non-loopback hosts) |
| `OPERATOR_API_KEY` | *(unset)* | Operator credential, 32+ chars. Unset = local-dev mode (loopback only). Never set to blank |
| `ALLOWED_HOSTS` | `["localhost","127.0.0.1","[::1]","::1"]` | Accepted `Host` header names (port ignored) |
| `SESSION_TTL_SECONDS` | `28800` | Browser session lifetime |
| `COOKIE_SECURE` | auto | Force the `Secure` cookie flag (auto: HTTPS or non-loopback host) |
| `DATABASE_URL` | `postgresql+asyncpg://astrava:astrava_dev_password@localhost:5433/astrava` | Async database connection URL |
| `DATABASE_URL_SYNC` | `postgresql://astrava:astrava_dev_password@localhost:5433/astrava` | Sync connection URL for Alembic migrations |
| `ARTIFACT_STORAGE_PATH` | `./storage/artifacts` | Path for sandboxed deliverables |
| `CLAUDE_CLI_PATH` | `claude` | Path to Claude Code executable |
| `DEFAULT_CLAUDE_MODEL` | `haiku` | Claude model alias (resolves to `claude-haiku-5-5`) |
| `CLAUDE_EXECUTION_TIMEOUT_SECONDS` | `180` | Process execution timeout |

---

## Project Structure

```
astrava/
├── docker-compose.yml          # PostgreSQL 16 service
├── docs/                       # Engineering documentation
│   ├── ARCHITECTURE.md         # Full architectural specifications
│   ├── ROADMAP.md              # Milestones & delivery roadmap
│   ├── DECISIONS.md            # Architecture Decision Records (ADRs)
│   ├── PROGRESS.md             # Task completion matrix
│   ├── EXECUTION_LOG.md        # Persistent development journal
│   ├── API.md                  # REST API reference
│   ├── PROVIDERS.md            # CLI provider protocols & security
│   ├── V1_1_AUDIT.md           # Independent baseline & security audit
│   └── V1_1_RELEASE_REPORT.md  # V1.1 Release & hardening verification
├── backend/
│   ├── alembic/                # Relational database migrations
│   ├── app/
│   │   ├── api/v1/             # Endpoints (Projects, Tasks, Executions, Approvals, Artifacts, Intelligence, Orchestrator)
│   │   ├── db/                 # Async session & declarative Base
│   │   ├── models/             # SQLAlchemy 2.0 domain entities
│   │   ├── orchestrator/       # LangGraph state graph, runner & planner
│   │   ├── providers/          # Claude Code CLI Haiku 5.5 provider adapter
│   │   ├── schemas/            # Pydantic v2 schemas
│   │   ├── services/           # Async domain service layer
│   │   └── verification/       # Deterministic verification runner
│   └── tests/                  # Pytest test suite (20 tests, 100% passing)
├── frontend/
│   ├── src/
│   │   ├── __tests__/          # Vitest & Testing Library automated tests (4 test suites)
│   │   ├── api/                # API client connected to backend
│   │   ├── components/         # Logo, Sidebar, Header, Modals
│   │   ├── context/            # Light/Dark Theme Context & hook
│   │   ├── pages/              # Overview, Command Center, Projects, Executions, Artifacts, Approvals, Intelligence, Settings
│   │   └── types/              # TypeScript interface definitions
└── storage/
    └── artifacts/              # Sandboxed deliverables storage
```

---

## Verification & Quality Assurance

- **Backend Tests:** `uv run pytest` -> 20 passing tests across domain APIs, orchestrator graphs, provider adapters, input validation boundaries, and crash recovery.
- **Backend Linting:** `uv run ruff check .` -> Zero lint errors; 54 files formatted.
- **Frontend Tests:** `npm test` -> 4 automated test suites (ThemeContext, Sidebar, CommandCenter, App) running on Vitest + React Testing Library.
- **Frontend Linter:** `npm run lint` -> 0 warnings and 0 errors via Oxlint across 24 files.
- **Frontend Build:** `npm run build` -> Clean TypeScript compilation and Vite production build in < 100ms.
- **Live Provider Proof:** Validated against live Claude Code CLI with `claude-haiku-5-5` resolving exit code 0, duration, and token usage metrics.
- **Reliability Audit:** Zero duplicate entities on pipeline resumption; unbounded concurrency eliminated; process group cleanup on shutdown.
