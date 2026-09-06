from pathlib import Path

import pytest

from amor.domain import DependencyBootstrapMode, SandboxConfig, SandboxMode
from amor.execution import DependencyBootstrapError, discover_python_dependency_plan


def test_discovers_declared_and_validation_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "sample"
version = "0.1.0"
dependencies = ["httpx>=0.27,<1"]

[project.optional-dependencies]
test = ["pytest>=8,<10"]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic>=2,<3\n", encoding="utf-8")

    plan = discover_python_dependency_plan(
        tmp_path,
        [["python", "-m", "pytest"]],
    )

    assert plan.packages == ("httpx>=0.27,<1", "pytest>=8,<10", "pydantic>=2,<3")
    assert plan.sources == (
        "pyproject.toml",
        "requirements.txt",
        "validation command: pytest",
    )


def test_rejects_url_and_requirement_options(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "-r private.txt\npackage @ https://example.invalid/package.whl\n",
        encoding="utf-8",
    )

    with pytest.raises(DependencyBootstrapError, match="only package-index requirements"):
        discover_python_dependency_plan(tmp_path, [])


def test_dependency_bootstrap_is_docker_only() -> None:
    with pytest.raises(ValueError, match="only in Docker mode"):
        SandboxConfig(
            mode=SandboxMode.HOST,
            dependency_bootstrap=DependencyBootstrapMode.AUTO,
        )
