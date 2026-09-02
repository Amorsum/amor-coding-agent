from __future__ import annotations

import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable

from amor.domain.models import (
    AgentPhase,
    PolicyDecision,
    ToolEvent,
    ToolResult,
)
from amor.policy import PolicyEngine, PolicyViolation
from amor.trace import TraceRecorder
from amor.workspace import IsolatedWorkspace


class ToolRegistry:
    def __init__(
        self,
        workspace: IsolatedWorkspace,
        policy: PolicyEngine,
        trace: TraceRecorder,
        task_id: str,
        max_output_chars: int,
        max_file_bytes: int,
        command_timeout_seconds: int,
    ) -> None:
        self.workspace = workspace
        self.policy = policy
        self.trace = trace
        self.task_id = task_id
        self.max_output_chars = max_output_chars
        self.max_file_bytes = max_file_bytes
        self.command_timeout_seconds = command_timeout_seconds
        self.phase = AgentPhase.INITIALIZING

    def list_files(self, path: str = ".", max_depth: int = 3) -> ToolResult:
        arguments = {"path": path, "max_depth": max_depth}

        def execute() -> ToolResult:
            root = self.policy.resolve_read(path)
            if not root.is_dir():
                return ToolResult(ok=False, summary="requested path is not a directory")
            files: list[str] = []
            relative_root = root.relative_to(self.workspace.root).as_posix()
            pathspec = "." if relative_root == "." else relative_root
            process = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", pathspec],
                cwd=self.workspace.root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
            if process.returncode != 0:
                return ToolResult(ok=False, summary="failed to enumerate Git workspace", output=self._truncate(process.stderr))
            base = None if pathspec == "." else PurePosixPath(pathspec)
            for line in sorted(process.stdout.splitlines()):
                candidate = PurePosixPath(line)
                relative_to_root = candidate if base is None else candidate.relative_to(base)
                if len(relative_to_root.parts) > max_depth:
                    continue
                if any(part in {".git", "__pycache__"} or part.startswith(".env") for part in candidate.parts):
                    continue
                files.append(candidate.as_posix())
            output = "\n".join(files)
            return ToolResult(ok=True, summary=f"listed {len(files)} files", output=self._truncate(output))

        return self._invoke("list_files", arguments, execute)

    def search_code(self, query: str, path: str = ".") -> ToolResult:
        arguments = {"query": query, "path": path}

        def execute() -> ToolResult:
            root = self.policy.resolve_read(path)
            process = subprocess.run(
                ["rg", "--line-number", "--color", "never", "--glob", "!.git/**", "--glob", "!.env*", query, str(root)],
                cwd=self.workspace.root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
            if process.returncode not in {0, 1}:
                return ToolResult(ok=False, summary="search command failed", output=self._truncate(process.stderr))
            output = self._portable_output(process.stdout)
            hits = len(output.splitlines()) if output else 0
            return ToolResult(ok=True, summary=f"found {hits} matching lines", output=self._truncate(output))

        return self._invoke("search_code", arguments, execute)

    def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> ToolResult:
        arguments = {"path": path, "start_line": start_line, "end_line": end_line}

        def execute() -> ToolResult:
            target = self.policy.resolve_read(path)
            if not target.is_file():
                return ToolResult(ok=False, summary="requested path is not a file")
            if target.stat().st_size > self.max_file_bytes:
                return ToolResult(ok=False, summary="file exceeds configured size limit")
            if start_line < 1 or end_line < start_line:
                return ToolResult(ok=False, summary="invalid line range")
            lines = target.read_text(encoding="utf-8").splitlines()
            selected = lines[start_line - 1 : end_line]
            output = "\n".join(
                f"{number:>4}: {line}"
                for number, line in enumerate(selected, start=start_line)
            )
            return ToolResult(
                ok=True,
                summary=f"read lines {start_line}-{min(end_line, len(lines))} from {path}",
                output=self._truncate(output),
                metadata={"total_lines": len(lines)},
            )

        return self._invoke("read_file", arguments, execute)

    def apply_patch(self, path: str, expected_text: str, replacement_text: str) -> ToolResult:
        arguments = {
            "path": path,
            "expected_sha256": self._hash_text(expected_text),
            "replacement_sha256": self._hash_text(replacement_text),
        }

        def execute() -> ToolResult:
            target = self.policy.resolve_write(path)
            if not target.is_file():
                return ToolResult(ok=False, summary="patch target is not an existing file")
            if target.stat().st_size > self.max_file_bytes:
                return ToolResult(ok=False, summary="patch target exceeds configured size limit")
            before_bytes = target.read_bytes()
            before = before_bytes.decode("utf-8")
            occurrences = before.count(expected_text)
            if occurrences != 1:
                return ToolResult(
                    ok=False,
                    summary=f"patch context must match exactly once; found {occurrences}",
                )
            after = before.replace(expected_text, replacement_text, 1)
            target.write_text(after, encoding="utf-8", newline="\n")
            diff = self.workspace.diff()
            return ToolResult(
                ok=True,
                summary=f"patched {path}",
                output=self._truncate(diff),
                metadata={
                    "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
                    "after_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                },
            )

        return self._invoke("apply_patch", arguments, execute)

    def run_validation(self, command: list[str]) -> ToolResult:
        arguments = {"command": command}

        def execute() -> ToolResult:
            approved = self.policy.validate_command(command)
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
                name: value
                for name, value in os.environ.items()
                if name.upper() in allowed_environment_names
            }
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                process = subprocess.run(
                    list(approved),
                    cwd=self.workspace.root,
                    env=environment,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=self.command_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                output = (exc.stdout or "") + (exc.stderr or "")
                return ToolResult(ok=False, summary="validation timed out", output=self._truncate(output))
            output = self._truncate(process.stdout + process.stderr)
            return ToolResult(
                ok=process.returncode == 0,
                summary=f"validation exited with code {process.returncode}",
                output=output,
                metadata={"returncode": process.returncode},
            )

        return self._invoke("run_validation", arguments, execute)

    def get_git_diff(self) -> ToolResult:
        def execute() -> ToolResult:
            diff = self.workspace.diff()
            return ToolResult(
                ok=True,
                summary=f"diff contains {len(diff.splitlines())} lines",
                output=self._truncate(diff),
                metadata={"changed_files": self.workspace.changed_files()},
            )

        return self._invoke("get_git_diff", {}, execute)

    def _invoke(
        self,
        name: str,
        arguments: dict[str, object],
        execute: Callable[[], ToolResult],
    ) -> ToolResult:
        started = time.perf_counter()
        decision = PolicyDecision.ALLOWED
        try:
            result = execute()
        except PolicyViolation as exc:
            decision = PolicyDecision.DENIED
            result = ToolResult(ok=False, summary=str(exc))
        except subprocess.TimeoutExpired:
            result = ToolResult(ok=False, summary="tool execution timed out")
        except (OSError, UnicodeError) as exc:
            result = ToolResult(ok=False, summary=f"tool execution failed: {exc}")
        event = ToolEvent(
            event_id=f"evt_{uuid.uuid4().hex}",
            task_id=self.task_id,
            phase=self.phase,
            tool=name,
            arguments=arguments,
            policy_result=decision,
            result=result,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self.trace.record("tool", self.phase, event)
        return result

    def _truncate(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        omitted = len(value) - self.max_output_chars
        return value[: self.max_output_chars] + f"\n... <{omitted} characters omitted>"

    def _portable_output(self, value: str) -> str:
        root = str(self.workspace.root)
        return value.replace(root + os.sep, "").replace(root + "/", "")

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
