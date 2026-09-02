import json

import pytest

from amor.providers import OpenAIResponsesProvider, ProviderError


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_requires_api_key() -> None:
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIResponsesProvider(model="test-model", api_key="")


def test_parses_responses_function_calls_and_preserves_call_id(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeHTTPResponse(
            {
                "id": "resp_123",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": "search_code",
                        "arguments": '{"query":"average","path":"src"}',
                    },
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Searching relevant code."}],
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAIResponsesProvider(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=17,
        max_output_tokens=321,
    )

    turn = provider.respond(
        instructions="system",
        input_data=[{"type": "function_call_output", "call_id": "prior", "output": "{}"}],
        tools=[],
        previous_response_id="resp_prior",
    )

    assert turn.response_id == "resp_123"
    assert turn.tool_calls[0].call_id == "call_123"
    assert turn.tool_calls[0].arguments == {"query": "average", "path": "src"}
    assert turn.output_text == "Searching relevant code."
    request_body = json.loads(captured["request"].data.decode("utf-8"))
    assert request_body["previous_response_id"] == "resp_prior"
    assert request_body["parallel_tool_calls"] is False
    assert request_body["max_output_tokens"] == 321
    assert request_body["instructions"] == "system"
    assert captured["timeout"] == 17
