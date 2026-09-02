from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from amor.benchmarks.fake_scenarios import build_fake_provider
from amor.benchmarks.loader import BenchmarkLayout, list_task_ids, load_task
from amor.benchmarks.metrics import calculate_metrics
from amor.benchmarks.models import BenchmarkAttemptRecord, BenchmarkRunSummary
from amor.domain import (
    AgentPhase,
    RunReport,
    TaskSpec,
    TerminalStatus,
    VerificationCheck,
    VerificationResult,
)
from amor.orchestrator import ModelDrivenOrchestrator, ScriptedOrchestrator
from amor.policy import PolicyEngine
from amor.profiler import RepositoryProfiler
from amor.providers import ModelProvider
from amor.tools import ToolRegistry
from amor.trace import TraceRecorder
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


ProviderFactory = Callable[[TaskSpec, int], ModelProvider]
SUPPORTED_PROVIDERS = ("scripted", "fake", "openai-responses")


def run_benchmark(
    *,
    project_root: Path,
    artifacts_root: Path,
    provider_name: str,
    model: str | None,
    repeats: int,
    selected_task_ids: list[str] | None = None,
    provider_factory: ProviderFactory | None = None,
) -> BenchmarkRunSummary:
    if provider_name not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported benchmark provider: {provider_name}")
    if repeats < 1 or repeats > 20:
        raise ValueError("repeats must be between 1 and 20")
    if provider_name == "openai-responses" and provider_factory is None:
        raise ValueError("openai-responses benchmark requires a provider factory")

    layout = BenchmarkLayout(project_root.resolve() / "benchmarks")
    available = set(list_task_ids(layout))
    task_ids = selected_task_ids or sorted(available)
    unknown = sorted(set(task_ids) - available)
    if unknown:
        raise ValueError(f"unknown benchmark tasks: {', '.join(unknown)}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    run_root = artifacts_root.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    _write_json(
        run_root / "config.json",
        {
            "run_id": run_id,
            "provider": provider_name,
            "model": model,
            "repeats": repeats,
            "task_ids": task_ids,
            "started_at": started_at.isoformat(),
        },
    )

    attempts: list[BenchmarkAttemptRecord] = []
    for task_id in task_ids:
        task = load_task(layout, task_id)
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
                )
            )

    metrics = calculate_metrics(attempts, task_ids)
    summary = BenchmarkRunSummary(
        run_id=run_id,
        provider=provider_name,
        model=model,
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
            provider = build_fake_provider(task)
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
    failure_category = None if outcome_matches else _failure_category(
        final_status,
        verification,
        no_progress,
    )
    return BenchmarkAttemptRecord(
        task_id=task.task_id,
        attempt=attempt_number,
        category=task.category,
        difficulty=task.difficulty,
        expected_status=task.expected_status,
        actual_status=final_status,
        outcome_matches_expected=outcome_matches,
        verifier_passed=verification.passed,
        agent_requested_verification=agent_requested_verification,
        diagnosis_attempted=diagnosis_attempted,
        recovery_succeeded=diagnosis_attempted and outcome_matches,
        rounds=state.round,
        patch_attempts=len(state.attempted_fixes),
        tool_calls=model_requested_calls if provider_name != "scripted" else len(tool_events),
        denied_tool_calls=denied_calls,
        input_tokens=state.token_usage.get("input_tokens", 0),
        output_tokens=state.token_usage.get("output_tokens", 0),
        total_tokens=state.token_usage.get("total_tokens", 0),
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


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
