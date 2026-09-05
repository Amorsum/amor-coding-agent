import sys
import time
from pathlib import Path
from threading import Event, Timer

from amor.domain import RunLimits, TaskSpec
from amor.verifier import IndependentVerifier


def test_verification_subprocess_can_be_cancelled(tmp_path: Path) -> None:
    cancelled = Event()
    timer = Timer(0.2, cancelled.set)
    task = TaskSpec(
        task_id="cancel-test",
        repository=str(tmp_path),
        instruction="cancel a long validation",
        acceptance_criteria=["cancelled"],
        allowed_paths=["src/**"],
        visible_validation_commands=[],
        limits=RunLimits(max_seconds=30),
    )
    timer.start()
    started = time.monotonic()
    try:
        check = IndependentVerifier._run_check(
            "visible_tests_1",
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            task,
            cancelled.is_set,
        )
    finally:
        timer.cancel()

    assert not check.passed
    assert "cancelled" in check.summary
    assert time.monotonic() - started < 5
