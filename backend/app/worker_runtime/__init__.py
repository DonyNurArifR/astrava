"""API-side worker runtime abstraction (M1.5-2a).

Orchestration code depends on ``WorkerRuntime`` only. Implementations: ``BrokerWorkerRuntime``
(talks to the privilege-separated broker over a Unix socket) and ``FakeWorkerRuntime``
(in-process, for tests). Nothing here knows about Docker, images, mounts or networks.
"""

from app.worker_runtime.base import (
    CreateWorkerRequest,
    RuntimeCapacityError,
    RuntimeConflictError,
    RuntimeDeniedError,
    RuntimeInvalidError,
    RuntimeNotFoundError,
    RuntimeUnavailableError,
    WorkerRef,
    WorkerRuntime,
    WorkerRuntimeError,
)
from app.worker_runtime.factory import get_worker_runtime

__all__ = [
    "CreateWorkerRequest",
    "RuntimeCapacityError",
    "RuntimeConflictError",
    "RuntimeDeniedError",
    "RuntimeInvalidError",
    "RuntimeNotFoundError",
    "RuntimeUnavailableError",
    "WorkerRef",
    "WorkerRuntime",
    "WorkerRuntimeError",
    "get_worker_runtime",
]
