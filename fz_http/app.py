"""FastAPI application factory."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .routes import router
from .workspace import WorkspaceError


def create_app() -> FastAPI:
    app = FastAPI(
        title="fz HTTP API",
        version=__version__,
        description=(
            "HTTP interface to the fz parametric scientific computing framework "
            "(fzi/fzc/fzo/fzr/fzl/fzd). Interactive docs at /docs."
        ),
    )

    @app.exception_handler(WorkspaceError)
    async def _workspace_error_handler(_: Request, exc: WorkspaceError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(router)
    return app


# Module-level app for `uvicorn fz_http.app:app`.
app = create_app()
