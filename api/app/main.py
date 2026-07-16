from fastapi import FastAPI

from .routers import auth, freshness, outcomes, recommendations, roadmap, sources

app = FastAPI(title="Trading Product Dashboard API")

app.include_router(auth.router)
app.include_router(recommendations.router)
app.include_router(outcomes.router)
app.include_router(freshness.router)
app.include_router(sources.router)
app.include_router(roadmap.router)


@app.get("/healthz")
def healthz() -> dict:
    """No auth — used by docker-compose's healthcheck."""
    return {"status": "ok"}
