"""Shared scenario builders for the recovery tests."""


def task(tid: str, title: str, deps: list[str] | None = None, artifact: str | None = None) -> dict:
    return {
        "task_id": tid,
        "title": title,
        "description": f"deterministic task {title}",
        "assigned_agent_slug": "developer",
        "dependencies": deps or [],
        "expected_output_artifacts": [artifact] if artifact else [],
        "acceptance_criteria": ["produces a summary"],
    }


def cfg_two_chain(**extra) -> dict:
    """T1 -> T2 (two sequential waves)."""
    return {
        "tasks": [
            task("t1", "Task One", artifact="one.txt"),
            task("t2", "Task Two", ["t1"], artifact="two.txt"),
        ],
        **extra,
    }


def cfg_parallel(**extra) -> dict:
    """P1, P2, P3 independent (one wave of three)."""
    return {
        "tasks": [
            task("p1", "Par One", artifact="p1.txt"),
            task("p2", "Par Two", artifact="p2.txt"),
            task("p3", "Par Three", artifact="p3.txt"),
        ],
        **extra,
    }


def cfg_single(**extra) -> dict:
    return {"tasks": [task("s1", "Solo", artifact="solo.txt")], **extra}
