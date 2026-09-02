from amor.domain import ToolResult
from amor.orchestrator.progress import ProgressGuard


def test_blocks_third_identical_tool_call() -> None:
    guard = ProgressGuard(max_identical_calls=3)

    assert guard.observe_call("search_code", {"query": "x", "path": "src"}) is None
    assert guard.observe_call("search_code", {"query": "x", "path": "src"}) is None
    reason = guard.observe_call("search_code", {"query": "x", "path": "src"})

    assert reason is not None
    assert "repeated 3 times" in reason


def test_blocks_same_failure_when_diff_does_not_change() -> None:
    guard = ProgressGuard(max_identical_failures=2)
    failure = ToolResult(ok=False, summary="tests failed", output="same assertion")

    assert guard.observe_result("run_validation", failure, "diff") is None
    reason = guard.observe_result("run_validation", failure, "diff")

    assert reason == "same failed run_validation result repeated without a diff change"


def test_successful_diff_change_resets_failure_streak() -> None:
    guard = ProgressGuard(max_identical_failures=2)
    failure = ToolResult(ok=False, summary="failed")

    guard.observe_result("apply_patch", failure, "diff-a")
    guard.observe_result("apply_patch", ToolResult(ok=True, summary="patched"), "diff-b")

    assert guard.observe_result("apply_patch", failure, "diff-b") is None
