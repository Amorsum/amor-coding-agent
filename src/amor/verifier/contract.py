from __future__ import annotations

import hashlib
import json
from typing import Any

from amor.domain import TaskSpec


def build_verification_contract(
    task: TaskSpec,
    baseline_commit: str,
    *,
    acceptance_source: str,
    acceptance_plan_id: str | None = None,
    acceptance_plan_sha256: str | None = None,
) -> dict[str, Any]:
    """Freeze the user-controlled acceptance boundary before model execution."""
    payload: dict[str, Any] = {
        "schema_version": "v1",
        "task_id": task.task_id,
        "baseline_commit": baseline_commit,
        "instruction": task.instruction,
        "acceptance_criteria": task.acceptance_criteria,
        "allowed_paths": task.allowed_paths,
        "validation_commands": task.visible_validation_commands,
        "hidden_tests": False,
        "external_acceptance": {
            "plan_id": acceptance_plan_id,
            "contract_sha256": acceptance_plan_sha256,
        },
        "sources": {
            "instruction": "user",
            "acceptance_criteria": acceptance_source,
            "allowed_paths": "user-approved",
            "validation_commands": "user-approved",
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **payload,
        "contract_sha256": hashlib.sha256(canonical).hexdigest(),
    }
