from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from amor.domain import ToolResult


@dataclass
class ProgressGuard:
    """Detect deterministic loops without relying on a model self-assessment."""

    max_identical_calls: int = 3
    max_identical_failures: int = 3

    def __post_init__(self) -> None:
        self._last_call_fingerprint: str | None = None
        self._identical_call_count = 0
        self._last_failure_fingerprint: str | None = None
        self._identical_failure_count = 0
        self._last_failure_diff_hash: str | None = None

    def observe_call(self, name: str, arguments: dict) -> str | None:
        fingerprint = self._hash({"name": name, "arguments": arguments})
        if fingerprint == self._last_call_fingerprint:
            self._identical_call_count += 1
        else:
            self._last_call_fingerprint = fingerprint
            self._identical_call_count = 1
        if self._identical_call_count >= self.max_identical_calls:
            return f"identical tool call repeated {self._identical_call_count} times: {name}"
        return None

    def observe_result(self, name: str, result: ToolResult, diff: str) -> str | None:
        diff_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()
        if result.ok:
            if self._last_failure_diff_hash is not None and diff_hash != self._last_failure_diff_hash:
                self._last_failure_fingerprint = None
                self._identical_failure_count = 0
                self._last_failure_diff_hash = None
            return None
        fingerprint = self._hash(
            {
                "name": name,
                "summary": result.summary,
                "output": result.output[-2_000:],
                "diff_sha256": diff_hash,
            }
        )
        if fingerprint == self._last_failure_fingerprint:
            self._identical_failure_count += 1
        else:
            self._last_failure_fingerprint = fingerprint
            self._identical_failure_count = 1
        self._last_failure_diff_hash = diff_hash
        if self._identical_failure_count >= self.max_identical_failures:
            return f"same failed {name} result repeated without a diff change"
        return None

    @staticmethod
    def _hash(value: dict) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
