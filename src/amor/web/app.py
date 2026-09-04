from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from amor.web.artifacts import ArtifactNotFound, ArtifactStore, InvalidArtifact


def create_app(
    artifacts_root: Path | None = None,
    frontend_root: Path | None = None,
) -> FastAPI:
    resolved_artifacts = (artifacts_root or Path("artifacts")).resolve()
    store = ArtifactStore(resolved_artifacts)
    app = FastAPI(
        title="AMOR Artifact API",
        version="0.7.0",
        description="Read-only API for benchmark experiments and agent traces.",
    )
    app.state.artifact_store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "artifacts_ready": resolved_artifacts.is_dir(),
            "experiment_count": len(store.list_experiments()),
        }

    @app.get("/api/experiments")
    def list_experiments() -> dict[str, Any]:
        return {"items": store.list_experiments()}

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: str) -> dict[str, Any]:
        return _read_or_404(lambda: store.get_experiment(experiment_id))

    @app.get("/api/experiments/{experiment_id}/attempts/{strategy}/{task_id}/{attempt}")
    def get_attempt(
        experiment_id: str,
        strategy: str,
        task_id: str,
        attempt: int,
    ) -> dict[str, Any]:
        return _read_or_404(
            lambda: store.get_attempt(experiment_id, strategy, task_id, attempt)
        )

    static_root = _frontend_root(frontend_root)
    if static_root is not None:
        app.mount("/", StaticFiles(directory=static_root, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        def missing_frontend() -> str:
            return (
                "<h1>AMOR Artifact API</h1>"
                "<p>前端尚未构建。请在 web 目录运行 npm run build。</p>"
            )

    return app


def serve_dashboard(
    artifacts_root: Path,
    frontend_root: Path | None,
    host: str,
    port: int,
) -> None:
    import uvicorn

    uvicorn.run(
        create_app(artifacts_root=artifacts_root, frontend_root=frontend_root),
        host=host,
        port=port,
    )


def _read_or_404(reader: Any) -> dict[str, Any]:
    try:
        return reader()
    except ArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidArtifact as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _frontend_root(configured: Path | None) -> Path | None:
    candidates = (
        [configured]
        if configured is not None
        else [Path("web/dist"), Path("web/dist/client"), Path("web/out")]
    )
    for candidate in candidates:
        if candidate is not None:
            resolved = candidate.resolve()
            if (resolved / "index.html").is_file():
                return resolved
    return None
