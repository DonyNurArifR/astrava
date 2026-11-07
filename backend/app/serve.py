"""Supported production/dev entrypoint: validate security configuration, then serve.

Usage: ``uv run python -m app.serve``

Because uvicorn's own ``--host`` flag is invisible to the application, the request-time
local-development guard in ``app.core.guard`` remains the binding defense.
"""

import uvicorn

from app.config import settings
from app.core.security_config import validate_security_configuration


def main() -> None:
    validate_security_configuration(settings)
    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT)


if __name__ == "__main__":
    main()
