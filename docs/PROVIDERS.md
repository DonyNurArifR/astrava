# ASTRAVA Provider Integrations & Safety Protocols

---

## 1. Verified Model Execution: Claude Code CLI (Haiku 5.5)

### CLI Identification & Syntax
- **Executable:** `claude` (CLI Version `2.1.314`)
- **Model Flag:** `--model haiku`
- **Canonical Model:** `claude-haiku-5-5`
- **Output Format:** `--output-format json`
- **Non-Interactive Mode:** `-p`

### Verification Proof
Live execution was verified against the active Claude subscription:
```json
{
  "duration_api_ms": 4618,
  "session_id": "85950cb3-e0df-47f4-b6bd-0b4161c9e791",
  "total_cost_usd": 0.00357584,
  "usage": {
    "input_tokens": 4,
    "cache_creation_input_tokens": 15828,
    "cache_read_input_tokens": 33684,
    "output_tokens": 146
  },
  "modelUsage": {
    "claude-haiku-5-5": {
      "inputTokens": 4,
      "outputTokens": 146,
      "canonicalModel": "claude-haiku-5-5",
      "provider": "firstParty"
    }
  },
  "result": "Output: `test`"
}
```

---

## 2. Subprocess Security & Sandboxing

1. **No Raw Shell Concatenation:**
   All invocations use argument vectors (`asyncio.create_subprocess_exec`) with `shell=False`.
2. **Environment Filtering:**
   Only safe environment variables (`PATH`, `HOME`, `USER`, `LANG`, `TERM`) are passed to the child process. Host API tokens and credentials are not inherited.
3. **Secret Redaction:**
   Automatic regex filtering redacts GitHub tokens (`gho_...`, `ghp_...`), OpenAI keys (`sk-...`), and HTTP Bearer tokens before writing to logs or persisting state.
4. **Isolated Working Directory:**
   Each project executes strictly inside its allocated directory under `storage/artifacts/<project_id>/`.
5. **Execution Timeout:**
   Bounded timeouts (default 180 seconds). In the event of a timeout, the process is safely terminated via `proc.kill()` and `proc.wait()`.

---

## 3. Cost Optimization Policy

1. Claude Haiku 5.5 is prioritized for all implementation and code generation tasks to maintain low token consumption and fast execution latency.
2. Deterministic verification tools (lint, compile, pytest, typecheck) run **before** and **after** model execution to minimize unnecessary LLM passes.
3. Model token usage (input, output, cache reads/writes) and cost basis are parsed and stored in `model_executions` for total auditability.
