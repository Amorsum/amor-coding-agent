import subprocess
import sys
from pathlib import Path

from amor.benchmarks import BenchmarkLayout
from amor.delivery import deliver_verified_patch, patch_digest
from amor.domain import RunLimits, TaskSpec
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    ).stdout.strip()


def test_verified_patch_is_delivered_to_separate_branch_and_reverified(tmp_path: Path) -> None:
    fixture = WorkspaceManager().create_from_fixture(
        BenchmarkLayout(project_root() / "benchmarks").fixtures / "python_utils",
        tmp_path / "fixture",
    )
    verified = WorkspaceManager().create_from_repository(
        fixture.source_repository,
        tmp_path / "verified-run",
    )
    calculator = verified.root / "src" / "calculator.py"
    calculator.write_text(
        calculator.read_text(encoding="utf-8").replace(
            "    return sum(values) / len(values)\n",
            "    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
        ),
        encoding="utf-8",
        newline="\n",
    )
    patch = verified.full_patch()
    task = TaskSpec(
        task_id="delivery-task",
        repository=str(fixture.source_repository),
        instruction="average([]) returns 0.0",
        acceptance_criteria=["empty average returns 0.0"],
        allowed_paths=["src/**"],
        visible_validation_commands=[
            [
                sys.executable,
                "-c",
                "from src.calculator import average; assert average([]) == 0.0",
            ]
        ],
        limits=RunLimits(max_seconds=30),
    )
    source_head = git(fixture.source_repository, "rev-parse", "HEAD")
    source_branch = git(fixture.source_repository, "branch", "--show-current")

    report = deliver_verified_patch(
        project_root=project_root(),
        repository=fixture.source_repository,
        baseline_commit=fixture.baseline_commit,
        patch=patch,
        expected_patch_sha256=patch_digest(patch),
        branch_name="amor/delivery-test",
        commit_requested=True,
        commit_message="fix: handle empty averages",
        task=task,
        acceptance_plan_path=None,
        delivery_root=tmp_path / "delivery",
    )

    assert report.status == "SUCCEEDED"
    assert report.verification is not None and report.verification.passed
    assert report.commit_sha
    assert git(fixture.source_repository, "rev-parse", "HEAD") == source_head
    assert git(fixture.source_repository, "branch", "--show-current") == source_branch == "main"
    assert git(fixture.source_repository, "status", "--short") == ""
    delivered_source = git(
        fixture.source_repository,
        "show",
        "amor/delivery-test:src/calculator.py",
    )
    assert "if not values:" in delivered_source
    assert (tmp_path / "delivery" / "delivery-report.json").is_file()
