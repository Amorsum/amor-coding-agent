import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from amor.acceptance import write_acceptance_plan
from amor.benchmarks import BenchmarkLayout
from amor.domain import (
    AgentPhase,
    AgentState,
    RunReport,
    TaskSpec,
    TerminalStatus,
    VerificationCheck,
    VerificationResult,
)
from amor.web.app import create_app
from amor.web.jobs import TaskJobManager
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def wait_for_status(client: TestClient, job_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == expected:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {expected}: {job}")


def test_local_web_job_plans_waits_for_approval_and_runs(tmp_path: Path) -> None:
    fixture = WorkspaceManager().create_from_fixture(
        BenchmarkLayout(project_root() / "benchmarks").fixtures / "python_utils",
        tmp_path / "fixture",
    )
    artifacts = tmp_path / "artifacts"

    def provider_factory(*args, **kwargs):
        return object()

    def planner(**kwargs):
        kwargs["trace_listener"](
            {
                "event_type": "acceptance_planner_turn",
                "phase": "EXPLORING",
                "payload": {"round": 1, "tool_names": ["read_file"], "usage": {}},
            }
        )
        return write_acceptance_plan(
            kwargs["artifacts_root"] / "web-plan" / "acceptance-plan.json",
            {
                "schema_version": "v1",
                "plan_id": "web-plan",
                "status": "READY",
                "baseline_commit": fixture.baseline_commit,
                "instruction": kwargs["instruction"],
                "acceptance_criteria": ["empty input returns 0.0"],
                "preserved_behaviors": ["non-empty averages remain unchanged"],
                "edge_cases": ["empty list"],
                "allowed_paths": kwargs["allowed_paths"],
                "validation_commands": kwargs["validation_commands"],
                "python_cases": [
                    {
                        "name": "empty average",
                        "module": "src.calculator",
                        "callable": "average",
                        "args_json": "[[]]",
                        "kwargs_json": "{}",
                        "expectation": "equals",
                        "expected_json": "0.0",
                        "exception_type": "",
                        "rationale": "requested behavior",
                    }
                ],
                "evidence_files": ["src/calculator.py"],
                "questions": [],
                "summary": "empty input contract",
                "provider": kwargs["provider_name"],
                "model": kwargs["model"],
                "token_usage": {},
                "created_at": datetime.now(timezone.utc),
            },
        )

    def runner(**kwargs):
        kwargs["trace_listener"](
            {
                "event_type": "tool",
                "phase": "VALIDATING",
                "payload": {
                    "tool": "run_validation",
                    "policy_result": "allowed",
                    "result": {"ok": True, "summary": "tests passed"},
                    "duration_ms": 12,
                },
            }
        )
        task = TaskSpec(
            task_id="web-task",
            repository=str(kwargs["repository"]),
            instruction=kwargs["instruction"],
            acceptance_criteria=kwargs["acceptance_criteria"],
            allowed_paths=kwargs["allowed_paths"],
            visible_validation_commands=kwargs["validation_commands"],
            provider=kwargs["provider_name"],
            model=kwargs["model"],
            limits=kwargs["limits"],
        )
        state = AgentState(task_id=task.task_id, phase=AgentPhase.SUCCEEDED)
        verification = VerificationResult(
            passed=True,
            checks=[VerificationCheck(name="external_acceptance", passed=True, summary="1/1 passed")],
        )
        run_root = kwargs["artifacts_root"] / "web-run" / task.task_id
        run_root.mkdir(parents=True)
        trace_path = run_root / "trace.jsonl"
        trace_path.write_text("", encoding="utf-8")
        report = RunReport(
            run_id="web-run",
            task=task,
            baseline_commit=fixture.baseline_commit,
            final_status=TerminalStatus.SUCCEEDED,
            state=state,
            verification=verification,
            verification_history=[verification],
            git_diff="diff --git a/src/calculator.py b/src/calculator.py",
            trace_path=str(trace_path),
            workspace_path=str(run_root / "workspace"),
            started_at=state.started_at,
        )
        (run_root / "final-report.json").write_text(
            json.dumps(report.model_dump(mode="json")),
            encoding="utf-8",
        )
        return report

    manager = TaskJobManager(
        artifacts,
        project_root=project_root(),
        provider_factory=provider_factory,
        planner=planner,
        runner=runner,
    )
    with TestClient(
        create_app(
            artifacts_root=artifacts,
            frontend_root=tmp_path / "missing",
            job_manager=manager,
        )
    ) as client:
        payload = {
            "repository": str(fixture.source_repository),
            "instruction": "average([]) must return 0.0",
            "acceptance_criteria": ["empty input returns 0.0"],
            "allowed_paths": ["src/**"],
            "validation_commands": [[sys.executable, "-c", "raise SystemExit(0)"]],
            "provider": "openai-responses",
            "model": "planner-model",
            "confirm_send_code": True,
        }
        response = client.post("/api/jobs", json=payload, headers={"Origin": "http://localhost:8765"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        planned = wait_for_status(client, job_id, "AWAITING_APPROVAL")
        assert planned["plan"]["python_cases"][0]["expected_json"] == "0.0"

        event_stream = client.get(f"/api/jobs/{job_id}/events")
        assert "event: job" in event_stream.text
        assert "event: settled" in event_stream.text

        approval = {
            "contract_sha256": planned["plan"]["contract_sha256"],
            "provider": "openai-responses",
            "model": "implementation-model",
            "confirm_send_code": True,
        }
        stale_approval = {**approval, "contract_sha256": "0" * 64}
        rejected = client.post(
            f"/api/jobs/{job_id}/approve",
            json=stale_approval,
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        assert rejected.status_code == 409
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "AWAITING_APPROVAL"

        response = client.post(
            f"/api/jobs/{job_id}/approve",
            json=approval,
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        assert response.status_code == 202
        completed = wait_for_status(client, job_id, "SUCCEEDED")
        assert completed["run"]["verification"]["passed"] is True
        assert any(event["kind"] == "tool" for event in completed["events"])
        assert client.get("/api/jobs").json()["items"][0]["events"] == []

        second = client.post(
            "/api/jobs",
            json={**payload, "instruction": "create another acceptance plan"},
            headers={"Origin": "http://localhost:8765"},
        ).json()
        waiting = wait_for_status(client, second["job_id"], "AWAITING_APPROVAL")
        cancelled = client.post(
            f"/api/jobs/{waiting['job_id']}/cancel",
            headers={"Origin": "http://localhost:8765"},
        )
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "CANCELLED"


def test_mutating_job_api_rejects_non_loopback_browser_origin(tmp_path: Path) -> None:
    manager = TaskJobManager(tmp_path / "artifacts", provider_factory=lambda *args, **kwargs: object())
    with TestClient(
        create_app(
            artifacts_root=tmp_path / "artifacts",
            frontend_root=tmp_path / "missing",
            job_manager=manager,
        )
    ) as client:
        response = client.post(
            "/api/jobs",
            json={},
            headers={"Origin": "https://attacker.example"},
        )
        assert response.status_code == 403
