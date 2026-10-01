import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.routes import router
from app.api.runtime import SessionFactory, StationRuntime
from app.db import SessionLocal


def create_app(session_factory: SessionFactory = SessionLocal) -> FastAPI:
    def build_runtime() -> StationRuntime | None:
        """Create the runtime (and its ticker) once the DB has a station."""
        try:
            rt = StationRuntime(session_factory)
        except LookupError:  # not seeded yet; routes answer 503 until it is
            app.state.runtime = None
            return None
        app.state.runtime = rt
        app.state.ticker = asyncio.get_running_loop().create_task(rt.run_ticker())
        return rt

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        build_runtime()
        try:
            yield
        finally:
            ticker: asyncio.Task[None] | None = app.state.ticker
            if ticker is not None:
                ticker.cancel()
                with suppress(asyncio.CancelledError):
                    await ticker

    app = FastAPI(title="VoltQueue", lifespan=lifespan)
    app.state.runtime = None
    app.state.ticker = None
    app.state.build_runtime = build_runtime
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
