from __future__ import annotations

import json
import hashlib
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from amor.benchmarks.fake_scenarios import build_fake_provider
from amor.benchmarks.loader import (
    BENCHMARK_DATASET_VERSION,
    BenchmarkLayout,
    benchmark_fingerprint,
    list_task_ids,
    load_task,
)
from amor.benchmarks.metrics import calculate_metrics
from amor.benchmarks.models import BenchmarkAttemptRecord, BenchmarkRunSummary
from amor.context import ContextStrategy
from amor.domain import (
    AgentPhase,
    RunReport,
    TaskSpec,
    TerminalStatus,
    VerificationCheck,
    VerificationResult,
)
from amor.orchestrator import (
    PROMPT_VERSION,
    ModelDrivenOrchestrator,
    PlanningStrategy,
    ScriptedOrchestrator,
)
from amor.policy import PolicyEngine
from amor.profiler import RepositoryProfiler
from amor.providers import ModelProvider
from amor.tools import ToolRegistry
from amor.trace import TraceRecorder
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


ProviderFactory = Callable[[TaskSpec, int], ModelProvider]
SUPPORTED_PROVIDERS = ("scripted", "fake", "openai-responses", "deepseek-responses")
API_PROVIDERS = ("openai-responses", "deepseek-responses")


def run_benchmark(
    *,
    project_root: Path,
    artifacts_root: Path,
    provider_name: str,
    model: str | None,
    repeats: int,
    selected_task_ids: list[str] | None = None,
    provider_factory: ProviderFactory | None = None,
    context_strategy: ContextStrategy | str = ContextStrategy.SEARCH_FIRST,
    planning_strategy: PlanningStrategy | str = PlanningStrategy.STRUCTURED,
    context_budget_chars: int = 40_000,
    run_id_override: str | None = None,
    model_max_output_tokens: int = 4_000,
    max_total_tokens: int | None = None,
    cost_currency: str | None = None,
    input_cost_per_million: float | None = None,
    cached_input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> BenchmarkRunSummary:
    if provider_name not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported benchmark provider: {provider_name}")
    if repeats < 1 or repeats > 20:
        raise ValueError("repeats must be between 1 and 20")
    if provider_name in API_PROVIDERS and provider_factory is None:
        raise ValueError(f"{provider_name} benchmark requires a provider factory")
    strategy = ContextStrategy(context_strategy)
    planning = PlanningStrategy(planning_strategy)
    if provider_name == "scripted" and planning != PlanningStrategy.STRUCTURED:
        raise ValueError("scripted benchmark only supports structured planning")
    if context_budget_chars < 1_000:
        raise ValueError("context budget must be at least 1000 characters")
    if model_max_output_tokens < 1:
        raise ValueError("model max output tokens must be positive")
    if max_total_tokens is not None and max_total_tokens < 1:
        raise ValueError("max total tokens must be positive")
    if (input_cost_per_million is None) != (output_cost_per_million is None):
        raise ValueError("input and output token prices must be provided together")
    prices_configured = input_cost_per_million is not None
    if prices_configured != bool(cost_currency and cost_currency.strip()):
        raise ValueError("cost currency and input/output token prices must be provided together")
    if cached_input_cost_per_million is not None and not prices_configured:
        raise ValueError("cached input token price requires input and output token prices")
    if any(
        price is not None and price < 0
        for price in (
            input_cost_per_million,
            cached_input_cost_per_million,
            output_cost_per_million,
        )
    ):
        raise ValueError("token prices cannot be negative")
    normalized_currency = cost_currency.strip().upper() if cost_currency else None

    layout = BenchmarkLayout(project_root.resolve() / "benchmarks")
    available = set(list_task_ids(layout))
    task_ids = selected_task_ids or sorted(available)
    unknown = sorted(set(task_ids) - available)
    if unknown:
        raise ValueError(f"unknown benchmark tasks: {', '.join(unknown)}")
    dataset_fingerprint = benchmark_fingerprint(layout, task_ids)

    if run_id_override is not None and (
        not run_id_override or Path(run_id_override).name != run_id_override
    ):
        raise ValueError("run id override must be a non-empty path segment")
    run_id = run_id_override or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    started_at = datetime.now(timezone.utc)
    run_root = artifacts_root.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    _write_json(
        run_root / "config.json",
        {
            "run_id": run_id,
            "dataset_version": BENCHMARK_DATASET_VERSION,
            "dataset_fingerprint": dataset_fingerprint,
            "provider": provider_name,
            "model": model,
            "context_strategy": strategy.value,
            "planning_strategy": planning.value,
            "context_budget_chars": context_budget_chars,
            "prompt_version": PROMPT_VERSION,
            "model_max_output_tokens": model_max_output_tokens,
            "max_total_tokens": max_total_tokens,
            "cost_currency": normalized_currency,
            "input_cost_per_million": input_cost_per_million,
            "cached_input_cost_per_million": cached_input_cost_per_million,
            "output_cost_per_million": output_cost_per_million,
            "repeats": repeats,
            "task_ids": task_ids,
            "started_at": started_at.isoformat(),
        },
    )

    attempts: list[BenchmarkAttemptRecord] = []
    for task_id in task_ids:
        task = load_task(layout, task_id)
        if max_total_tokens is not None:
            task = task.model_copy(
                update={
                    "limits": task.limits.model_copy(
                        update={"max_total_tokens": max_total_tokens}
                    )
                }
            )
        for attempt_number in range(1, repeats + 1):
            attempt_dir = run_root / "tasks" / task_id / f"attempt-{attempt_number:02d}"
            attempts.append(
                _run_attempt(
                    run_id=run_id,
                    layout=layout,
                    task=task,
                    attempt_number=attempt_number,
                    attempt_dir=attempt_dir,
                    provider_name=provider_name,
                    provider_factory=provider_factory,
                    context_strategy=strategy,
                    planning_strategy=planning,
                    context_budget_chars=context_budget_chars,
                    input_cost_per_million=input_cost_per_million,
                    cached_input_cost_per_million=cached_input_cost_per_million,
                    output_cost_per_million=output_cost_per_million,
                )
            )

    metrics = calculate_metrics(attempts, task_ids)
    summary = BenchmarkRunSummary(
        run_id=run_id,
        dataset_version=BENCHMARK_DATASET_VERSION,
        dataset_fingerprint=dataset_fingerprint,
        provider=provider_name,
        model=model,
        context_strategy=strategy.value,
        planning_strategy=planning.value,
        context_budget_chars=context_budget_chars,
        prompt_version=PROMPT_VERSION,
        model_max_output_tokens=model_max_output_tokens,
        max_total_tokens=max_total_tokens,
        cost_currency=normalized_currency,
        input_cost_per_million=input_cost_per_million,
        cached_input_cost_per_million=cached_input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
        repeats=repeats,
        task_ids=task_ids,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        passed=all(attempt.outcome_matches_expected for attempt in attempts),
        metrics=metrics,
        attempts=attempts,
    )
    _write_json(run_root / "metrics.json", metrics.model_dump(mode="json"))
    _write_json(
        run_root / "failures.json",
        [
            attempt.model_dump(mode="json")
            for attempt in attempts
            if not attempt.outcome_matches_expected
        ],
    )
    _write_json(run_root / "summary.json", summary.model_dump(mode="json"))
    return summary


def _run_attempt(
    *,
    run_id: str,
    layout: BenchmarkLayout,
    task: TaskSpec,
    attempt_number: int,
    attempt_dir: Path,
    provider_name: str,
    provider_factory: ProviderFactory | None,
    context_strategy: ContextStrategy,
    planning_strategy: PlanningStrategy,
    context_budget_chars: int,
    input_cost_per_million: float | None,
    cached_input_cost_per_million: float | None,
    output_cost_per_million: float | None,
) -> BenchmarkAttemptRecord:
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.perf_counter()
    if task.fixture is None:
        raise ValueError(f"benchmark task {task.task_id} has no fixture")
    workspace = WorkspaceManager().create_from_fixture(layout.fixtures / task.fixture, attempt_dir)
    trace_path = attempt_dir / "trace.jsonl"
    trace = TraceRecorder(trace_path, task.task_id)
    policy = PolicyEngine(workspace.root, task.allowed_paths, task.visible_validation_commands)
    tools = ToolRegistry(
        workspace,
        policy,
        trace,
        task.task_id,
        task.limits.max_output_chars,
        task.limits.max_file_bytes,
        task.limits.max_seconds,
    )

    if provider_name == "scripted":
        orchestrator = ScriptedOrchestrator(task, tools, trace)
    else:
        if provider_name == "fake":
            provider = build_fake_provider(task, context_strategy, planning_strategy)
        else:
            assert provider_factory is not None
            provider = provider_factory(task, attempt_number)
        profile = RepositoryProfiler().profile(workspace.source_repository)
        orchestrator = ModelDrivenOrchestrator(
            task,
            profile.model_dump(mode="json"),
            provider,
            tools,
            trace,
            context_strategy=context_strategy,
            context_budget_chars=context_budget_chars,
            planning_strategy=planning_strategy,
        )

    state = orchestrator.run_until_final_verification()
    agent_requested_verification = state.phase == AgentPhase.FINAL_VERIFYING
    if task.expected_status == TerminalStatus.BLOCKED:
        verification = _verify_expected_block(task, state.phase, workspace.diff(), state.relevant_files)
        trace.record("verification", state.phase, verification)
        if state.phase == AgentPhase.FINAL_VERIFYING:
            orchestrator.machine.transition(AgentPhase.FAILED, "task should have stopped safely instead of requesting completion")
            final_status = TerminalStatus.FAILED
        else:
            final_status = TerminalStatus(state.phase.value)
    elif state.phase == AgentPhase.FINAL_VERIFYING:
        verification = IndependentVerifier(layout).verify(task, workspace)
        trace.record("verification", AgentPhase.FINAL_VERIFYING, verification)
        terminal_phase = AgentPhase.SUCCEEDED if verification.passed else AgentPhase.FAILED
        orchestrator.machine.transition(
            terminal_phase,
            "independent verifier passed" if verification.passed else "independent verifier rejected the patch",
        )
        final_status = TerminalStatus(terminal_phase.value)
    else:
        verification = VerificationResult(
            passed=False,
            checks=[VerificationCheck(name="agent_loop", passed=False, summary=f"agent stopped in {state.phase.value}")],
            failure_category="agent_loop_failure",
        )
        final_status = TerminalStatus(state.phase.value)

    diff = workspace.diff()
    evidence_present = all(path in state.relevant_files for path in task.required_evidence_paths)
    outcome_matches = (
        final_status == task.expected_status
        and verification.passed
        and (task.expected_status != TerminalStatus.BLOCKED or (not diff and evidence_present))
    )
    report = RunReport(
        run_id=run_id,
        task=task,
        baseline_commit=workspace.baseline_commit,
        final_status=final_status,
        state=state,
        verification=verification,
        git_diff=diff,
        trace_path=str(trace_path.resolve()),
        workspace_path=str(workspace.root.resolve()),
        started_at=started_at,
    )
    report_path = attempt_dir / "final-report.json"
    _write_json(report_path, report.model_dump(mode="json"))

    trace_events = _read_trace(trace_path)
    tool_events = [event for event in trace_events if event.get("event_type") == "tool"]
    model_requested_calls = sum(
        len(event.get("payload", {}).get("tool_names", []))
        for event in trace_events
        if event.get("event_type") == "model_turn"
    )
    denied_calls = sum(
        event.get("payload", {}).get("policy_result") == "denied"
        for event in tool_events
    )
    diagnosis_attempted = any(
        event.get("event_type") == "state_transition"
        and event.get("payload", {}).get("to") == AgentPhase.DIAGNOSING.value
        for event in trace_events
    )
    no_progress = any(event.get("event_type") == "no_progress_detected" for event in trace_events)
    context_events = [
        event.get("payload", {})
        for event in trace_events
        if event.get("event_type") == "context_evidence"
    ]
    successful_reads = [
        event for event in context_events
        if event.get("tool") == "read_file" and event.get("successful")
    ]
    unique_read_paths = {
        event["path"] for event in successful_reads if event.get("path")
    }
    search_events = [event for event in context_events if event.get("tool") == "search_code"]
    modified_files_read = len(set(state.modified_files) & unique_read_paths)
    context_relevance_rate = (
        round(modified_files_read / len(unique_read_paths), 4)
        if unique_read_paths
        else 0.0
    )
    failure_category = None if outcome_matches else _failure_category(
        final_status,
        verification,
        no_progress,
    )
    visible_checks = [
        check for check in verification.checks if check.name.startswith("visible_tests_")
    ]
    regression_detected = (
        agent_requested_verification
        and bool(visible_checks)
        and all(check.passed for check in visible_checks)
        and any(check.name == "hidden_tests" and not check.passed for check in verification.checks)
    )
    patch_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest() if diff else None
    return BenchmarkAttemptRecord(
        task_id=task.task_id,
        attempt=attempt_number,
        category=task.category,
        difficulty=task.difficulty,
        expected_status=task.expected_status,
        actual_status=final_status,
        context_strategy=context_strategy.value,
        planning_strategy=planning_strategy.value,
        outcome_matches_expected=outcome_matches,
        first_try_success=(
            task.expected_status == TerminalStatus.SUCCEEDED
            and outcome_matches
            and len(state.attempted_fixes) == 1
        ),
        regression_detected=regression_detected,
        verifier_passed=verification.passed,
        agent_requested_verification=agent_requested_verification,
        diagnosis_attempted=diagnosis_attempted,
        recovery_succeeded=(
            diagnosis_attempted
            and outcome_matches
            and final_status == TerminalStatus.SUCCEEDED
        ),
        rounds=state.round,
        patch_attempts=len(state.attempted_fixes),
        tool_calls=model_requested_calls if provider_name != "scripted" else len(tool_events),
        denied_tool_calls=denied_calls,
        input_tokens=state.token_usage.get("input_tokens", 0),
        cached_input_tokens=state.token_usage.get("cached_input_tokens", 0),
        output_tokens=state.token_usage.get("output_tokens", 0),
        reasoning_tokens=state.token_usage.get("reasoning_tokens", 0),
        total_tokens=state.token_usage.get("total_tokens", 0),
        estimated_cost=_estimated_cost(
            state.token_usage.get("input_tokens", 0),
            state.token_usage.get("cached_input_tokens", 0),
            state.token_usage.get("output_tokens", 0),
            input_cost_per_million,
            cached_input_cost_per_million,
            output_cost_per_million,
        ),
        patch_hash=patch_hash,
        files_read=len(successful_reads),
        unique_files_read=len(unique_read_paths),
        lines_read=sum(int(event.get("lines_read", 0)) for event in successful_reads),
        repeated_reads=sum(bool(event.get("repeated")) for event in successful_reads),
        search_calls=len(search_events),
        zero_result_searches=sum(bool(event.get("zero_result")) for event in search_events),
        context_requested_chars=sum(int(event.get("requested_chars", 0)) for event in context_events),
        context_retained_chars=sum(int(event.get("retained_chars", 0)) for event in context_events),
        context_compressions=sum(bool(event.get("compressed")) for event in context_events),
        modified_files_read=modified_files_read,
        context_relevance_rate=context_relevance_rate,
        duration_ms=int((time.perf_counter() - started_monotonic) * 1000),
        failure_category=failure_category,
        report_path=str(report_path.resolve()),
        trace_path=str(trace_path.resolve()),
    )


def _verify_expected_block(
    task: TaskSpec,
    phase: AgentPhase,
    diff: str,
    relevant_files: list[str],
) -> VerificationResult:
    checks = [
        VerificationCheck(
            name="safe_terminal_status",
            passed=phase == AgentPhase.BLOCKED,
            summary=f"expected BLOCKED, observed {phase.value}",
        ),
        VerificationCheck(
            name="empty_diff",
            passed=not diff,
            summary="no repository changes" if not diff else "unexpected repository changes were produced",
        ),
        VerificationCheck(
            name="required_evidence",
            passed=all(path in relevant_files for path in task.required_evidence_paths),
            summary=f"required evidence: {', '.join(task.required_evidence_paths) or 'none'}",
        ),
    ]
    passed = all(check.passed for check in checks)
    return VerificationResult(
        passed=passed,
        checks=checks,
        failure_category=None if passed else "unsafe_or_unjustified_stop",
    )


def _failure_category(
    final_status: TerminalStatus,
    verification: VerificationResult,
    no_progress: bool,
) -> str:
    if no_progress:
        return "no_progress"
    if final_status == TerminalStatus.BUDGET_EXHAUSTED:
        return "budget_exhausted"
    if verification.failure_category:
        return verification.failure_category
    if final_status == TerminalStatus.BLOCKED:
        return "unexpected_blocked"
    return "unexpected_terminal_status"


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _estimated_cost(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    input_cost_per_million: float | None,
    cached_input_cost_per_million: float | None,
    output_cost_per_million: float | None,
) -> float | None:
    if input_cost_per_million is None or output_cost_per_million is None:
        return None
    billable_cached_tokens = min(max(cached_input_tokens, 0), input_tokens)
    uncached_input_tokens = input_tokens - billable_cached_tokens
    cached_rate = (
        cached_input_cost_per_million
        if cached_input_cost_per_million is not None
        else input_cost_per_million
    )
    return round(
        (
            uncached_input_tokens * input_cost_per_million
            + billable_cached_tokens * cached_rate
            + output_tokens * output_cost_per_million
        )
        / 1_000_000,
        8,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
