from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from amor.providers.base import ModelToolCall, ModelTurn, ProviderError


class OpenAIResponsesProvider:
    """Small Responses API client with no SDK dependency and no credential logging."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: int = 120,
        max_output_tokens: int = 4_000,
    ) -> None:
        if not model.strip():
            raise ProviderError("model is required")
        if not api_key.strip():
            raise ProviderError("OPENAI_API_KEY is required")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_environment(
        cls,
        *,
        model: str,
        base_url: str | None = None,
        timeout_seconds: int = 120,
    ) -> "OpenAIResponsesProvider":
        return cls(
            model=model,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout_seconds=timeout_seconds,
        )

    def respond(
        self,
        *,
        instructions: str,
        input_data: str | list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
    ) -> ModelTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_data,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_output_tokens": self.max_output_tokens,
            "store": True,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2_000]
            raise ProviderError(f"Responses API returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Responses API request failed: {exc}") from exc

        if raw.get("error"):
            error = raw["error"]
            raise ProviderError(f"Responses API error: {error.get('code', 'unknown')}: {error.get('message', '')}")

        tool_calls: list[ModelToolCall] = []
        text_parts: list[str] = []
        for item in raw.get("output", []):
            if item.get("type") == "function_call":
                try:
                    arguments = json.loads(item.get("arguments", "{}"))
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"model returned invalid JSON arguments for {item.get('name')}") from exc
                tool_calls.append(
                    ModelToolCall(
                        call_id=item["call_id"],
                        name=item["name"],
                        arguments=arguments,
                    )
                )
            elif item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))

        usage = raw.get("usage") or {}
        normalized_usage = {
            name: int(value)
            for name, value in usage.items()
            if isinstance(value, int)
        }
        response_id = raw.get("id")
        if not response_id:
            raise ProviderError("Responses API result did not contain a response id")
        return ModelTurn(
            response_id=response_id,
            tool_calls=tool_calls,
            output_text="\n".join(text_parts).strip(),
            usage=normalized_usage,
        )

