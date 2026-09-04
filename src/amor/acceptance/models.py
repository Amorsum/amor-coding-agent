from __future__ import annotations

import builtins
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_DOTTED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _load_strict_json(value: str) -> object:
    def reject_constant(constant: str) -> object:
        raise ValueError(f"non-standard JSON constant is not allowed: {constant}")

    return json.loads(value, parse_constant=reject_constant)


class PythonAcceptanceCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    module: str
    callable: str
    args_json: str = Field(default="[]", max_length=20_000)
    kwargs_json: str = Field(default="{}", max_length=20_000)
    expectation: Literal["equals", "raises"]
    expected_json: str = Field(default="null", max_length=20_000)
    exception_type: str = ""
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_safe_structure(self) -> "PythonAcceptanceCase":
        for label, value in (("module", self.module), ("callable", self.callable)):
            if not _DOTTED_NAME.fullmatch(value) or "__" in value:
                raise ValueError(f"{label} must be a safe dotted Python name")
        try:
            args = _load_strict_json(self.args_json)
            kwargs = _load_strict_json(self.kwargs_json)
            if self.expectation == "equals":
                _load_strict_json(self.expected_json)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("case arguments and expected values must be valid JSON") from exc
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError("args_json must decode to a list and kwargs_json to an object")
        if self.expectation == "raises":
            if not _DOTTED_NAME.fullmatch(self.exception_type) or "." in self.exception_type:
                raise ValueError("raises expectation requires a simple exception type")
            exception_class = getattr(builtins, self.exception_type, None)
            if not isinstance(exception_class, type) or not issubclass(exception_class, Exception):
                raise ValueError("raises expectation requires a built-in Exception type")
        elif self.exception_type:
            raise ValueError("equals expectation must not declare exception_type")
        return self


class AcceptanceProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    preserved_behaviors: list[str] = Field(max_length=20)
    edge_cases: list[str] = Field(max_length=20)
    python_cases: list[PythonAcceptanceCase] = Field(min_length=1, max_length=20)
    questions: list[str] = Field(max_length=10)
    summary: str = Field(min_length=1, max_length=1_000)


class AcceptancePlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["v1"] = "v1"
    plan_id: str
    status: Literal["READY", "NEEDS_INPUT"]
    baseline_commit: str
    instruction: str
    acceptance_criteria: list[str]
    preserved_behaviors: list[str]
    edge_cases: list[str]
    allowed_paths: list[str]
    validation_commands: list[list[str]]
    python_cases: list[PythonAcceptanceCase]
    evidence_files: list[str]
    questions: list[str]
    summary: str
    provider: str
    model: str
    token_usage: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    contract_sha256: str
