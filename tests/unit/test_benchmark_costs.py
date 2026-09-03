import pytest

from amor.benchmarks.runner import _estimated_cost, run_benchmark


def test_estimated_cost_separates_cached_and_uncached_input() -> None:
    assert _estimated_cost(
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        output_tokens=100_000,
        input_cost_per_million=2.0,
        cached_input_cost_per_million=0.5,
        output_cost_per_million=8.0,
    ) == 2.425


def test_estimated_cost_defaults_cached_tokens_to_normal_input_rate() -> None:
    assert _estimated_cost(100, 80, 50, 2.0, None, 4.0) == 0.0004


def test_pricing_requires_a_currency(tmp_path) -> None:
    with pytest.raises(ValueError, match="currency"):
        run_benchmark(
            project_root=tmp_path,
            artifacts_root=tmp_path / "artifacts",
            provider_name="fake",
            model="fake-model",
            repeats=1,
            input_cost_per_million=1.0,
            output_cost_per_million=2.0,
        )
