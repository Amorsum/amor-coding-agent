import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import amor.github as github
from amor.delivery import DeliveryReport, patch_digest
from amor.domain import VerificationCheck, VerificationResult
from amor.github import GitHubPublicationError, publish_verified_delivery


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    ).stdout.rstrip("\r\n")


def delivery_fixture(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "AMOR Test")
    git(repository, "config", "user.email", "amor@example.invalid")
    source = repository / "value.txt"
    source.write_text("before\n", encoding="utf-8", newline="\n")
    git(repository, "add", "value.txt")
    git(repository, "commit", "-m", "baseline")
    baseline = git(repository, "rev-parse", "HEAD")
    git(repository, "switch", "-c", "amor/verified-change")
    source.write_text("after\n", encoding="utf-8", newline="\n")
    git(repository, "add", "value.txt")
    git(repository, "commit", "-m", "fix: verified change")
    commit_sha = git(repository, "rev-parse", "HEAD")
    patch = git(
        repository,
        "diff",
        "--binary",
        "--no-ext-diff",
        baseline,
        commit_sha,
        "--",
    )
    git(repository, "remote", "add", "origin", "git@github.com:example/verified-project.git")
    delivery_root = tmp_path / "delivery"
    delivery_root.mkdir()
    now = datetime.now(timezone.utc)
    report = DeliveryReport(
        delivery_id="delivery-example",
        status="SUCCEEDED",
        branch_name="amor/verified-change",
        baseline_commit=baseline,
        patch_sha256=patch_digest(patch),
        commit_requested=True,
        commit_sha=commit_sha,
        verification=VerificationResult(
            passed=True,
            checks=[VerificationCheck(name="visible:tests", passed=True, summary="PRIVATE OUTPUT")],
        ),
        workspace_path=str(repository),
        created_at=now,
        finished_at=now,
    )
    report_path = delivery_root / "delivery-report.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path, "secret-github-token"


def test_verified_delivery_opens_draft_pr_without_persisting_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path, token = delivery_fixture(tmp_path)
    pushed: dict[str, str] = {}

    def push(
        workspace: Path,
        *,
        owner: str,
        repository: str,
        branch_name: str,
        token: str,
        proxy: str | None,
    ) -> None:
        assert proxy is None
        pushed.update(
            workspace=str(workspace),
            owner=owner,
            repository=repository,
            branch=branch_name,
            token=token,
        )

    def request(
        owner: str,
        repository: str,
        request_token: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        assert (owner, repository, request_token) == ("example", "verified-project", token)
        assert payload["draft"] is True
        assert payload["head"] == "amor/verified-change"
        assert "PRIVATE OUTPUT" not in str(payload["body"])
        return {
            "number": 7,
            "html_url": "https://github.com/example/verified-project/pull/7",
        }

    monkeypatch.setattr(github, "_push_branch", push)
    report = publish_verified_delivery(
        delivery_report_path=report_path,
        remote_name="origin",
        base_branch="main",
        title="fix: verified change",
        token=token,
        confirm_publish=True,
        requester=request,
    )

    assert report.status == "SUCCEEDED"
    assert report.push_succeeded
    assert report.pull_request_number == 7
    assert pushed["branch"] == "amor/verified-change"
    persisted = (
        report_path.parent / "github-publications" / f"{report.publication_id}.json"
    ).read_text(encoding="utf-8")
    assert token not in persisted
    assert "PRIVATE OUTPUT" not in persisted


def test_github_failure_records_pushed_branch_without_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path, token = delivery_fixture(tmp_path)
    monkeypatch.setattr(github, "_push_branch", lambda *args, **kwargs: None)

    def fail(*args, **kwargs):
        raise GitHubPublicationError(f"request rejected for {token}")

    report = publish_verified_delivery(
        delivery_report_path=report_path,
        remote_name="origin",
        base_branch="main",
        title="fix: verified change",
        token=token,
        confirm_publish=True,
        requester=fail,
    )

    assert report.status == "FAILED"
    assert report.push_succeeded
    assert report.error == "request rejected for [redacted]"
    assert token not in (
        report_path.parent / "github-publications" / f"{report.publication_id}.json"
    ).read_text(encoding="utf-8")


def test_github_publication_rejects_dirty_delivery_workspace(tmp_path: Path) -> None:
    report_path, token = delivery_fixture(tmp_path)
    report = DeliveryReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    (Path(report.workspace_path) / "untracked.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(GitHubPublicationError, match="remain clean"):
        publish_verified_delivery(
            delivery_report_path=report_path,
            remote_name="origin",
            base_branch="main",
            title="fix: verified change",
            token=token,
            confirm_publish=True,
        )


def test_push_uses_non_overwriting_lease_and_environment_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run_git(
        args: list[str],
        cwd: Path,
        *,
        environment: dict[str, str] | None = None,
    ) -> str:
        observed.update(args=args, cwd=cwd, environment=environment)
        return ""

    monkeypatch.setattr(github, "_git", run_git)
    github._push_branch(
        tmp_path,
        owner="example",
        repository="verified-project",
        branch_name="amor/verified-change",
        token="secret-github-token",
        proxy="http://127.0.0.1:7890",
    )

    args = observed["args"]
    environment = observed["environment"]
    assert isinstance(args, list)
    assert "--force-with-lease=refs/heads/amor/verified-change:" in args
    assert "secret-github-token" not in " ".join(args)
    assert isinstance(environment, dict)
    assert environment["GIT_CONFIG_COUNT"] == "2"
    assert environment["GIT_CONFIG_KEY_1"] == "https.proxy"
    assert environment["GIT_CONFIG_VALUE_1"] == "http://127.0.0.1:7890"


def test_github_publication_rejects_proxy_credentials(tmp_path: Path) -> None:
    with pytest.raises(GitHubPublicationError, match="without credentials"):
        publish_verified_delivery(
            delivery_report_path=tmp_path / "missing.json",
            remote_name="origin",
            base_branch="main",
            title="fix: verified change",
            token="secret-github-token",
            confirm_publish=True,
            proxy="http://user:password@127.0.0.1:7890",
        )
