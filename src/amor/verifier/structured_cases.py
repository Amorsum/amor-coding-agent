from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class AcceptanceContractError(ValueError):
    pass


_DOTTED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _strict_json(value: str) -> object:
    def reject_constant(constant: str) -> object:
        raise ValueError(f"non-standard JSON constant is not allowed: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def _load_cases(plan_path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceContractError(f"cannot read acceptance contract: {exc}") from exc
    if not isinstance(document, dict):
        raise AcceptanceContractError("acceptance contract must be a JSON object")
    recorded = document.get("contract_sha256")
    unsigned = {key: value for key, value in document.items() if key != "contract_sha256"}
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    actual = hashlib.sha256(canonical).hexdigest()
    if not isinstance(recorded, str) or recorded != actual:
        raise AcceptanceContractError("acceptance contract hash mismatch")
    if document.get("schema_version") != "v1":
        raise AcceptanceContractError("unsupported acceptance contract schema")
    if document.get("status") != "READY":
        raise AcceptanceContractError("acceptance contract still requires user input")
    cases = document.get("python_cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise AcceptanceContractError("acceptance contract must contain 1-20 Python cases")
    for case in cases:
        _validate_case(case)
    return cases


def _validate_case(case: object) -> None:
    if not isinstance(case, dict):
        raise AcceptanceContractError("Python acceptance case must be an object")
    required = {
        "name",
        "module",
        "callable",
        "args_json",
        "kwargs_json",
        "expectation",
        "expected_json",
        "exception_type",
        "rationale",
    }
    if set(case) != required:
        raise AcceptanceContractError("Python acceptance case fields are invalid")
    for key in ("name", "module", "callable", "args_json", "kwargs_json", "expected_json", "exception_type", "rationale"):
        if not isinstance(case[key], str):
            raise AcceptanceContractError(f"Python acceptance case {key} must be text")
    if not case["name"] or len(case["name"]) > 120:
        raise AcceptanceContractError("Python acceptance case name is invalid")
    if not case["rationale"] or len(case["rationale"]) > 500:
        raise AcceptanceContractError("Python acceptance case rationale is invalid")
    for key in ("module", "callable"):
        value = case[key]
        if not _DOTTED_NAME.fullmatch(value) or "__" in value:
            raise AcceptanceContractError(f"Python acceptance case {key} is unsafe")
    if len(case["args_json"]) > 20_000 or len(case["kwargs_json"]) > 20_000:
        raise AcceptanceContractError("Python acceptance case input is too large")
    try:
        args = _strict_json(case["args_json"])
        kwargs = _strict_json(case["kwargs_json"])
    except (json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceContractError("Python acceptance case input is invalid JSON") from exc
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise AcceptanceContractError("args_json and kwargs_json have invalid shapes")
    expectation = case["expectation"]
    if expectation == "equals":
        if case["exception_type"]:
            raise AcceptanceContractError("equals case must not declare exception_type")
        try:
            _strict_json(case["expected_json"])
        except (json.JSONDecodeError, ValueError) as exc:
            raise AcceptanceContractError("expected_json is invalid") from exc
    elif expectation == "raises":
        exception_name = case["exception_type"]
        exception_class = getattr(builtins, exception_name, None)
        if (
            not _DOTTED_NAME.fullmatch(exception_name)
            or "." in exception_name
            or not isinstance(exception_class, type)
            or not issubclass(exception_class, Exception)
        ):
            raise AcceptanceContractError("raises case exception_type is invalid")
    else:
        raise AcceptanceContractError("Python acceptance case expectation is invalid")


def run_cases(plan_path: Path) -> int:
    try:
        cases = _load_cases(plan_path)
    except AcceptanceContractError as exc:
        print(f"acceptance contract rejected: {exc}")
        return 2

    # The runner starts with ``python -I <absolute trusted script>`` so a target
    # repository cannot shadow AMOR while the contract is loaded. Only after
    # that boundary is validated do we make target modules importable.
    for module_name in tuple(sys.modules):
        if module_name == "amor" or module_name.startswith("amor."):
            del sys.modules[module_name]
    repository_root = Path.cwd()
    source_root = repository_root / "src"
    sys.path.insert(0, str(repository_root))
    if source_root.is_dir():
        sys.path.insert(0, str(source_root))

    failures = 0
    for case in cases:
        try:
            module = importlib.import_module(case["module"])
            target: Any = module
            for part in case["callable"].split("."):
                target = getattr(target, part)
            args = _strict_json(case["args_json"])
            kwargs = _strict_json(case["kwargs_json"])
            if case["expectation"] == "raises":
                exception_class = getattr(builtins, case["exception_type"], None)
                if not isinstance(exception_class, type) or not issubclass(exception_class, Exception):
                    raise TypeError(f"unsupported exception type: {case['exception_type']}")
                try:
                    target(*args, **kwargs)
                except exception_class:
                    print(f"PASS {case['name']}")
                except Exception as exc:  # noqa: BLE001 - report target behavior
                    failures += 1
                    print(
                        f"FAIL {case['name']}: expected {case['exception_type']}, "
                        f"got {type(exc).__name__}: {exc}"
                    )
                else:
                    failures += 1
                    print(f"FAIL {case['name']}: expected {case['exception_type']}, no exception was raised")
            else:
                expected = _strict_json(case["expected_json"])
                actual = target(*args, **kwargs)
                if actual == expected:
                    print(f"PASS {case['name']}")
                else:
                    failures += 1
                    print(f"FAIL {case['name']}: expected {expected!r}, got {actual!r}")
        except Exception as exc:  # noqa: BLE001 - isolate malformed target/case failures
            failures += 1
            print(f"FAIL {case['name']}: {type(exc).__name__}: {exc}")
    print(f"structured acceptance: {len(cases) - failures}/{len(cases)} passed")
    return 0 if failures == 0 else 1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: structured_cases.py <acceptance-plan.json>")
        return 2
    return run_cases(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
