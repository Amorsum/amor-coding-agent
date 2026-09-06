from pathlib import Path

import pytest

from amor.benchmarks import BenchmarkLayout
from amor.profiler import RepositoryProfiler
from amor.workspace import (
    WorkspaceManager,
    create_working_tree_snapshot,
    working_tree_matches,
)
from amor.workspace.manager import _run_git
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


def test_protected_snapshot_captures_dirty_tree_without_touching_source(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "fixture",
    )
    repository = workspace.source_repository
    original_branch = _run_git(["branch", "--show-current"], repository)
    tracked = repository / "src" / "calculator.py"
    tracked.write_text(tracked.read_text(encoding="utf-8") + "\nSNAPSHOT_MARKER = True\n", encoding="utf-8")
    (repository / "notes.txt").write_text("untracked snapshot file\n", encoding="utf-8")
    status_before = _run_git(["status", "--short"], repository)

    snapshot = create_working_tree_snapshot(repository)

    assert snapshot.dirty is True
    assert snapshot.baseline_commit != snapshot.source_head_commit
    assert snapshot.ref == f"refs/amor/snapshots/{snapshot.baseline_commit}"
    assert _run_git(["rev-parse", snapshot.ref], repository) == snapshot.baseline_commit
    assert _run_git(["branch", "--show-current"], repository) == original_branch
    assert _run_git(["status", "--short"], repository) == status_before
    assert working_tree_matches(
        repository,
        source_head_commit=snapshot.source_head_commit,
        tree_hash=snapshot.tree_hash,
    )

    isolated = WorkspaceManager().create_from_repository(
        repository,
        tmp_path / "snapshot-run",
        baseline_commit=snapshot.baseline_commit,
        require_clean=False,
    )
    assert "SNAPSHOT_MARKER = True" in (isolated.root / "src" / "calculator.py").read_text(encoding="utf-8")
    assert (isolated.root / "notes.txt").read_text(encoding="utf-8") == "untracked snapshot file\n"

    (repository / "notes.txt").write_text("changed after snapshot\n", encoding="utf-8")
    assert not working_tree_matches(
        repository,
        source_head_commit=snapshot.source_head_commit,
        tree_hash=snapshot.tree_hash,
    )
