from __future__ import annotations

import argparse
import json
from pathlib import Path

from amor.domain import RunLimits
from amor.local_runner import run_repository_task
from amor.profiler import RepositoryProfiler
from amor.providers import OpenAIResponsesProvider, ProviderError
from amor.runner import DEFAULT_TASK_IDS, run_demo
from amor.workspace.manager import WorkspaceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amor", description="AMOR coding-agent foundation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run the deterministic first-iteration tasks")
    demo.add_argument("--project-root", type=Path, default=Path.cwd())
    demo.add_argument("--artifacts", type=Path, default=Path("artifacts/runs"))
    demo.add_argument("--task", action="append", choices=DEFAULT_TASK_IDS)

    profile = subparsers.add_parser("profile", help="inspect a local Git repository without modifying it")
    profile.add_argument("repository", type=Path)

    run = subparsers.add_parser("run", help="run a model-driven task in an isolated local Git worktree")
    run.add_argument("repository", type=Path)
    run.add_argument("--task", required=True, help="natural-language coding task")
    run.add_argument("--accept", action="append", default=[], help="acceptance criterion; may be repeated")
    run.add_argument("--allow", action="append", required=True, help="allowed write glob; may be repeated")
    run.add_argument(
        "--validation-json",
        action="append",
        required=True,
        help='approved argv JSON array, e.g. ["python","-m","pytest"]',
    )
    run.add_argument("--model", required=True, help="exact Responses API model id")
    run.add_argument("--base-url", help="Responses-compatible API base URL")
    run.add_argument("--artifacts", type=Path, default=Path("artifacts/runs"))
    run.add_argument("--max-rounds", type=int, default=20)
    run.add_argument("--max-seconds", type=int, default=900)
    run.add_argument(
        "--confirm-send-code",
        action="store_true",
        help="confirm that selected repository snippets may be sent to the configured model provider",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.command == "demo":
        project_root = arguments.project_root.resolve()
        artifacts = arguments.artifacts
        if not artifacts.is_absolute():
            artifacts = project_root / artifacts
        reports = run_demo(project_root, artifacts.resolve(), arguments.task)
        for report in reports:
            print(f"{report.task.task_id}: {report.final_status.value}")
            print(f"  report: {Path(report.trace_path).parent / 'final-report.json'}")
        return 0 if all(report.verification.passed for report in reports) else 1
    if arguments.command == "profile":
        try:
            profile = RepositoryProfiler().profile(arguments.repository)
        except WorkspaceError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    if arguments.command == "run":
        if not arguments.confirm_send_code:
            raise SystemExit("refusing API run without --confirm-send-code")
        try:
            validation_commands = [_parse_command_json(value) for value in arguments.validation_json]
            provider = OpenAIResponsesProvider.from_environment(
                model=arguments.model,
                base_url=arguments.base_url,
                timeout_seconds=arguments.max_seconds,
            )
        except (ValueError, ProviderError) as exc:
            raise SystemExit(str(exc)) from exc
        project_root = Path.cwd().resolve()
        artifacts = arguments.artifacts
        if not artifacts.is_absolute():
            artifacts = project_root / artifacts
        try:
            report = run_repository_task(
                project_root=project_root,
                repository=arguments.repository,
                instruction=arguments.task,
                acceptance_criteria=arguments.accept,
                allowed_paths=arguments.allow,
                validation_commands=validation_commands,
                provider_name="openai-responses",
                model=arguments.model,
                provider=provider,
                artifacts_root=artifacts,
                limits=RunLimits(max_rounds=arguments.max_rounds, max_seconds=arguments.max_seconds),
            )
        except (RuntimeError, WorkspaceError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(f"{report.task.task_id}: {report.final_status.value}")
        print(f"  workspace: {report.workspace_path}")
        print(f"  report: {Path(report.trace_path).parent / 'final-report.json'}")
        return 0 if report.verification.passed else 1
    return 2


def _parse_command_json(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or not all(isinstance(item, str) and item for item in parsed):
        raise ValueError("each --validation-json value must be a non-empty JSON array of strings")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
