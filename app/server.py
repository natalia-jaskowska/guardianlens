"""FastAPI server for the GuardianLens dashboard.

Endpoints
---------

- ``GET /``                — Jinja2-rendered single page (initial state baked in)
- ``GET /api/state``       — one-shot JSON snapshot
- ``GET /api/stream``      — Server-Sent Events stream of JSON snapshots (every 2 s)
- ``GET /static/*``        — vanilla CSS / JS / assets
- ``GET /screenshots/*``   — the latest captured PNGs (read-only mount)

Lifecycle
---------

The :class:`AppState` is constructed inside the FastAPI ``lifespan``
handler so the monitor thread starts when the server starts and stops
cleanly on shutdown. The whole thing is built by :func:`create_app`,
which is called from ``run.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.state import AppState
from guardlens.config import GuardLensConfig

logger = logging.getLogger(__name__)

APP_DIR: Path = Path(__file__).parent
STATIC_DIR: Path = APP_DIR / "static"
TEMPLATES_DIR: Path = APP_DIR / "templates"

STREAM_INTERVAL_SECONDS: float = 2.0
"""How often the SSE generator yields a fresh state snapshot."""


def create_app(config: GuardLensConfig) -> FastAPI:
    """Build the FastAPI app for the given configuration.

    The :class:`AppState` (worker, database, alerts) is created and
    started here. ``run.py`` calls this once and hands the result to
    uvicorn.
    """
    state = AppState(config)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        state.start()
        logger.info("FastAPI dashboard ready on %s:%d", config.dashboard.server_name, config.dashboard.server_port)
        try:
            yield
        finally:
            state.stop()

    app = FastAPI(
        title=config.dashboard.title,
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.guardlens = state

    # ---- static + screenshot mounts ------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    config.monitor.screenshots_dir.mkdir(parents=True, exist_ok=True)
    # follow_symlink=True is required so the watch-folder mode can serve
    # scraped images that live outside the screenshots directory and are
    # only symlinked into it.
    app.mount(
        "/screenshots",
        StaticFiles(
            directory=str(config.monitor.screenshots_dir),
            check_dir=False,
            follow_symlink=True,
        ),
        name="screenshots",
    )

    # ---- routes -------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        snapshot = state.build_state()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": config.dashboard.title,
                "model_name": config.ollama.inference_model,
                "db_path": str(config.database.path),
                "initial_state": snapshot,
            },
        )

    @app.get("/api/state")
    async def api_state() -> JSONResponse:
        return JSONResponse(state.build_state())

    @app.get("/api/analysis/{analysis_id}")
    async def api_analysis(analysis_id: int) -> JSONResponse:
        """Return the full serialized analysis for one DB row.

        Used by the dashboard's "click an alert history card to inspect"
        flow — keeps the per-tick SSE payload small while still letting
        the user load full reasoning chain / why this matters /
        recommended action / telegram details on demand.
        """
        from app.serializers import serialize_analysis

        analysis = state.database.analysis_by_id(analysis_id)
        if analysis is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(serialize_analysis(analysis, history=state.session.recent()))

    @app.get("/api/stream")
    async def api_stream(request: Request) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[bytes]:
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    snapshot = state.build_state()
                    payload = json.dumps(snapshot, default=str)
                    yield f"data: {payload}\n\n".encode("utf-8")
                    await asyncio.sleep(STREAM_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                # Normal — client disconnected.
                return

        headers = {
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx-style buffering if reverse-proxied
        }
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    @app.post("/api/pause")
    async def api_pause() -> JSONResponse:
        state.worker.pause()
        return JSONResponse({"status": "paused"})

    @app.post("/api/resume")
    async def api_resume() -> JSONResponse:
        state.worker.resume()
        return JSONResponse({"status": "running"})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
