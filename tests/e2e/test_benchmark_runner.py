import json
from pathlib import Path

from amor.benchmarks.runner import run_benchmark
from amor.domain import TerminalStatus


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_fake_provider_runs_all_five_tasks_and_writes_metrics(tmp_path: Path) -> None:
    summary = run_benchmark(
        project_root=project_root(),
        artifacts_root=tmp_path / "benchmarks",
        provider_name="fake",
        model="fake-model",
        repeats=1,
    )

    assert summary.passed
    assert summary.metrics.task_count == 5
    assert summary.metrics.successful_attempts == 5
    assert summary.metrics.attempt_success_rate == 1.0
    assert summary.metrics.false_completion_rate == 0.0
    assert summary.metrics.scope_violation_rate == 0.0
    assert summary.metrics.diagnosed_attempts == 1
    assert summary.metrics.recovered_attempts == 1
    assert summary.metrics.total_tokens > 0
    assert summary.context_strategy == "search-first"
    assert summary.metrics.average_files_read > 0
    assert summary.metrics.average_lines_read > 0
    assert summary.metrics.context_retained_chars > 0
    assert summary.metrics.context_retention_rate == 1.0

    by_task = {attempt.task_id: attempt for attempt in summary.attempts}
    injection = by_task["py_utils_prompt_injection"]
    assert injection.actual_status == TerminalStatus.BLOCKED
    assert injection.verifier_passed
    assert injection.denied_tool_calls == 1

    run_root = tmp_path / "benchmarks" / summary.run_id
    assert (run_root / "config.json").is_file()
    assert (run_root / "metrics.json").is_file()
    assert json.loads((run_root / "failures.json").read_text(encoding="utf-8")) == []


def test_scripted_provider_covers_new_tasks(tmp_path: Path) -> None:
    task_ids = [
        "py_utils_order_discount",
        "py_utils_retry_type",
        "py_utils_prompt_injection",
    ]
    summary = run_benchmark(
        project_root=project_root(),
        artifacts_root=tmp_path / "benchmarks",
        provider_name="scripted",
        model=None,
        repeats=1,
        selected_task_ids=task_ids,
    )

    assert summary.passed
    assert summary.metrics.stable_tasks == 3
    assert summary.metrics.policy_denial_attempt_rate == 0.3333


def test_benchmark_repeat_reports_stability(tmp_path: Path) -> None:
    summary = run_benchmark(
        project_root=project_root(),
        artifacts_root=tmp_path / "benchmarks",
        provider_name="scripted",
        model=None,
        repeats=3,
        selected_task_ids=["py_utils_prompt_injection"],
    )

    assert summary.metrics.attempt_count == 3
    assert summary.metrics.stable_tasks == 1
    assert summary.metrics.stable_task_rate == 1.0
