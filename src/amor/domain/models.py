from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentPhase(StrEnum):
    INITIALIZING = "INITIALIZING"
    PROFILING_REPO = "PROFILING_REPO"
    PLANNING = "PLANNING"
    EXPLORING = "EXPLORING"
    EDITING = "EDITING"
    VALIDATING = "VALIDATING"
    DIAGNOSING = "DIAGNOSING"
    FINAL_VERIFYING = "FINAL_VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"


class TerminalStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class PolicyDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class RunLimits(BaseModel):
    max_rounds: int = Field(default=8, ge=1, le=100)
    max_seconds: int = Field(default=120, ge=1, le=3600)
    max_output_chars: int = Field(default=20_000, ge=100, le=1_000_000)
    max_file_bytes: int = Field(default=256_000, ge=1, le=10_000_000)


class TaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fixture: str | None = None
    repository: str | None = None
    instruction: str
    acceptance_criteria: list[str]
    allowed_paths: list[str]
    visible_validation_commands: list[list[str]]
    provider: str = "scripted"
    model: str | None = None
    limits: RunLimits = Field(default_factory=RunLimits)

    @model_validator(mode="after")
    def has_one_repository_source(self) -> "TaskSpec":
        if bool(self.fixture) == bool(self.repository):
            raise ValueError("exactly one of fixture or repository must be configured")
        return self


class RepositoryProfile(BaseModel):
    root: str
    languages: list[str]
    package_manager: str | None = None
    suggested_validation_commands: list[list[str]] = Field(default_factory=list)
    source_roots: list[str] = Field(default_factory=list)
    test_roots: list[str] = Field(default_factory=list)
    instruction_files: list[str] = Field(default_factory=list)
    dirty_worktree: bool
    head_commit: str


class PlanStep(BaseModel):
    step_id: int
    task: str
    status: StepStatus = StepStatus.PENDING
    evidence: list[str] = Field(default_factory=list)


class AgentState(BaseModel):
    task_id: str
    phase: AgentPhase = AgentPhase.INITIALIZING
    plan: list[PlanStep] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    attempted_fixes: list[str] = Field(default_factory=list)
    latest_error_summary: str | None = None
    round: int = 0
    token_usage: dict[str, int] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utc_now)


class ToolResult(BaseModel):
    ok: bool
    summary: str
    output: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolEvent(BaseModel):
    event_id: str
    task_id: str
    phase: AgentPhase
    tool: str
    arguments: dict[str, Any]
    policy_result: PolicyDecision
    result: ToolResult
    duration_ms: int
    created_at: datetime = Field(default_factory=utc_now)


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    summary: str
    duration_ms: int = 0


class VerificationResult(BaseModel):
    passed: bool
    checks: list[VerificationCheck]
    failure_category: str | None = None


class RunReport(BaseModel):
    run_id: str
    task: TaskSpec
    baseline_commit: str
    final_status: TerminalStatus
    state: AgentState
    verification: VerificationResult
    git_diff: str
    trace_path: str
    workspace_path: str
    started_at: datetime
    finished_at: datetime = Field(default_factory=utc_now)
