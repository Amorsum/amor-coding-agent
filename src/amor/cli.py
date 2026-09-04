from __future__ import annotations

import argparse
import json
from pathlib import Path

from amor.domain import RunLimits
from amor.benchmarks.experiment import run_planning_experiment, run_strategy_experiment
from amor.benchmarks.runner import SUPPORTED_PROVIDERS, run_benchmark
from amor.context import SUPPORTED_CONTEXT_STRATEGIES, ContextStrategy
from amor.local_runner import run_repository_task
from amor.orchestrator import SUPPORTED_PLANNING_STRATEGIES, PlanningStrategy
from amor.profiler import RepositoryProfiler
from amor.providers import DeepSeekResponsesProvider, ModelProvider, OpenAIResponsesProvider, ProviderError
from amor.runner import DEFAULT_TASK_IDS, run_demo
from amor.workspace.manager import WorkspaceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amor", description="AMOR coding-agent foundation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run the deterministic first-iteration tasks")
    demo.add_argument("--project-root", type=Path, default=Path.cwd())
    demo.add_argument("--artifacts", type=Path, default=Path("artifacts/runs"))
    demo.add_argument("--task", action="append", choices=DEFAULT_TASK_IDS)

    profile = subparsers.add_parser("profile", help="inspect a local Git repository without modifying it")
    profile.add_argument("repository", type=Path)

    run = subparsers.add_parser("run", help="run a model-driven task in an isolated local Git worktree")
    run.add_argument("repository", type=Path)
    run.add_argument("--task", required=True, help="natural-language coding task")
    run.add_argument("--accept", action="append", default=[], help="acceptance criterion; may be repeated")
    run.add_argument("--allow", action="append", required=True, help="allowed write glob; may be repeated")
    run.add_argument(
        "--validation-json",
        action="append",
        required=True,
        help='approved argv JSON array, e.g. ["python","-m","pytest"]',
    )
    run.add_argument(
        "--provider",
        choices=("openai-responses", "deepseek-responses"),
        default="openai-responses",
    )
    run.add_argument("--model", required=True, help="exact provider model id")
    run.add_argument("--base-url", help="Responses-compatible API base URL")
    run.add_argument("--artifacts", type=Path, default=Path("artifacts/runs"))
    run.add_argument("--max-rounds", type=int, default=20)
    run.add_argument("--max-seconds", type=int, default=900)
    run.add_argument("--max-tokens", type=int, default=100_000)
    run.add_argument(
        "--max-verification-retries",
        type=int,
        default=2,
        help="additional repair attempts after independent verification fails",
    )
    run.add_argument("--max-output-tokens", type=int, default=4_000)
    run.add_argument("--strategy", choices=SUPPORTED_CONTEXT_STRATEGIES, default=ContextStrategy.SEARCH_FIRST.value)
    run.add_argument("--planning", choices=SUPPORTED_PLANNING_STRATEGIES, default=PlanningStrategy.STRUCTURED.value)
    run.add_argument("--context-budget-chars", type=int, default=40_000)
    run.add_argument(
        "--confirm-send-code",
        action="store_true",
        help="confirm that selected repository snippets may be sent to the configured model provider",
    )

    benchmark = subparsers.add_parser("benchmark", help="run fixed tasks and produce reproducible metrics")
    benchmark.add_argument("--provider", choices=SUPPORTED_PROVIDERS, default="fake")
    benchmark.add_argument("--model", help="exact provider model id; required for API providers")
    benchmark.add_argument("--task-id", action="append", help="benchmark task id; may be repeated")
    benchmark.add_argument("--repeat", type=int, default=1)
    benchmark.add_argument("--base-url", help="Responses-compatible API base URL")
    benchmark.add_argument("--artifacts", type=Path, default=Path("artifacts/benchmarks"))
    benchmark.add_argument("--strategy", choices=SUPPORTED_CONTEXT_STRATEGIES, default=ContextStrategy.SEARCH_FIRST.value)
    benchmark.add_argument("--planning", choices=SUPPORTED_PLANNING_STRATEGIES, default=PlanningStrategy.STRUCTURED.value)
    benchmark.add_argument("--context-budget-chars", type=int, default=40_000)
    benchmark.add_argument("--max-output-tokens", type=int, default=4_000)
    benchmark.add_argument("--max-tokens", type=int, help="override each task's total model-token budget")
    benchmark.add_argument("--cost-currency", help="pricing currency recorded in artifacts, e.g. USD or CNY")
    benchmark.add_argument("--input-cost-per-million", type=float)
    benchmark.add_argument("--cached-input-cost-per-million", type=float)
    benchmark.add_argument("--output-cost-per-million", type=float)
    benchmark.add_argument(
        "--confirm-send-code",
        action="store_true",
        help="confirm benchmark fixture snippets may be sent to the configured model provider",
    )

    experiment = subparsers.add_parser("experiment", help="run a controlled context or planning experiment")
    experiment.add_argument(
        "--provider",
        choices=("fake", "openai-responses", "deepseek-responses"),
        default="fake",
    )
    experiment.add_argument("--model", help="exact provider model id; required for API providers")
    experiment.add_argument("--task-id", action="append", help="benchmark task id; may be repeated")
    experiment.add_argument("--repeat", type=int, default=3)
    experiment.add_argument("--base-url", help="Responses-compatible API base URL")
    experiment.add_argument("--artifacts", type=Path, default=Path("artifacts/experiments"))
    experiment.add_argument("--dimension", choices=("context", "planning"), default="context")
    experiment.add_argument(
        "--strategy",
        action="append",
        choices=SUPPORTED_CONTEXT_STRATEGIES,
        help="context experiment only; exactly two values in baseline/candidate order",
    )
    experiment.add_argument("--context-budget-chars", type=int, default=40_000)
    experiment.add_argument("--max-output-tokens", type=int, default=4_000)
    experiment.add_argument("--max-tokens", type=int, help="override each task's total model-token budget")
    experiment.add_argument("--cost-currency", help="pricing currency recorded in artifacts, e.g. USD or CNY")
    experiment.add_argument("--input-cost-per-million", type=float)
    experiment.add_argument("--cached-input-cost-per-million", type=float)
    experiment.add_argument("--output-cost-per-million", type=float)
    experiment.add_argument(
        "--confirm-send-code",
        action="store_true",
        help="confirm benchmark fixture snippets may be sent to the configured model provider",
    )

    web = subparsers.add_parser("web", help="serve the local read-only artifact dashboard")
    web.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    web.add_argument("--frontend", type=Path, help="built dashboard directory")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.command == "demo":
        project_root = arguments.project_root.resolve()
        artifacts = arguments.artifacts
        if not artifacts.is_absolute():
            artifacts = project_root / artifacts
        reports = run_demo(project_root, artifacts.resolve(), arguments.task)
        for report in reports:
            print(f"{report.task.task_id}: {report.final_status.value}")
            print(f"  report: {Path(report.trace_path).parent / 'final-report.json'}")
        return 0 if all(report.verification.passed for report in reports) else 1
    if arguments.command == "profile":
        try:
            profile = RepositoryProfiler().profile(arguments.repository)
        except WorkspaceError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    if arguments.command == "run":
        if not arguments.confirm_send_code:
            raise SystemExit("refusing API run without --confirm-send-code")
        try:
            validation_commands = [_parse_command_json(value) for value in arguments.validation_json]
            provider = _build_api_provider(
                arguments.provider,
                model=arguments.model,
                base_url=arguments.base_url,
                timeout_seconds=arguments.max_seconds,
                max_output_tokens=arguments.max_output_tokens,
            )
        except (ValueError, ProviderError) as exc:
            raise SystemExit(str(exc)) from exc
        project_root = Path.cwd().resolve()
        artifacts = arguments.artifacts
        if not artifacts.is_absolute():
            artifacts = project_root / artifacts
        try:
            report = run_repository_task(
                project_root=project_root,
                repository=arguments.repository,
                instruction=arguments.task,
                acceptance_criteria=arguments.accept,
                allowed_paths=arguments.allow,
                validation_commands=validation_commands,
                provider_name=arguments.provider,
                model=arguments.model,
                provider=provider,
                artifacts_root=artifacts,
                limits=RunLimits(
                    max_rounds=arguments.max_rounds,
                    max_seconds=arguments.max_seconds,
                    max_total_tokens=arguments.max_tokens,
                    max_verification_retries=arguments.max_verification_retries,
                ),
                context_strategy=arguments.strategy,
                context_budget_chars=arguments.context_budget_chars,
                planning_strategy=arguments.planning,
            )
        except (RuntimeError, WorkspaceError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(f"{report.task.task_id}: {report.final_status.value}")
        print(f"  workspace: {report.workspace_path}")
        print(f"  report: {Path(report.trace_path).parent / 'final-report.json'}")
        return 0 if report.verification.passed else 1
    if arguments.command == "benchmark":
        provider_factory = None
        benchmark_model = arguments.model
        if arguments.provider in ("openai-responses", "deepseek-responses"):
            if not arguments.confirm_send_code:
                raise SystemExit("refusing API benchmark without --confirm-send-code")
            if not benchmark_model:
                raise SystemExit(f"--model is required for {arguments.provider}")
            try:
                _build_api_provider(
                    arguments.provider,
                    model=benchmark_model,
                    base_url=arguments.base_url,
                    max_output_tokens=arguments.max_output_tokens,
                )
            except ProviderError as exc:
                raise SystemExit(str(exc)) from exc
            provider_factory = lambda task, attempt: _build_api_provider(
                arguments.provider,
                model=benchmark_model,
                base_url=arguments.base_url,
                max_output_tokens=arguments.max_output_tokens,
            )
        elif benchmark_model is None:
            benchmark_model = "fake-model" if arguments.provider == "fake" else None

        project_root = Path.cwd().resolve()
        artifacts = arguments.artifacts
        if not artifacts.is_absolute():
            artifacts = project_root / artifacts
        try:
            summary = run_benchmark(
                project_root=project_root,
                artifacts_root=artifacts,
                provider_name=arguments.provider,
                model=benchmark_model,
                repeats=arguments.repeat,
                selected_task_ids=arguments.task_id,
                provider_factory=provider_factory,
                context_strategy=arguments.strategy,
                planning_strategy=arguments.planning,
                context_budget_chars=arguments.context_budget_chars,
                model_max_output_tokens=arguments.max_output_tokens,
                max_total_tokens=arguments.max_tokens,
                cost_currency=_resolved_cost_currency(arguments),
                input_cost_per_million=arguments.input_cost_per_million,
                cached_input_cost_per_million=arguments.cached_input_cost_per_million,
                output_cost_per_million=arguments.output_cost_per_million,
            )
        except (RuntimeError, ValueError, WorkspaceError) as exc:
            raise SystemExit(str(exc)) from exc
        run_root = artifacts.resolve() / summary.run_id
        print(f"benchmark {summary.run_id}: {'PASSED' if summary.passed else 'FAILED'}")
        print(
            f"  attempts: {summary.metrics.successful_attempts}/{summary.metrics.attempt_count} "
            f"({summary.metrics.attempt_success_rate:.1%})"
        )
        print(f"  total tokens: {summary.metrics.total_tokens}")
        print(f"  summary: {run_root / 'summary.json'}")
        return 0 if summary.passed else 1
    if arguments.command == "experiment":
        provider_factory = None
        experiment_model = arguments.model
        if arguments.provider in ("openai-responses", "deepseek-responses"):
            if not arguments.confirm_send_code:
                raise SystemExit("refusing API experiment without --confirm-send-code")
            if not experiment_model:
                raise SystemExit(f"--model is required for {arguments.provider}")
            try:
                _build_api_provider(
                    arguments.provider,
                    model=experiment_model,
                    base_url=arguments.base_url,
                    max_output_tokens=arguments.max_output_tokens,
                )
            except ProviderError as exc:
                raise SystemExit(str(exc)) from exc
            provider_factory = lambda task, attempt: _build_api_provider(
                arguments.provider,
                model=experiment_model,
                base_url=arguments.base_url,
                max_output_tokens=arguments.max_output_tokens,
            )
        elif experiment_model is None:
            experiment_model = "fake-model"

        if arguments.dimension == "planning" and arguments.strategy:
            raise SystemExit("--strategy is only valid for a context experiment")
        project_root = Path.cwd().resolve()
        artifacts = arguments.artifacts
        if not artifacts.is_absolute():
            artifacts = project_root / artifacts
        try:
            common_arguments = {
                "project_root": project_root,
                "artifacts_root": artifacts,
                "provider_name": arguments.provider,
                "model": experiment_model,
                "repeats": arguments.repeat,
                "selected_task_ids": arguments.task_id,
                "provider_factory": provider_factory,
                "context_budget_chars": arguments.context_budget_chars,
                "model_max_output_tokens": arguments.max_output_tokens,
                "max_total_tokens": arguments.max_tokens,
                "cost_currency": _resolved_cost_currency(arguments),
                "input_cost_per_million": arguments.input_cost_per_million,
                "cached_input_cost_per_million": arguments.cached_input_cost_per_million,
                "output_cost_per_million": arguments.output_cost_per_million,
            }
            if arguments.dimension == "planning":
                result = run_planning_experiment(
                    **common_arguments,
                    strategies=[PlanningStrategy.DIRECT.value, PlanningStrategy.STRUCTURED.value],
                )
            else:
                result = run_strategy_experiment(
                    **common_arguments,
                    strategies=arguments.strategy
                    or [ContextStrategy.BROAD.value, ContextStrategy.SEARCH_FIRST.value],
                )
        except (RuntimeError, ValueError, WorkspaceError) as exc:
            raise SystemExit(str(exc)) from exc
        comparison_path = artifacts.resolve() / result.experiment_id / "comparison.json"
        comparison = result.comparison
        print(
            f"{result.dimension} experiment {result.experiment_id}: "
            f"{comparison.baseline_strategy} -> {comparison.candidate_strategy}"
        )
        print(f"  success-rate delta: {comparison.success_rate_delta:+.1%}")
        print(f"  input-token reduction: {comparison.input_token_reduction_rate:.1%}")
        print(f"  tool-call reduction: {comparison.tool_call_reduction_rate:.1%}")
        print(f"  context-char reduction: {comparison.context_char_reduction_rate:.1%}")
        if comparison.estimated_cost_reduction_rate is not None:
            print(f"  estimated-cost reduction: {comparison.estimated_cost_reduction_rate:.1%}")
        print(f"  comparison: {comparison_path}")
        print(f"  report: {comparison_path.parent / 'report.md'}")
        return 0
    if arguments.command == "web":
        if arguments.port < 1 or arguments.port > 65535:
            raise SystemExit("--port must be between 1 and 65535")
        from amor.web import serve_dashboard

        serve_dashboard(
            artifacts_root=arguments.artifacts.resolve(),
            frontend_root=arguments.frontend.resolve() if arguments.frontend else None,
            host=arguments.host,
            port=arguments.port,
        )
        return 0
    return 2


def _parse_command_json(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or not all(isinstance(item, str) and item for item in parsed):
        raise ValueError("each --validation-json value must be a non-empty JSON array of strings")
    return parsed


def _build_api_provider(
    provider_name: str,
    *,
    model: str,
    base_url: str | None,
    timeout_seconds: int = 120,
    max_output_tokens: int,
) -> ModelProvider:
    provider_class = {
        "openai-responses": OpenAIResponsesProvider,
        "deepseek-responses": DeepSeekResponsesProvider,
    }.get(provider_name)
    if provider_class is None:
        raise ProviderError(f"unsupported API provider: {provider_name}")
    return provider_class.from_environment(
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )


def _resolved_cost_currency(arguments: argparse.Namespace) -> str | None:
    has_pricing = any(
        value is not None
        for value in (
            arguments.input_cost_per_million,
            arguments.cached_input_cost_per_million,
            arguments.output_cost_per_million,
        )
    )
    if not has_pricing:
        return arguments.cost_currency
    if arguments.cost_currency:
        return arguments.cost_currency
    return "CNY" if arguments.provider == "deepseek-responses" else "USD"


if __name__ == "__main__":
    raise SystemExit(main())
