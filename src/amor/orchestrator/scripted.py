from __future__ import annotations

from amor.domain import AgentPhase, AgentState, PlanStep, StepStatus, TaskSpec, ToolResult
from amor.orchestrator.state_machine import StateMachine
from amor.tools import ToolRegistry
from amor.trace import TraceRecorder


class ScriptedOrchestrator:
    """Deterministic agent used to prove the first vertical slice without an LLM."""

    def __init__(self, task: TaskSpec, tools: ToolRegistry, trace: TraceRecorder) -> None:
        self.task = task
        self.tools = tools
        self.trace = trace
        self.state = AgentState(task_id=task.task_id)
        self.machine = StateMachine(self.state, trace)

    def run_until_final_verification(self) -> AgentState:
        self._transition(AgentPhase.PROFILING_REPO, "isolated worktree is ready")
        profile = self.tools.list_files(max_depth=4)
        if not profile.ok:
            self._transition(AgentPhase.FAILED, profile.summary)
            return self.state

        self._transition(AgentPhase.PLANNING, "repository profile is available")
        self.state.plan = [
            PlanStep(step_id=1, task="定位相关实现和现有测试", status=StepStatus.IN_PROGRESS),
            PlanStep(step_id=2, task="实施最小范围修复"),
            PlanStep(step_id=3, task="运行可见验证并根据反馈修复"),
            PlanStep(step_id=4, task="交给独立 Verifier 验收"),
        ]
        self.trace.record("plan_updated", self.state.phase, {"plan": [step.model_dump(mode="json") for step in self.state.plan]})

        self._transition(AgentPhase.EXPLORING, "structured plan has been created")
        if self.task.task_id == "py_utils_average_empty":
            self._repair_average()
        elif self.task.task_id == "py_utils_port_range":
            self._repair_port_range()
        else:
            self._transition(AgentPhase.BLOCKED, "no deterministic script exists for this fixture task")
            return self.state

        if self.state.phase == AgentPhase.VALIDATING:
            diff = self.tools.get_git_diff()
            if not diff.ok or not diff.output:
                self._transition(AgentPhase.FAILED, "no reviewable Git diff was produced")
                return self.state
            self.state.plan[2].status = StepStatus.COMPLETED
            self.state.plan[3].status = StepStatus.IN_PROGRESS
            self._transition(AgentPhase.FINAL_VERIFYING, "visible validation passed")
        return self.state

    def _repair_average(self) -> None:
        if not self._explore("average", "src/calculator.py"):
            return
        self._transition(AgentPhase.EDITING, "empty input is divided by zero")
        if not self._has_edit_budget():
            return
        result = self.tools.apply_patch(
            "src/calculator.py",
            '    return sum(values) / len(values)\n',
            '    if not values:\n        return 0.0\n    return sum(values) / len(values)\n',
        )
        if not self._record_patch(result, "src/calculator.py"):
            return
        self._transition(AgentPhase.VALIDATING, "minimal patch was applied")
        validation = self.tools.run_validation(self.task.visible_validation_commands[0])
        if not validation.ok:
            self.state.latest_error_summary = validation.summary
            self._transition(AgentPhase.FAILED, "deterministic average patch failed visible tests")

    def _repair_port_range(self) -> None:
        if not self._explore("parse_port", "src/config.py"):
            return
        self._transition(AgentPhase.EDITING, "port has no range validation")
        if not self._has_edit_budget():
            return
        first_patch = self.tools.apply_patch(
            "src/config.py",
            '    return int(value)\n',
            '    port = int(value)\n    if port > 65535:\n        raise ValueError("port must be between 1 and 65535")\n    return port\n',
        )
        if not self._record_patch(first_patch, "src/config.py"):
            return
        self._transition(AgentPhase.VALIDATING, "first range patch was applied")
        first_validation = self.tools.run_validation(self.task.visible_validation_commands[0])
        if first_validation.ok:
            return

        self.state.latest_error_summary = first_validation.output[-2_000:]
        self._transition(AgentPhase.DIAGNOSING, "visible test shows zero is still accepted")
        self.state.hypotheses.append("lower-bound validation is missing")
        self._transition(AgentPhase.EDITING, "update the condition to cover both bounds")
        if not self._has_edit_budget():
            return
        second_patch = self.tools.apply_patch(
            "src/config.py",
            "    if port > 65535:\n",
            "    if port < 1 or port > 65535:\n",
        )
        if not self._record_patch(second_patch, "src/config.py"):
            return
        self._transition(AgentPhase.VALIDATING, "diagnosis produced a revised patch")
        second_validation = self.tools.run_validation(self.task.visible_validation_commands[0])
        if not second_validation.ok:
            self.state.latest_error_summary = second_validation.output[-2_000:]
            self._transition(AgentPhase.FAILED, "revised port patch failed visible tests")

    def _explore(self, symbol: str, path: str) -> bool:
        search = self.tools.search_code(symbol, "src")
        read = self.tools.read_file(path, 1, 120)
        if not search.ok or not read.ok:
            self._transition(AgentPhase.BLOCKED, "required source evidence could not be read")
            return False
        self.state.relevant_files.append(path)
        self.state.plan[0].status = StepStatus.COMPLETED
        self.state.plan[0].evidence.append(f"search hit and local read: {path}")
        self.state.plan[1].status = StepStatus.IN_PROGRESS
        return True

    def _record_patch(self, result: ToolResult, path: str) -> bool:
        if not result.ok:
            self.state.latest_error_summary = result.summary
            self._transition(AgentPhase.FAILED, "patch application was rejected or failed")
            return False
        self.state.round += 1
        self.state.attempted_fixes.append(result.summary)
        if path not in self.state.modified_files:
            self.state.modified_files.append(path)
        self.state.plan[1].status = StepStatus.COMPLETED
        self.state.plan[2].status = StepStatus.IN_PROGRESS
        return True

    def _has_edit_budget(self) -> bool:
        if self.state.round < self.task.limits.max_rounds:
            return True
        self._transition(AgentPhase.BUDGET_EXHAUSTED, "maximum patch rounds reached")
        return False

    def _transition(self, phase: AgentPhase, reason: str) -> None:
        self.machine.transition(phase, reason)
        self.tools.phase = phase
