"""Runtime selection. Default: disabled (no runtime, nothing runs in a worker)."""

from pathlib import Path

from app.config import settings
from app.worker_runtime.base import RuntimeUnavailableError, WorkerRuntime


def get_worker_runtime() -> WorkerRuntime | None:
    """Return the configured runtime or None when workers are disabled.

    Only ``broker`` can be configured. A misconfigured broker raises ``RuntimeUnavailableError``
    (fail closed); there is no fallback to running work on the host.
    """
    mode = settings.WORKER_RUNTIME
    if mode == "disabled":
        return None
    if mode != "broker":
        raise RuntimeUnavailableError(f"unknown WORKER_RUNTIME {mode!r}")
    from app.worker_runtime.broker import BrokerWorkerRuntime, read_key_file

    if settings.BROKER_SOCKET_PATH is None or settings.BROKER_KEY_FILE is None:
        raise RuntimeUnavailableError("BROKER_SOCKET_PATH and BROKER_KEY_FILE are required")
    return BrokerWorkerRuntime(
        key=read_key_file(Path(settings.BROKER_KEY_FILE)),
        socket_path=Path(settings.BROKER_SOCKET_PATH),
        timeout_s=settings.BROKER_REQUEST_TIMEOUT_SECONDS,
    )
