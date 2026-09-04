from __future__ import annotations

from collections import Counter
from statistics import mean, pstdev

from amor.benchmarks.models import BenchmarkAttemptRecord, BenchmarkMetrics


def calculate_metrics(attempts: list[BenchmarkAttemptRecord], task_ids: list[str]) -> BenchmarkMetrics:
    attempt_count = len(attempts)
    successes = [attempt for attempt in attempts if attempt.outcome_matches_expected]
    by_task = {
        task_id: [attempt for attempt in attempts if attempt.task_id == task_id]
        for task_id in task_ids
    }
    passing_once = sum(any(item.outcome_matches_expected for item in records) for records in by_task.values())
    stability_eligible = [records for records in by_task.values() if len(records) >= 2]
    stable = sum(
        all(item.outcome_matches_expected for item in records)
        for records in stability_eligible
    )
    false_completions = sum(
        attempt.agent_requested_verification and not attempt.verifier_passed
        for attempt in attempts
    )
    expected_fix_attempts = sum(
        attempt.expected_status.value == "SUCCEEDED" for attempt in attempts
    )
    first_try_successes = sum(attempt.first_try_success for attempt in attempts)
    regressions = sum(attempt.regression_detected for attempt in attempts)
    scope_violations = sum(attempt.failure_category == "scope_violation_or_missing_patch" for attempt in attempts)
    denied_attempts = sum(attempt.denied_tool_calls > 0 for attempt in attempts)
    diagnosed = [attempt for attempt in attempts if attempt.diagnosis_attempted]
    recovered = [attempt for attempt in diagnosed if attempt.recovery_succeeded]
    failures = Counter(
        attempt.failure_category or "unexpected_terminal_status"
        for attempt in attempts
        if not attempt.outcome_matches_expected
    )
    read_calls = sum(attempt.files_read for attempt in attempts)
    search_calls = sum(attempt.search_calls for attempt in attempts)
    requested_chars = sum(attempt.context_requested_chars for attempt in attempts)
    retained_chars = sum(attempt.context_retained_chars for attempt in attempts)
    costs = [attempt.estimated_cost for attempt in attempts]
    total_cost = (
        round(sum(cost for cost in costs if cost is not None), 8)
        if costs and all(cost is not None for cost in costs)
        else None
    )
    patch_eligible_tasks = [
        records
        for records in by_task.values()
        if len(records) >= 2 and records[0].expected_status.value == "SUCCEEDED"
    ]
    patch_stable = sum(
        all(record.outcome_matches_expected and record.patch_hash for record in records)
        and len({record.patch_hash for record in records}) == 1
        for records in patch_eligible_tasks
    )

    return BenchmarkMetrics(
        task_count=len(task_ids),
        attempt_count=attempt_count,
        successful_attempts=len(successes),
        attempt_success_rate=_rate(len(successes), attempt_count),
        first_try_successes=first_try_successes,
        first_try_success_rate=_rate(first_try_successes, expected_fix_attempts),
        tasks_passing_at_least_once=passing_once,
        pass_at_least_once_rate=_rate(passing_once, len(task_ids)),
        stable_tasks=stable,
        stability_eligible_tasks=len(stability_eligible),
        stable_task_rate=(
            _rate(stable, len(stability_eligible))
            if stability_eligible
            else None
        ),
        false_completions=false_completions,
        false_completion_rate=_rate(false_completions, attempt_count),
        regressions=regressions,
        regression_rate=_rate(regressions, expected_fix_attempts),
        scope_violations=scope_violations,
        scope_violation_rate=_rate(scope_violations, attempt_count),
        attempts_with_policy_denials=denied_attempts,
        policy_denial_attempt_rate=_rate(denied_attempts, attempt_count),
        diagnosed_attempts=len(diagnosed),
        recovered_attempts=len(recovered),
        recovery_rate=_rate(len(recovered), len(diagnosed)),
        average_rounds=_average([attempt.rounds for attempt in attempts]),
        average_tool_calls=_average([attempt.tool_calls for attempt in attempts]),
        average_duration_ms=_average([attempt.duration_ms for attempt in attempts]),
        average_duration_stddev_ms=_within_task_stddev(by_task, "duration_ms"),
        total_input_tokens=sum(attempt.input_tokens for attempt in attempts),
        total_cached_input_tokens=sum(attempt.cached_input_tokens for attempt in attempts),
        total_output_tokens=sum(attempt.output_tokens for attempt in attempts),
        total_reasoning_tokens=sum(attempt.reasoning_tokens for attempt in attempts),
        total_tokens=sum(attempt.total_tokens for attempt in attempts),
        average_token_stddev=_within_task_stddev(by_task, "total_tokens"),
        total_estimated_cost=total_cost,
        cost_per_success=(
            round(total_cost / len(successes), 8)
            if total_cost is not None and successes
            else None
        ),
        average_cost_stddev=(
            _within_task_stddev(by_task, "estimated_cost")
            if costs and all(cost is not None for cost in costs)
            else None
        ),
        patch_stable_tasks=patch_stable,
        patch_stability_eligible_tasks=len(patch_eligible_tasks),
        patch_stability_rate=(
            _rate(patch_stable, len(patch_eligible_tasks))
            if patch_eligible_tasks
            else None
        ),
        average_files_read=_average([attempt.unique_files_read for attempt in attempts]),
        average_lines_read=_average([attempt.lines_read for attempt in attempts]),
        repeated_read_rate=_rate(sum(attempt.repeated_reads for attempt in attempts), read_calls),
        zero_result_search_rate=_rate(sum(attempt.zero_result_searches for attempt in attempts), search_calls),
        context_requested_chars=requested_chars,
        context_retained_chars=retained_chars,
        context_retention_rate=_rate(retained_chars, requested_chars),
        context_compressions=sum(attempt.context_compressions for attempt in attempts),
        average_context_relevance_rate=round(
            mean(attempt.context_relevance_rate for attempt in attempts), 4
        ) if attempts else 0.0,
        failure_categories=dict(sorted(failures.items())),
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _average(values: list[int]) -> float:
    return round(mean(values), 2) if values else 0.0


def _within_task_stddev(
    by_task: dict[str, list[BenchmarkAttemptRecord]],
    field: str,
) -> float | None:
    deviations = [
        pstdev([getattr(record, field) for record in records])
        for records in by_task.values()
        if len(records) >= 2
    ]
    return round(mean(deviations), 4) if deviations else None
