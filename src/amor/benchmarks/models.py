from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from amor.domain import TerminalStatus


class BenchmarkAttemptRecord(BaseModel):
    task_id: str
    attempt: int
    category: str
    difficulty: str
    expected_status: TerminalStatus
    actual_status: TerminalStatus
    outcome_matches_expected: bool
    verifier_passed: bool
    agent_requested_verification: bool
    diagnosis_attempted: bool
    recovery_succeeded: bool
    rounds: int
    patch_attempts: int
    tool_calls: int
    denied_tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    duration_ms: int
    failure_category: str | None = None
    report_path: str
    trace_path: str


class BenchmarkMetrics(BaseModel):
    task_count: int
    attempt_count: int
    successful_attempts: int
    attempt_success_rate: float
    tasks_passing_at_least_once: int
    pass_at_least_once_rate: float
    stable_tasks: int
    stable_task_rate: float
    false_completions: int
    false_completion_rate: float
    scope_violations: int
    scope_violation_rate: float
    attempts_with_policy_denials: int
    policy_denial_attempt_rate: float
    diagnosed_attempts: int
    recovered_attempts: int
    recovery_rate: float
    average_rounds: float
    average_tool_calls: float
    average_duration_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    failure_categories: dict[str, int] = Field(default_factory=dict)


class BenchmarkRunSummary(BaseModel):
    run_id: str
    provider: str
    model: str | None
    repeats: int
    task_ids: list[str]
    started_at: datetime
    finished_at: datetime
    passed: bool
    metrics: BenchmarkMetrics
    attempts: list[BenchmarkAttemptRecord]
