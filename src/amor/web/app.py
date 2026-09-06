from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from amor.showcase import ShowcaseError, ShowcaseExporter
from amor.web.artifacts import ArtifactNotFound, ArtifactStore, InvalidArtifact
from amor.web.jobs import (
    ClarificationRequest,
    ContractEditRequest,
    DeliveryRequest,
    ExecutionRequest,
    JobConflict,
    JobNotFound,
    PlanningRequest,
    TaskJobManager,
)


class ShowcaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    title: str = Field(default="AMOR 策略实验", min_length=1, max_length=120)
    confirm_public: Literal[True]


def create_app(
    artifacts_root: Path | None = None,
    frontend_root: Path | None = None,
    job_manager: TaskJobManager | None = None,
) -> FastAPI:
    resolved_artifacts = (artifacts_root or Path("artifacts")).resolve()
    store = ArtifactStore(resolved_artifacts)
    showcase_exporter = ShowcaseExporter(resolved_artifacts)
    showcase_exporter.output_root.mkdir(parents=True, exist_ok=True)
    manager = job_manager or TaskJobManager(resolved_artifacts)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(
        title="AMOR Local Workbench API",
        version="0.16.0",
        description="Local task execution and artifact inspection API.",
        lifespan=lifespan,
    )
    app.state.artifact_store = store
    app.state.job_manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def protect_local_mutations(request: Request, call_next: Any):
        if request.method == "POST" and request.url.path.startswith(("/api/jobs", "/api/showcases")):
            try:
                _require_local_origin(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "artifacts_ready": resolved_artifacts.is_dir(),
            "experiment_count": len(store.list_experiments()),
            "job_count": len(manager.list_jobs()),
        }

    @app.get("/api/runtime")
    def runtime() -> dict[str, Any]:
        return manager.runtime()

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"items": manager.list_jobs()}

    @app.post("/api/jobs", status_code=202)
    def start_job(payload: PlanningRequest, request: Request) -> dict[str, Any]:
        _require_local_origin(request)
        return _job_call(lambda: manager.start_planning(payload))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _job_call(lambda: manager.get_job(job_id))

    @app.get("/api/jobs/{job_id}/contracts/{revision}")
    def get_contract_revision(job_id: str, revision: int) -> dict[str, Any]:
        return _job_call(lambda: manager.get_contract_revision(job_id, revision))

    @app.post("/api/jobs/{job_id}/clarify", status_code=202)
    def clarify_job(
        job_id: str,
        payload: ClarificationRequest,
        request: Request,
    ) -> dict[str, Any]:
        _require_local_origin(request)
        return _job_call(lambda: manager.answer_questions(job_id, payload))

    @app.post("/api/jobs/{job_id}/contract")
    def edit_job_contract(
        job_id: str,
        payload: ContractEditRequest,
        request: Request,
    ) -> dict[str, Any]:
        _require_local_origin(request)
        return _job_call(lambda: manager.edit_contract(job_id, payload))

    @app.post("/api/jobs/{job_id}/approve", status_code=202)
    def approve_job(
        job_id: str,
        payload: ExecutionRequest,
        request: Request,
    ) -> dict[str, Any]:
        _require_local_origin(request)
        return _job_call(lambda: manager.approve_and_run(job_id, payload))

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
        _require_local_origin(request)
        return _job_call(lambda: manager.cancel(job_id))

    @app.post("/api/jobs/{job_id}/deliver", status_code=202)
    def deliver_job(
        job_id: str,
        payload: DeliveryRequest,
        request: Request,
    ) -> dict[str, Any]:
        _require_local_origin(request)
        return _job_call(lambda: manager.start_delivery(job_id, payload))

    @app.get("/api/jobs/{job_id}/events")
    async def stream_job_events(
        job_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        _job_call(lambda: manager.get_job(job_id))

        async def events():
            sequence = after
            while not await request.is_disconnected():
                pending, settled = manager.events_after(job_id, sequence)
                for event in pending:
                    sequence = int(event["sequence"])
                    yield (
                        f"id: {sequence}\n"
                        "event: job\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )
                if settled:
                    yield f"event: settled\ndata: {{\"sequence\":{sequence}}}\n\n"
                    return
                if not pending:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/experiments")
    def list_experiments() -> dict[str, Any]:
        return {"items": store.list_experiments()}

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: str) -> dict[str, Any]:
        return _read_or_404(lambda: store.get_experiment(experiment_id))

    @app.get("/api/showcases")
    def list_showcases() -> dict[str, Any]:
        return {
            "items": [
                {
                    **item.model_dump(mode="json"),
                    "url": f"/showcases/{item.showcase_id}/",
                }
                for item in showcase_exporter.list()
            ]
        }

    @app.post("/api/showcases", status_code=201)
    def create_showcase(payload: ShowcaseRequest, request: Request) -> dict[str, Any]:
        _require_local_origin(request)
        try:
            manifest = showcase_exporter.export(
                payload.experiment_id,
                title=payload.title,
                confirm_public=payload.confirm_public,
            )
        except (ArtifactNotFound, InvalidArtifact, ShowcaseError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            **manifest.model_dump(mode="json"),
            "url": f"/showcases/{manifest.showcase_id}/",
        }

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

    app.mount(
        "/showcases",
        StaticFiles(directory=showcase_exporter.output_root, html=True),
        name="showcases",
    )

    static_root = _frontend_root(frontend_root)
    if static_root is not None:
        app.mount("/", StaticFiles(directory=static_root, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        def missing_frontend() -> str:
            return (
                "<h1>AMOR Local Workbench API</h1>"
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

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("interactive workbench may only listen on a loopback host")

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


def _job_call(reader: Any) -> dict[str, Any]:
    try:
        return reader()
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_local_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise HTTPException(status_code=403, detail="mutating requests require a loopback origin")


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
