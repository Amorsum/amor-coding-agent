import json
from pathlib import Path

from amor.benchmarks.experiment import run_planning_experiment, run_strategy_experiment


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
        cost_currency="USD",
        input_cost_per_million=1.0,
        cached_input_cost_per_million=0.25,
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
    assert document["dimension"] == "context"
    assert document["input_cost_per_million"] == 1.0
    assert document["cached_input_cost_per_million"] == 0.25
    assert document["cost_currency"] == "USD"
    assert len(document["variants"]) == 2
    report = (comparison_path.parent / "report.md").read_text(encoding="utf-8")
    assert "AMOR 上下文策略实验报告" in report
    assert "确定性的实验管道验证" in report
    assert "未测量" in report
    assert "单次运行成功率" in report
    assert "AMOR Context Experiment Report" not in report


def test_fake_planning_experiment_compares_direct_and_structured(tmp_path: Path) -> None:
    result = run_planning_experiment(
        project_root=project_root(),
        artifacts_root=tmp_path / "experiments",
        provider_name="fake",
        model="fake-model",
        repeats=1,
        strategies=["direct", "structured"],
        selected_task_ids=["py_utils_average_empty", "py_utils_parse_bool"],
    )

    assert result.dimension == "planning"
    assert result.context_strategy == "search-first"
    assert result.planning_strategy is None
    assert result.comparison.baseline_strategy == "direct"
    assert result.comparison.candidate_strategy == "structured"
    assert result.comparison.success_rate_delta == 0.0
    assert result.comparison.tool_call_reduction_rate < 0
    assert all(variant.passed for variant in result.variants)
    report_path = tmp_path / "experiments" / result.experiment_id / "report.md"
    report = report_path.read_text(encoding="utf-8")
    assert "AMOR 规划策略实验报告" in report
    assert "## 受控对比" in report
    assert "AMOR Planning Experiment Report" not in report
    direct_summary = json.loads(
        (tmp_path / "experiments" / result.experiment_id / "direct" / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    direct_trace = Path(direct_summary["attempts"][0]["trace_path"]).read_text(encoding="utf-8")
    assert '"to": "PLANNING"' not in direct_trace
    assert '"event_type": "plan_updated"' not in direct_trace


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
