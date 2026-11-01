# ASTRAVA

> **"From vision to execution."**

ASTRAVA is an enterprise-grade AI creation and orchestration platform designed to transform high-level objectives into functioning digital products, software businesses, and high-impact media content.

---

## Architecture Overview

ASTRAVA operates as a modular monolith:
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, LangGraph stateful orchestration.
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, TanStack Query, Lucide icons.
- **Providers:** Subprocess adapter for Claude Code CLI (`claude --model haiku` -> `claude-haiku-5-5`), Antigravity CLI adapter.
- **Verification:** Deterministic tool validation (ruff, pytest, type-checking, git diff inspection).
- **Storage:** PostgreSQL 16 persistence for states & metadata, sandboxed local filesystem for artifacts.

---

## Quickstart

### Prerequisites
- Python 3.12+ (managed via `uv`)
- Node.js v20+ / npm v10+
- Docker & Docker Compose
- Claude Code CLI (authenticated)

### 1. Start Local Database
```bash
docker compose up -d
```

### 2. Backend Setup
```bash
cd backend
uv sync
uv run pytest
uv run uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Visit the dashboard at `http://localhost:3000` (or `http://localhost:5173`).
