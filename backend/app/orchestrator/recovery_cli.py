"""Operator-run recovery of orphaned executions (M1.5-1c).

    python -m app.orchestrator.recovery_cli --list
    python -m app.orchestrator.recovery_cli <execution_id>

Recovery is never started automatically: re-entering the workflow can invoke the model provider
again (at-least-once for work that was not durably settled), so the operator decides. Exit codes:
0 recovered or nothing to do, 3 another live owner holds the execution, 4 ownership was lost,
5 recovery blocked because stale workers could not be proven stopped (fail closed; retry later).
"""

import argparse
import asyncio
import json
import sys
import uuid

from app.db.session import AsyncSessionLocal
from app.orchestrator.runner import OrchestrationRunner
from app.services.execution_lease import LeaseHeldError, StaleWorkerError
from app.services.worker_run_service import WorkerReconcileError


async def _main(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        if args.list:
            ids = await OrchestrationRunner.find_recoverable_executions(db)
            print(json.dumps({"recoverable": [str(i) for i in ids]}))
            return 0
        try:
            execution = await OrchestrationRunner.recover_execution(
                db, uuid.UUID(args.execution_id)
            )
        except LeaseHeldError as exc:
            print(json.dumps({"error": "lease_held", "detail": str(exc)}))
            return 3
        except StaleWorkerError as exc:
            print(json.dumps({"error": "stale_worker", "detail": str(exc)}))
            return 4
        except WorkerReconcileError as exc:
            print(json.dumps({"error": "recovery_blocked", "detail": str(exc)}))
            return 5
        except ValueError as exc:
            print(json.dumps({"error": "not_found", "detail": str(exc)}))
            return 1
        print(json.dumps({"execution_id": str(execution.id), "status": execution.status.value}))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover orphaned ASTRAVA executions")
    parser.add_argument("execution_id", nargs="?", help="execution to recover")
    parser.add_argument("--list", action="store_true", help="list recoverable executions")
    args = parser.parse_args()
    if not args.list and not args.execution_id:
        parser.error("give an execution_id or --list")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
