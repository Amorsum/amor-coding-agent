from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict

from amor.benchmarks import BenchmarkLayout
from amor.domain import TaskSpec, VerificationResult
from amor.profiler import RepositoryProfiler
from amor.verifier import IndependentVerifier
from amor.workspace import IsolatedWorkspace


class DeliveryError(RuntimeError):
    pass


class DeliveryReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    delivery_id: str
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    branch_name: str
    baseline_commit: str
    patch_sha256: str
    commit_requested: bool
    commit_sha: str | None = None
    verification: VerificationResult | None = None
    workspace_path: str
    error: str | None = None
    created_at: datetime
    finished_at: datetime


def patch_digest(patch: str) -> str:
    return hashlib.sha256(_canonical_patch(patch).encode("utf-8")).hexdigest()


def deliver_verified_patch(
    *,
    project_root: Path,
    repository: Path,
    baseline_commit: str,
    patch: str,
    expected_patch_sha256: str,
    branch_name: str,
    commit_requested: bool,
    commit_message: str,
    task: TaskSpec,
    acceptance_plan_path: Path | None,
    delivery_root: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> DeliveryReport:
    """Apply one verified patch to a new local branch in a separate worktree."""

    repository = repository.resolve()
    delivery_root = delivery_root.resolve()
    created_at = _utc_now()
    delivery_id = created_at.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    canonical_patch = _canonical_patch(patch)
    actual_patch_sha256 = patch_digest(patch)
    if not patch.strip():
        raise DeliveryError("verified run does not contain a patch")
    if actual_patch_sha256 != expected_patch_sha256:
        raise DeliveryError("verified patch hash mismatch")

    profile = RepositoryProfiler().profile(repository)
    if profile.dirty_worktree:
        raise DeliveryError("repository must remain clean before delivery")
    if profile.head_commit != baseline_commit:
        raise DeliveryError("repository HEAD changed after verification")
    _validate_branch_name(repository, branch_name)
    if _branch_exists(repository, branch_name):
        raise DeliveryError(f"delivery branch already exists: {branch_name}")
    if commit_requested:
        _require_commit_identity(repository)
        if not commit_message.strip():
            raise DeliveryError("commit message must not be blank")

    workspace_root = delivery_root / "workspace"
    if delivery_root.exists():
        raise DeliveryError(f"delivery directory already exists: {delivery_root}")
    delivery_root.mkdir(parents=True)
    if _cancelled(should_cancel):
        return _write_report(
            delivery_root,
            DeliveryReport(
                delivery_id=delivery_id,
                status="CANCELLED",
                branch_name=branch_name,
                baseline_commit=baseline_commit,
                patch_sha256=actual_patch_sha256,
                commit_requested=commit_requested,
                workspace_path=str(workspace_root),
                created_at=created_at,
                finished_at=_utc_now(),
            ),
        )

    _git(
        ["worktree", "add", "-b", branch_name, str(workspace_root), baseline_commit],
        repository,
    )
    if _cancelled(should_cancel):
        return _cancelled_report(
            delivery_root,
            delivery_id,
            branch_name,
            baseline_commit,
            actual_patch_sha256,
            commit_requested,
            workspace_root,
            created_at,
        )

    _git(
        ["apply", "--binary", "--whitespace=nowarn", "-"],
        workspace_root,
        input_text=canonical_patch,
    )
    workspace = IsolatedWorkspace(repository, workspace_root, baseline_commit)
    applied_patch_sha256 = patch_digest(workspace.full_patch())
    if applied_patch_sha256 != actual_patch_sha256:
        raise DeliveryError("applied patch differs from the verified patch")
    if _cancelled(should_cancel):
        return _cancelled_report(
            delivery_root,
            delivery_id,
            branch_name,
            baseline_commit,
            actual_patch_sha256,
            commit_requested,
            workspace_root,
            created_at,
        )

    verifier = IndependentVerifier(BenchmarkLayout(project_root.resolve() / "benchmarks"))
    verification = verifier.verify(
        task,
        workspace,
        include_hidden_tests=False,
        structured_plan_path=acceptance_plan_path,
        should_cancel=should_cancel,
    )
    if _cancelled(should_cancel):
        return _cancelled_report(
            delivery_root,
            delivery_id,
            branch_name,
            baseline_commit,
            actual_patch_sha256,
            commit_requested,
            workspace_root,
            created_at,
            verification=verification,
        )
    if not verification.passed:
        return _write_report(
            delivery_root,
            DeliveryReport(
                delivery_id=delivery_id,
                status="FAILED",
                branch_name=branch_name,
                baseline_commit=baseline_commit,
                patch_sha256=actual_patch_sha256,
                commit_requested=commit_requested,
                verification=verification,
                workspace_path=str(workspace_root),
                error="verification failed after applying the patch",
                created_at=created_at,
                finished_at=_utc_now(),
            ),
        )

    commit_sha: str | None = None
    if commit_requested:
        _git(["add", "--all"], workspace_root)
        _git(["commit", "-m", commit_message.strip()], workspace_root)
        commit_sha = _git(["rev-parse", "HEAD"], workspace_root)

    return _write_report(
        delivery_root,
        DeliveryReport(
            delivery_id=delivery_id,
            status="SUCCEEDED",
            branch_name=branch_name,
            baseline_commit=baseline_commit,
            patch_sha256=actual_patch_sha256,
            commit_requested=commit_requested,
            commit_sha=commit_sha,
            verification=verification,
            workspace_path=str(workspace_root),
            created_at=created_at,
            finished_at=_utc_now(),
        ),
    )


def _cancelled_report(
    delivery_root: Path,
    delivery_id: str,
    branch_name: str,
    baseline_commit: str,
    patch_sha256: str,
    commit_requested: bool,
    workspace_root: Path,
    created_at: datetime,
    *,
    verification: VerificationResult | None = None,
) -> DeliveryReport:
    return _write_report(
        delivery_root,
        DeliveryReport(
            delivery_id=delivery_id,
            status="CANCELLED",
            branch_name=branch_name,
            baseline_commit=baseline_commit,
            patch_sha256=patch_sha256,
            commit_requested=commit_requested,
            verification=verification,
            workspace_path=str(workspace_root),
            created_at=created_at,
            finished_at=_utc_now(),
        ),
    )


def _write_report(delivery_root: Path, report: DeliveryReport) -> DeliveryReport:
    (delivery_root / "delivery-report.json").write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def _validate_branch_name(repository: Path, branch_name: str) -> None:
    if not branch_name or branch_name != branch_name.strip():
        raise DeliveryError("branch name must not be blank or padded")
    process = subprocess.run(
        ["git", "check-ref-format", "--branch", branch_name],
        cwd=repository,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise DeliveryError(process.stderr.strip() or "invalid delivery branch name")


def _branch_exists(repository: Path, branch_name: str) -> bool:
    process = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if process.returncode not in {0, 1}:
        raise DeliveryError("could not inspect existing branches")
    return process.returncode == 0


def _require_commit_identity(repository: Path) -> None:
    for key in ("user.name", "user.email"):
        process = subprocess.run(
            ["git", "config", "--get", key],
            cwd=repository,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if process.returncode != 0 or not process.stdout.strip():
            raise DeliveryError(f"Git {key} is required for a delivery commit")


def _git(args: list[str], cwd: Path, *, input_text: str | None = None) -> str:
    if input_text is None:
        process = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        stdout = process.stdout
        stderr = process.stderr
    else:
        # Bytes avoid Windows translating LF patch data to CRLF on stdin.
        process = subprocess.run(
            ["git", *args],
            cwd=cwd,
            input=input_text.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        stdout = process.stdout.decode("utf-8", errors="replace")
        stderr = process.stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise DeliveryError(stderr.strip() or stdout.strip() or "Git command failed")
    return stdout.rstrip("\r\n")


def _cancelled(should_cancel: Callable[[], bool] | None) -> bool:
    return should_cancel is not None and should_cancel()


def _canonical_patch(patch: str) -> str:
    normalized = patch.rstrip("\r\n")
    return normalized + "\n" if normalized else ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
