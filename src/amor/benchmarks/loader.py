from __future__ import annotations

import json
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from amor.domain import TaskSpec


BENCHMARK_DATASET_VERSION = "v2-20-task"


@dataclass(frozen=True)
class BenchmarkLayout:
    root: Path

    @property
    def fixtures(self) -> Path:
        return self.root / "fixtures"

    @property
    def tasks(self) -> Path:
        return self.root / "tasks"

    @property
    def hidden_tests(self) -> Path:
        return self.root / "hidden_tests"


def load_task(layout: BenchmarkLayout, task_id: str) -> TaskSpec:
    task_path = layout.tasks / f"{task_id}.json"
    raw = json.loads(task_path.read_text(encoding="utf-8"))
    for command in raw["visible_validation_commands"]:
        command[:] = [sys.executable if value == "{python}" else value for value in command]
    return TaskSpec.model_validate(raw)


def list_task_ids(layout: BenchmarkLayout) -> list[str]:
    return sorted(path.stem for path in layout.tasks.glob("*.json"))


def load_hidden_suite(layout: BenchmarkLayout, task_id: str) -> Path:
    manifest_path = layout.hidden_tests / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    suite_name = manifest.get(task_id)
    if suite_name is None:
        raise KeyError(f"no hidden acceptance suite for task {task_id}")
    suite_path = (layout.hidden_tests / suite_name).resolve()
    if not suite_path.is_dir():
        raise FileNotFoundError(suite_path)
    return suite_path


def benchmark_fingerprint(layout: BenchmarkLayout, task_ids: list[str]) -> str:
    """Hash selected task specs, fixtures, and hidden suites for reproducibility."""
    manifest = json.loads((layout.hidden_tests / "manifest.json").read_text(encoding="utf-8"))
    paths: set[Path] = {layout.hidden_tests / "manifest.json"}
    fixture_names: set[str] = set()
    for task_id in sorted(task_ids):
        task_path = layout.tasks / f"{task_id}.json"
        paths.add(task_path)
        raw = json.loads(task_path.read_text(encoding="utf-8"))
        fixture_names.add(raw["fixture"])
        suite_name = manifest.get(task_id)
        if suite_name:
            paths.update(path for path in (layout.hidden_tests / suite_name).rglob("*") if path.is_file())
    for fixture_name in fixture_names:
        paths.update(path for path in (layout.fixtures / fixture_name).rglob("*") if path.is_file())

    digest = hashlib.sha256()
    for path in sorted(paths):
        relative_parts = path.relative_to(layout.root).parts
        if ".git" in relative_parts or "__pycache__" in relative_parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(layout.root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
