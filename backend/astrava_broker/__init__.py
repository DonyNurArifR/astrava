"""ASTRAVA Worker Broker (M1.5-2a): closed, typed worker-control contract and a fake backend.

M1.5-2a ships NO Docker backend. Nothing in this package imports a container client, reads a
Docker socket path or starts a process on behalf of a caller. The API process may import only
``astrava_broker.contract`` (shared vocabulary); the broker never imports ``app``.
"""

__version__ = "0.1.0-2a"
