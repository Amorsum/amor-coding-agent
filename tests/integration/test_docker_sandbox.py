import os
from pathlib import Path
from datetime import datetime, timezone

import pytest

from amor.domain import DependencyBootstrapMode, SandboxConfig, SandboxMode
from amor.execution import (
    DockerCommandExecutor,
    docker_runtime_status,
    prepare_python_dependencies,
)
from amor.benchmarks import BenchmarkLayout, load_task
from amor.acceptance import write_acceptance_plan
from amor.verifier import IndependentVerifier
from amor.workspace import WorkspaceManager


_DOCKER = docker_runtime_status()


@pytest.mark.skipif(
    os.environ.get("AMOR_RUN_NETWORK_TESTS") != "1"
    or not (_DOCKER["engine_available"] and _DOCKER["image_available"]),
    reason="requires AMOR_RUN_NETWORK_TESTS=1, Docker, and PyPI access",
)
def test_real_dependency_bootstrap_feeds_networkless_validation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    (workspace / "src" / "value.py").write_text("VALUE = 7\n", encoding="utf-8")
    (workspace / "tests" / "test_value.py").write_text(
        "from value import VALUE\n\ndef test_value():\n    assert VALUE == 7\n",
        encoding="utf-8",
    )
    (workspace / "pyproject.toml").write_text(
        '[project]\nname="bootstrap-test"\nversion="0.1.0"\n\n'
        '[tool.pytest.ini_options]\npythonpath=["src"]\n',
        encoding="utf-8",
    )
    config = SandboxConfig(
        mode=SandboxMode.DOCKER,
        dependency_bootstrap=DependencyBootstrapMode.AUTO,
    )
    executor = DockerCommandExecutor(workspace, config, tmp_path / "dependencies")

    report = prepare_python_dependencies(
        executor,
        workspace,
        [["python", "-m", "pytest", "-q"]],
    )
    result = executor.run(
        ["python", "-m", "pytest", "-q"],
        cwd=workspace,
        timeout_seconds=30,
        max_output_chars=2_000,
    )

    assert report["installed"] is True
    assert result.ok, result.output
    assert "1 passed" in result.output


@pytest.mark.skipif(
    not (_DOCKER["engine_available"] and _DOCKER["image_available"]),
    reason=f"Docker sandbox prerequisites unavailable: {_DOCKER['reason']}",
)
def test_real_docker_sandbox_is_networkless_and_does_not_inherit_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMOR_TEST_SECRET", "must-not-enter-container")
    executor = DockerCommandExecutor(
        tmp_path,
        SandboxConfig(mode=SandboxMode.DOCKER),
    )
    script = (
        "import os,socket;"
        "assert 'AMOR_TEST_SECRET' not in os.environ;"
        "p='sandbox-created.txt';open(p,'w').write('isolated\\n');"
        "s=socket.socket();s.settimeout(1);"
        "\ntry:s.connect(('1.1.1.1',53));raise SystemExit('network unexpectedly available')"
        "\nexcept OSError:print('NETWORK_BLOCKED')"
    )

    result = executor.run(
        ["python", "-c", script],
        cwd=tmp_path,
        timeout_seconds=10,
        max_output_chars=2_000,
    )

    assert result.ok, result.output
    assert "NETWORK_BLOCKED" in result.output
    assert (tmp_path / "sandbox-created.txt").read_text(encoding="utf-8") == "isolated\n"
    assert "AMOR_TEST_SECRET" not in result.output


@pytest.mark.skipif(
    not (_DOCKER["engine_available"] and _DOCKER["image_available"]),
    reason=f"Docker sandbox prerequisites unavailable: {_DOCKER['reason']}",
)
def test_real_docker_verifier_runs_visible_and_hidden_tests(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    layout = BenchmarkLayout(project_root / "benchmarks")
    task = load_task(layout, "py_utils_average_empty").model_copy(
        update={"sandbox": SandboxConfig(mode=SandboxMode.DOCKER)}
    )
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "run",
    )
    calculator = workspace.root / "src" / "calculator.py"
    calculator.write_text(
        calculator.read_text(encoding="utf-8").replace(
            "    return sum(values) / len(values)\n",
            "    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = IndependentVerifier(layout).verify(task, workspace)

    assert result.passed, [check.summary for check in result.checks]
    assert next(check for check in result.checks if check.name == "visible_tests_1").passed
    assert next(check for check in result.checks if check.name == "hidden_tests").passed


@pytest.mark.skipif(
    not (_DOCKER["engine_available"] and _DOCKER["image_available"]),
    reason=f"Docker sandbox prerequisites unavailable: {_DOCKER['reason']}",
)
def test_real_docker_verifier_runs_external_structured_acceptance(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    layout = BenchmarkLayout(project_root / "benchmarks")
    task = load_task(layout, "py_utils_average_empty").model_copy(
        update={"sandbox": SandboxConfig(mode=SandboxMode.DOCKER)}
    )
    workspace = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "run",
    )
    calculator = workspace.root / "src" / "calculator.py"
    calculator.write_text(
        calculator.read_text(encoding="utf-8").replace(
            "    return sum(values) / len(values)\n",
            "    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
        ),
        encoding="utf-8",
        newline="\n",
    )
    plan_path = tmp_path / "contract" / "acceptance-plan.json"
    write_acceptance_plan(
        plan_path,
        {
            "schema_version": "v1",
            "plan_id": "docker-plan",
            "status": "READY",
            "baseline_commit": workspace.baseline_commit,
            "instruction": task.instruction,
            "acceptance_criteria": task.acceptance_criteria,
            "preserved_behaviors": ["non-empty averages remain unchanged"],
            "edge_cases": ["empty list"],
            "allowed_paths": task.allowed_paths,
            "validation_commands": task.visible_validation_commands,
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
            "summary": "Docker structured acceptance",
            "provider": "fake",
            "model": "fake-planner",
            "token_usage": {},
            "created_at": datetime.now(timezone.utc),
        },
    )

    result = IndependentVerifier(layout).verify(
        task,
        workspace,
        include_hidden_tests=False,
        structured_plan_path=plan_path,
    )

    assert result.passed, [check.summary for check in result.checks]
    external = next(check for check in result.checks if check.name == "external_acceptance")
    assert external.passed
    assert "1/1 passed" in external.summary
