from __future__ import annotations

from amor.domain import AgentPhase, AgentState
from amor.trace import TraceRecorder


class InvalidTransition(RuntimeError):
    pass


ALLOWED_TRANSITIONS: dict[AgentPhase, set[AgentPhase]] = {
    AgentPhase.INITIALIZING: {AgentPhase.PROFILING_REPO, AgentPhase.FAILED},
    AgentPhase.PROFILING_REPO: {
        AgentPhase.PLANNING,
        AgentPhase.EXPLORING,
        AgentPhase.FAILED,
    },
    AgentPhase.PLANNING: {AgentPhase.EXPLORING, AgentPhase.BLOCKED, AgentPhase.FAILED},
    AgentPhase.EXPLORING: {
        AgentPhase.EDITING,
        AgentPhase.VALIDATING,
        AgentPhase.BLOCKED,
        AgentPhase.BUDGET_EXHAUSTED,
        AgentPhase.FAILED,
    },
    AgentPhase.EDITING: {
        AgentPhase.EXPLORING,
        AgentPhase.VALIDATING,
        AgentPhase.BLOCKED,
        AgentPhase.FAILED,
        AgentPhase.BUDGET_EXHAUSTED,
    },
    AgentPhase.VALIDATING: {
        AgentPhase.DIAGNOSING,
        AgentPhase.EXPLORING,
        AgentPhase.EDITING,
        AgentPhase.FINAL_VERIFYING,
        AgentPhase.BLOCKED,
        AgentPhase.FAILED,
        AgentPhase.BUDGET_EXHAUSTED,
    },
    AgentPhase.DIAGNOSING: {
        AgentPhase.EXPLORING,
        AgentPhase.EDITING,
        AgentPhase.BLOCKED,
        AgentPhase.FAILED,
        AgentPhase.BUDGET_EXHAUSTED,
    },
    AgentPhase.FINAL_VERIFYING: {
        AgentPhase.DIAGNOSING,
        AgentPhase.SUCCEEDED,
        AgentPhase.FAILED,
    },
}


class StateMachine:
    def __init__(self, state: AgentState, trace: TraceRecorder) -> None:
        self.state = state
        self.trace = trace

    def transition(self, target: AgentPhase, reason: str) -> None:
        allowed = ALLOWED_TRANSITIONS.get(self.state.phase, set())
        if target not in allowed:
            raise InvalidTransition(f"{self.state.phase.value} cannot transition to {target.value}")
        previous = self.state.phase
        self.state.phase = target
        self.trace.record(
            "state_transition",
            target,
            {"from": previous.value, "to": target.value, "reason": reason},
        )
