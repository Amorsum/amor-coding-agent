from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

from amor.benchmarks.loader import BenchmarkLayout, load_hidden_suite
from amor.domain import TaskSpec, VerificationCheck, VerificationResult
from amor.workspace import IsolatedWorkspace


class IndependentVerifier:
    """Final acceptance authority, deliberately separate from the agent tool loop."""

    def __init__(self, layout: BenchmarkLayout) -> None:
        self.layout = layout

    def verify(
        self,
        task: TaskSpec,
        workspace: IsolatedWorkspace,
        *,
        include_hidden_tests: bool = True,
    ) -> VerificationResult:
        checks: list[VerificationCheck] = []

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
            checks.append(self._run_check(f"visible_tests_{index}", command, workspace.root, task))

        if not include_hidden_tests:
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
        checks.append(self._run_check("hidden_tests", hidden_command, workspace.root, task))

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
    ) -> VerificationCheck:
        started = time.perf_counter()
        allowed_environment_names = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed_environment_names
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=task.limits.max_seconds,
                check=False,
            )
            combined = (process.stdout + process.stderr).strip()
            max_chars = min(task.limits.max_output_chars, 4_000)
            if len(combined) > max_chars:
                combined = combined[:max_chars] + "\n... <verifier output truncated>"
            summary = combined or f"command exited with code {process.returncode}"
            return VerificationCheck(
                name=name,
                passed=process.returncode == 0,
                summary=summary,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except subprocess.TimeoutExpired:
            return VerificationCheck(
                name=name,
                passed=False,
                summary="verification timed out",
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
