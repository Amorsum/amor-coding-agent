from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class ArtifactNotFound(LookupError):
    pass


class InvalidArtifact(ValueError):
    pass


class ArtifactStore:
    """Read-only, path-safe view over AMOR experiment artifacts."""

    def __init__(self, root: Path, *, max_file_bytes: int = 10_000_000) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes

    def list_experiments(self) -> list[dict[str, Any]]:
        experiments = []
        for comparison_path in self._comparison_paths():
            try:
                document = self._read_json(comparison_path)
                experiments.append(self._experiment_summary(comparison_path, document))
            except (InvalidArtifact, OSError):
                continue
        return sorted(experiments, key=lambda item: item["started_at"], reverse=True)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        comparison_path, document = self._find_experiment(experiment_id)
        result = deepcopy(document)
        result["id"] = self._artifact_id(comparison_path.parent)
        result["variants"] = [
            {key: value for key, value in variant.items() if key != "summary_path"}
            for variant in document.get("variants", [])
            if isinstance(variant, dict)
        ]
        result["attempts"] = self._list_attempts(comparison_path.parent, document)
        return result

    def get_attempt(
        self,
        experiment_id: str,
        strategy: str,
        task_id: str,
        attempt: int,
    ) -> dict[str, Any]:
        comparison_path, document = self._find_experiment(experiment_id)
        attempts = self._list_attempts(comparison_path.parent, document)
        record = next(
            (
                item
                for item in attempts
                if item["strategy"] == strategy
                and item["task_id"] == task_id
                and item["attempt"] == attempt
            ),
            None,
        )
        if record is None:
            raise ArtifactNotFound("attempt not found")

        variant = next(
            item
            for item in document["variants"]
            if item.get("strategy") == strategy
        )
        run_id = self._safe_segment(variant.get("run_id"), "run id")
        safe_task_id = self._safe_segment(task_id, "task id")
        task_root = comparison_path.parent / run_id / "tasks" / safe_task_id
        attempt_dir = next(
            (
                candidate
                for candidate in (
                    task_root / f"attempt-{attempt:02d}",
                    task_root / f"attempt-{attempt}",
                )
                if (candidate / "final-report.json").is_file()
                and (candidate / "trace.jsonl").is_file()
            ),
            task_root / f"attempt-{attempt:02d}",
        )
        report = self._read_json(attempt_dir / "final-report.json")
        trace = self._read_json_lines(attempt_dir / "trace.jsonl")
        return {
            "attempt": record,
            "report": {
                key: value
                for key, value in report.items()
                if key not in {"trace_path", "workspace_path"}
            },
            "trace": trace,
        }

    def _list_attempts(
        self,
        experiment_root: Path,
        document: dict[str, Any],
    ) -> list[dict[str, Any]]:
        attempts = []
        variants = document.get("variants")
        if not isinstance(variants, list):
            raise InvalidArtifact("experiment variants must be a list")
        for variant in variants:
            if not isinstance(variant, dict):
                raise InvalidArtifact("experiment variant must be an object")
            strategy = self._safe_segment(variant.get("strategy"), "strategy")
            run_id = self._safe_segment(variant.get("run_id"), "run id")
            summary = self._read_json(experiment_root / run_id / "summary.json")
            records = summary.get("attempts")
            if not isinstance(records, list):
                raise InvalidArtifact("benchmark attempts must be a list")
            for record in records:
                if not isinstance(record, dict):
                    raise InvalidArtifact("benchmark attempt must be an object")
                sanitized = {
                    key: value
                    for key, value in record.items()
                    if key not in {"report_path", "trace_path"}
                }
                sanitized["strategy"] = strategy
                attempts.append(sanitized)
        return attempts

    def _find_experiment(self, experiment_id: str) -> tuple[Path, dict[str, Any]]:
        if len(experiment_id) != 16 or any(char not in "0123456789abcdef" for char in experiment_id):
            raise ArtifactNotFound("experiment not found")
        for comparison_path in self._comparison_paths():
            if self._artifact_id(comparison_path.parent) == experiment_id:
                return comparison_path, self._read_json(comparison_path)
        raise ArtifactNotFound("experiment not found")

    def _comparison_paths(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        paths: set[Path] = set()
        for pattern in (
            "comparison.json",
            "*/comparison.json",
            "*/*/comparison.json",
            "*/*/*/comparison.json",
        ):
            paths.update(
                path
                for path in self.root.glob(pattern)
                if path.is_file() and self._is_within_root(path)
            )
        return sorted(paths)

    def _experiment_summary(self, comparison_path: Path, document: dict[str, Any]) -> dict[str, Any]:
        variants = document.get("variants")
        if not isinstance(variants, list) or not variants:
            raise InvalidArtifact("experiment has no variants")
        strategies = [
            variant.get("strategy")
            for variant in variants
            if isinstance(variant, dict) and isinstance(variant.get("strategy"), str)
        ]
        return {
            "id": self._artifact_id(comparison_path.parent),
            "experiment_id": document.get("experiment_id", comparison_path.parent.name),
            "dimension": document.get("dimension", "context"),
            "provider": document.get("provider", "unknown"),
            "model": document.get("model"),
            "started_at": document.get("started_at", ""),
            "finished_at": document.get("finished_at", ""),
            "passed": all(bool(variant.get("passed")) for variant in variants if isinstance(variant, dict)),
            "repeats": document.get("repeats", 0),
            "task_count": len(document.get("task_ids", [])),
            "strategies": strategies,
            "fake_provider": document.get("provider") == "fake",
        }

    def _artifact_id(self, directory: Path) -> str:
        relative = directory.resolve().relative_to(self.root).as_posix()
        return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]

    def _read_json(self, path: Path) -> dict[str, Any]:
        resolved = self._validated_file(path)
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidArtifact(f"invalid JSON artifact: {resolved.name}") from exc
        if not isinstance(value, dict):
            raise InvalidArtifact(f"artifact must contain an object: {resolved.name}")
        return value

    def _read_json_lines(self, path: Path) -> list[dict[str, Any]]:
        resolved = self._validated_file(path)
        events = []
        for line_number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InvalidArtifact(f"invalid trace event at line {line_number}") from exc
            if not isinstance(event, dict):
                raise InvalidArtifact(f"trace event at line {line_number} must be an object")
            events.append(event)
        return events

    def _validated_file(self, path: Path) -> Path:
        resolved = path.resolve()
        if not self._is_within_root(resolved) or not resolved.is_file():
            raise ArtifactNotFound("artifact file not found")
        if resolved.stat().st_size > self.max_file_bytes:
            raise InvalidArtifact(f"artifact exceeds {self.max_file_bytes} bytes")
        return resolved

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _safe_segment(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
            raise InvalidArtifact(f"invalid {label}")
        return value
