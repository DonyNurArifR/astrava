# ASTRAVA — instructions for all agents

Start every session, and every recovery, by reading `AGENT_PROTOCOL.md`, then `AGENT_STATE.md`, then the tail of `EXECUTION_LOG.md`. Git (`git rev-parse HEAD`, `git status`) outranks any document. If the checkpoint commit in `AGENT_STATE.md` differs from `HEAD`, stop and run the recovery procedure (protocol section 6) before acting.

- **Claude orchestrator** (`astrava_orchestrator`): owns execution, integration, testing, delivery and the authoritative `AGENT_STATE.md`.
- **Agy / Antigravity** (`astrava_planner`): planning, architecture research and independent review. Report findings directly to the Claude orchestrator through Herdr; write only the files and sections your assignment names (your checkpoint lives between the `AGY-CHECKPOINT` markers in `AGENT_STATE.md`; log events by appending to `EXECUTION_LOG.md`).
- **Claude Code executors** (`astrava_executor`): bounded implementation tasks only, within the files named in the task.

Rules for everyone: no commits or pushes without explicit operator approval; no secrets in any file; no scope beyond the approved milestone; no completion claims without verifiable evidence; never discard changes you did not make.
