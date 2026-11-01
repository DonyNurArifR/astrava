# ASTRAVA V1.2.1 — INDEPENDENT ARCHITECTURAL & RELIABILITY AUDIT

**Date:** 2026-11-01  
**Auditor:** Gemini (Antigravity AI Lead Architect)  
**Baseline Commit:** `d713a21080786ae48f860ffe4466278278d43679`  
**Target Release:** V1.2.1 (Multi-Agent Reliability & Quality Assurance)

---

## 1. Executive Summary

ASTRAVA V1.2 introduced a foundational multi-agent architecture with an Agent Registry (16 agents across SaaS and Media studios), semantic objective understanding, and a topological workflow planner.

This independent audit investigates whether the multi-agent engine satisfies enterprise reliability, fault tolerance, and quality assurance under concurrent executions, partial stage interruptions, and failure scenarios.

### Summary of Audit Findings

| ID | Severity | Area | Description |
| :--- | :--- | :--- | :--- |
| **AUD-01** | **High** | DAG Validation | `PlannerService.validate_and_compute_stages` deduplicates task IDs into a `set` before cycle checking. Duplicate task IDs in a plan are misdiagnosed as circular dependencies rather than rejected explicitly. |
| **AUD-02** | **Critical** | Concurrency & Fault Recovery | When an independent task fails in a concurrent wave (`asyncio.gather`), `dispatch_task_node` terminates without registering completed sibling tasks into `completed_task_ids` or creating their artifacts, leaving successful sibling work unpersisted and requiring duplicate re-execution on retry. |
| **AUD-03** | **High** | Failure Policy & Bounded Retries | Tasks currently have zero automated retry capability on transient provider timeouts or malformed outputs. Agent `execution_config.max_retries` is unreferenced during execution. |
| **AUD-04** | **Medium** | Context Management | Upstream deliverable injection blindly slices string output at `:2500` characters without structure or source traceability. Failed prerequisite outputs can inadvertently be passed downstream if not filtered. |
| **AUD-05** | **High** | QA Verification Rigor | `VerificationEngine` checks syntax and git diffs, but does not execute actual test discovery/runners (e.g. `pytest`) or distinguish between semantic agent test plans and executed test command results. |
| **AUD-06** | **Medium** | Configuration Reproducibility | Agent system prompts and configurations are queried from static in-memory dictionaries rather than frozen immutable execution snapshots, meaning runtime modifications could alter downstream tasks in active workflows. |
| **AUD-07** | **Medium** | Frontend State Visibility | The Command Center and Executions views only expose coarse states (`pending`, `completed`, `failed`), omitting intermediate states (`running`, `retrying`, `verifying`, `blocked`, `awaiting_approval`) and concurrent execution indicators. |

---

## 2. Detailed Technical Investigation

### 2.1 DAG Planning & Validation (AUD-01)
- **Source Inspection:** `backend/app/orchestrator/planner.py:50`
  ```python
  task_ids = {t.task_id for t in tasks}
  in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
  ```
- **Vulnerability:** If an input plan contains duplicate task IDs (e.g. `[Task(id="a"), Task(id="a")]`), `len(task_ids) == 1 < len(tasks) == 2`. The loop over `queue` processes only 1 element, leaving `processed_count = 1 != 2`, triggering:
  `raise ValueError(f"Circular dependency detected involving tasks: {', '.join(unprocessed)}")`
- **Impact:** Misleading error diagnosis. Duplicate task identifiers must be checked before building adjacency lists and rejected explicitly.

### 2.2 Concurrent Wave Execution & Partial Failure Recovery (AUD-02)
- **Source Inspection:** `backend/app/orchestrator/workflow_graph.py:209-240`
  ```python
  results = await asyncio.gather(
      *[_execute_single_task(t, state, project_work_dir) for t in ready_tasks],
      return_exceptions=True,
  )
  ...
  return {
      "tasks": tasks,
      "usage_records": usage_list,
      "status": "failed" if any_failed else "running",
      "error": error_msg,
  }
  ```
- **Vulnerability:**
  1. In a wave with Tasks A and B running in parallel, suppose Task A completes successfully, but Task B fails.
  2. `any_failed` evaluates to `True`, so `dispatch_task_node` sets `status: "failed"`.
  3. LangGraph conditional edge `route_after_dispatch` checks `if state.get("status") == "failed": return "__end__"`.
  4. Execution skips `verify_node` and `artifact_node`.
  5. Task A is **never added** to `completed_task_ids`, its output artifact is **never registered**, and its completion is not recorded in the DB.
  6. Upon recovery or retry, Task A must run again from scratch, violating idempotency and generating duplicate costs.
- **Remediation:** `dispatch_task_node` must record state updates for all completed tasks in the wave. Completed sibling tasks must be safely verified and registered in `artifacts` and `completed_task_ids`. The failure status must only block downstream dependents of the failed task.

### 2.3 Bounded Retries & Error Handling (AUD-03)
- **Source Inspection:** `backend/app/models/agent.py:32` specifies `execution_config = {"timeout_seconds": 120, "max_retries": 1}`.
- **Vulnerability:** Neither `_execute_single_task` nor `dispatch_task_node` consults `max_retries`. Any transient Claude Code CLI error, timeout, or malformed JSON immediately terminates the task as failed.
- **Remediation:** Introduce an automated retry loop inside `_execute_single_task` bounded by `agent.execution_config.get("max_retries", 1)` with exponential backoff (e.g. 1s) and explicit retry event logging.

### 2.4 Context Management & Traceability (AUD-04)
- **Source Inspection:** `backend/app/orchestrator/workflow_graph.py:105-113`
  ```python
  for dep_id in task.get("dependencies", []):
      dep_task = task_lookup.get(dep_id, {})
      dep_title = dep_task.get("title", dep_id)
      dep_out = dep_task.get("output_text", "")
      if dep_out:
          upstream_context_blocks.append(
              f"=== Deliverable from [{dep_title}] ===\n{dep_out[:2500]}"
          )
  ```
- **Vulnerability:**
  1. Blind slicing `[:2500]` can slice mid-token or mid-JSON schema.
  2. If an upstream task failed, but has partial `output_text`, it could be passed as valid context. Only tasks in `completed_task_ids` should supply context.
  3. No record exists in task metadata or DB identifying which artifacts/upstream tasks were fed into the agent.
- **Remediation:** Add `used_context_sources` metadata (task ID, title, agent slug, size). Enforce that only `completed` tasks supply context. Bounded formatting with markdown headers and clean limits.

### 2.5 QA Verification Rigor (AUD-05)
- **Source Inspection:** `backend/app/verification/engine.py:113`
- **Vulnerability:** `VerificationEngine.verify_task` only runs `py_compile` syntax checks. It does not run automated tests (such as `pytest`), frontend build checks, or verify that expected output JSON files match schemas.
- **Remediation:** Extend `VerificationEngine` to execute actual test discovery when tests exist, validate JSON schema deliverables, record exit codes, stdout, and stderr, and distinguish between semantic reviews and deterministic test executions.

### 2.6 Agent Configuration Snapshots (AUD-06)
- **Source Inspection:** `backend/app/orchestrator/workflow_graph.py:20` references module-global `AGENT_MAP`.
- **Vulnerability:** If an agent definition is updated in PostgreSQL while a long-running execution is in progress, the execution environment becomes non-reproducible.
- **Remediation:** Capture an immutable `agent_snapshots` mapping in `state` at workflow start (`start_pipeline`). Use the snapshot during execution.

### 2.7 Frontend Execution Granularity (AUD-07)
- **Source Inspection:** `frontend/src/pages/CommandCenterPage.tsx:432`
- **Vulnerability:** Status pills only display `Completed`, `Failed`, `Awaiting Approval`, or `Pending`. Users cannot see when tasks are `Running (Parallel)`, `Retrying`, `Verifying`, or `Blocked`.
- **Remediation:** Expose granular task lifecycle states in the UI with distinct visual badges.

---

## 3. Remediation Roadmap

1. **Phase 1: DAG Execution Correctness**
   - Implement explicit duplicate task ID validation.
   - Guard against missing dependencies and circular graphs.
   - Refactor `dispatch_task_node` to update and preserve completed tasks even if a sibling task fails.
2. **Phase 2: Parallel Stage Crash & Interruption Recovery**
   - Build controlled multi-task parallel stage recovery test with PostgreSQL.
   - Verify that interrupted parallel waves resume only unfinished tasks while preserving already completed ones.
3. **Phase 3: Context Management & Traceability**
   - Structure upstream context, filter out non-completed tasks, add `used_context_sources` audit metadata.
4. **Phase 4: Agent Output Validation & Bounded Retries**
   - Add schema validation and bounded retries in `_execute_single_task`.
   - Enhance `VerificationEngine` for genuine test execution and deliverable verification.
5. **Phase 5: Agent Configuration Snapshotting**
   - Snapshot agent definitions into `state["agent_snapshots"]` on pipeline initialization.
6. **Phase 6: Frontend Execution Granularity**
   - Enhance CommandCenter and Execution pages with parallel wave indicators and task states.
7. **Phase 7: Live Multi-Agent End-to-End Proof**
   - Run complete SaaS and Media multi-agent workflows with live Claude Haiku CLI.
