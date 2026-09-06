from __future__ import annotations

import os

from amor.providers.base import ModelProvider, ProviderError
from amor.providers.deepseek_responses import DeepSeekResponsesProvider
from amor.providers.openai_responses import OpenAIResponsesProvider


def build_api_provider(
    provider_name: str,
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int = 120,
    max_output_tokens: int = 4_000,
) -> ModelProvider:
    provider_class = {
        "openai-responses": OpenAIResponsesProvider,
        "deepseek-responses": DeepSeekResponsesProvider,
    }.get(provider_name)
    if provider_class is None:
        raise ProviderError(f"unsupported API provider: {provider_name}")
    if api_key is None:
        return provider_class.from_environment(
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )
    default_urls = {
        "openai-responses": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "deepseek-responses": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    }
    return provider_class(
        model=model,
        api_key=api_key,
        base_url=base_url or default_urls[provider_name],
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )


def provider_configuration() -> dict[str, bool]:
    return {
        "openai-responses": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "deepseek-responses": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
    }
