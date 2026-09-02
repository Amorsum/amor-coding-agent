from pathlib import Path

import pytest

from amor.benchmarks import BenchmarkLayout
from amor.profiler import RepositoryProfiler
from amor.workspace import WorkspaceManager
from amor.workspace.manager import WorkspaceError


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_profiles_python_repository_without_running_suggestions(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "fixture",
    )

    profile = RepositoryProfiler().profile(workspace.source_repository)

    assert profile.languages == ["Python"]
    assert profile.package_manager is None
    assert profile.source_roots == ["src"]
    assert profile.test_roots == ["tests"]
    assert profile.dirty_worktree is False
    assert profile.suggested_validation_commands


def test_repository_worktree_creation_rejects_uncommitted_changes(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "fixture",
    )
    (workspace.source_repository / "README.md").write_text("local change\n", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="uncommitted or untracked"):
        WorkspaceManager().create_from_repository(
            workspace.source_repository,
            tmp_path / "should-not-exist",
        )
