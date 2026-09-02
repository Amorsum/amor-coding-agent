from __future__ import annotations

from typing import Any

from amor.providers.base import ModelTurn, ProviderError


class FakeModelProvider:
    """Deterministic provider used by orchestration tests; it never performs network I/O."""

    def __init__(self, turns: list[ModelTurn]) -> None:
        self._turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def respond(
        self,
        *,
        instructions: str,
        input_data: str | list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
    ) -> ModelTurn:
        self.requests.append(
            {
                "instructions": instructions,
                "input_data": input_data,
                "tools": tools,
                "previous_response_id": previous_response_id,
            }
        )
        if not self._turns:
            raise ProviderError("fake provider has no queued model turn")
        return self._turns.pop(0)

