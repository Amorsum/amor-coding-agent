from amor.context import ContextManager, ContextStrategy
from amor.domain import ToolResult


def test_context_manager_compresses_to_total_budget_and_records_evidence() -> None:
    manager = ContextManager(ContextStrategy.SEARCH_FIRST, char_budget=1_000)
    result = ToolResult(ok=True, summary="large validation output", output="A" * 800 + "B" * 800)

    prepared, evidence = manager.prepare_tool_result(
        "run_validation",
        {"command": ["python", "-m", "pytest"]},
        result,
    )

    assert len(prepared.output) == 1_000
    assert prepared.output.startswith("A")
    assert prepared.output.endswith("B")
    assert evidence.compressed
    assert evidence.requested_chars == 1_600
    assert evidence.retained_chars == 1_000
    assert evidence.kind == "validation_log"


def test_context_manager_tracks_repeated_reads_and_empty_searches() -> None:
    manager = ContextManager("broad", char_budget=2_000)
    read = ToolResult(ok=True, summary="read source", output="   1: value = 1")

    _, first = manager.prepare_tool_result(
        "read_file",
        {"path": "src/value.py", "start_line": 1, "end_line": 20},
        read,
    )
    _, second = manager.prepare_tool_result(
        "read_file",
        {"path": "src/value.py", "start_line": 1, "end_line": 20},
        read,
    )
    _, search = manager.prepare_tool_result(
        "search_code",
        {"query": "missing", "path": "src"},
        ToolResult(ok=True, summary="found 0 matching lines"),
    )

    assert not first.repeated
    assert second.repeated
    assert first.lines_read == 1
    assert search.zero_result


def test_context_manager_never_exceeds_budget_across_turns() -> None:
    manager = ContextManager("search-first", char_budget=1_000)

    first, _ = manager.prepare_tool_result(
        "search_code",
        {"query": "x", "path": "."},
        ToolResult(ok=True, summary="first", output="x" * 900),
    )
    second, evidence = manager.prepare_tool_result(
        "read_file",
        {"path": "src/x.py", "start_line": 1, "end_line": 200},
        ToolResult(ok=True, summary="second", output="y" * 900),
    )

    assert len(first.output) == 900
    assert len(second.output) == 100
    assert manager.retained_chars == 1_000
    assert evidence.compressed
