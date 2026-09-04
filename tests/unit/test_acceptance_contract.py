import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from amor.acceptance import AcceptanceContractError, load_acceptance_plan, write_acceptance_plan


def payload() -> dict:
    return {
        "schema_version": "v1",
        "plan_id": "plan-test",
        "status": "READY",
        "baseline_commit": "abc123",
        "instruction": "return odd values",
        "acceptance_criteria": ["results are odd"],
        "preserved_behaviors": [],
        "edge_cases": ["zero"],
        "allowed_paths": ["src/**"],
        "validation_commands": [["python", "-m", "pytest"]],
        "python_cases": [
            {
                "name": "upper bound",
                "module": "src.numbers",
                "callable": "generate",
                "args_json": "[6]",
                "kwargs_json": "{}",
                "expectation": "equals",
                "expected_json": "[1, 3, 5]",
                "exception_type": "",
                "rationale": "checks parity, range, and order together",
            }
        ],
        "evidence_files": ["src/numbers.py"],
        "questions": [],
        "summary": "odd output contract",
        "provider": "fake",
        "model": "fake-planner",
        "token_usage": {},
        "created_at": datetime.now(timezone.utc),
    }


def test_contract_hash_detects_manual_tampering(tmp_path: Path) -> None:
    path = tmp_path / "acceptance-plan.json"
    original = write_acceptance_plan(path, payload())
    assert load_acceptance_plan(path) == original

    document = json.loads(path.read_text(encoding="utf-8"))
    document["acceptance_criteria"] = ["always return one"]
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(AcceptanceContractError, match="hash mismatch"):
        load_acceptance_plan(path)


@pytest.mark.parametrize(
    ("expectation", "expected_json", "exception_type"),
    [
        ("equals", "NaN", ""),
        ("raises", "null", "SystemExit"),
    ],
)
def test_contract_rejects_unsafe_structured_expectations(
    tmp_path: Path,
    expectation: str,
    expected_json: str,
    exception_type: str,
) -> None:
    document = payload()
    document["python_cases"][0].update(
        {
            "expectation": expectation,
            "expected_json": expected_json,
            "exception_type": exception_type,
        }
    )

    with pytest.raises(ValueError):
        write_acceptance_plan(tmp_path / "acceptance-plan.json", document)
