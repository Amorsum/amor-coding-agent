import pytest

from amor.cli import _resolved_cost_currency, build_parser, main


def test_run_accepts_deepseek_provider() -> None:
    arguments = build_parser().parse_args(
        [
            "run",
            ".",
            "--task",
            "fix it",
            "--allow",
            "src/**",
            "--validation-json",
            '["python","-m","pytest"]',
            "--provider",
            "deepseek-responses",
            "--model",
            "deepseek-v4-pro",
        ]
    )

    assert arguments.provider == "deepseek-responses"
    assert arguments.max_verification_retries == 2
    assert arguments.sandbox == "docker"
    assert arguments.sandbox_memory_mb == 512


def test_deepseek_pricing_defaults_to_cny() -> None:
    arguments = build_parser().parse_args(
        [
            "benchmark",
            "--provider",
            "deepseek-responses",
            "--input-cost-per-million",
            "1",
            "--output-cost-per-million",
            "2",
        ]
    )

    assert _resolved_cost_currency(arguments) == "CNY"


def test_web_defaults_to_local_only_host() -> None:
    arguments = build_parser().parse_args(["web"])

    assert arguments.host == "127.0.0.1"
    assert arguments.port == 8765
    assert str(arguments.artifacts) == "artifacts"


def test_plan_task_collects_user_approved_boundaries() -> None:
    arguments = build_parser().parse_args(
        [
            "plan-task",
            ".",
            "--task",
            "fix empty input",
            "--allow",
            "src/**",
            "--model",
            "planner-model",
        ]
    )

    assert arguments.command == "plan-task"
    assert arguments.allow == ["src/**"]
    assert arguments.validation_json == []
    assert arguments.max_tokens == 40_000


def test_run_can_use_a_frozen_contract_without_repeating_task_flags() -> None:
    arguments = build_parser().parse_args(
        [
            "run",
            ".",
            "--contract",
            "artifacts/plans/example/acceptance-plan.json",
            "--approve-contract",
            "--model",
            "implementation-model",
        ]
    )

    assert arguments.task is None
    assert arguments.allow == []
    assert arguments.approve_contract


def test_web_rejects_public_listen_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["amor", "web", "--host", "0.0.0.0"])

    with pytest.raises(SystemExit, match="loopback host"):
        main()
