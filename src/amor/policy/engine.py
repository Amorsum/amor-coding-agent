from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Sequence


class PolicyViolation(RuntimeError):
    pass


class PolicyEngine:
    """Tool-level policy; model output can never bypass these checks."""

    def __init__(
        self,
        workspace_root: Path,
        allowed_write_patterns: Sequence[str],
        allowed_commands: Sequence[Sequence[str]],
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.allowed_write_patterns = tuple(allowed_write_patterns)
        self.allowed_commands = {tuple(command) for command in allowed_commands}

    def resolve_read(self, requested_path: str) -> Path:
        target, relative = self._resolve_inside_workspace(requested_path)
        self._reject_sensitive(relative)
        return target

    def resolve_write(self, requested_path: str) -> Path:
        target, relative = self._resolve_inside_workspace(requested_path)
        self._reject_sensitive(relative)
        portable = PurePosixPath(relative.as_posix())
        if not any(portable.match(pattern) for pattern in self.allowed_write_patterns):
            raise PolicyViolation(f"write path is outside task scope: {relative.as_posix()}")
        return target

    def validate_command(self, command: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(command)
        if normalized not in self.allowed_commands:
            raise PolicyViolation("validation command is not in the task allowlist")
        return normalized

    def _resolve_inside_workspace(self, requested_path: str) -> tuple[Path, Path]:
        candidate = Path(requested_path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        target = candidate.resolve()
        try:
            relative = target.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PolicyViolation("path escapes the isolated workspace") from exc
        return target, relative

    @staticmethod
    def _reject_sensitive(relative: Path) -> None:
        for part in relative.parts:
            lowered = part.lower()
            if lowered == ".git" or lowered.startswith(".env"):
                raise PolicyViolation(f"sensitive path is denied: {relative.as_posix()}")

