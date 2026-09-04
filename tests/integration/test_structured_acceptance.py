import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from amor.acceptance import write_acceptance_plan
from amor.benchmarks import BenchmarkLayout
from amor.domain import RunLimits, TaskSpec
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_external_structured_case_rejects_old_code_and_accepts_repair(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "fixture",
    )
    plan = write_acceptance_plan(
        tmp_path / "contract" / "acceptance-plan.json",
        {
            "schema_version": "v1",
            "plan_id": "plan-test",
            "status": "READY",
            "baseline_commit": workspace.baseline_commit,
            "instruction": "average([]) returns 0.0",
            "acceptance_criteria": ["empty input returns 0.0"],
            "preserved_behaviors": ["non-empty input remains unchanged"],
            "edge_cases": ["empty list"],
            "allowed_paths": ["src/**"],
            "validation_commands": [[sys.executable, "-c", "raise SystemExit(0)"]],
            "python_cases": [
                {
                    "name": "empty list",
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
            "summary": "empty average contract",
            "provider": "fake",
            "model": "fake-planner",
            "token_usage": {},
            "created_at": datetime.now(timezone.utc),
        },
    )
    task = TaskSpec(
        task_id="local-test",
        repository=str(workspace.source_repository),
        instruction=plan.instruction,
        acceptance_criteria=plan.acceptance_criteria,
        allowed_paths=plan.allowed_paths,
        visible_validation_commands=plan.validation_commands,
        limits=RunLimits(max_seconds=120),
    )
    verifier = IndependentVerifier(layout)
    plan_path = tmp_path / "contract" / "acceptance-plan.json"

    shadow_runner = workspace.root / "amor/verifier/structured_cases.py"
    shadow_runner.parent.mkdir(parents=True)
    (workspace.root / "amor/__init__.py").write_text("", encoding="utf-8")
    (shadow_runner.parent / "__init__.py").write_text("", encoding="utf-8")
    shadow_runner.write_text(
        "raise SystemExit(0)\n",
        encoding="utf-8",
        newline="\n",
    )

    before = verifier.verify(
        task,
        workspace,
        include_hidden_tests=False,
        structured_plan_path=plan_path,
    )
    assert not before.passed
    assert any(
        check.name == "external_acceptance"
        and not check.passed
        and "FAIL empty list" in check.summary
        for check in before.checks
    )
    shutil.rmtree(workspace.root / "amor")

    calculator = workspace.root / "src/calculator.py"
    calculator.write_text(
        calculator.read_text(encoding="utf-8").replace(
            "    return sum(values) / len(values)\n",
            "    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
        ),
        encoding="utf-8",
        newline="\n",
    )
    after = verifier.verify(
        task,
        workspace,
        include_hidden_tests=False,
        structured_plan_path=plan_path,
    )
    assert after.passed
    assert any(
        check.name == "external_acceptance" and "1/1 passed" in check.summary
        for check in after.checks
    )
