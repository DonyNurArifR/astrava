"""``BrokerWorkerRuntime``: speaks the closed contract to the broker over a Unix domain socket.

It builds envelopes only from typed arguments, signs them, authenticates the answer and
re-validates it (the broker's output is untrusted). Any transport failure is
``RuntimeUnavailableError``: callers fail closed.
"""

import os
import secrets
import stat
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from app.worker_runtime.base import (
    ERROR_CLASSES,
    CreateWorkerRequest,
    RuntimeDeniedError,
    RuntimeUnavailableError,
    WorkerRef,
    WorkerRuntime,
    WorkerRuntimeError,
)
from astrava_broker.contract import (
    PROTOCOL_VERSION,
    ContractError,
    ErrorCode,
    ExportManifest,
    HealthResult,
    Op,
    OutputResult,
    Response,
    WorkerSummary,
    parse_response,
    sign_request,
)


def read_key_file(path: Path) -> bytes:
    """Same file hygiene as the broker: regular file, ours, mode 0600, >= 32 bytes."""
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise RuntimeUnavailableError(f"broker key unreadable: {exc.strerror}") from None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise RuntimeUnavailableError("broker key file has unsafe type, owner or mode")
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise RuntimeUnavailableError("broker key too short")
    return key


class BrokerWorkerRuntime(WorkerRuntime):
    def __init__(
        self,
        *,
        key: bytes,
        socket_path: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 10.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (socket_path is None) == (transport is None):
            raise ValueError("give exactly one of socket_path or transport")
        self._key = key
        self._clock = clock
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(uds=str(socket_path)),
            base_url="http://broker",
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- transport ------------------------------------------------------------------------
    async def _call(
        self,
        op: Op,
        *,
        ref: WorkerRef | None = None,
        execution_id: uuid.UUID | None = None,
        lease_epoch: int | None = None,
        args: dict[str, Any] | None = None,
    ) -> Response:
        request_id = uuid.uuid4()
        unsigned: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "op": op.value,
            "request_id": str(request_id),
            "worker_run_id": str(ref.worker_run_id) if ref else None,
            "execution_id": str(ref.execution_id if ref else execution_id)
            if (ref or execution_id)
            else None,
            "lease_epoch": ref.lease_epoch if ref else lease_epoch,
            "ts": self._clock(),
            "nonce": secrets.token_hex(16),
            "args": args or {},
        }
        body = sign_request(self._key, unsigned)
        try:
            http = await self._client.post("/v1/call", json=body)
        except httpx.HTTPError as exc:
            raise RuntimeUnavailableError(f"broker unreachable: {type(exc).__name__}") from None
        try:
            resp = parse_response(http.content, self._key, request_id=request_id)
        except ContractError as exc:
            # An unauthenticated or malformed answer is never believed.
            raise RuntimeDeniedError(f"broker response rejected: {exc.message}") from None
        if not resp.ok:
            raise ERROR_CLASSES.get(resp.code, WorkerRuntimeError)(resp.message or resp.code.value)
        return resp

    @staticmethod
    def _need[T](value: T | None, what: str) -> T:
        if value is None:
            raise WorkerRuntimeError(f"broker response missing {what}")
        return value

    # ---- the nine operations --------------------------------------------------------------
    async def create_worker(self, request: CreateWorkerRequest) -> WorkerSummary:
        resp = await self._call(
            Op.CREATE_WORKER,
            ref=request.ref,
            args={
                "kind": request.kind.value,
                "image_alias": request.image_alias.value,
                "profile": request.profile.value,
                "repo_id": request.repo_id,
                "base_ref": request.base_ref,
                "task_id": str(request.task_id),
                "attempt": request.attempt,
                "wall_timeout_s": request.wall_timeout_s,
                "job": request.job,
                "input_ref": str(request.input_ref) if request.input_ref else None,
            },
        )
        return self._need(resp.worker, "worker")

    async def start_worker(self, ref: WorkerRef) -> WorkerSummary:
        return self._need((await self._call(Op.START_WORKER, ref=ref)).worker, "worker")

    async def get_status(self, ref: WorkerRef) -> WorkerSummary:
        return self._need((await self._call(Op.GET_STATUS, ref=ref)).worker, "worker")

    async def collect_output(self, ref: WorkerRef, max_bytes: int) -> OutputResult:
        resp = await self._call(Op.COLLECT_OUTPUT, ref=ref, args={"max_bytes": max_bytes})
        return self._need(resp.output, "output")

    async def export_artifacts(
        self, ref: WorkerRef, max_files: int, max_bytes: int
    ) -> ExportManifest:
        resp = await self._call(
            Op.EXPORT_ARTIFACTS, ref=ref, args={"max_files": max_files, "max_bytes": max_bytes}
        )
        return self._need(resp.manifest, "manifest")

    async def terminate_worker(self, ref: WorkerRef, grace_s: int = 5) -> WorkerSummary:
        resp = await self._call(Op.TERMINATE_WORKER, ref=ref, args={"grace_s": grace_s})
        return self._need(resp.worker, "worker")

    async def cleanup_worker(self, ref: WorkerRef) -> WorkerSummary:
        return self._need((await self._call(Op.CLEANUP_WORKER, ref=ref)).worker, "worker")

    async def list_workers(self, execution_id: uuid.UUID, lease_epoch: int) -> list[WorkerSummary]:
        resp = await self._call(Op.LIST_WORKERS, execution_id=execution_id, lease_epoch=lease_epoch)
        return list(self._need(resp.workers, "workers"))

    async def health(self) -> HealthResult:
        return self._need((await self._call(Op.HEALTH)).health, "health")


__all__ = ["BrokerWorkerRuntime", "read_key_file", "ErrorCode"]
