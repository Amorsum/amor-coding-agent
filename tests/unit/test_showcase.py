import json
from pathlib import Path

import pytest

from amor.showcase import ShowcaseError, ShowcaseExporter
from amor.web.artifacts import ArtifactStore


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _experiment(artifacts: Path) -> str:
    root = artifacts / "experiments" / "example"
    metrics = {
        "task_count": 1,
        "attempt_count": 1,
        "successful_attempts": 1,
        "attempt_success_rate": 1.0,
        "first_try_success_rate": 1.0,
        "stable_task_rate": None,
        "false_completion_rate": 0.0,
        "regression_rate": 0.0,
        "scope_violation_rate": 0.0,
        "policy_denial_attempt_rate": 0.0,
        "recovery_rate": 0.0,
        "average_rounds": 4.0,
        "average_tool_calls": 6.0,
        "average_duration_ms": 1200.0,
        "total_tokens": 500,
        "total_estimated_cost": None,
        "cost_per_success": None,
        "patch_stability_rate": None,
        "average_files_read": 2.0,
        "average_lines_read": 40.0,
        "context_retention_rate": 0.5,
        "average_context_relevance_rate": 0.5,
        "failure_categories": {},
        "workspace_path": "D:/private/repository",
    }
    _write_json(
        root / "comparison.json",
        {
            "experiment_id": "experiment-public",
            "dimension": "planning",
            "provider": "fake",
            "model": "fake-model",
            "dataset_version": "test-v1",
            "dataset_fingerprint": "a" * 64,
            "prompt_version": "test-prompt",
            "repeats": 1,
            "task_ids": ["task_one"],
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:00Z",
            "variants": [
                {"strategy": "direct", "run_id": "run-direct", "passed": True, "metrics": metrics},
                {"strategy": "structured", "run_id": "run-structured", "passed": True, "metrics": metrics},
            ],
            "comparison": {
                "baseline_strategy": "direct",
                "candidate_strategy": "structured",
                "success_rate_delta": 0.0,
                "input_token_reduction_rate": 0.1,
                "tool_call_reduction_rate": 0.2,
                "context_char_reduction_rate": 0.3,
                "files_read_reduction_rate": 0.4,
                "git_diff": "PRIVATE PATCH",
            },
        },
    )
    attempt = {
        "task_id": "task_one",
        "attempt": 1,
        "category": "edge_case",
        "difficulty": "easy",
        "expected_status": "SUCCEEDED",
        "actual_status": "SUCCEEDED",
        "context_strategy": "search-first",
        "planning_strategy": "direct",
        "outcome_matches_expected": True,
        "first_try_success": True,
        "verifier_passed": True,
        "rounds": 4,
        "tool_calls": 6,
        "denied_tool_calls": 0,
        "total_tokens": 500,
        "duration_ms": 1200,
        "failure_category": None,
        "report_path": "D:/private/final-report.json",
        "trace_path": "D:/private/trace.jsonl",
        "instruction": "PRIVATE TASK",
        "api_key": "PRIVATE KEY",
    }
    for run_id, strategy in (("run-direct", "direct"), ("run-structured", "structured")):
        _write_json(
            root / run_id / "summary.json",
            {"attempts": [{**attempt, "planning_strategy": strategy}]},
        )
    return ArtifactStore(artifacts).list_experiments()[0]["id"]


def test_showcase_export_is_static_hashed_and_redacted(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    experiment_id = _experiment(artifacts)
    exporter = ShowcaseExporter(artifacts)

    manifest = exporter.export(
        experiment_id,
        title="AMOR <公开> & evidence",
        confirm_public=True,
    )

    destination = artifacts / "showcases" / manifest.showcase_id
    payload = (destination / "showcase.json").read_text(encoding="utf-8")
    page = (destination / "index.html").read_text(encoding="utf-8")
    combined = payload + page
    assert manifest.files.keys() == {"index.html", "showcase.json"}
    assert "PRIVATE" not in combined
    assert "D:/private" not in combined
    assert "git_diff" not in combined
    assert "trace_path" not in combined
    assert "workspace_path" not in combined
    assert "AMOR &lt;公开&gt; &amp; evidence" in page
    assert 'Content-Security-Policy' in page
    assert exporter.get(manifest.showcase_id) == manifest


def test_showcase_export_requires_explicit_public_confirmation(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    experiment_id = _experiment(artifacts)

    with pytest.raises(ShowcaseError, match="explicit confirmation"):
        ShowcaseExporter(artifacts).export(experiment_id, confirm_public=False)


def test_showcase_manifest_detects_content_tampering(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    experiment_id = _experiment(artifacts)
    exporter = ShowcaseExporter(artifacts)
    manifest = exporter.export(experiment_id, confirm_public=True)
    page = artifacts / "showcases" / manifest.showcase_id / "index.html"
    page.write_text("tampered", encoding="utf-8")

    with pytest.raises(ShowcaseError, match="hash mismatch"):
        exporter.get(manifest.showcase_id)
