from __future__ import annotations

import os
from threading import RLock
from typing import Literal

from amor.providers.base import ProviderError


ProviderName = Literal["openai-responses", "deepseek-responses"]
CredentialSource = Literal["environment", "session", "missing"]

_ENVIRONMENT_KEYS: dict[str, str] = {
    "openai-responses": "OPENAI_API_KEY",
    "deepseek-responses": "DEEPSEEK_API_KEY",
}


class ProviderCredentialStore:
    """Process-local provider credentials that are never serialized."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._session_keys: dict[str, str] = {}

    def set_session(self, provider: ProviderName, api_key: str) -> None:
        key = api_key.strip()
        if len(key) < 8:
            raise ValueError("API Key 长度不能少于 8 个字符")
        if len(key) > 8_192 or any(character in key for character in "\r\n\0"):
            raise ValueError("API Key 格式无效")
        with self._lock:
            self._session_keys[provider] = key

    def clear_session(self, provider: ProviderName) -> None:
        with self._lock:
            self._session_keys.pop(provider, None)

    def clear(self) -> None:
        with self._lock:
            self._session_keys.clear()

    def source(self, provider: ProviderName) -> CredentialSource:
        with self._lock:
            if self._session_keys.get(provider):
                return "session"
        if os.environ.get(_ENVIRONMENT_KEYS[provider], "").strip():
            return "environment"
        return "missing"

    def require(self, provider: ProviderName) -> str:
        with self._lock:
            session_key = self._session_keys.get(provider)
        if session_key:
            return session_key
        environment_key = os.environ.get(_ENVIRONMENT_KEYS[provider], "").strip()
        if environment_key:
            return environment_key
        raise ProviderError(f"{_ENVIRONMENT_KEYS[provider]} is required")

    def configuration(self) -> dict[str, bool]:
        return {provider: self.source(provider) != "missing" for provider in _ENVIRONMENT_KEYS}

    def sources(self) -> dict[str, CredentialSource]:
        return {provider: self.source(provider) for provider in _ENVIRONMENT_KEYS}
