from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from amor.acceptance.models import AcceptancePlan


class AcceptanceContractError(ValueError):
    pass


def contract_digest(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "contract_sha256"}
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_acceptance_plan(path: Path, payload: dict[str, Any]) -> AcceptancePlan:
    provisional = AcceptancePlan.model_validate(
        {**payload, "contract_sha256": "pending"}
    )
    document = provisional.model_dump(mode="json")
    document["contract_sha256"] = contract_digest(document)
    plan = AcceptancePlan.model_validate(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return plan


def load_acceptance_plan(path: Path) -> AcceptancePlan:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceContractError(f"cannot read acceptance contract: {exc}") from exc
    if not isinstance(document, dict):
        raise AcceptanceContractError("acceptance contract must be a JSON object")
    recorded = document.get("contract_sha256")
    actual = contract_digest(document)
    if not isinstance(recorded, str) or recorded != actual:
        raise AcceptanceContractError("acceptance contract hash mismatch")
    try:
        return AcceptancePlan.model_validate(document)
    except ValueError as exc:
        raise AcceptanceContractError(f"invalid acceptance contract: {exc}") from exc
