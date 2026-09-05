from __future__ import annotations

import sys
import time
from pathlib import Path, PurePosixPath
from typing import Callable

from amor.benchmarks.loader import BenchmarkLayout, load_hidden_suite
from amor.domain import TaskSpec, VerificationCheck, VerificationResult
from amor.execution import CommandExecutor, HostCommandExecutor, build_command_executor
from amor.workspace import IsolatedWorkspace


class IndependentVerifier:
    """Final acceptance authority, deliberately separate from the agent tool loop."""

    def __init__(
        self,
        layout: BenchmarkLayout,
        command_executor: CommandExecutor | None = None,
    ) -> None:
        self.layout = layout
        self.command_executor = command_executor

    def verify(
        self,
        task: TaskSpec,
        workspace: IsolatedWorkspace,
        *,
        include_hidden_tests: bool = True,
        structured_plan_path: Path | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> VerificationResult:
        checks: list[VerificationCheck] = []
        executor = self.command_executor or build_command_executor(workspace.root, task.sandbox)

        changed_files = workspace.changed_files()
        scope_passed = bool(changed_files) and all(
            any(PurePosixPath(path).match(pattern) for pattern in task.allowed_paths)
            for path in changed_files
        )
        if not changed_files:
            scope_summary = "no patch was produced"
        elif scope_passed:
            scope_summary = f"changed files are in scope: {', '.join(changed_files)}"
        else:
            scope_summary = f"out-of-scope change detected: {', '.join(changed_files)}"
        checks.append(VerificationCheck(name="scope", passed=scope_passed, summary=scope_summary))

        checks.append(self._static_check(workspace.root, changed_files))

        for index, command in enumerate(task.visible_validation_commands, start=1):
            if should_cancel is not None and should_cancel():
                checks.append(
                    VerificationCheck(
                        name=f"visible_tests_{index}",
                        passed=False,
                        summary="verification cancelled by user",
                    )
                )
                break
            checks.append(
                self._run_check(
                    f"visible_tests_{index}",
                    command,
                    workspace.root,
                    task,
                    should_cancel,
                    command_executor=executor,
                )
            )
            if should_cancel is not None and should_cancel():
                break

        if structured_plan_path is not None and not (should_cancel and should_cancel()):
            plan_path = structured_plan_path.resolve()
            try:
                plan_path.relative_to(workspace.root.resolve())
            except ValueError:
                runner_path = Path(__file__).with_name("structured_cases.py").resolve()
                if executor.mode.value == "docker":
                    source_root = Path(__file__).resolve().parents[2]
                    command = [
                        sys.executable,
                        "-I",
                        "-c",
                        (
                            "import runpy,sys;"
                            "sys.path.insert(0,sys.argv[1]);"
                            "sys.argv=[sys.argv[2],sys.argv[3]];"
                            "runpy.run_path(sys.argv[0],run_name='__main__')"
                        ),
                        str(source_root),
                        str(runner_path),
                        str(plan_path),
                    ]
                    read_only_inputs = (source_root, plan_path)
                else:
                    command = [sys.executable, "-I", str(runner_path), str(plan_path)]
                    read_only_inputs = ()
                checks.append(
                    self._run_check(
                        "external_acceptance",
                        command,
                        workspace.root,
                        task,
                        should_cancel,
                        command_executor=executor,
                        read_only_inputs=read_only_inputs,
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        name="external_acceptance",
                        passed=False,
                        summary="structured acceptance plan must remain outside the agent workspace",
                    )
                )

        if not include_hidden_tests or (should_cancel and should_cancel()):
            passed = all(check.passed for check in checks)
            return VerificationResult(
                passed=passed,
                checks=checks,
                failure_category=None if passed else self._failure_category(checks),
            )

        hidden_suite = load_hidden_suite(self.layout, task.task_id)
        try:
            hidden_suite.relative_to(workspace.root.resolve())
        except ValueError:
            pass
        else:
            checks.append(
                VerificationCheck(
                    name="hidden_tests",
                    passed=False,
                    summary="hidden tests must remain outside the agent workspace",
                )
            )
            return VerificationResult(
                passed=False,
                checks=checks,
                failure_category="verifier_configuration_error",
            )

        hidden_command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(hidden_suite),
            "-v",
        ]
        checks.append(
            self._run_check(
                "hidden_tests",
                hidden_command,
                workspace.root,
                task,
                should_cancel,
                command_executor=executor,
                read_only_inputs=(hidden_suite,),
            )
        )

        passed = all(check.passed for check in checks)
        return VerificationResult(
            passed=passed,
            checks=checks,
            failure_category=None if passed else self._failure_category(checks),
        )

    @staticmethod
    def _run_check(
        name: str,
        command: list[str],
        cwd: Path,
        task: TaskSpec,
        should_cancel: Callable[[], bool] | None = None,
        *,
        command_executor: CommandExecutor | None = None,
        read_only_inputs: tuple[Path, ...] = (),
    ) -> VerificationCheck:
        started = time.perf_counter()
        executor = command_executor or HostCommandExecutor()
        outcome = executor.run(
            command,
            cwd=cwd,
            timeout_seconds=task.limits.max_seconds,
            max_output_chars=min(task.limits.max_output_chars, 4_000),
            should_cancel=should_cancel,
            read_only_inputs=read_only_inputs,
        )
        if outcome.cancelled:
            summary = "verification cancelled by user"
        elif outcome.timed_out:
            summary = "verification timed out"
        elif outcome.startup_error:
            summary = f"verification command could not start: {outcome.startup_error}"
        elif outcome.resource_exhausted:
            summary = f"verification stopped: {outcome.resource_exhausted}"
        else:
            summary = outcome.output.strip() or f"command exited with code {outcome.returncode}"
        return VerificationCheck(
            name=name,
            passed=outcome.ok,
            summary=summary,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _failure_category(checks: list[VerificationCheck]) -> str:
        failed_names = {check.name for check in checks if not check.passed}
        if "scope" in failed_names:
            return "scope_violation_or_missing_patch"
        if "static_compile" in failed_names:
            return "static_validation_failure"
        if "hidden_tests" in failed_names:
            return "behavior_not_fixed"
        if "external_acceptance" in failed_names:
            return "acceptance_contract_failure"
        return "visible_validation_failure"

    @staticmethod
    def _static_check(workspace_root: Path, changed_files: list[str]) -> VerificationCheck:
        started = time.perf_counter()
        checked = 0
        try:
            python_paths = [
                workspace_root / relative
                for relative in changed_files
                if relative.endswith(".py")
            ]
            for path in sorted(python_paths):
                if not path.is_file():
                    continue
                source = path.read_text(encoding="utf-8")
                compile(source, str(path), "exec")
                checked += 1
        except (OSError, UnicodeError, SyntaxError) as exc:
            return VerificationCheck(
                name="static_compile",
                passed=False,
                summary=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return VerificationCheck(
            name="static_compile",
            passed=True,
            summary=f"compiled {checked} Python source files in memory",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
