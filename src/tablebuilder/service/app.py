# ABOUTME: FastAPI application factory with lifespan for worker management.
# ABOUTME: Registers all route modules and starts/stops the background worker.

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from tablebuilder.service.db import ServiceDB
from tablebuilder.service.worker import Worker


def _data_dir() -> Path:
    """Resolve the data directory: DATA_DIR env var > ./data/ > ~/.tablebuilder/."""
    import os
    if env_dir := os.environ.get("TABLEBUILDER_DATA_DIR"):
        return Path(env_dir)
    # Check if ./data/ exists (project-local mode)
    local_data = Path.cwd() / "data"
    if local_data.exists():
        return local_data
    return Path.home() / ".tablebuilder"


DEFAULT_DB_PATH = _data_dir() / "service.db"
DEFAULT_RESULTS_DIR = _data_dir() / "results"


def create_app(
    db_path: Path = DEFAULT_DB_PATH,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    encryption_key: str = "",
    anthropic_api_key: str = "",
    start_worker: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    worker: Worker | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal worker
        if start_worker and encryption_key:
            worker = Worker(
                db=app.state.db,
                results_dir=results_dir,
                encryption_key=encryption_key,
            )
            worker.start()
        yield
        if worker:
            worker.stop()
            worker.join(timeout=30)

    app = FastAPI(title="TableBuilder Service", lifespan=lifespan)

    # Attach shared state
    app.state.db = ServiceDB(db_path)
    app.state.encryption_key = encryption_key
    app.state.results_dir = results_dir
    app.state.chat_resolver = None
    if anthropic_api_key:
        from tablebuilder.service.chat_resolver import ChatResolver
        app.state.chat_resolver = ChatResolver(anthropic_api_key=anthropic_api_key)

    # Register routes
    from tablebuilder.service.routes_api import router as api_router
    app.include_router(api_router)

    from tablebuilder.service.routes_chat import router as chat_router
    app.include_router(chat_router)

    from tablebuilder.service.routes_web import router as web_router
    app.include_router(web_router)

    return app


def _create_default_app() -> FastAPI:
    """Module-level app factory for uvicorn. Reads config from env vars."""
    import os
    encryption_key = os.environ.get("DB_ENCRYPTION_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return create_app(encryption_key=encryption_key, anthropic_api_key=anthropic_key)


# Module-level instance for uvicorn (e.g., uvicorn tablebuilder.service.app:app)
app = _create_default_app()
