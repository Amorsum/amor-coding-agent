from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.request
from typing import Any

from amor.providers.base import ModelTurn, ProviderError
from amor.providers.responses_common import parse_responses_turn


class DeepSeekResponsesProvider:
    """Stateless DeepSeek Responses client that replays complete local history."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: int = 120,
        max_output_tokens: int = 4_000,
    ) -> None:
        if not model.strip():
            raise ProviderError("model is required")
        if not api_key.strip():
            raise ProviderError("DEEPSEEK_API_KEY is required")
        if max_output_tokens < 1:
            raise ProviderError("max_output_tokens must be positive")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self._history: list[dict[str, Any]] = []

    @classmethod
    def from_environment(
        cls,
        *,
        model: str,
        base_url: str | None = None,
        timeout_seconds: int = 120,
        max_output_tokens: int = 4_000,
    ) -> "DeepSeekResponsesProvider":
        return cls(
            model=model,
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )

    def respond(
        self,
        *,
        instructions: str,
        input_data: str | list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
    ) -> ModelTurn:
        del previous_response_id  # DeepSeek Responses is stateless.
        if isinstance(input_data, str):
            if self._history:
                raise ProviderError(
                    "DeepSeek provider session already started; create a fresh provider for each run"
                )
            pending_input = [{"role": "user", "content": input_data}]
        else:
            pending_input = copy.deepcopy(input_data)

        request_history = [*self._history, *pending_input]

        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": request_history,
            "tools": tools,
            "tool_choice": "auto",
            "max_output_tokens": self.max_output_tokens,
        }
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
            raise ProviderError(f"DeepSeek Responses API returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"DeepSeek Responses API request failed: {exc}") from exc

        turn = parse_responses_turn(raw)
        self._history = request_history
        output = raw.get("output")
        if isinstance(output, list):
            self._history.extend(copy.deepcopy(item) for item in output if isinstance(item, dict))
        return turn
