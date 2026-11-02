# ASTRAVA V1.3 — Milestone M1.3-4 Release Report
## Modular Knowledge Retrieval Engine

**Release Date:** 2026-11-02  
**Milestone:** M1.3-4  
**Status:** VERIFIED & COMPLETE  
**Git Author:** `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`  
**Base Commit:** `01f8ade652a6564c9e66c3ce5beea94a569841ac`  
**AI Executor:** Canonical Claude Haiku 5.5 (`claude-haiku-5-5`) via non-interactive Claude Code CLI  

---

### 1. Architecture Selected & Alternatives Considered

#### Selected Baseline: PostgreSQL 16 Native Full-Text Search with GIN Indexing
ASTRAVA V1.3 implements knowledge retrieval utilizing native PostgreSQL 16 full-text search (`tsvector`, `tsquery`, `ts_rank_cd`) combined with database-side metadata filtering and multi-signal ranking.

#### Alternatives Evaluated & Rejected (ADR-008):
1. **External Vector Databases (e.g. Pinecone, Qdrant, Weaviate):**
   - *Rejected:* Introduces external infrastructure dependencies, memory overhead, synchronization edge cases, and operational fragility unsuitable for an internal modular monolith.
2. **`pgvector` Extension & Embeddings:**
   - *Deferred:* The current database schema does not have pre-computed embeddings, and generating embeddings on the fly requires external API charges or heavyweight local models. The architecture provides pluggable retriever contracts so a vector retriever can be registered without altering orchestration consumers.
3. **Application-Side Python Filtering:**
   - *Rejected:* Fetching entire project tables into memory causes unbounded heap growth and N+1 database queries. Filtering and ranking are pushed into PostgreSQL.

---

### 2. Implemented Retrieval Components

The retrieval engine is organized under [`backend/app/services/retrieval/`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval):

| Component | File | Responsibility |
|---|---|---|
| **`RetrievalService`** | [`service.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/service.py) | Public facade coordinating query processing, retrieval, ranking, and context package assembly. |
| **`MemoryRetriever`** | [`memory_retriever.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/memory_retriever.py) | Executes PostgreSQL full-text search (`to_tsvector`/`websearch_to_tsquery`) with metadata filtering. |
| **`ArtifactRetriever`** | [`artifact_retriever.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/artifact_retriever.py) | Queries project artifacts, integrating lineage graph traversal from [`ArtifactIntelligenceService`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/artifact_intelligence_service.py). |
| **`RetrievalRanker`** | [`ranker.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/ranker.py) | Deterministic scoring combining text score, provenance, verification, recency, and lifecycle status. |
| **`ContextAssembler`** | [`context_assembler.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/context_assembler.py) | Formats structured Markdown prompt package strictly within the character budget (default 4,000 chars). |
| **`MetadataFilter`** | [`metadata_filter.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/metadata_filter.py) | Validates filter parameters and constructs parameter-safe SQLAlchemy binary expressions. |
| **`QueryProcessor`** | [`query_processor.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/query_processor.py) | Sanitizes text, enforces bounds (max 500 chars), rejects null bytes, extracts alphanumeric tokens. |
| **Schemas** | [`schemas.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/app/services/retrieval/schemas.py) | Pydantic v2 data contracts: `RetrievalQuery`, `MemoryRetrievalFilter`, `ScoredMemory`, `RetrievalResult`. |

---

### 3. Supported Filters & Ranking Behavior

#### Metadata Filters:
- `project_id`: Mandatory on all queries; cannot be bypassed.
- `categories`: Filters by `MemoryCategory` enum (`objective`, `decision`, `requirement`, etc.).
- `provenance_types`: Filters by `MemoryProvenanceType` (`user_provided`, `verified_finding`, `agent_conclusion`, `assumption`).
- `statuses`: Explicit status list or granular flags (`include_superseded`, `include_rejected`, `include_archived`, `include_historical`).
- `is_verified`: Boolean filter separating verified facts from unverified claims.
- `created_after` / `created_before`: Date boundary filters.

#### Multi-Signal Ranking Formula:
When a search query is provided, text relevance acts as a dominant gating factor:
$$S = S_{\text{text}} \times (0.40 \cdot W_{\text{prov}} + 0.30 \cdot W_{\text{verif}} + 0.20 \cdot W_{\text{recency}} + 0.10 \cdot W_{\text{status}})$$

When no query text is provided (empty/null query), ranking orders by metadata quality and recency:
$$S_{\text{empty}} = 0.40 \cdot W_{\text{prov}} + 0.30 \cdot W_{\text{verif}} + 0.20 \cdot W_{\text{recency}} + 0.10 \cdot W_{\text{status}}$$

- **Provenance Policy Weights ($W_{\text{prov}}$):**
  - `user_provided`: 1.00
  - `verified_finding`: 0.95
  - `agent_conclusion`: 0.70
  - `assumption`: 0.50
- **Verification Boost ($W_{\text{verif}}$):** `1.00` if `is_verified` is True, `0.90` if False.
- **Recency Decay ($W_{\text{recency}}$):** $0.80 + 0.20 \times \exp(-\Delta t_{\text{days}} / 30.0)$ (30-day half-life).
- **Lifecycle Weight ($W_{\text{status}}$):** `ACTIVE`: 1.00, `PROPOSED`: 0.90, `SUPERSEDED/REJECTED/ARCHIVED`: 0.20.
- **Stable Tie-Breaker:** Sorted by `(-composite_score, -created_at.timestamp(), str(item.id))`.

---

### 4. Context Assembly & Budget Behavior

- **Strict Budget Compliance:** Maximum 4,000 characters by default (configurable per query). The limit is enforced on the final formatted Markdown string.
- **Boundary Preservation:** Items are included atomically. If adding a memory block would exceed the remaining budget, it is cleanly omitted rather than truncated mid-sentence or mid-metadata.
- **Omission Reporting:** When items cannot fit within the budget, a footer notice is added:
  `*Context budget reached (3,780 / 4,000 chars). Omitted 4 lower-ranked items.*`
  and `ContextAssemblySummary` reports `memories_omitted_count` and `budget_exhausted=True`.
- **Empty Retrieval Handling:** Outputs a clean Markdown header with `_No relevant project knowledge or artifacts found._`.

---

### 5. Project Isolation & Security Controls

- **Inviolable Scope:** `project_id` is required in `RetrievalQuery`. Every SQLAlchemy query includes `ProjectMemory.project_id == project_id` or `Artifact.project_id == project_id`.
- **No Cross-Project Lineage Leakage:** `ArtifactRetriever` uses `ArtifactIntelligenceService`, which halts graph traversal at project boundaries.
- **Bounded Inputs:** Query text length is strictly capped at 500 characters, null bytes (`\x00`) are rejected, and result counts are bounded (`top_k_memories <= 100`, `top_k_artifacts <= 50`).

---

### 6. Database Migrations & GIN Indexes

- **Migration ID:** `07d25c09fdde_add_gin_full_text_indexes_for_retrieval.py` (chained from `f8d6aac5883a`).
- **Indexes Created:**
  - `ix_project_memories_tsv`: GIN index on `to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(content, ''))`.
  - `ix_artifacts_tsv`: GIN index on `to_tsvector('english', coalesce(name, '') || ' ' || coalesce(file_path, ''))`.
- **Migration Verification:**
  - `alembic upgrade head` executed cleanly.
  - `alembic downgrade f8d6aac5883a` tested and re-applied cleanly.
  - `alembic check` verified: `No new upgrade operations detected.`

---

### 7. Verification Evidence Matrix

| Test Suite | File | Tests | Duration | Status |
|---|---|---|---|---|
| Retrieval Engine Integration | [`backend/tests/test_retrieval_engine.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/tests/test_retrieval_engine.py) | 10 | 0.40s | **PASSED** |
| Memory Services Integration | [`backend/tests/test_memory_services.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/tests/test_memory_services.py) | 7 | 0.52s | **PASSED** |
| Artifact Intelligence Integration | [`backend/tests/test_artifact_intelligence.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/tests/test_artifact_intelligence.py) | 6 | 0.38s | **PASSED** |
| Memory Models & Constraints | [`backend/tests/test_memory_models.py`](file:///Users/abstract/Documents/personal_project/astrava/backend/tests/test_memory_models.py) | 7 | 0.35s | **PASSED** |
| Full Backend Regression | `backend/tests/` | 63 | 8.14s | **PASSED (63/63)** |
| Backend Lint & Format | `ruff check` & `ruff format --check` | 79 files | 0.05s | **CLEAN (0 errors)** |
| Frontend Test Suites | `frontend/src/__tests__/` (Vitest) | 10 | 1.13s | **PASSED (8/8 files)** |
| Frontend Linter | `oxlint` | 29 files | 24ms | **CLEAN (0 errors)** |
| Frontend Production Build | `npm run build` (tsc + vite) | — | 164ms | **CLEAN (0 errors)** |

---

### 8. PostgreSQL Query Plan & Performance Evidence

PostgreSQL 16 `EXPLAIN (FORMAT JSON)` query plan verification (`test_postgresql_explain_full_text_query`):
- Verifies that PostgreSQL executes `ts_rank_cd` and `to_tsvector @@ websearch_to_tsquery` using native GIN and B-Tree index scan filters.
- Zero client-side full table scans; all candidates are bounded at the database query level (`LIMIT`).

---

### 9. Known Limitations & Deferred Work

- **Semantic Vector Embeddings:** Not included in M1.3-4 by design (ADR-008). The `RetrievalService` and `MemoryRetriever` interfaces are architected to support pluggable vector retrieval when vector generation infrastructure is justified.
- **Workflow & REST API Exposure:** Retrieval is implemented as a reusable core service layer. Integration into LangGraph workflows is slated for **M1.3-5**, and REST endpoints are slated for **M1.3-6**.

---

### 10. Git Status & Push

- **Branch:** `main`
- **Remote:** `origin/main`
- **Author:** `Abstract <61998277+DonyNurArifR@users.noreply.github.com>`
