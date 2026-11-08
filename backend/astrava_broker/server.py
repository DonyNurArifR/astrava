"""HTTP/1.1-over-Unix-socket front end. One route, POST /v1/call; everything else is 404.

The socket lives in a 0700 directory and is chmod 0600. In tier A (same macOS user) these file
modes plus the MAC are the only controls and are NOT a security boundary against code running as
the same user; tier B (a separate OS user owns the socket directory and the key) is.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import stat
import sys

from fastapi import FastAPI, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from astrava_broker.backend import FakeBackend
from astrava_broker.config import BrokerConfig, load_key
from astrava_broker.contract import MAX_REQUEST_BYTES
from astrava_broker.service import BrokerService
from astrava_broker.state import BrokerState


def build_service(config: BrokerConfig) -> BrokerService:
    key = load_key(config.key_file)
    state = BrokerState(config.state_dir)
    backend = FakeBackend(config.state_dir)
    return BrokerService(config, key, backend, state)


def create_app(service: BrokerService) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):  # noqa: ANN202
        async def loop() -> None:
            while True:
                await asyncio.sleep(service.config.reaper_interval_s)
                with contextlib.suppress(Exception):
                    async with service._lock:
                        service.reap()

        task = asyncio.ensure_future(loop())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(StarletteHTTPException)
    async def _plain(_: Request, exc: StarletteHTTPException) -> Response:
        return Response(status_code=exc.status_code)

    @app.post("/v1/call")
    async def call(request: Request) -> Response:
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return Response(status_code=415)
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_REQUEST_BYTES):
            return Response(status_code=413)
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_REQUEST_BYTES:
                return Response(status_code=413)
            chunks.append(chunk)
        status, body = await service.handle(b"".join(chunks))
        return Response(content=body, status_code=status, media_type="application/json")

    return app


def prepare_socket_dir(socket_path) -> None:  # noqa: ANN001
    parent = socket_path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)
    if socket_path.exists() or socket_path.is_symlink():
        if not stat.S_ISSOCK(os.lstat(socket_path).st_mode):
            raise SystemExit("refusing to replace a non-socket at the socket path")
        socket_path.unlink()


def main() -> int:
    import uvicorn

    config = BrokerConfig.from_env()
    os.umask(0o077)
    service = build_service(config)
    prepare_socket_dir(config.socket_path)
    # Bind the socket ourselves: uvicorn's own UDS binding re-chmods the path to 0666.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(config.socket_path))  # created under umask 0077 => 0600
    os.chmod(config.socket_path, 0o600)
    sock.listen(64)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(service),
            log_level="warning",
            access_log=False,
            server_header=False,
            date_header=False,
        )
    )
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
