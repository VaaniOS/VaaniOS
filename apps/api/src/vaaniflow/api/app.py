from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vaaniflow.api.routers import runs, sandbox, search


def create_app() -> FastAPI:
    """FastAPI application factory for VaaniFlow."""
    app = FastAPI(
        title="VaaniFlow API",
        description="Reliable Voice-to-Business-Action Platform for Indian SMEs",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(runs.router)
    app.include_router(search.router)
    app.include_router(sandbox.router)

    @app.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        return {"status": "healthy", "service": "vaaniflow"}

    return app


app = create_app()
