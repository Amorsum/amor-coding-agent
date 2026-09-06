from pathlib import Path

from amor.benchmarks import BenchmarkLayout, load_task
from amor.domain import AgentPhase
from amor.policy import PolicyEngine
from amor.tools import ToolRegistry
from amor.trace import TraceRecorder
from amor.tools import registry as registry_module
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_patch_is_isolated_and_policy_is_recorded(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    task = load_task(layout, "py_utils_average_empty")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / task.fixture,
        tmp_path / "run",
    )
    trace = TraceRecorder(tmp_path / "run" / "trace.jsonl", task.task_id)
    policy = PolicyEngine(workspace.root, task.allowed_paths, task.visible_validation_commands)
    tools = ToolRegistry(
        workspace,
        policy,
        trace,
        task.task_id,
        task.limits.max_output_chars,
        task.limits.max_file_bytes,
        task.limits.max_seconds,
    )
    tools.phase = AgentPhase.EDITING

    denied_read = tools.read_file("../source-repository/src/calculator.py")
    denied_write = tools.apply_patch("tests/test_calculator.py", "x", "y")
    patch = tools.apply_patch(
        "src/calculator.py",
        "    return sum(values) / len(values)\n",
        "    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
    )

    assert not denied_read.ok
    assert not denied_write.ok
    assert patch.ok
    assert workspace.changed_files() == ["src/calculator.py"]
    source_text = (workspace.source_repository / "src/calculator.py").read_text(encoding="utf-8")
    assert "if not values" not in source_text
    trace_text = trace.path.read_text(encoding="utf-8")
    assert '"policy_result": "denied"' in trace_text
    assert '"before_sha256"' in trace_text


def test_workspace_diff_includes_untracked_files(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "run",
    )
    (workspace.root / "src" / "new_module.py").write_text(
        "VALUE = 42\n",
        encoding="utf-8",
    )

    patch = workspace.full_patch()

    assert "new file mode" in patch
    assert "src/new_module.py" in patch
    assert "+VALUE = 42" in patch


def test_unapproved_command_never_executes(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    task = load_task(layout, "py_utils_average_empty")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / task.fixture,
        tmp_path / "run",
    )
    trace = TraceRecorder(tmp_path / "run" / "trace.jsonl", task.task_id)
    tools = ToolRegistry(
        workspace,
        PolicyEngine(workspace.root, task.allowed_paths, task.visible_validation_commands),
        trace,
        task.task_id,
        task.limits.max_output_chars,
        task.limits.max_file_bytes,
        task.limits.max_seconds,
    )

    result = tools.run_validation(["python", "-c", "open('should-not-exist', 'w').write('x')"])

    assert not result.ok
    assert not (workspace.root / "should-not-exist").exists()


def test_search_falls_back_when_ripgrep_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    task = load_task(layout, "py_utils_average_empty")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / task.fixture,
        tmp_path / "run",
    )
    tools = ToolRegistry(
        workspace,
        PolicyEngine(workspace.root, task.allowed_paths, task.visible_validation_commands),
        TraceRecorder(tmp_path / "run" / "trace.jsonl", task.task_id),
        task.task_id,
        task.limits.max_output_chars,
        task.limits.max_file_bytes,
        task.limits.max_seconds,
    )
    monkeypatch.setattr(registry_module.shutil, "which", lambda _: None)

    result = tools.search_code(r"def\s+average", "src")

    assert result.ok
    assert "src/calculator.py" in result.output
    assert result.metadata["search_backend"] == "python"
