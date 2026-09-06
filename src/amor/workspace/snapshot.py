from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from amor.workspace.manager import WorkspaceError, _run_git


@dataclass(frozen=True)
class RepositorySnapshot:
    source_head_commit: str
    tree_hash: str
    baseline_commit: str
    ref: str | None
    changed_files: list[str]

    @property
    def dirty(self) -> bool:
        return bool(self.changed_files)


def inspect_working_tree(repository: Path) -> RepositorySnapshot:
    repository = repository.resolve()
    source_head = _run_git(["rev-parse", "HEAD"], repository)
    status = _run_git(["status", "--short"], repository)
    changed_files = [line[3:].replace("\\", "/") for line in status.splitlines() if line]
    with tempfile.TemporaryDirectory(prefix="amor-snapshot-index-") as temporary:
        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        _run_git(["read-tree", source_head], repository, environment)
        _run_git(["add", "--all", "--", "."], repository, environment)
        tree_hash = _run_git(["write-tree"], repository, environment)
    return RepositorySnapshot(
        source_head_commit=source_head,
        tree_hash=tree_hash,
        baseline_commit=source_head,
        ref=None,
        changed_files=changed_files,
    )


def create_working_tree_snapshot(repository: Path) -> RepositorySnapshot:
    inspected = inspect_working_tree(repository)
    if not inspected.dirty:
        return inspected
    head_tree = _run_git(["rev-parse", f"{inspected.source_head_commit}^{{tree}}"], repository)
    if inspected.tree_hash == head_tree:
        raise WorkspaceError(
            "dirty submodule or unsupported working-tree state cannot be captured safely"
        )
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "AMOR Snapshot",
            "GIT_AUTHOR_EMAIL": "amor-snapshot@example.invalid",
            "GIT_COMMITTER_NAME": "AMOR Snapshot",
            "GIT_COMMITTER_EMAIL": "amor-snapshot@example.invalid",
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
    )
    commit = _run_git(
        ["commit-tree", inspected.tree_hash, "-p", inspected.source_head_commit, "-m", "AMOR working-tree snapshot"],
        repository,
        environment,
    )
    reference = f"refs/amor/snapshots/{commit}"
    _run_git(["update-ref", reference, commit], repository)
    return RepositorySnapshot(
        source_head_commit=inspected.source_head_commit,
        tree_hash=inspected.tree_hash,
        baseline_commit=commit,
        ref=reference,
        changed_files=inspected.changed_files,
    )


def working_tree_matches(
    repository: Path,
    *,
    source_head_commit: str,
    tree_hash: str,
) -> bool:
    current = inspect_working_tree(repository)
    return current.source_head_commit == source_head_commit and current.tree_hash == tree_hash
