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
    context_strategy: str
    planning_strategy: str
    outcome_matches_expected: bool
    first_try_success: bool
    regression_detected: bool
    verifier_passed: bool
    agent_requested_verification: bool
    diagnosis_attempted: bool
    recovery_succeeded: bool
    rounds: int
    patch_attempts: int
    tool_calls: int
    denied_tool_calls: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    estimated_cost: float | None = None
    patch_hash: str | None = None
    files_read: int
    unique_files_read: int
    lines_read: int
    repeated_reads: int
    search_calls: int
    zero_result_searches: int
    context_requested_chars: int
    context_retained_chars: int
    context_compressions: int
    modified_files_read: int
    context_relevance_rate: float
    duration_ms: int
    failure_category: str | None = None
    report_path: str
    trace_path: str


class BenchmarkMetrics(BaseModel):
    task_count: int
    attempt_count: int
    successful_attempts: int
    attempt_success_rate: float
    first_try_successes: int
    first_try_success_rate: float
    tasks_passing_at_least_once: int
    pass_at_least_once_rate: float
    stable_tasks: int
    stability_eligible_tasks: int
    stable_task_rate: float | None = None
    false_completions: int
    false_completion_rate: float
    regressions: int
    regression_rate: float
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
    average_duration_stddev_ms: float | None = None
    total_input_tokens: int
    total_cached_input_tokens: int
    total_output_tokens: int
    total_reasoning_tokens: int
    total_tokens: int
    average_token_stddev: float | None = None
    total_estimated_cost: float | None = None
    cost_per_success: float | None = None
    average_cost_stddev: float | None = None
    patch_stable_tasks: int
    patch_stability_eligible_tasks: int
    patch_stability_rate: float | None = None
    average_files_read: float
    average_lines_read: float
    repeated_read_rate: float
    zero_result_search_rate: float
    context_requested_chars: int
    context_retained_chars: int
    context_retention_rate: float
    context_compressions: int
    average_context_relevance_rate: float
    failure_categories: dict[str, int] = Field(default_factory=dict)


class BenchmarkRunSummary(BaseModel):
    run_id: str
    dataset_version: str
    dataset_fingerprint: str
    provider: str
    model: str | None
    context_strategy: str
    planning_strategy: str
    context_budget_chars: int
    prompt_version: str
    model_max_output_tokens: int
    max_total_tokens: int | None = None
    cost_currency: str | None = None
    input_cost_per_million: float | None = None
    cached_input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    repeats: int
    task_ids: list[str]
    started_at: datetime
    finished_at: datetime
    passed: bool
    metrics: BenchmarkMetrics
    attempts: list[BenchmarkAttemptRecord]


class StrategyExperimentVariant(BaseModel):
    strategy: str
    run_id: str
    passed: bool
    metrics: BenchmarkMetrics
    summary_path: str


class StrategyExperimentComparison(BaseModel):
    baseline_strategy: str
    candidate_strategy: str
    success_rate_delta: float
    input_token_reduction_rate: float
    tool_call_reduction_rate: float
    context_char_reduction_rate: float
    files_read_reduction_rate: float
    estimated_cost_reduction_rate: float | None = None


class StrategyExperimentSummary(BaseModel):
    experiment_id: str
    dataset_version: str
    dataset_fingerprint: str
    dimension: str = "context"
    provider: str
    model: str | None
    context_strategy: str | None = None
    planning_strategy: str | None = None
    repeats: int
    task_ids: list[str]
    context_budget_chars: int
    prompt_version: str
    model_max_output_tokens: int
    max_total_tokens: int | None = None
    cost_currency: str | None = None
    input_cost_per_million: float | None = None
    cached_input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    started_at: datetime
    finished_at: datetime
    variants: list[StrategyExperimentVariant]
    comparison: StrategyExperimentComparison
