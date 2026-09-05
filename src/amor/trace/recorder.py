from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from amor.domain.models import AgentPhase, utc_now


class TraceRecorder:
    """Append-only JSONL trace used by CLI, tests, and the future UI."""

    def __init__(
        self,
        path: Path,
        task_id: str,
        listener: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.path = path
        self.task_id = task_id
        self.listener = listener
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        event_type: str,
        phase: AgentPhase,
        payload: BaseModel | dict[str, Any],
    ) -> None:
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        event = {
            "event_type": event_type,
            "task_id": self.task_id,
            "phase": phase.value,
            "created_at": utc_now().isoformat(),
            "payload": data,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        if self.listener is not None:
            try:
                self.listener(event)
            except Exception:
                # Observability must never change execution semantics.
                pass
