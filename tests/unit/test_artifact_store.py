import json
from pathlib import Path

import pytest

from amor.web.artifacts import ArtifactNotFound, ArtifactStore


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def create_experiment(root: Path) -> Path:
    experiment = root / "suite" / "exp-1"
    write_json(
        experiment / "comparison.json",
        {
            "experiment_id": "exp-1",
            "dimension": "planning",
            "provider": "fake",
            "model": "fake-model",
            "started_at": "2026-09-04T00:00:00Z",
            "finished_at": "2026-09-04T00:01:00Z",
            "repeats": 1,
            "task_ids": ["task-one"],
            "variants": [
                {
                    "strategy": "direct",
                    "run_id": "direct",
                    "passed": True,
                    "metrics": {"attempt_success_rate": 1.0},
                    "summary_path": "C:/should/not/leak.json",
                }
            ],
            "comparison": {"success_rate_delta": 0.0},
        },
    )
    attempt = {
        "task_id": "task-one",
        "attempt": 1,
        "actual_status": "SUCCEEDED",
        "outcome_matches_expected": True,
        "report_path": "C:/untrusted/report.json",
        "trace_path": "C:/untrusted/trace.jsonl",
    }
    write_json(experiment / "direct" / "summary.json", {"attempts": [attempt]})
    attempt_root = experiment / "direct" / "tasks" / "task-one" / "attempt-01"
    write_json(
        attempt_root / "final-report.json",
        {
            "final_status": "SUCCEEDED",
            "git_diff": "diff --git a/a.py b/a.py",
            "verification": {"passed": True, "checks": []},
            "trace_path": "C:/private/trace.jsonl",
            "workspace_path": "C:/private/workspace",
        },
    )
    attempt_root.joinpath("trace.jsonl").write_text(
        json.dumps({"event_type": "state_transition", "phase": "SUCCEEDED"}) + "\n",
        encoding="utf-8",
    )
    return experiment


def test_store_lists_experiments_without_leaking_recorded_paths(tmp_path: Path) -> None:
    create_experiment(tmp_path)
    store = ArtifactStore(tmp_path)

    items = store.list_experiments()
    assert len(items) == 1
    assert items[0]["dimension"] == "planning"
    assert items[0]["fake_provider"] is True

    detail = store.get_experiment(items[0]["id"])
    assert "summary_path" not in detail["variants"][0]
    assert "report_path" not in detail["attempts"][0]
    assert "trace_path" not in detail["attempts"][0]


def test_store_reads_only_a_listed_attempt(tmp_path: Path) -> None:
    create_experiment(tmp_path)
    store = ArtifactStore(tmp_path)
    experiment_id = store.list_experiments()[0]["id"]

    detail = store.get_attempt(experiment_id, "direct", "task-one", 1)
    assert detail["report"]["git_diff"].startswith("diff --git")
    assert "workspace_path" not in detail["report"]
    assert detail["trace"][0]["event_type"] == "state_transition"

    with pytest.raises(ArtifactNotFound):
        store.get_attempt(experiment_id, "direct", "../outside", 1)


def test_store_reads_legacy_unpadded_attempt_directories(tmp_path: Path) -> None:
    experiment = create_experiment(tmp_path)
    padded = experiment / "direct" / "tasks" / "task-one" / "attempt-01"
    padded.rename(padded.with_name("attempt-1"))
    store = ArtifactStore(tmp_path)
    experiment_id = store.list_experiments()[0]["id"]

    detail = store.get_attempt(experiment_id, "direct", "task-one", 1)
    assert detail["report"]["final_status"] == "SUCCEEDED"


def test_store_rejects_unknown_or_malformed_experiment_ids(tmp_path: Path) -> None:
    create_experiment(tmp_path)
    store = ArtifactStore(tmp_path)

    with pytest.raises(ArtifactNotFound):
        store.get_experiment("../../outside")
