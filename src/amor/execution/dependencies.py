from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from amor.domain import DependencyBootstrapMode, SandboxConfig
from amor.execution.command import DockerCommandExecutor


class DependencyBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class DependencyBootstrapPlan:
    packages: tuple[str, ...]
    sources: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"packages": list(self.packages), "sources": list(self.sources)}


_PACKAGE_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_OPTIONAL_GROUPS = ("test", "tests", "testing", "dev")
_REQUIREMENT_FILES = ("requirements.txt", "requirements-dev.txt", "requirements-test.txt")


def discover_python_dependency_plan(
    workspace: Path,
    validation_commands: Sequence[Sequence[str]],
) -> DependencyBootstrapPlan:
    workspace = workspace.resolve()
    packages: list[str] = []
    sources: list[str] = []

    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file():
        try:
            document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise DependencyBootstrapError(f"cannot read pyproject.toml dependencies: {exc}") from exc
        project = document.get("project", {})
        if isinstance(project, dict):
            declared = project.get("dependencies", [])
            packages.extend(_validated_specs(declared, "pyproject.toml [project].dependencies"))
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                for group in _OPTIONAL_GROUPS:
                    if group in optional:
                        packages.extend(
                            _validated_specs(
                                optional[group],
                                f"pyproject.toml [project.optional-dependencies].{group}",
                            )
                        )
        sources.append("pyproject.toml")

    for filename in _REQUIREMENT_FILES:
        path = workspace / filename
        if not path.is_file():
            continue
        packages.extend(_read_requirement_file(path))
        sources.append(filename)

    if _uses_pytest(validation_commands):
        packages.append("pytest>=8,<10")
        sources.append("validation command: pytest")

    return DependencyBootstrapPlan(
        packages=tuple(_deduplicate(packages)),
        sources=tuple(dict.fromkeys(sources)),
    )


def dependency_bootstrap_enabled(config: SandboxConfig) -> bool:
    return config.dependency_bootstrap == DependencyBootstrapMode.AUTO


def prepare_python_dependencies(
    executor: DockerCommandExecutor,
    workspace: Path,
    validation_commands: Sequence[Sequence[str]],
    *,
    should_cancel=None,
) -> dict[str, object]:
    plan = discover_python_dependency_plan(workspace, validation_commands)
    outcome = executor.prepare_python_packages(plan.packages, should_cancel=should_cancel)
    if not outcome.ok:
        if outcome.cancelled:
            reason = "dependency preparation was cancelled"
        elif outcome.timed_out:
            reason = "dependency preparation timed out"
        elif outcome.resource_exhausted:
            reason = outcome.resource_exhausted
        elif outcome.startup_error:
            reason = outcome.startup_error
        else:
            reason = outcome.output.strip() or f"pip exited with code {outcome.returncode}"
        raise DependencyBootstrapError(f"Docker dependency preparation failed: {reason[:2_000]}")
    return {
        **plan.as_dict(),
        "duration_ms": outcome.duration_ms,
        "installed": bool(plan.packages),
        "network_scope": "dependency-bootstrap-only",
        "index_url": "https://pypi.org/simple",
        "validation_network": "disabled",
    }


def _read_requirement_file(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DependencyBootstrapError(f"cannot read {path.name}: {exc}") from exc
    specs: list[str] = []
    for line_number, raw in enumerate(lines, start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        specs.extend(_validated_specs([value], f"{path.name}:{line_number}"))
    return specs


def _validated_specs(values: object, source: str) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise DependencyBootstrapError(f"{source} must contain a list of package requirements")
    return [_validate_spec(value.strip(), source) for value in values]


def _validate_spec(value: str, source: str) -> str:
    if not value:
        raise DependencyBootstrapError(f"empty dependency declaration in {source}")
    lowered = value.lower()
    if (
        value.startswith("-")
        or "@" in value
        or "://" in lowered
        or "\\" in value
        or "/" in value
        or "${" in value
        or "`" in value
    ):
        raise DependencyBootstrapError(
            f"unsupported dependency declaration in {source}: {value}; "
            "only package-index requirements are allowed"
        )
    if _PACKAGE_NAME.match(value) is None:
        raise DependencyBootstrapError(f"invalid dependency declaration in {source}: {value}")
    return value


def _uses_pytest(commands: Sequence[Sequence[str]]) -> bool:
    for command in commands:
        lowered = [part.lower() for part in command]
        if lowered and Path(lowered[0]).name in {"pytest", "pytest.exe"}:
            return True
        if any(lowered[index : index + 2] == ["-m", "pytest"] for index in range(len(lowered) - 1)):
            return True
    return False


def _deduplicate(packages: Sequence[str]) -> list[str]:
    selected: dict[str, str] = {}
    for package in packages:
        match = _PACKAGE_NAME.match(package)
        assert match is not None
        key = match.group(1).replace("_", "-").lower()
        selected.setdefault(key, package)
    return list(selected.values())
