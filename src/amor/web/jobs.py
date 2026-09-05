from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from threading import Event, RLock
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from amor.acceptance import (
    AcceptancePlan,
    PythonAcceptanceCase,
    load_acceptance_plan,
    run_acceptance_planning,
    write_acceptance_plan,
)
from amor.context import ContextStrategy
from amor.delivery import DeliveryReport, deliver_verified_patch, patch_digest
from amor.domain import RunLimits, RunReport, SandboxConfig, TaskSpec
from amor.execution import docker_runtime_status
from amor.local_runner import run_repository_task
from amor.orchestrator import PlanningStrategy
from amor.profiler import RepositoryProfiler
from amor.providers import ModelProvider, build_api_provider


ProviderName = Literal["openai-responses", "deepseek-responses"]


class JobError(RuntimeError):
    pass


class JobNotFound(JobError):
    pass


class JobConflict(JobError):
    pass


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    REPLANNING = "REPLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    NEEDS_INPUT = "NEEDS_INPUT"
    EXECUTION_QUEUED = "EXECUTION_QUEUED"
    RUNNING = "RUNNING"
    DELIVERY_QUEUED = "DELIVERY_QUEUED"
    DELIVERING = "DELIVERING"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


TERMINAL_JOB_STATUSES = {
    JobStatus.NEEDS_INPUT,
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.BLOCKED,
    JobStatus.BUDGET_EXHAUSTED,
    JobStatus.DELIVERY_FAILED,
    JobStatus.CANCELLED,
}


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=2_000)
    instruction: str = Field(min_length=1, max_length=10_000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)
    allowed_paths: list[str] = Field(min_length=1, max_length=30)
    validation_commands: list[list[str]] = Field(default_factory=list, max_length=10)
    provider: ProviderName = "openai-responses"
    model: str = Field(min_length=1, max_length=200)
    max_rounds: int = Field(default=12, ge=1, le=40)
    max_tokens: int = Field(default=40_000, ge=1, le=2_000_000)
    max_output_tokens: int = Field(default=4_000, ge=1, le=100_000)
    context_budget_chars: int = Field(default=40_000, ge=1_000, le=1_000_000)
    confirm_send_code: Literal[True]

    @field_validator("repository")
    @classmethod
    def repository_is_absolute(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("repository must be an absolute path")
        return str(path.resolve())

    @field_validator("acceptance_criteria", "allowed_paths")
    @classmethod
    def clean_text_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list values must not be empty")
        return cleaned

    @field_validator("validation_commands")
    @classmethod
    def commands_are_argv(cls, commands: list[list[str]]) -> list[list[str]]:
        if any(not command or any(not item for item in command) for command in commands):
            raise ValueError("validation commands must be non-empty argv arrays")
        return commands


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: ProviderName = "openai-responses"
    model: str = Field(min_length=1, max_length=200)
    max_rounds: int = Field(default=20, ge=1, le=100)
    max_seconds: int = Field(default=900, ge=1, le=3_600)
    max_tokens: int = Field(default=100_000, ge=1, le=10_000_000)
    max_verification_retries: int = Field(default=2, ge=0, le=10)
    max_output_tokens: int = Field(default=4_000, ge=1, le=100_000)
    context_budget_chars: int = Field(default=40_000, ge=1_000, le=1_000_000)
    context_strategy: Literal["broad", "search-first"] = "search-first"
    planning_strategy: Literal["direct", "structured"] = "structured"
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    confirm_send_code: Literal[True]


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1_000)
    answer: str = Field(min_length=1, max_length=4_000)

    @field_validator("question", "answer")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("clarification text must not be blank")
        return cleaned


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def questions_are_unique(self) -> "ClarificationRequest":
        questions = [item.question for item in self.answers]
        if len(questions) != len(set(questions)):
            raise ValueError("clarification questions must be unique")
        return self


class ContractEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    preserved_behaviors: list[str] = Field(default_factory=list, max_length=20)
    edge_cases: list[str] = Field(default_factory=list, max_length=20)
    allowed_paths: list[str] = Field(min_length=1, max_length=30)
    validation_commands: list[list[str]] = Field(min_length=1, max_length=10)
    python_cases: list[PythonAcceptanceCase] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=1_000)
    revision_note: str = Field(default="人工编辑契约", min_length=1, max_length=500)

    @field_validator(
        "acceptance_criteria",
        "preserved_behaviors",
        "edge_cases",
        "allowed_paths",
    )
    @classmethod
    def clean_text_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list values must not be empty")
        return cleaned

    @field_validator("validation_commands")
    @classmethod
    def commands_are_argv(cls, commands: list[list[str]]) -> list[list[str]]:
        if any(not command or any(not item for item in command) for command in commands):
            raise ValueError("validation commands must be non-empty argv arrays")
        return commands

    @field_validator("summary", "revision_note")
    @classmethod
    def clean_summary(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("contract text must not be blank")
        return cleaned


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    branch_name: str = Field(min_length=1, max_length=200)
    commit_requested: bool = True
    commit_message: str = Field(default="fix: apply verified AMOR patch", max_length=500)
    confirm_apply: Literal[True]

    @field_validator("branch_name", "commit_message")
    @classmethod
    def clean_delivery_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("delivery text must not be blank")
        if "\n" in cleaned or "\r" in cleaned:
            raise ValueError("delivery text must be a single line")
        return cleaned


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int
    created_at: datetime
    kind: str
    phase: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ClarificationRound(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    based_on_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    answers: list[ClarificationAnswer]
    created_at: datetime


class ContractRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: int = Field(ge=1)
    source: Literal["planner", "clarification", "manual"]
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact: str = Field(min_length=1, max_length=2_000)
    note: str = Field(min_length=1, max_length=500)
    created_at: datetime


class DeliveryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    request: DeliveryRequest
    report: dict[str, Any] | None = None
    report_artifact: str | None = None
    workspace_artifact: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
    status: JobStatus
    phase: str
    planning_request: PlanningRequest
    execution_request: ExecutionRequest | None = None
    plan: dict[str, Any] | None = None
    plan_artifact: str | None = None
    run: dict[str, Any] | None = None
    run_artifact: str | None = None
    error: str | None = None
    clarifications: list[ClarificationRound] = Field(default_factory=list)
    contract_revisions: list[ContractRevision] = Field(default_factory=list)
    patch_sha256: str | None = None
    deliveries: list[DeliveryState] = Field(default_factory=list)
    events: list[JobEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


@dataclass
class _ManagedJob:
    snapshot: JobSnapshot
    cancel_event: Event = field(default_factory=Event)
    future: Future[None] | None = None


ProviderFactory = Callable[..., ModelProvider]
Planner = Callable[..., AcceptancePlan]
Runner = Callable[..., RunReport]
Deliverer = Callable[..., DeliveryReport]


class TaskJobManager:
    """Single-worker local task queue with persisted, browser-safe snapshots."""

    def __init__(
        self,
        artifacts_root: Path,
        *,
        project_root: Path | None = None,
        provider_factory: ProviderFactory = build_api_provider,
        planner: Planner = run_acceptance_planning,
        runner: Runner = run_repository_task,
        deliverer: Deliverer = deliver_verified_patch,
    ) -> None:
        self.artifacts_root = artifacts_root.resolve()
        self.jobs_root = self.artifacts_root / "jobs"
        self.project_root = (
            project_root.resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self.provider_factory = provider_factory
        self.planner = planner
        self.runner = runner
        self.deliverer = deliverer
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="amor-local-job")
        self._jobs: dict[str, _ManagedJob] = {}
        self._load_existing()

    def runtime(self) -> dict[str, Any]:
        from amor.providers import provider_configuration

        return {
            "mode": "local",
            "max_concurrent_jobs": 1,
            "working_directory": str(Path.cwd().resolve()),
            "providers": provider_configuration(),
            "docker": docker_runtime_status(),
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.snapshot.created_at,
                reverse=True,
            )
            return [self._public_snapshot(item.snapshot, include_events=False) for item in jobs]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return self._public_snapshot(self._get(job_id).snapshot, include_events=True)

    def get_contract_revision(self, job_id: str, revision: int) -> dict[str, Any]:
        with self._lock:
            snapshot = self._get(job_id).snapshot
            metadata = next(
                (item for item in snapshot.contract_revisions if item.revision == revision),
                None,
            )
            if metadata is None:
                raise JobNotFound("contract revision not found")
            path = self._artifact_path(metadata.artifact)
            return load_acceptance_plan(path).model_dump(mode="json")

    def events_after(self, job_id: str, sequence: int) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            snapshot = self._get(job_id).snapshot
            events = [
                event.model_dump(mode="json")
                for event in snapshot.events
                if event.sequence > sequence
            ]
            settled = snapshot.status in TERMINAL_JOB_STATUSES or snapshot.status == JobStatus.AWAITING_APPROVAL
            return events, settled

    def start_planning(self, request: PlanningRequest) -> dict[str, Any]:
        repository = Path(request.repository)
        profile = RepositoryProfiler().profile(repository)
        if profile.dirty_worktree:
            raise JobConflict("repository must be clean before acceptance planning")
        if "Python" not in profile.languages:
            raise JobConflict("acceptance planning currently supports Python repositories only")
        self.provider_factory(
            request.provider,
            model=request.model,
            max_output_tokens=request.max_output_tokens,
        )

        now = _utc_now()
        job_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        snapshot = JobSnapshot(
            job_id=job_id,
            status=JobStatus.QUEUED,
            phase="QUEUED",
            planning_request=request,
            created_at=now,
            updated_at=now,
        )
        managed = _ManagedJob(snapshot=snapshot)
        with self._lock:
            self._jobs[job_id] = managed
            self._append_event_locked(managed, "job", "任务已进入验收规划队列")
            managed.future = self._executor.submit(self._run_planning, job_id)
        return self.get_job(job_id)

    def approve_and_run(self, job_id: str, request: ExecutionRequest) -> dict[str, Any]:
        with self._lock:
            managed = self._get(job_id)
            if managed.snapshot.status != JobStatus.AWAITING_APPROVAL:
                raise JobConflict("job is not awaiting contract approval")
            plan = self._load_job_plan(managed.snapshot)
            if plan.contract_sha256 != request.contract_sha256:
                raise JobConflict("contract changed after it was reviewed; refresh before approval")
            self.provider_factory(
                request.provider,
                model=request.model,
                timeout_seconds=request.max_seconds,
                max_output_tokens=request.max_output_tokens,
            )
            managed.snapshot.execution_request = request
            managed.snapshot.status = JobStatus.EXECUTION_QUEUED
            managed.snapshot.phase = "EXECUTION_QUEUED"
            managed.snapshot.error = None
            self._append_event_locked(managed, "approval", "验收契约已批准，执行任务进入队列")
            managed.future = self._executor.submit(self._run_execution, job_id)
            return self._public_snapshot(managed.snapshot, include_events=True)

    def answer_questions(
        self,
        job_id: str,
        request: ClarificationRequest,
    ) -> dict[str, Any]:
        with self._lock:
            managed = self._get(job_id)
            if managed.snapshot.status != JobStatus.NEEDS_INPUT:
                raise JobConflict("job is not waiting for clarification")
            plan = self._load_job_plan(managed.snapshot)
            if plan.contract_sha256 != request.contract_sha256:
                raise JobConflict("contract changed after it was reviewed; refresh before answering")
            expected = set(plan.questions)
            received = {item.question for item in request.answers}
            if received != expected:
                missing = sorted(expected - received)
                unknown = sorted(received - expected)
                details = []
                if missing:
                    details.append("missing: " + "; ".join(missing))
                if unknown:
                    details.append("unknown: " + "; ".join(unknown))
                raise JobConflict("answers must match the current questions (" + ", ".join(details) + ")")
            self._require_unchanged_repository(managed.snapshot, plan)
            planning = managed.snapshot.planning_request
            self.provider_factory(
                planning.provider,
                model=planning.model,
                max_output_tokens=planning.max_output_tokens,
            )
            managed.snapshot.clarifications.append(
                ClarificationRound(
                    based_on_sha256=plan.contract_sha256,
                    answers=request.answers,
                    created_at=_utc_now(),
                )
            )
            managed.cancel_event.clear()
            managed.snapshot.status = JobStatus.QUEUED
            managed.snapshot.phase = "REVISION_QUEUED"
            managed.snapshot.error = None
            self._append_event_locked(
                managed,
                "clarification",
                "补充信息已保存，契约修订进入队列",
                payload={"answer_count": len(request.answers)},
            )
            managed.future = self._executor.submit(self._run_planning, job_id)
            return self._public_snapshot(managed.snapshot, include_events=True)

    def edit_contract(
        self,
        job_id: str,
        request: ContractEditRequest,
    ) -> dict[str, Any]:
        with self._lock:
            managed = self._get(job_id)
            if managed.snapshot.status not in {
                JobStatus.AWAITING_APPROVAL,
                JobStatus.NEEDS_INPUT,
            }:
                raise JobConflict("job contract cannot be edited in its current status")
            current = self._load_job_plan(managed.snapshot)
            if current.contract_sha256 != request.contract_sha256:
                raise JobConflict("contract changed after it was opened; refresh before saving")
            self._require_unchanged_repository(managed.snapshot, current)
            payload = current.model_dump(mode="json")
            payload.update(
                {
                    "status": "READY",
                    "acceptance_criteria": request.acceptance_criteria,
                    "preserved_behaviors": request.preserved_behaviors,
                    "edge_cases": request.edge_cases,
                    "allowed_paths": request.allowed_paths,
                    "validation_commands": request.validation_commands,
                    "python_cases": [
                        item.model_dump(mode="json") for item in request.python_cases
                    ],
                    "questions": [],
                    "summary": request.summary,
                    "created_at": _utc_now(),
                }
            )
            plan = self._record_contract_revision_locked(
                managed,
                payload,
                source="manual",
                note=request.revision_note,
            )
            managed.snapshot.status = JobStatus.AWAITING_APPROVAL
            managed.snapshot.phase = "AWAITING_APPROVAL"
            managed.snapshot.execution_request = None
            managed.snapshot.error = None
            self._append_event_locked(
                managed,
                "contract_edited",
                "人工修改已冻结为新的契约版本，等待重新审批",
                payload={"contract_sha256": plan.contract_sha256},
            )
            return self._public_snapshot(managed.snapshot, include_events=True)

    def start_delivery(
        self,
        job_id: str,
        request: DeliveryRequest,
    ) -> dict[str, Any]:
        with self._lock:
            managed = self._get(job_id)
            if managed.snapshot.status not in {
                JobStatus.SUCCEEDED,
                JobStatus.DELIVERY_FAILED,
            }:
                raise JobConflict("only a successfully verified run can be delivered")
            plan = self._load_job_plan(managed.snapshot)
            if plan.contract_sha256 != request.contract_sha256:
                raise JobConflict("contract changed after the run; delivery was refused")
            run = managed.snapshot.run
            if not isinstance(run, dict) or not run.get("verification", {}).get("passed"):
                raise JobConflict("successful verifier evidence is missing")
            patch = run.get("git_diff")
            if not isinstance(patch, str) or not patch.strip():
                raise JobConflict("verified run does not contain a patch")
            actual_patch_sha256 = patch_digest(patch)
            if managed.snapshot.patch_sha256 != actual_patch_sha256:
                raise JobConflict("stored patch fingerprint no longer matches the verified run")
            if request.patch_sha256 != actual_patch_sha256:
                raise JobConflict("patch changed after it was reviewed; refresh before delivery")
            self._require_unchanged_repository(managed.snapshot, plan)
            TaskSpec.model_validate(run.get("task"))

            now = _utc_now()
            delivery = DeliveryState(
                attempt=len(managed.snapshot.deliveries) + 1,
                status="QUEUED",
                request=request,
                created_at=now,
                updated_at=now,
            )
            managed.snapshot.deliveries.append(delivery)
            managed.cancel_event.clear()
            managed.snapshot.status = JobStatus.DELIVERY_QUEUED
            managed.snapshot.phase = "DELIVERY_QUEUED"
            managed.snapshot.error = None
            self._append_event_locked(
                managed,
                "delivery_queued",
                f"已验收补丁将交付到本地分支 {request.branch_name}",
                payload={
                    "branch_name": request.branch_name,
                    "patch_sha256": request.patch_sha256,
                    "commit_requested": request.commit_requested,
                },
            )
            managed.future = self._executor.submit(self._run_delivery, job_id)
            return self._public_snapshot(managed.snapshot, include_events=True)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            managed = self._get(job_id)
            if managed.snapshot.status in TERMINAL_JOB_STATUSES:
                return self._public_snapshot(managed.snapshot, include_events=True)
            delivery = self._current_delivery(managed.snapshot)
            delivery_active = managed.snapshot.status in {
                JobStatus.DELIVERY_QUEUED,
                JobStatus.DELIVERING,
            }
            managed.cancel_event.set()
            if managed.future is not None and managed.future.cancel():
                if delivery_active and delivery is not None:
                    delivery.status = "CANCELLED"
                    delivery.updated_at = _utc_now()
                    managed.snapshot.status = JobStatus.SUCCEEDED
                    managed.snapshot.phase = "SUCCEEDED"
                    self._append_event_locked(managed, "delivery_cancelled", "补丁交付已在执行前取消")
                else:
                    managed.snapshot.status = JobStatus.CANCELLED
                    managed.snapshot.phase = "CANCELLED"
                    self._append_event_locked(managed, "cancelled", "任务已在执行前取消")
            elif managed.snapshot.status == JobStatus.AWAITING_APPROVAL:
                managed.snapshot.status = JobStatus.CANCELLED
                managed.snapshot.phase = "CANCELLED"
                self._append_event_locked(managed, "cancelled", "任务已取消")
            else:
                managed.snapshot.status = JobStatus.CANCEL_REQUESTED
                self._append_event_locked(
                    managed,
                    "cancel_requested",
                    (
                        "已请求取消补丁交付，将在当前安全步骤结束后停止"
                        if delivery_active
                        else "已请求取消，将在当前安全步骤结束后停止"
                    ),
                )
            return self._public_snapshot(managed.snapshot, include_events=True)

    def shutdown(self) -> None:
        with self._lock:
            for managed in self._jobs.values():
                if managed.snapshot.status not in TERMINAL_JOB_STATUSES:
                    managed.cancel_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_planning(self, job_id: str) -> None:
        managed = self._managed(job_id)
        if managed.cancel_event.is_set():
            self._finish_cancelled(job_id)
            return
        request = managed.snapshot.planning_request
        try:
            current_plan = (
                self._load_job_plan(managed.snapshot)
                if managed.snapshot.plan_artifact is not None
                else None
            )
            revision_context = self._revision_context(managed.snapshot, current_plan)
            if revision_context is None:
                self._set_status(
                    job_id,
                    JobStatus.PLANNING,
                    "PLANNING",
                    "独立规划器正在读取仓库证据",
                )
            else:
                self._set_status(
                    job_id,
                    JobStatus.REPLANNING,
                    "REPLANNING",
                    "独立规划器正在根据补充信息修订契约",
                )
            provider = self.provider_factory(
                request.provider,
                model=request.model,
                max_output_tokens=request.max_output_tokens,
            )
            plan = self.planner(
                repository=Path(request.repository),
                instruction=request.instruction,
                acceptance_criteria=request.acceptance_criteria,
                allowed_paths=(
                    current_plan.allowed_paths
                    if current_plan is not None
                    else request.allowed_paths
                ),
                validation_commands=(
                    current_plan.validation_commands
                    if current_plan is not None
                    else request.validation_commands or None
                ),
                provider_name=request.provider,
                model=request.model,
                provider=provider,
                artifacts_root=self.artifacts_root / "plans",
                max_rounds=request.max_rounds,
                max_total_tokens=request.max_tokens,
                context_budget_chars=request.context_budget_chars,
                should_cancel=managed.cancel_event.is_set,
                trace_listener=self._trace_listener(job_id),
                revision_context=revision_context,
            )
            if managed.cancel_event.is_set():
                self._finish_cancelled(job_id)
                return
            with self._lock:
                source: Literal["planner", "clarification"] = (
                    "clarification" if revision_context is not None else "planner"
                )
                note = (
                    f"根据第 {len(managed.snapshot.clarifications)} 轮补充信息重新规划"
                    if revision_context is not None
                    else "独立规划器生成初始契约"
                )
                plan = self._record_contract_revision_locked(
                    managed,
                    plan.model_dump(mode="json"),
                    source=source,
                    note=note,
                )
                if plan.status == "READY":
                    managed.snapshot.status = JobStatus.AWAITING_APPROVAL
                    managed.snapshot.phase = "AWAITING_APPROVAL"
                    message = "验收契约已冻结，等待人工审批"
                else:
                    managed.snapshot.status = JobStatus.NEEDS_INPUT
                    managed.snapshot.phase = "NEEDS_INPUT"
                    message = "规划器需要补充信息，请查看契约问题"
                self._append_event_locked(managed, "plan_ready", message)
        except Exception as exc:
            self._finish_error(job_id, exc)

    def _run_execution(self, job_id: str) -> None:
        managed = self._managed(job_id)
        if managed.cancel_event.is_set():
            self._finish_cancelled(job_id)
            return
        self._set_status(job_id, JobStatus.RUNNING, "INITIALIZING", "执行 Agent 正在初始化隔离工作区")
        planning = managed.snapshot.planning_request
        execution = managed.snapshot.execution_request
        if execution is None:
            self._finish_error(job_id, JobConflict("execution settings are missing"))
            return
        try:
            plan = self._load_job_plan(managed.snapshot)
            provider = self.provider_factory(
                execution.provider,
                model=execution.model,
                timeout_seconds=execution.max_seconds,
                max_output_tokens=execution.max_output_tokens,
            )
            report = self.runner(
                project_root=self.project_root,
                repository=Path(planning.repository),
                instruction=plan.instruction,
                acceptance_criteria=plan.acceptance_criteria,
                allowed_paths=plan.allowed_paths,
                validation_commands=plan.validation_commands,
                provider_name=execution.provider,
                model=execution.model,
                provider=provider,
                artifacts_root=self.artifacts_root / "runs",
                limits=RunLimits(
                    max_rounds=execution.max_rounds,
                    max_seconds=execution.max_seconds,
                    max_total_tokens=execution.max_tokens,
                    max_verification_retries=execution.max_verification_retries,
                ),
                context_strategy=ContextStrategy(execution.context_strategy),
                context_budget_chars=execution.context_budget_chars,
                planning_strategy=PlanningStrategy(execution.planning_strategy),
                acceptance_plan=plan,
                acceptance_plan_path=self.artifacts_root / managed.snapshot.plan_artifact,
                should_cancel=managed.cancel_event.is_set,
                trace_listener=self._trace_listener(job_id),
                sandbox=execution.sandbox,
            )
            with self._lock:
                managed.snapshot.run = _safe_report(report)
                managed.snapshot.patch_sha256 = patch_digest(report.git_diff)
                managed.snapshot.run_artifact = self._relative_artifact(
                    Path(report.trace_path).parent / "final-report.json"
                )
                status = JobStatus(report.final_status.value)
                managed.snapshot.status = status
                managed.snapshot.phase = report.state.phase.value
                self._append_event_locked(
                    managed,
                    "run_finished",
                    "任务验收通过" if status == JobStatus.SUCCEEDED else f"任务结束：{status.value}",
                )
        except Exception as exc:
            self._finish_error(job_id, exc)

    def _run_delivery(self, job_id: str) -> None:
        managed = self._managed(job_id)
        delivery = self._current_delivery(managed.snapshot)
        if delivery is None:
            self._finish_delivery_error(job_id, JobConflict("delivery settings are missing"))
            return
        if managed.cancel_event.is_set():
            self._finish_delivery_cancelled(job_id)
            return
        with self._lock:
            delivery.status = "RUNNING"
            delivery.updated_at = _utc_now()
            managed.snapshot.status = JobStatus.DELIVERING
            managed.snapshot.phase = "DELIVERING"
            self._append_event_locked(
                managed,
                "delivery_started",
                "正在新的交付 worktree 中应用并重新验收补丁",
            )

        try:
            plan = self._load_job_plan(managed.snapshot)
            self._require_unchanged_repository(managed.snapshot, plan)
            run = managed.snapshot.run
            if not isinstance(run, dict):
                raise JobConflict("verified run evidence is missing")
            patch = run.get("git_diff")
            if not isinstance(patch, str):
                raise JobConflict("verified patch is missing")
            request = delivery.request
            delivery_root = (
                self.jobs_root
                / job_id
                / "deliveries"
                / f"attempt-{delivery.attempt:04d}"
            )
            report = self.deliverer(
                project_root=self.project_root,
                repository=Path(managed.snapshot.planning_request.repository),
                baseline_commit=plan.baseline_commit,
                patch=patch,
                expected_patch_sha256=request.patch_sha256,
                branch_name=request.branch_name,
                commit_requested=request.commit_requested,
                commit_message=request.commit_message,
                task=TaskSpec.model_validate(run.get("task")),
                acceptance_plan_path=self._artifact_path(managed.snapshot.plan_artifact or ""),
                delivery_root=delivery_root,
                should_cancel=managed.cancel_event.is_set,
            )
            with self._lock:
                delivery.report = report.model_dump(mode="json", exclude={"workspace_path"})
                delivery.report_artifact = self._relative_artifact(
                    delivery_root / "delivery-report.json"
                )
                delivery.workspace_artifact = self._relative_artifact(Path(report.workspace_path))
                delivery.status = report.status
                delivery.error = report.error
                delivery.updated_at = _utc_now()
                if report.status == "SUCCEEDED":
                    managed.snapshot.status = JobStatus.SUCCEEDED
                    managed.snapshot.phase = "DELIVERED"
                    managed.snapshot.error = None
                    message = (
                        f"补丁已重新验收并提交到本地分支 {report.branch_name}"
                        if report.commit_sha
                        else f"补丁已重新验收并保留在交付 worktree：{report.branch_name}"
                    )
                    kind = "delivery_finished"
                elif report.status == "CANCELLED":
                    managed.snapshot.status = JobStatus.SUCCEEDED
                    managed.snapshot.phase = "SUCCEEDED"
                    managed.snapshot.error = None
                    message = "补丁交付已取消；原验收结果保持不变"
                    kind = "delivery_cancelled"
                else:
                    managed.snapshot.status = JobStatus.DELIVERY_FAILED
                    managed.snapshot.phase = "DELIVERY_FAILED"
                    managed.snapshot.error = report.error
                    message = "补丁落地后的独立验收未通过"
                    kind = "delivery_failed"
                self._append_event_locked(
                    managed,
                    kind,
                    message,
                    payload={
                        "branch_name": report.branch_name,
                        "commit_sha": report.commit_sha,
                        "patch_sha256": report.patch_sha256,
                    },
                )
        except Exception as exc:
            if managed.cancel_event.is_set():
                self._finish_delivery_cancelled(job_id)
            else:
                self._finish_delivery_error(job_id, exc)

    def _trace_listener(self, job_id: str) -> Callable[[dict[str, Any]], None]:
        def listen(event: dict[str, Any]) -> None:
            kind = str(event.get("event_type", "trace"))
            phase = str(event.get("phase", "RUNNING"))
            payload = event.get("payload")
            safe_payload: dict[str, Any] = {}
            message = kind
            if isinstance(payload, dict):
                if kind == "state_transition":
                    safe_payload = {
                        key: payload.get(key)
                        for key in ("from", "to", "reason")
                    }
                    message = str(payload.get("reason", "Agent 状态已更新"))
                elif kind == "tool":
                    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                    safe_payload = {
                        "tool": payload.get("tool"),
                        "policy_result": payload.get("policy_result"),
                        "ok": result.get("ok"),
                        "summary": result.get("summary"),
                        "duration_ms": payload.get("duration_ms"),
                    }
                    message = f"工具：{payload.get('tool', 'unknown')}"
                elif kind in {"model_turn", "acceptance_planner_turn"}:
                    safe_payload = {
                        "round": payload.get("round"),
                        "tool_names": payload.get("tool_names"),
                        "usage": payload.get("usage"),
                    }
                    message = "模型返回了新的工具决策"
                elif kind == "verification":
                    safe_payload = {
                        "passed": payload.get("passed"),
                        "failure_category": payload.get("failure_category"),
                    }
                    message = "独立 Verifier 已完成一次验收"
                elif kind == "sandbox_configured":
                    safe_payload = {
                        key: payload.get(key)
                        for key in (
                            "mode",
                            "image",
                            "cpus",
                            "memory_mb",
                            "pids_limit",
                            "tmpfs_mb",
                            "workspace_growth_mb",
                            "network_disabled",
                        )
                    }
                    message = (
                        "目标项目命令将在 Docker 无网络沙箱中执行"
                        if payload.get("mode") == "docker"
                        else "目标项目命令使用宿主机兼容模式"
                    )
                else:
                    return
            with self._lock:
                managed = self._get(job_id)
                if managed.snapshot.status == JobStatus.CANCEL_REQUESTED:
                    visible_phase = JobStatus.CANCEL_REQUESTED.value
                else:
                    visible_phase = phase
                    managed.snapshot.phase = phase
                self._append_event_locked(
                    managed,
                    kind,
                    message,
                    phase=visible_phase,
                    payload=safe_payload,
                )

        return listen

    def _set_status(
        self,
        job_id: str,
        status: JobStatus,
        phase: str,
        message: str,
    ) -> None:
        with self._lock:
            managed = self._get(job_id)
            managed.snapshot.status = status
            managed.snapshot.phase = phase
            self._append_event_locked(managed, "status", message)

    def _finish_cancelled(self, job_id: str) -> None:
        with self._lock:
            managed = self._get(job_id)
            managed.snapshot.status = JobStatus.CANCELLED
            managed.snapshot.phase = "CANCELLED"
            self._append_event_locked(managed, "cancelled", "任务已取消")

    def _finish_error(self, job_id: str, exc: Exception) -> None:
        with self._lock:
            managed = self._get(job_id)
            if managed.cancel_event.is_set():
                managed.snapshot.status = JobStatus.CANCELLED
                managed.snapshot.phase = "CANCELLED"
                managed.snapshot.error = None
                self._append_event_locked(managed, "cancelled", "任务已取消")
                return
            managed.snapshot.status = JobStatus.FAILED
            managed.snapshot.phase = "FAILED"
            managed.snapshot.error = str(exc)[:2_000]
            self._append_event_locked(managed, "error", "任务执行失败")

    def _finish_delivery_cancelled(self, job_id: str) -> None:
        with self._lock:
            managed = self._get(job_id)
            delivery = self._current_delivery(managed.snapshot)
            if delivery is not None:
                delivery.status = "CANCELLED"
                delivery.updated_at = _utc_now()
            managed.snapshot.status = JobStatus.SUCCEEDED
            managed.snapshot.phase = "SUCCEEDED"
            managed.snapshot.error = None
            self._append_event_locked(
                managed,
                "delivery_cancelled",
                "补丁交付已取消；原验收结果保持不变",
            )

    def _finish_delivery_error(self, job_id: str, exc: Exception) -> None:
        with self._lock:
            managed = self._get(job_id)
            delivery = self._current_delivery(managed.snapshot)
            error = str(exc)[:2_000]
            if delivery is not None:
                delivery.status = "FAILED"
                delivery.error = error
                delivery.updated_at = _utc_now()
            managed.snapshot.status = JobStatus.DELIVERY_FAILED
            managed.snapshot.phase = "DELIVERY_FAILED"
            managed.snapshot.error = error
            self._append_event_locked(managed, "delivery_failed", "补丁交付失败")

    def _append_event_locked(
        self,
        managed: _ManagedJob,
        kind: str,
        message: str,
        *,
        phase: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        sequence = managed.snapshot.events[-1].sequence + 1 if managed.snapshot.events else 1
        now = _utc_now()
        managed.snapshot.events.append(
            JobEvent(
                sequence=sequence,
                created_at=now,
                kind=kind,
                phase=phase or managed.snapshot.phase,
                message=message,
                payload=payload or {},
            )
        )
        if len(managed.snapshot.events) > 500:
            managed.snapshot.events = managed.snapshot.events[-500:]
        managed.snapshot.updated_at = now
        self._persist_locked(managed.snapshot)

    def _record_contract_revision_locked(
        self,
        managed: _ManagedJob,
        payload: dict[str, Any],
        *,
        source: Literal["planner", "clarification", "manual"],
        note: str,
    ) -> AcceptancePlan:
        revision = len(managed.snapshot.contract_revisions) + 1
        path = self.jobs_root / managed.snapshot.job_id / "contracts" / f"revision-{revision:04d}.json"
        plan = write_acceptance_plan(path, payload)
        artifact = self._relative_artifact(path)
        managed.snapshot.plan = plan.model_dump(mode="json")
        managed.snapshot.plan_artifact = artifact
        managed.snapshot.contract_revisions.append(
            ContractRevision(
                revision=revision,
                source=source,
                contract_sha256=plan.contract_sha256,
                artifact=artifact,
                note=note,
                created_at=_utc_now(),
            )
        )
        return plan

    @staticmethod
    def _current_delivery(snapshot: JobSnapshot) -> DeliveryState | None:
        return snapshot.deliveries[-1] if snapshot.deliveries else None

    @staticmethod
    def _revision_context(
        snapshot: JobSnapshot,
        current_plan: AcceptancePlan | None,
    ) -> dict[str, Any] | None:
        if current_plan is None or not snapshot.clarifications:
            return None
        return {
            "previous_contract": current_plan.model_dump(mode="json"),
            "clarification_rounds": [
                item.model_dump(mode="json") for item in snapshot.clarifications
            ],
        }

    @staticmethod
    def _require_unchanged_repository(
        snapshot: JobSnapshot,
        plan: AcceptancePlan,
    ) -> None:
        profile = RepositoryProfiler().profile(Path(snapshot.planning_request.repository))
        if profile.dirty_worktree:
            raise JobConflict("repository changed after planning; restore a clean worktree first")
        if profile.head_commit != plan.baseline_commit:
            raise JobConflict("repository HEAD changed after planning; create a new task")

    def _artifact_path(self, artifact: str) -> Path:
        path = (self.artifacts_root / artifact).resolve()
        try:
            path.relative_to(self.artifacts_root)
        except ValueError as exc:
            raise JobConflict("job artifact escaped the artifact root") from exc
        return path

    def _load_job_plan(self, snapshot: JobSnapshot) -> AcceptancePlan:
        if not snapshot.plan_artifact:
            raise JobConflict("acceptance plan artifact is missing")
        return load_acceptance_plan(self._artifact_path(snapshot.plan_artifact))

    def _managed(self, job_id: str) -> _ManagedJob:
        with self._lock:
            return self._get(job_id)

    def _get(self, job_id: str) -> _ManagedJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFound("job not found") from exc

    def _relative_artifact(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.artifacts_root).as_posix()
        except ValueError as exc:
            raise JobConflict("job artifact escaped the configured artifact root") from exc

    def _persist_locked(self, snapshot: JobSnapshot) -> None:
        directory = self.jobs_root / snapshot.job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "job.json"
        temporary = directory / "job.json.tmp"
        temporary.write_text(
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)

    def _load_existing(self) -> None:
        if not self.jobs_root.is_dir():
            return
        for path in sorted(self.jobs_root.glob("*/job.json")):
            try:
                if path.stat().st_size > 10_000_000:
                    continue
                snapshot = JobSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if snapshot.job_id != path.parent.name:
                continue
            managed = _ManagedJob(snapshot=snapshot)
            self._jobs[snapshot.job_id] = managed
            if snapshot.patch_sha256 is None and isinstance(snapshot.run, dict):
                patch = snapshot.run.get("git_diff")
                if isinstance(patch, str):
                    snapshot.patch_sha256 = patch_digest(patch)
                    self._persist_locked(snapshot)
            if snapshot.plan_artifact and snapshot.plan and not snapshot.contract_revisions:
                try:
                    plan = self._load_job_plan(snapshot)
                except (RuntimeError, ValueError):
                    pass
                else:
                    snapshot.contract_revisions.append(
                        ContractRevision(
                            revision=1,
                            source="planner",
                            contract_sha256=plan.contract_sha256,
                            artifact=snapshot.plan_artifact,
                            note="v0.10 迁移的初始契约",
                            created_at=plan.created_at,
                        )
                    )
                    self._persist_locked(snapshot)
            delivery = self._current_delivery(snapshot)
            if delivery is not None and snapshot.status in {
                JobStatus.DELIVERY_QUEUED,
                JobStatus.DELIVERING,
                JobStatus.CANCEL_REQUESTED,
            }:
                delivery.status = "FAILED"
                delivery.error = "local service restarted before delivery completed"
                delivery.updated_at = _utc_now()
                snapshot.status = JobStatus.DELIVERY_FAILED
                snapshot.phase = "DELIVERY_FAILED"
                snapshot.error = delivery.error
                self._append_event_locked(
                    managed,
                    "delivery_interrupted",
                    "服务重启，未完成的补丁交付已终止",
                )
                continue
            if snapshot.status in {
                JobStatus.QUEUED,
                JobStatus.PLANNING,
                JobStatus.REPLANNING,
                JobStatus.EXECUTION_QUEUED,
                JobStatus.RUNNING,
                JobStatus.DELIVERY_QUEUED,
                JobStatus.DELIVERING,
                JobStatus.CANCEL_REQUESTED,
            }:
                snapshot.status = JobStatus.FAILED
                snapshot.phase = "FAILED"
                snapshot.error = "local service restarted before the job completed"
                self._append_event_locked(managed, "interrupted", "服务重启，未完成任务已终止")

    @staticmethod
    def _public_snapshot(snapshot: JobSnapshot, *, include_events: bool) -> dict[str, Any]:
        document = snapshot.model_dump(mode="json")
        if not include_events:
            document["events"] = []
        return document


def _safe_report(report: RunReport) -> dict[str, Any]:
    return report.model_dump(
        mode="json",
        exclude={"trace_path", "workspace_path"},
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
