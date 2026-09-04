import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from amor.acceptance import write_acceptance_plan
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
    validation = [sys.executable, "-m", "unittest", "tests.test_calculator", "-v"]
    plan_path = tmp_path / "contract" / "acceptance-plan.json"
    plan = write_acceptance_plan(
        plan_path,
        {
            "schema_version": "v1",
            "plan_id": "plan-e2e",
            "status": "READY",
            "baseline_commit": fixture_workspace.baseline_commit,
            "instruction": "average([]) must return 0.0",
            "acceptance_criteria": ["empty input returns 0.0", "existing tests pass"],
            "preserved_behaviors": ["non-empty averages remain unchanged"],
            "edge_cases": ["empty list"],
            "allowed_paths": ["src/**"],
            "validation_commands": [validation],
            "python_cases": [
                {
                    "name": "empty average",
                    "module": "src.calculator",
                    "callable": "average",
                    "args_json": "[[]]",
                    "kwargs_json": "{}",
                    "expectation": "equals",
                    "expected_json": "0.0",
                    "exception_type": "",
                    "rationale": "requested behavior",
                }
            ],
            "evidence_files": ["src/calculator.py", "tests/test_calculator.py"],
            "questions": [],
            "summary": "accept empty input without regressing existing behavior",
            "provider": "fake",
            "model": "fake-planner",
            "token_usage": {},
            "created_at": datetime.now(timezone.utc),
        },
    )
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
                {"command": validation},
            ),
            call(6, "get_git_diff", {}),
            call(7, "submit_for_verification", {"summary": "tests pass and diff is minimal"}),
        ]
    )

    report = run_repository_task(
        project_root=project_root(),
        repository=source_repository,
        instruction="average([]) must return 0.0",
        acceptance_criteria=plan.acceptance_criteria,
        allowed_paths=plan.allowed_paths,
        validation_commands=plan.validation_commands,
        provider_name="fake",
        model="fake-model",
        provider=provider,
        artifacts_root=tmp_path / "local-runs",
        limits=RunLimits(max_rounds=10, max_seconds=120),
        acceptance_plan=plan,
        acceptance_plan_path=plan_path,
    )

    assert report.final_status == TerminalStatus.SUCCEEDED
    assert report.verification.passed
    assert any(check.name == "external_acceptance" for check in report.verification.checks)
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
    contract = json.loads(
        (Path(report.trace_path).parent / "verification-contract.json").read_text(encoding="utf-8")
    )
    assert contract["sources"]["acceptance_criteria"] == "approved-planner-contract"
    assert contract["external_acceptance"]["contract_sha256"] == plan.contract_sha256


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


def test_local_run_repairs_after_independent_verifier_rejection(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    fixture_workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "repository-fixture",
    )
    validation = [sys.executable, "-c", "raise SystemExit(0)"]
    provider = FakeModelProvider(
        [
            call(1, "update_plan", {"steps": ["inspect", "patch", "verify"], "reason": "initial plan"}),
            call(2, "read_file", {"path": "src/calculator.py", "start_line": 1, "end_line": 40}),
            call(
                3,
                "apply_patch",
                {
                    "path": "src/calculator.py",
                    "expected_text": "    return sum(values) / len(values)\n",
                    "replacement_text": "    return (\n",
                },
            ),
            call(4, "run_validation", {"command": validation}),
            call(5, "get_git_diff", {}),
            call(6, "submit_for_verification", {"summary": "ready"}),
            call(
                7,
                "apply_patch",
                {
                    "path": "src/calculator.py",
                    "expected_text": "    return (\n",
                    "replacement_text": (
                        "    if not values:\n"
                        "        return 0.0\n"
                        "    return sum(values) / len(values)\n"
                    ),
                },
            ),
            call(8, "run_validation", {"command": validation}),
            call(9, "get_git_diff", {}),
            call(10, "submit_for_verification", {"summary": "repaired"}),
        ]
    )

    report = run_repository_task(
        project_root=project_root(),
        repository=fixture_workspace.source_repository,
        instruction="average([]) must return 0.0",
        acceptance_criteria=["empty input returns 0.0"],
        allowed_paths=["src/**"],
        validation_commands=[validation],
        provider_name="fake",
        model="fake-model",
        provider=provider,
        artifacts_root=tmp_path / "local-runs",
        limits=RunLimits(
            max_rounds=12,
            max_seconds=120,
            max_verification_retries=1,
        ),
    )

    assert report.final_status == TerminalStatus.SUCCEEDED
    assert report.state.verification_attempts == 2
    assert len(report.verification_history) == 2
    assert report.verification_history[0].failure_category == "static_validation_failure"
    assert report.verification_history[1].passed
    assert "if not values" in report.git_diff
    trace = Path(report.trace_path).read_text(encoding="utf-8")
    assert '"event_type": "verification_feedback"' in trace
    feedback = provider.requests[6]["input_data"][0]
    assert feedback["call_id"] == "call_6"
    assert "static_validation_failure" in feedback["output"]

    contract_path = Path(report.trace_path).parent / "verification-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["baseline_commit"] == report.baseline_commit
    assert contract["sources"]["acceptance_criteria"] == "user"
    assert len(contract["contract_sha256"]) == 64


def test_terminal_verification_is_allowed_after_final_turn_crosses_token_budget(
    tmp_path: Path,
) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    fixture_workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "repository-fixture",
    )
    validation = [sys.executable, "-m", "unittest", "tests.test_calculator", "-v"]
    provider = FakeModelProvider(
        [
            call(1, "search_code", {"query": "def average", "path": "src"}),
            call(2, "read_file", {"path": "src/calculator.py", "start_line": 1, "end_line": 40}),
            call(
                3,
                "apply_patch",
                {
                    "path": "src/calculator.py",
                    "expected_text": "    return sum(values) / len(values)\n",
                    "replacement_text": (
                        "    if not values:\n"
                        "        return 0.0\n"
                        "    return sum(values) / len(values)\n"
                    ),
                },
            ),
            call(4, "run_validation", {"command": validation}),
            call(5, "get_git_diff", {}),
            call(6, "submit_for_verification", {"summary": "ready"}),
        ]
    )

    report = run_repository_task(
        project_root=project_root(),
        repository=fixture_workspace.source_repository,
        instruction="average([]) must return 0.0",
        acceptance_criteria=["empty input returns 0.0"],
        allowed_paths=["src/**"],
        validation_commands=[validation],
        provider_name="fake",
        model="fake-model",
        provider=provider,
        artifacts_root=tmp_path / "local-runs",
        limits=RunLimits(max_rounds=8, max_seconds=120, max_total_tokens=80),
        planning_strategy="direct",
    )

    assert report.final_status == TerminalStatus.SUCCEEDED
    assert report.verification.passed
    assert report.state.token_usage["total_tokens"] == 90
    assert report.state.budget_overrun_tokens == 10
    trace = Path(report.trace_path).read_text(encoding="utf-8")
    assert '"event_type": "budget_overrun"' in trace
    assert '"terminal_submission_allowed": true' in trace


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
