from pathlib import Path

import pytest

from amor.domain import AgentPhase, AgentState
from amor.orchestrator.state_machine import InvalidTransition, StateMachine
from amor.trace import TraceRecorder


def test_records_valid_transition(tmp_path: Path) -> None:
    state = AgentState(task_id="task")
    machine = StateMachine(state, TraceRecorder(tmp_path / "trace.jsonl", "task"))

    machine.transition(AgentPhase.PROFILING_REPO, "workspace ready")

    assert state.phase == AgentPhase.PROFILING_REPO
    assert "workspace ready" in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")


def test_rejects_invalid_transition(tmp_path: Path) -> None:
    state = AgentState(task_id="task")
    machine = StateMachine(state, TraceRecorder(tmp_path / "trace.jsonl", "task"))

    with pytest.raises(InvalidTransition):
        machine.transition(AgentPhase.SUCCEEDED, "unverified self-declaration")

