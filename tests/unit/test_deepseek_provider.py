import json

import pytest

from amor.providers import DeepSeekResponsesProvider, ProviderError


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_requires_its_own_api_key() -> None:
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        DeepSeekResponsesProvider(model="deepseek-v4-pro", api_key="")


def test_environment_uses_deepseek_variables(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/api")

    provider = DeepSeekResponsesProvider.from_environment(model="deepseek-v4-pro")

    assert provider.api_key == "deepseek-key"
    assert provider.base_url == "https://example.test/api"


def test_replays_complete_history_without_server_side_session_fields(monkeypatch) -> None:
    responses = [
        {
            "id": "resp_1",
            "output": [
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search_code",
                    "arguments": '{"query":"average","path":"src"}',
                    "status": "completed",
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "input_tokens_details": {"cached_tokens": 3},
            },
        },
        {
            "id": "resp_2",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done."}],
                }
            ],
            "usage": {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24},
        },
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHTTPResponse(responses.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = DeepSeekResponsesProvider(
        model="deepseek-v4-pro",
        api_key="secret-key",
        timeout_seconds=19,
        max_output_tokens=321,
    )

    first = provider.respond(
        instructions="system",
        input_data="initial task",
        tools=[],
        previous_response_id=None,
    )
    second = provider.respond(
        instructions="system",
        input_data=[
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": '{"ok":true}',
            }
        ],
        tools=[],
        previous_response_id="resp_1",
    )

    assert first.tool_calls[0].call_id == "call_1"
    assert first.usage["cached_input_tokens"] == 3
    assert second.output_text == "Done."
    first_body = json.loads(requests[0][0].data.decode("utf-8"))
    second_body = json.loads(requests[1][0].data.decode("utf-8"))
    assert first_body["input"] == [{"role": "user", "content": "initial task"}]
    assert second_body["input"] == [
        {"role": "user", "content": "initial task"},
        {
            "id": "fc_1",
            "type": "function_call",
            "call_id": "call_1",
            "name": "search_code",
            "arguments": '{"query":"average","path":"src"}',
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"ok":true}',
        },
    ]
    assert "previous_response_id" not in second_body
    assert "store" not in second_body
    assert "parallel_tool_calls" not in second_body
    assert second_body["max_output_tokens"] == 321
    assert requests[1][1] == 19


def test_rejects_reusing_one_provider_for_a_new_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse({"id": "resp_1", "output": []}),
    )
    provider = DeepSeekResponsesProvider(model="deepseek-v4-pro", api_key="secret-key")
    provider.respond(instructions="system", input_data="one", tools=[], previous_response_id=None)

    with pytest.raises(ProviderError, match="fresh provider"):
        provider.respond(instructions="system", input_data="two", tools=[], previous_response_id=None)
