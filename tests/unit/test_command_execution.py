import sys
from pathlib import Path

import pytest

from amor.domain import SandboxConfig, SandboxMode
from amor.execution import CommandOutcome, DockerCommandExecutor, ExecutionError
from amor.execution import command as command_module


def docker_config() -> SandboxConfig:
    return SandboxConfig(
        mode=SandboxMode.DOCKER,
        image="python:3.12-slim",
        cpus=1.5,
        memory_mb=384,
        pids_limit=64,
        tmpfs_mb=32,
    )


def test_docker_executor_fails_closed_when_engine_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        command_module,
        "docker_runtime_status",
        lambda image: {
            "engine_available": False,
            "image_available": False,
            "reason": "engine stopped",
        },
    )

    with pytest.raises(ExecutionError, match="engine stopped"):
        DockerCommandExecutor(tmp_path, docker_config())


def test_docker_executor_builds_a_networkless_resource_limited_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        command_module,
        "docker_runtime_status",
        lambda image: {
            "engine_available": True,
            "image_available": True,
            "reason": None,
        },
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return CommandOutcome(
            returncode=0,
            output="ok",
            duration_ms=1,
            executor="docker",
            container_name="amor-test",
        )

    monkeypatch.setattr(command_module, "_run_process", fake_run)
    executor = DockerCommandExecutor(workspace, docker_config())

    result = executor.run(
        [sys.executable, "-c", "print('ok')", str(plan)],
        cwd=workspace,
        timeout_seconds=30,
        max_output_chars=1_000,
        read_only_inputs=(plan,),
    )

    assert result.ok
    argv = captured["command"]
    assert isinstance(argv, list)
    assert ["--network", "none"] == argv[argv.index("--network") : argv.index("--network") + 2]
    assert ["--cpus", "1.5"] == argv[argv.index("--cpus") : argv.index("--cpus") + 2]
    assert ["--memory", "384m"] == argv[argv.index("--memory") : argv.index("--memory") + 2]
    assert ["--pids-limit", "64"] == argv[argv.index("--pids-limit") : argv.index("--pids-limit") + 2]
    assert "--read-only" in argv
    assert "--cap-drop" in argv and "ALL" in argv
    assert "no-new-privileges" in argv
    assert argv[-4:] == ["python", "-c", "print('ok')", "/amor/inputs/0/plan.json"]


def test_docker_executor_uses_the_posix_host_identity_for_bind_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        command_module,
        "docker_runtime_status",
        lambda image: {"engine_available": True, "image_available": True, "reason": None},
    )
    monkeypatch.setattr(command_module, "_docker_user_arguments", lambda: ["--user", "1001:1001"])

    def fake_run(command, **kwargs):
        captured["command"] = command
        return CommandOutcome(returncode=0, output="ok", duration_ms=1, executor="docker")

    monkeypatch.setattr(command_module, "_run_process", fake_run)
    executor = DockerCommandExecutor(workspace, docker_config())

    executor.run(
        ["python", "-c", "print('ok')"],
        cwd=workspace,
        timeout_seconds=30,
        max_output_chars=1_000,
    )

    argv = captured["command"]
    assert isinstance(argv, list)
    assert argv[argv.index("--user") : argv.index("--user") + 2] == ["--user", "1001:1001"]


def test_docker_executor_rejects_unmounted_absolute_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        command_module,
        "docker_runtime_status",
        lambda image: {
            "engine_available": True,
            "image_available": True,
            "reason": None,
        },
    )
    executor = DockerCommandExecutor(workspace, docker_config())

    with pytest.raises(ExecutionError, match="explicit read-only verifier mount"):
        executor.run(
            ["python", str(outside)],
            cwd=workspace,
            timeout_seconds=30,
            max_output_chars=1_000,
        )


def test_dependency_bootstrap_has_scoped_network_and_no_source_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dependencies = tmp_path / "dependencies"
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        command_module,
        "docker_runtime_status",
        lambda image: {"engine_available": True, "image_available": True, "reason": None},
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        return CommandOutcome(returncode=0, output="installed", duration_ms=2, executor="docker")

    monkeypatch.setattr(command_module, "_run_process", fake_run)
    executor = DockerCommandExecutor(workspace, docker_config(), dependencies)

    result = executor.prepare_python_packages(["pytest>=8,<10"])

    assert result.ok
    argv = captured["command"]
    assert isinstance(argv, list)
    assert argv[argv.index("--network") : argv.index("--network") + 2] == ["--network", "bridge"]
    assert any("https://pypi.org/simple" in value for value in argv)
    assert "--only-binary=:all:" in argv
    assert str(workspace.resolve()) not in " ".join(argv)
    assert "/amor/deps" in " ".join(argv)


def test_validation_mounts_prepared_dependencies_read_only_and_stays_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dependencies = tmp_path / "dependencies"
    dependencies.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        command_module,
        "docker_runtime_status",
        lambda image: {"engine_available": True, "image_available": True, "reason": None},
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        return CommandOutcome(returncode=0, output="ok", duration_ms=1, executor="docker")

    monkeypatch.setattr(command_module, "_run_process", fake_run)
    executor = DockerCommandExecutor(workspace, docker_config(), dependencies)

    result = executor.run(
        ["python", "-m", "pytest"],
        cwd=workspace,
        timeout_seconds=30,
        max_output_chars=1_000,
    )

    assert result.ok
    argv = captured["command"]
    assert isinstance(argv, list)
    assert argv[argv.index("--network") : argv.index("--network") + 2] == ["--network", "none"]
    assert any("target=/amor/deps,readonly" in value for value in argv)
    assert "PYTHONPATH=/amor/deps/python:/workspace/src:/workspace" in argv
