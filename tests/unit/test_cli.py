from amor.cli import _resolved_cost_currency, build_parser


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
