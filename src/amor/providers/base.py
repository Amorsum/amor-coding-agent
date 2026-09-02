from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ProviderError(RuntimeError):
    pass


class ModelToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any]


class ModelTurn(BaseModel):
    response_id: str
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    output_text: str = ""
    usage: dict[str, int] = Field(default_factory=dict)


class ModelProvider(Protocol):
    def respond(
        self,
        *,
        instructions: str,
        input_data: str | list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
    ) -> ModelTurn: ...

