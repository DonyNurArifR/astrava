# ASTRAVA — Claude instructions

Read these before doing anything, every session and after every restart or interruption:
1. `AGENT_PROTOCOL.md` — checkpointing, recovery, coordination and git rules for every agent.
2. `AGENT_STATE.md` — current snapshot (branch, commit, milestone, in-progress work, exact next actions). Valid only while its checkpoint commit matches `git rev-parse HEAD`; otherwise run the recovery procedure (protocol section 6).
3. Tail of `EXECUTION_LOG.md` — what happened last.

Essentials:
- Claude owns execution, integration, testing and delivery and is accountable for verifying all delegated work. Agy (Antigravity, `astrava_planner`) plans and reviews; Claude Code executors do bounded tasks.
- Work only on the operator-approved milestone. Do not commit or push without explicit approval. Stage files by name; never stage `.claude/`, `.env`, credentials or build output.
- No paid API use, no OAuth-token minting or subscription-credential injection, no model substitution.
- Checkpoint (`AGENT_STATE.md` + `EXECUTION_LOG.md`) before delegating, after verifying results, after commits, and before handover.

Your user-level `~/.claude/CLAUDE.md` rules still apply in addition to this file.
