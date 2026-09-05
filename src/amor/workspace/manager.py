from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


def _run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise WorkspaceError(process.stderr.strip() or process.stdout.strip())
    # Porcelain status uses leading spaces as data; only trim line terminators.
    return process.stdout.rstrip("\r\n")


@dataclass(frozen=True)
class IsolatedWorkspace:
    source_repository: Path
    root: Path
    baseline_commit: str

    def diff(self) -> str:
        return _run_git(["diff", "--no-ext-diff", "--"], self.root)

    def full_patch(self) -> str:
        # A temporary index captures tracked, deleted, renamed, and new files without
        # mutating the detached worktree's real index. Plain `git diff` omits untracked
        # files and therefore cannot be used as a complete delivery artifact.
        with tempfile.TemporaryDirectory(prefix="amor-index-") as temporary:
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
            _run_git(["read-tree", "HEAD"], self.root, environment)
            _run_git(["add", "--all"], self.root, environment)
            patch = _run_git(
                ["diff", "--cached", "--binary", "--no-ext-diff", "--"],
                self.root,
                environment,
            )
            return patch + "\n" if patch else ""

    def changed_files(self) -> list[str]:
        output = _run_git(["status", "--short"], self.root)
        if not output:
            return []
        return [line[3:].replace("\\", "/") for line in output.splitlines()]


class WorkspaceManager:
    """Build a deterministic fixture repository and edit only a detached worktree."""

    def create_from_fixture(self, fixture_dir: Path, run_dir: Path) -> IsolatedWorkspace:
        fixture_dir = fixture_dir.resolve()
        run_dir = run_dir.resolve()
        if not fixture_dir.is_dir():
            raise WorkspaceError(f"fixture does not exist: {fixture_dir}")

        source_repository = run_dir / "source-repository"
        workspace_root = run_dir / "workspace"
        if source_repository.exists() or workspace_root.exists():
            raise WorkspaceError(f"run directory is not empty: {run_dir}")

        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            fixture_dir,
            source_repository,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
        _run_git(["init", "-b", "main"], source_repository)
        _run_git(["config", "user.name", "AMOR Fixture Builder"], source_repository)
        _run_git(["config", "user.email", "amor@example.invalid"], source_repository)
        _run_git(["config", "core.autocrlf", "false"], source_repository)
        _run_git(["add", "--all"], source_repository)

        fixed_env = os.environ.copy()
        fixed_env.update(
            {
                "GIT_AUTHOR_DATE": "2025-01-01T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2025-01-01T00:00:00+00:00",
            }
        )
        _run_git(["commit", "-m", "Deterministic benchmark baseline"], source_repository, fixed_env)
        baseline = _run_git(["rev-parse", "HEAD"], source_repository)
        _run_git(["worktree", "add", "--detach", str(workspace_root), baseline], source_repository)
        return IsolatedWorkspace(source_repository, workspace_root, baseline)

    def create_from_repository(self, repository: Path, run_dir: Path) -> IsolatedWorkspace:
        repository = repository.resolve()
        run_dir = run_dir.resolve()
        if not repository.is_dir():
            raise WorkspaceError(f"repository does not exist: {repository}")

        top_level = Path(_run_git(["rev-parse", "--show-toplevel"], repository)).resolve()
        if top_level != repository:
            raise WorkspaceError(f"select the Git repository root instead: {top_level}")
        status = _run_git(["status", "--short"], repository)
        if status:
            raise WorkspaceError(
                "repository has uncommitted or untracked changes; commit/stash them before creating an isolated run"
            )

        baseline = _run_git(["rev-parse", "HEAD"], repository)
        workspace_root = run_dir / "workspace"
        if workspace_root.exists():
            raise WorkspaceError(f"run workspace already exists: {workspace_root}")
        run_dir.mkdir(parents=True, exist_ok=True)
        _run_git(["worktree", "add", "--detach", str(workspace_root), baseline], repository)
        return IsolatedWorkspace(repository, workspace_root, baseline)
