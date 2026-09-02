from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from amor.domain import RepositoryProfile
from amor.workspace.manager import WorkspaceError, _run_git


class RepositoryProfiler:
    """Conservative repository discovery; suggestions are never executed automatically."""

    def profile(self, repository: Path) -> RepositoryProfile:
        repository = repository.resolve()
        if not repository.is_dir():
            raise WorkspaceError(f"repository does not exist: {repository}")
        top_level = Path(_run_git(["rev-parse", "--show-toplevel"], repository)).resolve()
        if top_level != repository:
            raise WorkspaceError(f"select the Git repository root instead: {top_level}")

        tracked_files = self._tracked_files(repository)
        lowered = {path.lower() for path in tracked_files}
        languages: list[str] = []
        if any(path.endswith(".py") for path in lowered):
            languages.append("Python")
        if any(path.endswith((".ts", ".tsx")) for path in lowered):
            languages.append("TypeScript")
        if any(path.endswith((".js", ".jsx")) for path in lowered):
            languages.append("JavaScript")

        package_manager = self._package_manager(lowered)
        suggested_commands: list[list[str]] = []
        if "Python" in languages:
            if any(path.startswith("tests/") and path.endswith(".py") for path in lowered):
                if "pytest.ini" in lowered or "conftest.py" in lowered or "pyproject.toml" in lowered:
                    suggested_commands.append(["python", "-m", "pytest"])
                else:
                    suggested_commands.append(["python", "-m", "unittest", "discover", "-s", "tests", "-v"])
        if "package.json" in lowered:
            executable = "npm.cmd" if sys.platform == "win32" else "npm"
            suggested_commands.append([executable, "test", "--", "--runInBand"])

        source_roots = [name for name in ("src", "app", "lib") if any(path.startswith(name + "/") for path in lowered)]
        test_roots = [name for name in ("tests", "test", "__tests__") if any(path.startswith(name + "/") for path in lowered)]
        instruction_files = [path for path in tracked_files if Path(path).name.lower() == "agents.md"]

        try:
            head_commit = _run_git(["rev-parse", "HEAD"], repository)
        except WorkspaceError:
            head_commit = ""

        return RepositoryProfile(
            root=str(repository),
            languages=languages,
            package_manager=package_manager,
            suggested_validation_commands=suggested_commands,
            source_roots=source_roots,
            test_roots=test_roots,
            instruction_files=instruction_files,
            dirty_worktree=bool(_run_git(["status", "--short"], repository)),
            head_commit=head_commit,
        )

    @staticmethod
    def _tracked_files(repository: Path) -> list[str]:
        process = subprocess.run(
            ["git", "ls-files"],
            cwd=repository,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise WorkspaceError(process.stderr.strip() or "failed to list tracked files")
        return [line.replace("\\", "/") for line in process.stdout.splitlines() if line]

    @staticmethod
    def _package_manager(files: set[str]) -> str | None:
        if "uv.lock" in files:
            return "uv"
        if "poetry.lock" in files:
            return "poetry"
        if "requirements.txt" in files or "pyproject.toml" in files:
            return "pip"
        if "pnpm-lock.yaml" in files:
            return "pnpm"
        if "yarn.lock" in files:
            return "yarn"
        if "package-lock.json" in files or "package.json" in files:
            return "npm"
        return None
