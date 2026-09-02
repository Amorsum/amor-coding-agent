from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from amor.domain import ToolResult


class ContextStrategy(StrEnum):
    BROAD = "broad"
    SEARCH_FIRST = "search-first"


SUPPORTED_CONTEXT_STRATEGIES = tuple(strategy.value for strategy in ContextStrategy)


class ContextEvidence(BaseModel):
    sequence: int
    strategy: ContextStrategy
    tool: str
    kind: str
    path: str | None = None
    reason: str
    successful: bool
    requested_chars: int
    retained_chars: int
    estimated_tokens: int
    lines_read: int = 0
    repeated: bool = False
    zero_result: bool = False
    compressed: bool = False


class ContextManager:
    """Selects bounded tool evidence and records why it entered model context."""

    def __init__(self, strategy: ContextStrategy | str, char_budget: int) -> None:
        self.strategy = ContextStrategy(strategy)
        if char_budget < 1_000:
            raise ValueError("context budget must be at least 1000 characters")
        self.char_budget = char_budget
        self.retained_chars = 0
        self._sequence = 0
        self._read_keys: set[tuple[str, int, int]] = set()

    def prepare_tool_result(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: ToolResult,
    ) -> tuple[ToolResult, ContextEvidence]:
        self._sequence += 1
        output = result.output
        requested_chars = len(output)
        available = max(0, self.char_budget - self.retained_chars)
        retained_output = self._retain(output, available, result.summary)
        retained_chars = len(retained_output)
        self.retained_chars += retained_chars

        path = arguments.get("path")
        normalized_path = path if isinstance(path, str) else None
        repeated = False
        lines_read = 0
        if tool == "read_file" and normalized_path:
            start_line = int(arguments.get("start_line", 1))
            end_line = int(arguments.get("end_line", start_line))
            read_key = (normalized_path, start_line, end_line)
            repeated = read_key in self._read_keys
            self._read_keys.add(read_key)
            if result.ok:
                lines_read = len(output.splitlines())

        zero_result = tool == "search_code" and result.ok and not output.strip()
        evidence = ContextEvidence(
            sequence=self._sequence,
            strategy=self.strategy,
            tool=tool,
            kind=self._kind(tool),
            path=normalized_path,
            reason=self._reason(tool, arguments, result),
            successful=result.ok,
            requested_chars=requested_chars,
            retained_chars=retained_chars,
            estimated_tokens=(retained_chars + 3) // 4,
            lines_read=lines_read,
            repeated=repeated,
            zero_result=zero_result,
            compressed=retained_output != output,
        )
        metadata = dict(result.metadata)
        metadata.update(
            {
                "context_strategy": self.strategy.value,
                "context_requested_chars": requested_chars,
                "context_retained_chars": retained_chars,
                "context_compressed": evidence.compressed,
            }
        )
        return result.model_copy(update={"output": retained_output, "metadata": metadata}), evidence

    @staticmethod
    def _kind(tool: str) -> str:
        return {
            "list_files": "repository_structure",
            "search_code": "search_result",
            "read_file": "source_code",
            "run_validation": "validation_log",
            "get_git_diff": "git_diff",
        }.get(tool, "tool_result")

    @staticmethod
    def _reason(tool: str, arguments: dict[str, Any], result: ToolResult) -> str:
        if tool == "search_code":
            return f"model searched for {arguments.get('query', '')!r}; {result.summary}"
        if tool == "read_file":
            return (
                f"model requested {arguments.get('path', '')}:"
                f"{arguments.get('start_line', 1)}-{arguments.get('end_line', 200)}; {result.summary}"
            )
        if tool == "run_validation":
            return f"approved validation feedback; {result.summary}"
        if tool == "get_git_diff":
            return f"patch review evidence; {result.summary}"
        return f"model requested {tool}; {result.summary}"

    @staticmethod
    def _retain(output: str, available: int, summary: str) -> str:
        if len(output) <= available:
            return output
        marker = f"\n... <context compressed; tool summary: {summary}>\n"
        if available <= len(marker):
            return marker[:available]
        content_budget = available - len(marker)
        head_size = (content_budget * 2) // 3
        tail_size = content_budget - head_size
        tail = output[-tail_size:] if tail_size else ""
        return output[:head_size] + marker + tail
