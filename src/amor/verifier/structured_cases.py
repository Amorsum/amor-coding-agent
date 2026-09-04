from __future__ import annotations

import builtins
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from amor.acceptance.contract import AcceptanceContractError, load_acceptance_plan


def run_cases(plan_path: Path) -> int:
    try:
        plan = load_acceptance_plan(plan_path)
    except AcceptanceContractError as exc:
        print(f"acceptance contract rejected: {exc}")
        return 2
    if plan.status != "READY":
        print("acceptance contract still requires user input")
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
    for case in plan.python_cases:
        try:
            module = importlib.import_module(case.module)
            target: Any = module
            for part in case.callable.split("."):
                target = getattr(target, part)
            args = json.loads(case.args_json)
            kwargs = json.loads(case.kwargs_json)
            if case.expectation == "raises":
                exception_class = getattr(builtins, case.exception_type, None)
                if not isinstance(exception_class, type) or not issubclass(exception_class, Exception):
                    raise TypeError(f"unsupported exception type: {case.exception_type}")
                try:
                    target(*args, **kwargs)
                except exception_class:
                    print(f"PASS {case.name}")
                except Exception as exc:  # noqa: BLE001 - report target behavior
                    failures += 1
                    print(
                        f"FAIL {case.name}: expected {case.exception_type}, "
                        f"got {type(exc).__name__}: {exc}"
                    )
                else:
                    failures += 1
                    print(f"FAIL {case.name}: expected {case.exception_type}, no exception was raised")
            else:
                expected = json.loads(case.expected_json)
                actual = target(*args, **kwargs)
                if actual == expected:
                    print(f"PASS {case.name}")
                else:
                    failures += 1
                    print(f"FAIL {case.name}: expected {expected!r}, got {actual!r}")
        except Exception as exc:  # noqa: BLE001 - isolate malformed target/case failures
            failures += 1
            print(f"FAIL {case.name}: {type(exc).__name__}: {exc}")
    print(f"structured acceptance: {len(plan.python_cases) - failures}/{len(plan.python_cases)} passed")
    return 0 if failures == 0 else 1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: structured_cases.py <acceptance-plan.json>")
        return 2
    return run_cases(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
