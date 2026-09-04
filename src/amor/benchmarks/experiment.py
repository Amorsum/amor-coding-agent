from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from amor.benchmarks.models import (
    BenchmarkRunSummary,
    StrategyExperimentComparison,
    StrategyExperimentSummary,
    StrategyExperimentVariant,
)
from amor.benchmarks.runner import ProviderFactory, run_benchmark
from amor.benchmarks.reporting import render_experiment_report
from amor.context import ContextStrategy
from amor.orchestrator import PROMPT_VERSION, PlanningStrategy


def run_strategy_experiment(
    *,
    project_root: Path,
    artifacts_root: Path,
    provider_name: str,
    model: str | None,
    repeats: int,
    strategies: list[ContextStrategy | str],
    selected_task_ids: list[str] | None = None,
    provider_factory: ProviderFactory | None = None,
    context_budget_chars: int = 40_000,
    model_max_output_tokens: int = 4_000,
    max_total_tokens: int | None = None,
    cost_currency: str | None = None,
    input_cost_per_million: float | None = None,
    cached_input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
    planning_strategy: PlanningStrategy | str = PlanningStrategy.STRUCTURED,
) -> StrategyExperimentSummary:
    normalized = [ContextStrategy(strategy) for strategy in strategies]
    if len(normalized) != 2 or len(set(normalized)) != 2:
        raise ValueError("strategy experiment requires exactly two distinct strategies")
    if provider_name == "scripted":
        raise ValueError("strategy experiment requires fake or an API provider")

    experiment_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    experiment_root = artifacts_root.resolve() / experiment_id
    variants: list[StrategyExperimentVariant] = []
    summaries = []
    for strategy in normalized:
        summary = run_benchmark(
            project_root=project_root,
            artifacts_root=experiment_root,
            provider_name=provider_name,
            model=model,
            repeats=repeats,
            selected_task_ids=selected_task_ids,
            provider_factory=provider_factory,
            context_strategy=strategy,
            planning_strategy=planning_strategy,
            context_budget_chars=context_budget_chars,
            run_id_override=strategy.value,
            model_max_output_tokens=model_max_output_tokens,
            max_total_tokens=max_total_tokens,
            cost_currency=cost_currency,
            input_cost_per_million=input_cost_per_million,
            cached_input_cost_per_million=cached_input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        )
        summaries.append(summary)
        variants.append(
            StrategyExperimentVariant(
                strategy=strategy.value,
                run_id=summary.run_id,
                passed=summary.passed,
                metrics=summary.metrics,
                summary_path=str((experiment_root / summary.run_id / "summary.json").resolve()),
            )
        )

    baseline, candidate = summaries
    comparison = _build_comparison(
        normalized[0].value,
        normalized[1].value,
        baseline,
        candidate,
    )
    result = StrategyExperimentSummary(
        experiment_id=experiment_id,
        dataset_version=baseline.dataset_version,
        dataset_fingerprint=baseline.dataset_fingerprint,
        dimension="context",
        provider=provider_name,
        model=model,
        planning_strategy=PlanningStrategy(planning_strategy).value,
        repeats=repeats,
        task_ids=baseline.task_ids,
        context_budget_chars=context_budget_chars,
        prompt_version=PROMPT_VERSION,
        model_max_output_tokens=model_max_output_tokens,
        max_total_tokens=max_total_tokens,
        cost_currency=baseline.cost_currency,
        input_cost_per_million=input_cost_per_million,
        cached_input_cost_per_million=cached_input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        variants=variants,
        comparison=comparison,
    )
    _write_json(experiment_root / "comparison.json", result.model_dump(mode="json"))
    _write_text(experiment_root / "report.md", render_experiment_report(result))
    return result


def run_planning_experiment(
    *,
    project_root: Path,
    artifacts_root: Path,
    provider_name: str,
    model: str | None,
    repeats: int,
    strategies: list[PlanningStrategy | str],
    selected_task_ids: list[str] | None = None,
    provider_factory: ProviderFactory | None = None,
    context_strategy: ContextStrategy | str = ContextStrategy.SEARCH_FIRST,
    context_budget_chars: int = 40_000,
    model_max_output_tokens: int = 4_000,
    max_total_tokens: int | None = None,
    cost_currency: str | None = None,
    input_cost_per_million: float | None = None,
    cached_input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> StrategyExperimentSummary:
    normalized = [PlanningStrategy(strategy) for strategy in strategies]
    if len(normalized) != 2 or len(set(normalized)) != 2:
        raise ValueError("planning experiment requires exactly two distinct strategies")
    if provider_name == "scripted":
        raise ValueError("planning experiment requires fake or an API provider")

    experiment_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    experiment_root = artifacts_root.resolve() / experiment_id
    variants: list[StrategyExperimentVariant] = []
    summaries: list[BenchmarkRunSummary] = []
    fixed_context = ContextStrategy(context_strategy)
    for strategy in normalized:
        summary = run_benchmark(
            project_root=project_root,
            artifacts_root=experiment_root,
            provider_name=provider_name,
            model=model,
            repeats=repeats,
            selected_task_ids=selected_task_ids,
            provider_factory=provider_factory,
            context_strategy=fixed_context,
            planning_strategy=strategy,
            context_budget_chars=context_budget_chars,
            run_id_override=strategy.value,
            model_max_output_tokens=model_max_output_tokens,
            max_total_tokens=max_total_tokens,
            cost_currency=cost_currency,
            input_cost_per_million=input_cost_per_million,
            cached_input_cost_per_million=cached_input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        )
        summaries.append(summary)
        variants.append(
            StrategyExperimentVariant(
                strategy=strategy.value,
                run_id=summary.run_id,
                passed=summary.passed,
                metrics=summary.metrics,
                summary_path=str((experiment_root / summary.run_id / "summary.json").resolve()),
            )
        )

    baseline, candidate = summaries
    comparison = _build_comparison(
        normalized[0].value,
        normalized[1].value,
        baseline,
        candidate,
    )
    result = StrategyExperimentSummary(
        experiment_id=experiment_id,
        dataset_version=baseline.dataset_version,
        dataset_fingerprint=baseline.dataset_fingerprint,
        dimension="planning",
        provider=provider_name,
        model=model,
        context_strategy=fixed_context.value,
        repeats=repeats,
        task_ids=baseline.task_ids,
        context_budget_chars=context_budget_chars,
        prompt_version=PROMPT_VERSION,
        model_max_output_tokens=model_max_output_tokens,
        max_total_tokens=max_total_tokens,
        cost_currency=baseline.cost_currency,
        input_cost_per_million=input_cost_per_million,
        cached_input_cost_per_million=cached_input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        variants=variants,
        comparison=comparison,
    )
    _write_json(experiment_root / "comparison.json", result.model_dump(mode="json"))
    _write_text(experiment_root / "report.md", render_experiment_report(result))
    return result


def _build_comparison(
    baseline_name: str,
    candidate_name: str,
    baseline: BenchmarkRunSummary,
    candidate: BenchmarkRunSummary,
) -> StrategyExperimentComparison:
    return StrategyExperimentComparison(
        baseline_strategy=baseline_name,
        candidate_strategy=candidate_name,
        success_rate_delta=round(
            candidate.metrics.attempt_success_rate - baseline.metrics.attempt_success_rate,
            4,
        ),
        input_token_reduction_rate=_reduction(
            baseline.metrics.total_input_tokens,
            candidate.metrics.total_input_tokens,
        ),
        tool_call_reduction_rate=_reduction(
            baseline.metrics.average_tool_calls,
            candidate.metrics.average_tool_calls,
        ),
        context_char_reduction_rate=_reduction(
            baseline.metrics.context_retained_chars,
            candidate.metrics.context_retained_chars,
        ),
        files_read_reduction_rate=_reduction(
            baseline.metrics.average_files_read,
            candidate.metrics.average_files_read,
        ),
        estimated_cost_reduction_rate=(
            _reduction(
                baseline.metrics.total_estimated_cost,
                candidate.metrics.total_estimated_cost,
            )
            if baseline.metrics.total_estimated_cost is not None
            and candidate.metrics.total_estimated_cost is not None
            else None
        ),
    )


def _reduction(baseline: float | int, candidate: float | int) -> float:
    if baseline == 0:
        return 0.0
    reduction = round((baseline - candidate) / baseline, 4)
    return 0.0 if abs(reduction) < 0.0005 else reduction


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")
