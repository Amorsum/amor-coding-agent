import json
from pathlib import Path

from amor.benchmarks.loader import (
    BENCHMARK_DATASET_VERSION,
    BenchmarkLayout,
    benchmark_fingerprint,
    list_task_ids,
    load_task,
)
from amor.domain import TerminalStatus


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_v2_dataset_has_twenty_tasks_and_hidden_suites_for_every_fix() -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    task_ids = list_task_ids(layout)
    tasks = [load_task(layout, task_id) for task_id in task_ids]
    manifest = json.loads((layout.hidden_tests / "manifest.json").read_text(encoding="utf-8"))
    successful_ids = {
        task.task_id for task in tasks if task.expected_status == TerminalStatus.SUCCEEDED
    }

    assert BENCHMARK_DATASET_VERSION == "v2-20-task"
    assert len(tasks) == 20
    assert len(successful_ids) == 16
    assert sum(task.expected_status == TerminalStatus.BLOCKED for task in tasks) == 4
    assert successful_ids <= set(manifest)
    assert all((layout.hidden_tests / manifest[task_id]).is_dir() for task_id in successful_ids)


def test_dataset_fingerprint_is_stable_and_selection_sensitive() -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    task_ids = list_task_ids(layout)

    complete = benchmark_fingerprint(layout, task_ids)
    repeated = benchmark_fingerprint(layout, list(reversed(task_ids)))
    subset = benchmark_fingerprint(layout, task_ids[:1])

    assert len(complete) == 64
    assert complete == repeated
    assert complete != subset
