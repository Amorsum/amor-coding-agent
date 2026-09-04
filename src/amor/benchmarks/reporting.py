from __future__ import annotations

from amor.benchmarks.models import StrategyExperimentSummary


def render_experiment_report(summary: StrategyExperimentSummary) -> str:
    baseline, candidate = summary.variants
    baseline_metrics = baseline.metrics
    candidate_metrics = candidate.metrics
    currency = summary.cost_currency or "未配置"
    costs_configured = summary.input_cost_per_million is not None
    cost_baseline = _cost(baseline_metrics.total_estimated_cost, currency, costs_configured)
    cost_candidate = _cost(candidate_metrics.total_estimated_cost, currency, costs_configured)
    provider_note = (
        "这是一次确定性的实验管道验证；Fake Provider 的数据不能作为模型质量证据。"
        if summary.provider == "fake"
        else "本次运行使用了真实模型 Provider；引用结果时应同时保留实验配置和原始轨迹。"
    )
    dimension_name = {
        "context": "上下文策略",
        "planning": "规划策略",
    }.get(summary.dimension, summary.dimension)
    comparison = summary.comparison
    cost_comparison = (
        f"- 估算费用降低率：{comparison.estimated_cost_reduction_rate:.1%}\n"
        if comparison.estimated_cost_reduction_rate is not None
        else ""
    )
    return (
        f"# AMOR {dimension_name}实验报告\n\n"
        "## 可复现性信息\n\n"
        f"- 实验 ID：`{summary.experiment_id}`\n"
        f"- 数据集：`{summary.dataset_version}` (`{summary.dataset_fingerprint}`)\n"
        f"- Provider / 模型：`{summary.provider}` / `{summary.model or '无'}`\n"
        f"- 任务数 / 重复次数：{len(summary.task_ids)} / {summary.repeats}\n"
        f"- Prompt 版本：`{summary.prompt_version}`\n"
        f"- 上下文策略：`{summary.context_strategy or '对照变量'}`\n"
        f"- 规划策略：`{summary.planning_strategy or '对照变量'}`\n"
        f"- 费用币种：`{currency}`\n\n"
        "## 实验结果\n\n"
        "| 指标 | " + baseline.strategy + " | " + candidate.strategy + " |\n"
        "|---|---:|---:|\n"
        f"| 单次运行成功率 | {baseline_metrics.attempt_success_rate:.1%} | {candidate_metrics.attempt_success_rate:.1%} |\n"
        f"| 稳定任务率 | {_rate(baseline_metrics.stable_task_rate)} | {_rate(candidate_metrics.stable_task_rate)} |\n"
        f"| 首轮成功率 | {baseline_metrics.first_try_success_rate:.1%} | {candidate_metrics.first_try_success_rate:.1%} |\n"
        f"| 回归率 | {baseline_metrics.regression_rate:.1%} | {candidate_metrics.regression_rate:.1%} |\n"
        f"| 平均工具调用次数 | {baseline_metrics.average_tool_calls:.2f} | {candidate_metrics.average_tool_calls:.2f} |\n"
        f"| 平均耗时（毫秒） | {baseline_metrics.average_duration_ms:.2f} | {candidate_metrics.average_duration_ms:.2f} |\n"
        f"| 任务内耗时标准差均值（毫秒） | {_number(baseline_metrics.average_duration_stddev_ms)} | {_number(candidate_metrics.average_duration_stddev_ms)} |\n"
        f"| Token 总数 | {baseline_metrics.total_tokens} | {candidate_metrics.total_tokens} |\n"
        f"| 任务内 Token 标准差均值 | {_number(baseline_metrics.average_token_stddev)} | {_number(candidate_metrics.average_token_stddev)} |\n"
        f"| 补丁稳定率 | {_rate(baseline_metrics.patch_stability_rate)} | {_rate(candidate_metrics.patch_stability_rate)} |\n"
        f"| 估算费用 | {cost_baseline} | {cost_candidate} |\n"
        f"| 任务内费用标准差均值 | {_cost(baseline_metrics.average_cost_stddev, currency, costs_configured)} | {_cost(candidate_metrics.average_cost_stddev, currency, costs_configured)} |\n\n"
        "## 受控对比\n\n"
        f"- 成功率差值：{comparison.success_rate_delta:+.1%}\n"
        f"- 输入 Token 降低率：{comparison.input_token_reduction_rate:.1%}\n"
        f"- 工具调用降低率：{comparison.tool_call_reduction_rate:.1%}\n"
        f"- 上下文字符降低率：{comparison.context_char_reduction_rate:.1%}\n"
        f"- 已读取文件数降低率：{comparison.files_read_reduction_rate:.1%}\n"
        f"{cost_comparison}"
        "\n## 结果解释边界\n\n"
        f"{provider_note}\n"
    )


def _cost(value: float | None, currency: str, configured: bool) -> str:
    if not configured:
        return "未估算"
    return "未测量" if value is None else f"{value:.8f} {currency}"


def _number(value: float | None) -> str:
    return "未测量" if value is None else f"{value:.2f}"


def _rate(value: float | None) -> str:
    return "未测量" if value is None else f"{value:.1%}"
