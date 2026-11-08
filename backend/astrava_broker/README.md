# astrava_broker (M1.5-2a)

Privilege-separated worker broker: the only component that is ever allowed to talk to a container
runtime. **In M1.5-2a it has no real backend** (no Docker, no containers); it ships the closed
typed contract, the service logic and a deterministic fake backend.

* Contract: `contract.py` (nine operations, `extra="forbid"`, bounded values, HMAC envelope).
* The API imports only `astrava_broker.contract` / `profiles`; the broker never imports `app`.
* Tier A (same macOS user) is **development only and is not a security boundary** against code
  running as that user. Tier B (separate OS user owning the socket directory and key) is required
  before any broader use.

Run (dev, fake backend only):

```bash
export ASTRAVA_BROKER_SOCKET=$HOME/.astrava-broker/run/s      # dir is created 0700; keep the path < 100 chars
export ASTRAVA_BROKER_KEY_FILE=$HOME/.astrava-broker/key      # regular file, mode 0600, >= 32 bytes
export ASTRAVA_BROKER_STATE_DIR=$HOME/.astrava-broker/state
export ASTRAVA_BROKER_BACKEND=fake                            # the only value accepted in 2a
python -m astrava_broker
```

API side: `WORKER_RUNTIME=broker BROKER_SOCKET_PATH=... BROKER_KEY_FILE=...` (default `disabled`).
Recovery with workers: `python -m app.orchestrator.recovery_cli <execution_id>` (exit 5 = blocked
because stale workers could not be proven stopped; retry once the broker is reachable).
