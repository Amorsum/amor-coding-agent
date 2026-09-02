import sys
from pathlib import Path

from amor.benchmarks import BenchmarkLayout
from amor.domain import RunLimits, TerminalStatus
from amor.local_runner import run_repository_task
from amor.providers import FakeModelProvider, ModelToolCall, ModelTurn
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def call(turn: int, name: str, arguments: dict) -> ModelTurn:
    return ModelTurn(
        response_id=f"resp_{turn}",
        tool_calls=[ModelToolCall(call_id=f"call_{turn}", name=name, arguments=arguments)],
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def test_model_driven_run_edits_only_isolated_worktree(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    fixture_workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "repository-fixture",
    )
    source_repository = fixture_workspace.source_repository
    original = (source_repository / "src/calculator.py").read_text(encoding="utf-8")
    provider = FakeModelProvider(
        [
            call(1, "update_plan", {"steps": ["find average", "patch empty input", "test and review"], "reason": "initial plan"}),
            call(2, "search_code", {"query": "def average", "path": "src"}),
            call(3, "read_file", {"path": "src/calculator.py", "start_line": 1, "end_line": 80}),
            call(
                4,
                "apply_patch",
                {
                    "path": "src/calculator.py",
                    "expected_text": "    return sum(values) / len(values)\n",
                    "replacement_text": "    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
                },
            ),
            call(
                5,
                "run_validation",
                {"command": [sys.executable, "-m", "unittest", "tests.test_calculator", "-v"]},
            ),
            call(6, "get_git_diff", {}),
            call(7, "submit_for_verification", {"summary": "tests pass and diff is minimal"}),
        ]
    )

    report = run_repository_task(
        project_root=project_root(),
        repository=source_repository,
        instruction="average([]) must return 0.0",
        acceptance_criteria=["empty input returns 0.0", "existing tests pass"],
        allowed_paths=["src/**"],
        validation_commands=[[sys.executable, "-m", "unittest", "tests.test_calculator", "-v"]],
        provider_name="fake",
        model="fake-model",
        provider=provider,
        artifacts_root=tmp_path / "local-runs",
        limits=RunLimits(max_rounds=10, max_seconds=120),
    )

    assert report.final_status == TerminalStatus.SUCCEEDED
    assert report.verification.passed
    assert "if not values" in report.git_diff
    assert (source_repository / "src/calculator.py").read_text(encoding="utf-8") == original
    trace = Path(report.trace_path).read_text(encoding="utf-8")
    assert '"event_type": "model_turn"' in trace
    assert '"to": "FINAL_VERIFYING"' in trace
    assert len(provider.requests) == 7
    assert report.state.token_usage == {"input_tokens": 70, "output_tokens": 35, "total_tokens": 105}
    assert provider.requests[1]["previous_response_id"] == "resp_1"
    assert provider.requests[1]["input_data"][0]["call_id"] == "call_1"
    assert all("Stable task: average([]) must return 0.0" in request["instructions"] for request in provider.requests)
    assert all("search_code before read_file" in request["instructions"] for request in provider.requests)
    assert '"event_type": "context_evidence"' in trace
    assert report.state.context_usage["retained_chars"] > 0


def test_model_driven_run_blocks_repeated_identical_searches(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    fixture_workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "repository-fixture",
    )
    repeated = {"query": "average", "path": "src"}
    provider = FakeModelProvider(
        [
            call(1, "update_plan", {"steps": ["search", "patch", "test"], "reason": "initial plan"}),
            call(2, "search_code", repeated),
            call(3, "search_code", repeated),
            call(4, "search_code", repeated),
        ]
    )

    report = run_repository_task(
        project_root=project_root(),
        repository=fixture_workspace.source_repository,
        instruction="fix average",
        acceptance_criteria=["tests pass"],
        allowed_paths=["src/**"],
        validation_commands=[[sys.executable, "-m", "unittest", "tests.test_calculator", "-v"]],
        provider_name="fake",
        model="fake-model",
        provider=provider,
        artifacts_root=tmp_path / "local-runs",
        limits=RunLimits(max_rounds=8, max_seconds=120),
    )

    assert report.final_status == TerminalStatus.BLOCKED
    assert "identical tool call repeated 3 times" in (report.state.latest_error_summary or "")
    assert '"event_type": "no_progress_detected"' in Path(report.trace_path).read_text(encoding="utf-8")


def test_model_driven_run_stops_before_tools_when_token_budget_is_exceeded(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    fixture_workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "repository-fixture",
    )
    provider = FakeModelProvider(
        [
            call(1, "update_plan", {"steps": ["search", "patch", "test"], "reason": "initial plan"}),
            call(2, "search_code", {"query": "average", "path": "src"}),
        ]
    )

    report = run_repository_task(
        project_root=project_root(),
        repository=fixture_workspace.source_repository,
        instruction="fix average",
        acceptance_criteria=["tests pass"],
        allowed_paths=["src/**"],
        validation_commands=[[sys.executable, "-m", "unittest", "tests.test_calculator", "-v"]],
        provider_name="fake",
        model="fake-model",
        provider=provider,
        artifacts_root=tmp_path / "local-runs",
        limits=RunLimits(max_rounds=8, max_seconds=120, max_total_tokens=20),
    )

    assert report.final_status == TerminalStatus.BUDGET_EXHAUSTED
    assert report.state.token_usage["total_tokens"] == 30
    trace = Path(report.trace_path).read_text(encoding="utf-8")
    assert '"event_type": "budget_exhausted"' in trace
    assert '"tool": "search_code"' not in trace
