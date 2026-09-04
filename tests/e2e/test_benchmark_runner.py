import json
from pathlib import Path

from amor.benchmarks.runner import run_benchmark
from amor.benchmarks.fake_scenarios import build_fake_provider
from amor.domain import TerminalStatus
from amor.providers import FakeModelProvider, ModelToolCall, ModelTurn


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_fake_provider_runs_all_twenty_tasks_and_writes_metrics(tmp_path: Path) -> None:
    summary = run_benchmark(
        project_root=project_root(),
        artifacts_root=tmp_path / "benchmarks",
        provider_name="fake",
        model="fake-model",
        repeats=1,
    )

    assert summary.passed
    assert summary.metrics.task_count == 20
    assert summary.metrics.successful_attempts == 20
    assert summary.metrics.attempt_success_rate == 1.0
    assert summary.metrics.false_completion_rate == 0.0
    assert summary.metrics.scope_violation_rate == 0.0
    assert summary.metrics.diagnosed_attempts == 1
    assert summary.metrics.recovered_attempts == 1
    assert summary.metrics.first_try_successes == 15
    assert summary.metrics.first_try_success_rate == 0.9375
    assert summary.metrics.regression_rate == 0.0
    assert summary.metrics.patch_stable_tasks == 0
    assert summary.metrics.patch_stability_eligible_tasks == 0
    assert summary.metrics.patch_stability_rate is None
    assert summary.metrics.total_tokens > 0
    assert summary.context_strategy == "search-first"
    assert summary.planning_strategy == "structured"
    assert summary.dataset_version == "v2-20-task"
    assert len(summary.dataset_fingerprint) == 64
    assert summary.metrics.average_files_read > 0
    assert summary.metrics.average_lines_read > 0
    assert summary.metrics.context_retained_chars > 0
    assert summary.metrics.context_retention_rate == 1.0

    by_task = {attempt.task_id: attempt for attempt in summary.attempts}
    injection = by_task["py_utils_prompt_injection"]
    assert injection.actual_status == TerminalStatus.BLOCKED
    assert injection.verifier_passed
    assert injection.denied_tool_calls == 1
    security_attempts = [
        attempt for attempt in summary.attempts if attempt.difficulty == "security"
    ]
    assert len(security_attempts) == 4
    assert all(attempt.actual_status == TerminalStatus.BLOCKED for attempt in security_attempts)
    assert all(attempt.denied_tool_calls == 1 for attempt in security_attempts)

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
    assert summary.metrics.stable_tasks == 0
    assert summary.metrics.stability_eligible_tasks == 0
    assert summary.metrics.stable_task_rate is None
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


def test_api_provider_factory_creates_an_isolated_session_per_attempt(tmp_path: Path) -> None:
    providers = []

    def provider_factory(task, attempt):
        provider = build_fake_provider(task, "search-first")
        providers.append(provider)
        return provider

    summary = run_benchmark(
        project_root=project_root(),
        artifacts_root=tmp_path / "benchmarks",
        provider_name="deepseek-responses",
        model="deepseek-v4-pro",
        repeats=2,
        selected_task_ids=["py_utils_average_empty"],
        provider_factory=provider_factory,
        max_total_tokens=5_000,
    )

    assert summary.passed
    assert len(providers) == 2
    assert providers[0] is not providers[1]
    assert summary.max_total_tokens == 5_000
    assert summary.metrics.patch_stability_rate == 1.0
    assert summary.metrics.average_token_stddev == 0.0


def test_hidden_rejection_after_visible_pass_is_counted_as_regression(tmp_path: Path) -> None:
    def turn(number, name, arguments):
        return ModelTurn(
            response_id=f"resp_{number}",
            tool_calls=[ModelToolCall(call_id=f"call_{number}", name=name, arguments=arguments)],
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )

    def provider_factory(task, attempt):
        del attempt
        return FakeModelProvider(
            [
                turn(1, "update_plan", {"steps": ["patch", "test", "review"], "reason": "test"}),
                turn(2, "read_file", {"path": "src/calculator.py", "start_line": 1, "end_line": 40}),
                turn(
                    3,
                    "apply_patch",
                    {
                        "path": "src/calculator.py",
                        "expected_text": "    return sum(values) / len(values)\n",
                        "replacement_text": "    if not values:\n        return 1.0\n    return sum(values) / len(values)\n",
                    },
                ),
                turn(4, "run_validation", {"command": task.visible_validation_commands[0]}),
                turn(5, "get_git_diff", {}),
                turn(6, "submit_for_verification", {"summary": "visible checks pass"}),
            ]
        )

    summary = run_benchmark(
        project_root=project_root(),
        artifacts_root=tmp_path / "benchmarks",
        provider_name="openai-responses",
        model="test-model",
        repeats=1,
        selected_task_ids=["py_utils_average_empty"],
        provider_factory=provider_factory,
    )

    assert not summary.passed
    assert summary.metrics.regressions == 1
    assert summary.metrics.regression_rate == 1.0
    assert summary.attempts[0].failure_category == "behavior_not_fixed"
