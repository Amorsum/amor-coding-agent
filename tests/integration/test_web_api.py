from pathlib import Path

from fastapi.testclient import TestClient

from amor.web.app import create_app
from tests.unit.test_artifact_store import create_experiment


def test_artifact_api_exposes_experiment_and_attempt(tmp_path: Path) -> None:
    create_experiment(tmp_path)
    client = TestClient(create_app(artifacts_root=tmp_path, frontend_root=tmp_path / "missing"))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["experiment_count"] == 1

    experiments = client.get("/api/experiments").json()["items"]
    experiment_id = experiments[0]["id"]
    detail = client.get(f"/api/experiments/{experiment_id}")
    assert detail.status_code == 200
    assert detail.json()["attempts"][0]["task_id"] == "task-one"

    attempt = client.get(
        f"/api/experiments/{experiment_id}/attempts/direct/task-one/1"
    )
    assert attempt.status_code == 200
    assert attempt.json()["report"]["verification"]["passed"] is True


def test_artifact_api_returns_not_found_for_unlisted_paths(tmp_path: Path) -> None:
    client = TestClient(create_app(artifacts_root=tmp_path, frontend_root=tmp_path / "missing"))

    response = client.get("/api/experiments/0000000000000000")
    assert response.status_code == 404


def test_web_app_serves_built_frontend_without_shadowing_api(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    frontend.joinpath("index.html").write_text("<h1>AMOR Workbench</h1>", encoding="utf-8")
    client = TestClient(create_app(artifacts_root=tmp_path / "artifacts", frontend_root=frontend))

    assert client.get("/").text == "<h1>AMOR Workbench</h1>"
    assert client.get("/api/health").json()["status"] == "ok"
