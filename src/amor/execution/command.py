from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from amor.domain import SandboxConfig, SandboxMode


class ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int | None
    output: str
    duration_ms: int
    executor: str
    timed_out: bool = False
    cancelled: bool = False
    startup_error: str | None = None
    resource_exhausted: str | None = None
    container_name: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.cancelled
            and self.startup_error is None
            and self.resource_exhausted is None
        )


class CommandExecutor(Protocol):
    mode: SandboxMode

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_output_chars: int,
        should_cancel: Callable[[], bool] | None = None,
        read_only_inputs: Sequence[Path] = (),
    ) -> CommandOutcome: ...


class HostCommandExecutor:
    mode = SandboxMode.HOST

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_output_chars: int,
        should_cancel: Callable[[], bool] | None = None,
        read_only_inputs: Sequence[Path] = (),
    ) -> CommandOutcome:
        del read_only_inputs
        return _run_process(
            list(command),
            cwd=cwd,
            environment=_safe_host_environment(),
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            should_cancel=should_cancel,
            executor=self.mode.value,
        )


class DockerCommandExecutor:
    mode = SandboxMode.DOCKER

    def __init__(
        self,
        workspace_root: Path,
        config: SandboxConfig,
        dependency_root: Path | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.config = config
        self.dependency_root = dependency_root.resolve() if dependency_root is not None else None
        status = docker_runtime_status(config.image)
        if not status["engine_available"]:
            raise ExecutionError(f"Docker engine is unavailable: {status['reason']}")
        if not status["image_available"]:
            raise ExecutionError(
                f"Docker image is not available locally: {config.image}; "
                f"pull it explicitly before starting the task"
            )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_output_chars: int,
        should_cancel: Callable[[], bool] | None = None,
        read_only_inputs: Sequence[Path] = (),
    ) -> CommandOutcome:
        container_name = f"amor-{uuid.uuid4().hex[:16]}"
        container_cwd = self._container_workspace_path(cwd.resolve())
        translated, mounts = self._translate_command(command, read_only_inputs)
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            *_docker_user_arguments(),
            "--network",
            "none",
            "--cpus",
            str(self.config.cpus),
            "--memory",
            f"{self.config.memory_mb}m",
            "--memory-swap",
            f"{self.config.memory_mb}m",
            "--pids-limit",
            str(self.config.pids_limit),
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={self.config.tmpfs_mb}m",
            "--mount",
            _bind_mount(self.workspace_root, "/workspace", read_only=False),
            "--workdir",
            container_cwd,
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        if self.dependency_root is not None:
            self.dependency_root.mkdir(parents=True, exist_ok=True)
            docker_command.extend(
                [
                    "--mount",
                    _bind_mount(self.dependency_root, "/amor/deps", read_only=True),
                    "--env",
                    "PYTHONPATH=/amor/deps/python:/workspace/src:/workspace",
                    "--env",
                    "PYTHONNOUSERSITE=1",
                    "--env",
                    "PIP_NO_INDEX=1",
                ]
            )
        for source, target in mounts:
            docker_command.extend(["--mount", _bind_mount(source, target, read_only=True)])
        docker_command.extend([self.config.image, *translated])
        starting_size = _directory_size(self.workspace_root)

        return _run_process(
            docker_command,
            cwd=self.workspace_root,
            environment=_docker_control_environment(),
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            should_cancel=should_cancel,
            executor=self.mode.value,
            container_name=container_name,
            on_stop=lambda: _kill_container(container_name),
            resource_check=lambda: _workspace_growth_error(
                self.workspace_root,
                starting_size,
                self.config.workspace_growth_mb,
            ),
        )

    def prepare_python_packages(
        self,
        packages: Sequence[str],
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CommandOutcome:
        if self.dependency_root is None:
            raise ExecutionError("dependency storage was not configured")
        if not packages:
            return CommandOutcome(
                returncode=0,
                output="no dependencies required",
                duration_ms=0,
                executor="docker",
            )

        self.dependency_root.mkdir(parents=True, exist_ok=True)
        python_root = self.dependency_root / "python"
        python_root.mkdir(parents=True, exist_ok=True)
        container_name = f"amor-deps-{uuid.uuid4().hex[:12]}"
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            *_docker_user_arguments(),
            "--network",
            "bridge",
            "--cpus",
            str(self.config.cpus),
            "--memory",
            f"{self.config.memory_mb}m",
            "--memory-swap",
            f"{self.config.memory_mb}m",
            "--pids-limit",
            str(self.config.pids_limit),
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={self.config.tmpfs_mb}m",
            "--mount",
            _bind_mount(self.dependency_root, "/amor/deps", read_only=False),
            "--workdir",
            "/tmp",
            "--env",
            "PIP_INDEX_URL=https://pypi.org/simple",
            "--env",
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "--env",
            "PIP_NO_INPUT=1",
            "--env",
            "PYTHONNOUSERSITE=1",
            self.config.image,
            "python",
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "--target",
            "/amor/deps/python",
            *packages,
        ]
        starting_size = _directory_size(self.dependency_root)
        return _run_process(
            docker_command,
            cwd=self.dependency_root,
            environment=_docker_control_environment(),
            timeout_seconds=self.config.dependency_timeout_seconds,
            max_output_chars=20_000,
            should_cancel=should_cancel,
            executor="docker-dependency-bootstrap",
            container_name=container_name,
            on_stop=lambda: _kill_container(container_name),
            resource_check=lambda: _workspace_growth_error(
                self.dependency_root,
                starting_size,
                self.config.dependency_cache_mb,
            ),
        )

    def _translate_command(
        self,
        command: Sequence[str],
        read_only_inputs: Sequence[Path],
    ) -> tuple[list[str], list[tuple[Path, str]]]:
        if not command or any(not isinstance(value, str) or not value for value in command):
            raise ExecutionError("command must be a non-empty argv sequence")

        roots: list[tuple[Path, str]] = []
        for index, raw in enumerate(read_only_inputs):
            source = raw.resolve()
            if not source.exists():
                raise ExecutionError(f"read-only verifier input does not exist: {source}")
            target = (
                f"/amor/inputs/{index}/{source.name}"
                if source.is_file()
                else f"/amor/inputs/{index}"
            )
            roots.append((source, target))

        translated: list[str] = []
        for index, value in enumerate(command):
            if index == 0 and _is_python_executable(value):
                translated.append("python")
                continue
            translated.append(self._translate_argument(value, roots))
        return translated, roots

    def _translate_argument(self, value: str, roots: Sequence[tuple[Path, str]]) -> str:
        candidate = Path(value)
        if not candidate.is_absolute():
            return value
        resolved = candidate.resolve()
        try:
            return self._container_workspace_path(resolved)
        except ExecutionError:
            pass
        for source, target in roots:
            if source.is_file():
                if resolved == source:
                    return target
                continue
            try:
                relative = resolved.relative_to(source)
            except ValueError:
                continue
            suffix = relative.as_posix()
            return target if not suffix or suffix == "." else f"{target}/{suffix}"
        raise ExecutionError(
            "absolute command arguments outside the workspace require an explicit read-only verifier mount"
        )

    def _container_workspace_path(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ExecutionError("command working directory escapes the isolated workspace") from exc
        suffix = relative.as_posix()
        return "/workspace" if suffix == "." else f"/workspace/{suffix}"


def build_command_executor(
    workspace_root: Path,
    config: SandboxConfig,
    dependency_root: Path | None = None,
) -> CommandExecutor:
    if config.mode == SandboxMode.DOCKER:
        return DockerCommandExecutor(workspace_root, config, dependency_root)
    return HostCommandExecutor()


def docker_runtime_status(image: str = "python:3.12-slim") -> dict[str, object]:
    try:
        cli = _probe(["docker", "--version"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "cli_available": False,
            "engine_available": False,
            "image_available": False,
            "image": image,
            "reason": str(exc),
        }
    if cli.returncode != 0:
        reason = (cli.stderr or cli.stdout).strip() or "Docker CLI is not installed"
        return {
            "cli_available": False,
            "engine_available": False,
            "image_available": False,
            "image": image,
            "reason": reason,
        }
    try:
        engine = _probe(["docker", "info", "--format", "{{.ServerVersion}}"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        engine = subprocess.CompletedProcess([], 1, "", str(exc))
    if engine.returncode != 0:
        reason = (engine.stderr or engine.stdout).strip() or "Docker engine is not running"
        return {
            "cli_available": True,
            "client_version": cli.stdout.strip(),
            "engine_available": False,
            "image_available": False,
            "image": image,
            "reason": reason,
        }
    try:
        image_check = _probe(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    except (OSError, subprocess.TimeoutExpired):
        image_check = subprocess.CompletedProcess([], 1, "", "image inspection failed")
    image_available = image_check.returncode == 0
    return {
        "cli_available": True,
        "client_version": cli.stdout.strip(),
        "engine_available": True,
        "server_version": engine.stdout.strip(),
        "image_available": image_available,
        "image": image,
        "reason": None if image_available else f"image {image} is not present locally",
    }


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    max_output_chars: int,
    should_cancel: Callable[[], bool] | None,
    executor: str,
    container_name: str | None = None,
    on_stop: Callable[[], None] | None = None,
    resource_check: Callable[[], str | None] | None = None,
) -> CommandOutcome:
    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return CommandOutcome(
            returncode=None,
            output="",
            duration_ms=int((time.perf_counter() - started) * 1000),
            executor=executor,
            startup_error=str(exc),
            container_name=container_name,
        )

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            output = _truncate_output(stdout + stderr, max_output_chars)
            resource_exhausted = resource_check() if resource_check is not None else None
            return CommandOutcome(
                returncode=process.returncode,
                output=output,
                duration_ms=int((time.perf_counter() - started) * 1000),
                executor=executor,
                resource_exhausted=resource_exhausted,
                container_name=container_name,
            )
        except subprocess.TimeoutExpired:
            cancelled = should_cancel is not None and should_cancel()
            timed_out = time.monotonic() >= deadline
            resource_exhausted = resource_check() if resource_check is not None else None
            if not cancelled and not timed_out and resource_exhausted is None:
                continue
            if on_stop is not None:
                on_stop()
            else:
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            return CommandOutcome(
                returncode=process.returncode,
                output=_truncate_output(stdout + stderr, max_output_chars),
                duration_ms=int((time.perf_counter() - started) * 1000),
                executor=executor,
                timed_out=timed_out,
                cancelled=cancelled,
                resource_exhausted=resource_exhausted,
                container_name=container_name,
            )


def _probe(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=5,
        check=False,
    )


def _kill_container(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "kill", name],
            env=_docker_control_environment(),
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _safe_host_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    environment = {
        name: value for name, value in os.environ.items() if name.upper() in allowed
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _docker_control_environment() -> dict[str, str]:
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "DOCKER_HOST", "DOCKER_CONTEXT"}
    return {name: value for name, value in os.environ.items() if name.upper() in allowed}


def _docker_user_arguments() -> list[str]:
    """Match POSIX host ownership so bind-mounted workspaces stay writable."""

    if os.name != "posix" or not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def _is_python_executable(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"python", "python3", "python.exe", "python3.exe"}:
        return True
    try:
        return Path(value).resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def _bind_mount(source: Path, target: str, *, read_only: bool) -> str:
    escaped = str(source.resolve()).replace(",", "\\,")
    suffix = ",readonly" if read_only else ""
    return f"type=bind,source={escaped},target={target}{suffix}"


def _truncate_output(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return value[:max_chars] + f"\n... <{omitted} characters omitted>"


def _directory_size(root: Path) -> int:
    total = 0
    try:
        for path in root.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
    except OSError:
        return total
    return total


def _workspace_growth_error(root: Path, starting_size: int, limit_mb: int) -> str | None:
    growth = max(0, _directory_size(root) - starting_size)
    limit = limit_mb * 1024 * 1024
    if growth <= limit:
        return None
    return f"workspace growth exceeded {limit_mb} MB"
