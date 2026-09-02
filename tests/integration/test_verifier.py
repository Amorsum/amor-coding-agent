from pathlib import Path

import pytest

from amor.benchmarks import BenchmarkLayout, load_task
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "task_id",
    [
        "py_utils_average_empty",
        "py_utils_port_range",
        "py_utils_order_discount",
        "py_utils_retry_type",
    ],
)
def test_verifier_rejects_unmodified_buggy_baseline(tmp_path: Path, task_id: str) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    task = load_task(layout, task_id)
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / task.fixture,
        tmp_path / task_id,
    )

    result = IndependentVerifier(layout).verify(task, workspace)

    assert not result.passed
    assert not next(check for check in result.checks if check.name == "scope").passed
    assert not next(check for check in result.checks if check.name == "hidden_tests").passed
