import json
from pathlib import Path

from amor.benchmarks.experiment import run_strategy_experiment


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_fake_experiment_compares_broad_and_search_first_context(tmp_path: Path) -> None:
    result = run_strategy_experiment(
        project_root=project_root(),
        artifacts_root=tmp_path / "experiments",
        provider_name="fake",
        model="fake-model",
        repeats=1,
        strategies=["broad", "search-first"],
        selected_task_ids=["py_utils_order_discount"],
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
    )

    assert all(variant.passed for variant in result.variants)
    assert result.comparison.success_rate_delta == 0.0
    assert result.comparison.input_token_reduction_rate > 0
    assert result.comparison.tool_call_reduction_rate > 0
    assert result.comparison.context_char_reduction_rate > 0
    assert result.comparison.files_read_reduction_rate > 0
    assert result.comparison.estimated_cost_reduction_rate is not None
    assert result.comparison.estimated_cost_reduction_rate > 0

    comparison_path = tmp_path / "experiments" / result.experiment_id / "comparison.json"
    document = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert document["comparison"]["baseline_strategy"] == "broad"
    assert document["input_cost_per_million"] == 1.0
    assert len(document["variants"]) == 2


def test_strategy_experiment_rejects_duplicate_variants(tmp_path: Path) -> None:
    try:
        run_strategy_experiment(
            project_root=project_root(),
            artifacts_root=tmp_path,
            provider_name="fake",
            model="fake-model",
            repeats=1,
            strategies=["search-first", "search-first"],
        )
    except ValueError as exc:
        assert "two distinct strategies" in str(exc)
    else:
        raise AssertionError("duplicate strategies should be rejected")
