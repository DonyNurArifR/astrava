"""M1.5-2a static security guards: the API cannot reach Docker; the broker cannot reach the app.

These scan source with the AST/text, so they hold regardless of what is installed or running.
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
BROKER = BACKEND / "astrava_broker"

DOCKER_MODULES = {
    "docker",
    "podman",
    "aiodocker",
    "docker_py",
    "python_on_whales",
    "testcontainers",
    "kubernetes",
    "containerd",
}
DOCKER_TEXT = re.compile(
    r"docker\.sock|docker_host|/var/run/docker|\.docker/run|dockerd|containerd\.sock|"
    r"podman\.sock|\bdocker\s+(run|exec|create|build|pull|cp)\b",
    re.IGNORECASE,
)


def py_files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return mods


def test_api_never_imports_a_container_client():
    for f in py_files(APP):
        bad = {m for m in imports(f) if m.split(".")[0] in DOCKER_MODULES}
        assert not bad, f"{f} imports container client {bad}"


def test_api_never_references_a_docker_socket_or_cli():
    for f in py_files(APP):
        text = f.read_text()
        m = DOCKER_TEXT.search(text)
        assert not m, f"{f} references Docker access: {m.group(0)!r}"


def test_api_never_spawns_docker_processes():
    spawners = {
        "run", "Popen", "call", "check_call", "check_output", "create_subprocess_exec",
        "create_subprocess_shell", "system", "popen", "spawn",
    }  # fmt: skip
    for f in py_files(APP):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in spawners:
                continue
            first = node.args[0]
            if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
                first = first.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                head = first.value.strip().split(" ")[0].rsplit("/", 1)[-1]
                assert head not in {"docker", "podman", "nerdctl"}, (
                    f"{f}:{node.lineno} spawns a container CLI"
                )


def test_api_imports_only_the_broker_contract_vocabulary():
    allowed = {"astrava_broker.contract", "astrava_broker.profiles"}
    for f in py_files(APP):
        for m in imports(f):
            if m.split(".")[0] == "astrava_broker":
                assert m in allowed, f"{f} imports {m}; only the contract may cross the boundary"


def test_broker_never_imports_the_application():
    for f in py_files(BROKER):
        for m in imports(f):
            assert m.split(".")[0] != "app", f"{f} imports the application ({m})"


def test_broker_does_not_import_application_secrets_or_database_drivers():
    forbidden = {
        "sqlalchemy",
        "asyncpg",
        "psycopg",
        "psycopg2",
        "alembic",
        "langgraph",
        "langchain_core",
        "pydantic_settings",
    }
    for f in py_files(BROKER):
        bad = {m for m in imports(f) if m.split(".")[0] in forbidden}
        assert not bad, f"{f} imports {bad}"


def test_milestone_2a_ships_no_docker_code_anywhere():
    for root in (APP, BROKER):
        for f in py_files(root):
            bad = {m for m in imports(f) if m.split(".")[0] in DOCKER_MODULES}
            assert not bad, f"{f} imports {bad} (Docker is M1.5-2b, broker only)"
            assert not DOCKER_TEXT.search(f.read_text()), f"{f} references Docker access"


def test_broker_does_not_spawn_processes_or_use_a_shell():
    banned_calls = {"system", "popen", "Popen", "run", "call", "check_call", "check_output"}
    banned_modules = {"subprocess", "pty", "ctypes"}
    for f in py_files(BROKER):
        assert not (imports(f) & banned_modules), f"{f} imports a process/FFI module"
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id in {"os", "subprocess"}:
                    assert node.func.attr not in banned_calls, f"{f}:{node.lineno}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "__import__"}, (
                    f"{f}:{node.lineno}"
                )


def test_contract_models_forbid_extra_fields():
    from pydantic import BaseModel

    from astrava_broker import contract

    for name in dir(contract):
        obj = getattr(contract, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj.__module__ == "astrava_broker.contract"
            and name not in {"ParsedRequest", "_OpSpec", "_Model"}
        ):
            assert obj.model_config.get("extra") == "forbid", f"{name} allows extra fields"


def test_contract_has_no_free_form_dict_or_command_fields():
    """The only free-form text field a caller controls is `job`, a bounded opaque string."""
    from astrava_broker import contract

    fields = contract.CreateWorkerArgs.model_fields
    assert set(fields) == {
        "kind", "image_alias", "profile", "repo_id", "base_ref", "task_id",
        "attempt", "wall_timeout_s", "job", "input_ref",
    }  # fmt: skip
    for model in (
        contract.CollectOutputArgs,
        contract.ExportArtifactsArgs,
        contract.TerminateArgs,
        contract.EmptyArgs,
    ):
        for finfo in model.model_fields.values():
            assert finfo.annotation in (int, str), "args must be plain bounded scalars"


def test_default_runtime_is_disabled_and_has_no_fallback():
    from app.config import Settings

    assert Settings.model_fields["WORKER_RUNTIME"].default == "disabled"
