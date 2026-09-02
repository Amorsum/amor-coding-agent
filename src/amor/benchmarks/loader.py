from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from amor.domain import TaskSpec


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
