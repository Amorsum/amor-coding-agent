from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from amor.benchmarks import BenchmarkLayout
from amor.context import ContextStrategy
from amor.domain import (
    AgentPhase,
    RunLimits,
    RunReport,
    StepStatus,
    TaskSpec,
    TerminalStatus,
    VerificationCheck,
    VerificationResult,
)
from amor.orchestrator import ModelDrivenOrchestrator, PlanningStrategy
from amor.policy import PolicyEngine
from amor.profiler import RepositoryProfiler
from amor.providers import ModelProvider
from amor.tools import ToolRegistry
from amor.trace import TraceRecorder
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


def run_repository_task(
    *,
    project_root: Path,
    repository: Path,
    instruction: str,
    acceptance_criteria: list[str],
    allowed_paths: list[str],
    validation_commands: list[list[str]],
    provider_name: str,
    model: str,
    provider: ModelProvider,
    artifacts_root: Path,
    limits: RunLimits,
    context_strategy: ContextStrategy | str = ContextStrategy.SEARCH_FIRST,
    context_budget_chars: int = 40_000,
    planning_strategy: PlanningStrategy | str = PlanningStrategy.STRUCTURED,
) -> RunReport:
    repository = repository.resolve()
    profile = RepositoryProfiler().profile(repository)
    if profile.dirty_worktree:
        raise RuntimeError("repository must be clean before an isolated AMOR run")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    task_id = f"local_{uuid.uuid4().hex[:12]}"
    task = TaskSpec(
        task_id=task_id,
        repository=str(repository),
        instruction=instruction,
        acceptance_criteria=acceptance_criteria or ["all user-approved validation commands pass"],
        allowed_paths=allowed_paths,
        visible_validation_commands=validation_commands,
        provider=provider_name,
        model=model,
        limits=limits,
    )
    run_dir = artifacts_root.resolve() / run_id / task_id
    workspace = WorkspaceManager().create_from_repository(repository, run_dir)
    trace_path = run_dir / "trace.jsonl"
    trace = TraceRecorder(trace_path, task_id)
    profile_path = run_dir / "repository-profile.json"
    profile_path.write_text(
        json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    policy = PolicyEngine(workspace.root, allowed_paths, validation_commands)
    tools = ToolRegistry(
        workspace,
        policy,
        trace,
        task_id,
        limits.max_output_chars,
        limits.max_file_bytes,
        limits.max_seconds,
    )
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

    if state.phase == AgentPhase.FINAL_VERIFYING:
        verifier = IndependentVerifier(BenchmarkLayout(project_root / "benchmarks"))
        verification = verifier.verify(task, workspace, include_hidden_tests=False)
        trace.record("verification", AgentPhase.FINAL_VERIFYING, verification)
        terminal_phase = AgentPhase.SUCCEEDED if verification.passed else AgentPhase.FAILED
        orchestrator.machine.transition(
            terminal_phase,
            "independent verifier passed" if verification.passed else "independent verifier rejected the patch",
        )
        if verification.passed:
            for step in state.plan:
                step.status = StepStatus.COMPLETED
        elif state.plan:
            state.plan[-1].status = StepStatus.FAILED
        final_status = TerminalStatus(terminal_phase.value)
    else:
        verification = VerificationResult(
            passed=False,
            checks=[
                VerificationCheck(
                    name="agent_loop",
                    passed=False,
                    summary=f"agent stopped in {state.phase.value}",
                )
            ],
            failure_category="agent_loop_failure",
        )
        final_status = TerminalStatus(state.phase.value)

    report = RunReport(
        run_id=run_id,
        task=task,
        baseline_commit=workspace.baseline_commit,
        final_status=final_status,
        state=state,
        verification=verification,
        git_diff=workspace.diff(),
        trace_path=str(trace_path.resolve()),
        workspace_path=str(workspace.root.resolve()),
        started_at=state.started_at,
    )
    report_path = run_dir / "final-report.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report
