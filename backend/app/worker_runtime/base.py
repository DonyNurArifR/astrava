"""The replaceable runtime interface and its error taxonomy.

Vocabulary types (kinds, profiles, states, summaries) come from ``astrava_broker.contract``,
the one module of the broker package the API is allowed to import. They carry no Docker concept.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from astrava_broker.contract import (
    ErrorCode,
    ExportManifest,
    HealthResult,
    ImageAlias,
    OutputResult,
    Profile,
    WorkerKind,
    WorkerSummary,
)


class WorkerRuntimeError(Exception):
    """Base class. Every failure of the runtime is an exception; there is no host fallback."""

    code: ErrorCode = ErrorCode.INTERNAL


class RuntimeUnavailableError(WorkerRuntimeError):
    """Broker or backend unreachable. Callers MUST fail closed (never run the work on the host)."""

    code = ErrorCode.RUNTIME_UNAVAILABLE


class RuntimeInvalidError(WorkerRuntimeError):
    code = ErrorCode.INVALID


class RuntimeDeniedError(WorkerRuntimeError):
    code = ErrorCode.DENIED


class RuntimeNotFoundError(WorkerRuntimeError):
    code = ErrorCode.NOT_FOUND


class RuntimeConflictError(WorkerRuntimeError):
    """Includes a stale lease epoch rejected by the broker."""

    code = ErrorCode.CONFLICT


class RuntimeCapacityError(WorkerRuntimeError):
    code = ErrorCode.CAPACITY


ERROR_CLASSES: dict[ErrorCode, type[WorkerRuntimeError]] = {
    ErrorCode.INVALID: RuntimeInvalidError,
    ErrorCode.DENIED: RuntimeDeniedError,
    ErrorCode.NOT_FOUND: RuntimeNotFoundError,
    ErrorCode.CONFLICT: RuntimeConflictError,
    ErrorCode.CAPACITY: RuntimeCapacityError,
    ErrorCode.RUNTIME_UNAVAILABLE: RuntimeUnavailableError,
    ErrorCode.TIMEOUT: RuntimeUnavailableError,
    ErrorCode.INTERNAL: WorkerRuntimeError,
}


@dataclass(frozen=True)
class WorkerRef:
    """Identifies a worker and the ownership under which the caller acts."""

    worker_run_id: uuid.UUID
    execution_id: uuid.UUID
    lease_epoch: int


@dataclass(frozen=True)
class CreateWorkerRequest:
    ref: WorkerRef
    task_id: uuid.UUID
    attempt: int
    kind: WorkerKind
    profile: Profile
    image_alias: ImageAlias
    repo_id: str
    base_ref: str
    wall_timeout_s: int
    job: str
    input_ref: uuid.UUID | None = None


class WorkerRuntime(ABC):
    """Nine operations, the same closed set as the broker contract. Nothing else can be asked."""

    @abstractmethod
    async def create_worker(self, request: CreateWorkerRequest) -> WorkerSummary: ...

    @abstractmethod
    async def start_worker(self, ref: WorkerRef) -> WorkerSummary: ...

    @abstractmethod
    async def get_status(self, ref: WorkerRef) -> WorkerSummary: ...

    @abstractmethod
    async def collect_output(self, ref: WorkerRef, max_bytes: int) -> OutputResult: ...

    @abstractmethod
    async def export_artifacts(
        self, ref: WorkerRef, max_files: int, max_bytes: int
    ) -> ExportManifest: ...

    @abstractmethod
    async def terminate_worker(self, ref: WorkerRef, grace_s: int = 5) -> WorkerSummary: ...

    @abstractmethod
    async def cleanup_worker(self, ref: WorkerRef) -> WorkerSummary: ...

    @abstractmethod
    async def list_workers(
        self, execution_id: uuid.UUID, lease_epoch: int
    ) -> list[WorkerSummary]: ...

    @abstractmethod
    async def health(self) -> HealthResult: ...

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        return None
