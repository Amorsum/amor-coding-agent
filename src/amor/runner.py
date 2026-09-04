from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from amor.benchmarks import BenchmarkLayout, load_task
from amor.domain import AgentPhase, RunReport, StepStatus, TerminalStatus
from amor.orchestrator import ScriptedOrchestrator
from amor.policy import PolicyEngine
from amor.tools import ToolRegistry
from amor.trace import TraceRecorder
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


DEFAULT_TASK_IDS = ["py_utils_average_empty", "py_utils_port_range"]


def run_demo(project_root: Path, artifacts_root: Path, task_ids: list[str] | None = None) -> list[RunReport]:
    benchmark_layout = BenchmarkLayout(project_root / "benchmarks")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    batch_dir = artifacts_root / run_id
    reports: list[RunReport] = []

    for task_id in task_ids or DEFAULT_TASK_IDS:
        task = load_task(benchmark_layout, task_id)
        task_run_dir = batch_dir / task_id
        workspace = WorkspaceManager().create_from_fixture(
            benchmark_layout.fixtures / task.fixture,
            task_run_dir,
        )
        trace_path = task_run_dir / "trace.jsonl"
        trace = TraceRecorder(trace_path, task.task_id)
        policy = PolicyEngine(
            workspace.root,
            task.allowed_paths,
            task.visible_validation_commands,
        )
        tools = ToolRegistry(
            workspace=workspace,
            policy=policy,
            trace=trace,
            task_id=task.task_id,
            max_output_chars=task.limits.max_output_chars,
            max_file_bytes=task.limits.max_file_bytes,
            command_timeout_seconds=task.limits.max_seconds,
        )
        orchestrator = ScriptedOrchestrator(task, tools, trace)
        state = orchestrator.run_until_final_verification()

        if state.phase == AgentPhase.FINAL_VERIFYING:
            verification = IndependentVerifier(benchmark_layout).verify(task, workspace)
            state.verification_attempts = 1
            trace.record("verification", AgentPhase.FINAL_VERIFYING, verification)
            terminal_phase = AgentPhase.SUCCEEDED if verification.passed else AgentPhase.FAILED
            orchestrator.machine.transition(
                terminal_phase,
                "independent verifier passed" if verification.passed else "independent verifier rejected the patch",
            )
            state.plan[3].status = StepStatus.COMPLETED if verification.passed else StepStatus.FAILED
            final_status = TerminalStatus(terminal_phase.value)
        else:
            from amor.domain import VerificationCheck, VerificationResult

            verification = VerificationResult(
                passed=False,
                checks=[VerificationCheck(name="agent_loop", passed=False, summary=f"agent stopped in {state.phase.value}")],
                failure_category="agent_loop_failure",
            )
            final_status = TerminalStatus(state.phase.value)

        diff = workspace.diff()
        report = RunReport(
            run_id=run_id,
            task=task,
            baseline_commit=workspace.baseline_commit,
            final_status=final_status,
            state=state,
            verification=verification,
            verification_history=[verification] if state.verification_attempts else [],
            git_diff=diff,
            trace_path=str(trace_path.resolve()),
            workspace_path=str(workspace.root.resolve()),
            started_at=state.started_at,
        )
        report_path = task_run_dir / "final-report.json"
        report_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        reports.append(report)

    summary_path = batch_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "passed": all(report.final_status == TerminalStatus.SUCCEEDED for report in reports),
                "tasks": [
                    {
                        "task_id": report.task.task_id,
                        "status": report.final_status.value,
                        "report": str((batch_dir / report.task.task_id / "final-report.json").resolve()),
                    }
                    for report in reports
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return reports
