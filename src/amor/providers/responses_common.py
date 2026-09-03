from __future__ import annotations

import json
from typing import Any

from amor.providers.base import ModelToolCall, ModelTurn, ProviderError


def parse_responses_turn(raw: Any) -> ModelTurn:
    if not isinstance(raw, dict):
        raise ProviderError("Responses API result was not a JSON object")
    if raw.get("error"):
        error = raw["error"]
        if isinstance(error, dict):
            code = error.get("code", "unknown")
            message = error.get("message", "")
        else:
            code = "unknown"
            message = str(error)
        raise ProviderError(f"Responses API error: {code}: {message}")

    tool_calls: list[ModelToolCall] = []
    text_parts: list[str] = []
    for item in raw.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            try:
                arguments = json.loads(item.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ProviderError(
                    f"model returned invalid JSON arguments for {item.get('name')}"
                ) from exc
            if not isinstance(arguments, dict):
                raise ProviderError(
                    f"model returned non-object arguments for {item.get('name')}"
                )
            try:
                tool_calls.append(
                    ModelToolCall(
                        call_id=item["call_id"],
                        name=item["name"],
                        arguments=arguments,
                    )
                )
            except KeyError as exc:
                raise ProviderError("model returned an incomplete function call") from exc
        elif item.get("type") == "message":
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text_parts.append(str(content.get("text", "")))

    response_id = raw.get("id")
    if not response_id:
        raise ProviderError("Responses API result did not contain a response id")
    return ModelTurn(
        response_id=str(response_id),
        tool_calls=tool_calls,
        output_text="\n".join(text_parts).strip(),
        usage=normalize_responses_usage(raw.get("usage")),
    )


def normalize_responses_usage(value: Any) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    normalized = {
        name: int(count)
        for name, count in usage.items()
        if isinstance(count, int) and not isinstance(count, bool)
    }
    input_details = usage.get("input_tokens_details")
    if isinstance(input_details, dict):
        cached_tokens = input_details.get("cached_tokens")
        if isinstance(cached_tokens, int) and not isinstance(cached_tokens, bool):
            normalized["cached_input_tokens"] = cached_tokens
    output_details = usage.get("output_tokens_details")
    if isinstance(output_details, dict):
        reasoning_tokens = output_details.get("reasoning_tokens")
        if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool):
            normalized["reasoning_tokens"] = reasoning_tokens
    return normalized
