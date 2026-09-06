from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from pydantic import BaseModel, ConfigDict, Field

from amor.delivery import DeliveryReport, patch_digest


class GitHubPublicationError(RuntimeError):
    pass


class GitHubPullRequestReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    publication_id: str
    status: Literal["SUCCEEDED", "FAILED"]
    delivery_id: str
    repository: str
    remote_name: str
    branch_name: str
    base_branch: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    patch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft: bool = True
    push_succeeded: bool
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime


GitHubRequester = Callable[[str, str, str, dict[str, Any]], dict[str, Any]]


def publish_verified_delivery(
    *,
    delivery_report_path: Path,
    remote_name: str,
    base_branch: str,
    title: str,
    token: str,
    confirm_publish: bool,
    proxy: str | None = None,
    requester: GitHubRequester | None = None,
) -> GitHubPullRequestReport:
    """Push a reverified delivery commit and open a GitHub Draft PR."""

    if not confirm_publish:
        raise GitHubPublicationError("GitHub publication requires explicit confirmation")
    if not token.strip():
        raise GitHubPublicationError("GITHUB_TOKEN or GH_TOKEN is required")
    clean_title = title.strip()
    if not clean_title or len(clean_title) > 256 or "\n" in clean_title or "\r" in clean_title:
        raise GitHubPublicationError("pull request title must be a single line of 1-256 characters")
    clean_remote = _remote_name(remote_name)
    clean_base = _single_line(base_branch, "base branch", 200)
    clean_proxy = _proxy_url(proxy)

    report_path = delivery_report_path.resolve()
    if not report_path.is_file() or report_path.stat().st_size > 1_000_000:
        raise GitHubPublicationError("delivery report was not found or is too large")
    try:
        delivery = DeliveryReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GitHubPublicationError("delivery report is invalid") from exc
    if delivery.status != "SUCCEEDED" or not delivery.verification or not delivery.verification.passed:
        raise GitHubPublicationError("only a successfully reverified delivery can be published")
    if not delivery.commit_requested or not delivery.commit_sha:
        raise GitHubPublicationError("delivery must contain a local commit before publication")

    workspace = Path(delivery.workspace_path).resolve()
    if not workspace.is_dir():
        raise GitHubPublicationError("delivery workspace no longer exists")
    top_level = Path(_git(["rev-parse", "--show-toplevel"], workspace)).resolve()
    if top_level != workspace:
        raise GitHubPublicationError("delivery workspace root changed")
    if _git(["status", "--porcelain"], workspace):
        raise GitHubPublicationError("delivery workspace must remain clean")
    if _git(["rev-parse", "HEAD"], workspace) != delivery.commit_sha:
        raise GitHubPublicationError("delivery commit changed after verification")
    if _git(["branch", "--show-current"], workspace) != delivery.branch_name:
        raise GitHubPublicationError("delivery branch changed after verification")
    _validate_branch(workspace, delivery.branch_name)
    _validate_branch(workspace, clean_base)
    committed_patch = _git(
        [
            "diff",
            "--binary",
            "--no-ext-diff",
            delivery.baseline_commit,
            delivery.commit_sha,
            "--",
        ],
        workspace,
    )
    if patch_digest(committed_patch) != delivery.patch_sha256:
        raise GitHubPublicationError("delivery patch changed after verification")

    remote_url = _git(["remote", "get-url", clean_remote], workspace)
    owner, repository = _parse_github_remote(remote_url)
    repository_label = f"{owner}/{repository}"
    publication_id = _utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output_path = (
        report_path.parent
        / "github-publications"
        / f"{publication_id}.json"
    )
    created_at = _utc_now()
    push_succeeded = False
    try:
        _push_branch(
            workspace,
            owner=owner,
            repository=repository,
            branch_name=delivery.branch_name,
            token=token,
            proxy=clean_proxy,
        )
        push_succeeded = True
        payload = {
            "title": clean_title,
            "head": delivery.branch_name,
            "base": clean_base,
            "body": _pull_request_body(delivery),
            "draft": True,
        }
        response = (
            requester(owner, repository, token, payload)
            if requester is not None
            else _create_draft_pull_request(owner, repository, token, payload, proxy=clean_proxy)
        )
        number = response.get("number")
        url = response.get("html_url")
        expected_prefix = f"https://github.com/{owner}/{repository}/pull/"
        if not isinstance(number, int) or not isinstance(url, str) or not url.startswith(expected_prefix):
            raise GitHubPublicationError("GitHub returned an invalid pull request response")
        report = GitHubPullRequestReport(
            publication_id=publication_id,
            status="SUCCEEDED",
            delivery_id=delivery.delivery_id,
            repository=repository_label,
            remote_name=clean_remote,
            branch_name=delivery.branch_name,
            base_branch=clean_base,
            commit_sha=delivery.commit_sha,
            patch_sha256=delivery.patch_sha256,
            push_succeeded=True,
            pull_request_number=number,
            pull_request_url=url,
            created_at=created_at,
            finished_at=_utc_now(),
        )
    except Exception as exc:
        error = str(exc).replace(token, "[redacted]")
        report = GitHubPullRequestReport(
            publication_id=publication_id,
            status="FAILED",
            delivery_id=delivery.delivery_id,
            repository=repository_label,
            remote_name=clean_remote,
            branch_name=delivery.branch_name,
            base_branch=clean_base,
            commit_sha=delivery.commit_sha,
            patch_sha256=delivery.patch_sha256,
            push_succeeded=push_succeeded,
            error=error[:1000],
            created_at=created_at,
            finished_at=_utc_now(),
        )
    _write_report(output_path, report)
    return report


def _push_branch(
    workspace: Path,
    *,
    owner: str,
    repository: str,
    branch_name: str,
    token: str,
    proxy: str | None,
) -> None:
    credential = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_COUNT": "2" if proxy else "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    if proxy:
        environment["GIT_CONFIG_KEY_1"] = "https.proxy"
        environment["GIT_CONFIG_VALUE_1"] = proxy
    try:
        _git(
            [
                "push",
                f"--force-with-lease=refs/heads/{branch_name}:",
                f"https://github.com/{owner}/{repository}.git",
                f"{branch_name}:refs/heads/{branch_name}",
            ],
            workspace,
            environment=environment,
        )
    except GitHubPublicationError as exc:
        raise GitHubPublicationError("GitHub branch push failed") from exc


def _create_draft_pull_request(
    owner: str,
    repository: str,
    token: str,
    payload: dict[str, Any],
    *,
    proxy: str | None,
) -> dict[str, Any]:
    request = Request(
        f"https://api.github.com/repos/{owner}/{repository}/pulls",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "AMOR-Coding-Agent/0.16",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    try:
        if proxy:
            response_context = build_opener(ProxyHandler({"http": proxy, "https": proxy})).open(
                request, timeout=30
            )
        else:
            response_context = urlopen(request, timeout=30)
        with response_context as response:
            raw = response.read(1_000_001)
    except HTTPError as exc:
        raise GitHubPublicationError(f"GitHub API returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise GitHubPublicationError("GitHub API request failed") from exc
    if len(raw) > 1_000_000:
        raise GitHubPublicationError("GitHub API response was too large")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubPublicationError("GitHub API returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise GitHubPublicationError("GitHub API returned an invalid response")
    return parsed


def _pull_request_body(delivery: DeliveryReport) -> str:
    checks = delivery.verification.checks if delivery.verification else []
    check_lines = "\n".join(
        f"- [{'x' if check.passed else ' '}] `{check.name}`"
        for check in checks
    )
    return (
        "## AMOR verification evidence\n\n"
        f"- Delivery: `{delivery.delivery_id}`\n"
        f"- Baseline commit: `{delivery.baseline_commit}`\n"
        f"- Verified commit: `{delivery.commit_sha}`\n"
        f"- Patch SHA-256: `{delivery.patch_sha256}`\n"
        "- Post-apply verifier: passed\n\n"
        "### Checks\n\n"
        f"{check_lines or '- No named checks recorded'}\n\n"
        "> Created as a draft. Review the diff and CI before marking it ready.\n"
    )


def _parse_github_remote(remote_url: str) -> tuple[str, str]:
    patterns = (
        r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
        r"ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, remote_url.strip(), flags=re.IGNORECASE)
        if match:
            owner, repository = match.groups()
            if re.fullmatch(r"[A-Za-z0-9_.-]+", owner) and re.fullmatch(
                r"[A-Za-z0-9_.-]+", repository
            ):
                return owner, repository
    raise GitHubPublicationError("remote must identify a github.com repository")


def _validate_branch(workspace: Path, branch_name: str) -> None:
    _git(["check-ref-format", "--branch", branch_name], workspace)


def _single_line(value: str, label: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or "\n" in cleaned or "\r" in cleaned:
        raise GitHubPublicationError(f"{label} must be a single line of 1-{maximum} characters")
    return cleaned


def _remote_name(value: str) -> str:
    cleaned = _single_line(value, "remote name", 100)
    if cleaned.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._-]+", cleaned):
        raise GitHubPublicationError("remote name contains unsupported characters")
    return cleaned


def _proxy_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise GitHubPublicationError(
            "proxy must be an http(s) URL without credentials, path, query, or fragment"
        )
    return cleaned.rstrip("/")


def _git(
    args: list[str],
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise GitHubPublicationError(
            process.stderr.strip() or process.stdout.strip() or "Git command failed"
        )
    return process.stdout.rstrip("\r\n")


def _write_report(path: Path, report: GitHubPullRequestReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
