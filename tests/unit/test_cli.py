from pathlib import Path

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
    assert arguments.install_dependencies is False


def test_run_can_explicitly_enable_dependency_bootstrap() -> None:
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
            "--model",
            "implementation-model",
            "--install-dependencies",
        ]
    )

    assert arguments.install_dependencies is True


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


def test_showcase_export_requires_an_explicit_experiment_and_confirmation() -> None:
    arguments = build_parser().parse_args(
        [
            "export-showcase",
            "--experiment",
            "a" * 16,
            "--title",
            "AMOR public evidence",
            "--confirm-public",
        ]
    )

    assert arguments.experiment == "a" * 16
    assert arguments.confirm_public is True


def test_stage_showcase_defaults_to_a_supported_static_directory() -> None:
    arguments = build_parser().parse_args(
        ["stage-showcase", "--showcase", "0123456789abcdef"]
    )

    assert arguments.command == "stage-showcase"
    assert arguments.artifacts == Path("artifacts")
    assert arguments.output == Path("out")
    assert arguments.confirm_public is False


def test_publish_pr_defaults_to_draft_main_branch() -> None:
    arguments = build_parser().parse_args(
        [
            "publish-pr",
            "--delivery",
            "artifacts/delivery-report.json",
            "--title",
            "fix: verified change",
        ]
    )

    assert arguments.remote == "origin"
    assert arguments.base == "main"
    assert arguments.proxy is None
    assert arguments.confirm_publish is False
