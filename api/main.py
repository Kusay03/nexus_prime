from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from neo4j import AsyncSession
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import settings
from db import close_driver, get_session, init_driver
from middleware.rate_limit import RateLimitMiddleware
from redis_client import close_redis, get_redis, init_redis
from routers import action, auth, case_management, ingest, ontology, query, workspace


FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
API_PREFIXES = {
    "auth",
    "ontology",
    "ingest",
    "query",
    "action",
    "workspace",
    "cases",
    "docs",
    "redoc",
    "openapi.json",
    "healthz",
}


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as exc:
            if exc.status_code != 404:
                raise

        first_segment = path.split("/", 1)[0]
        if first_segment in API_PREFIXES or "." in Path(path).name:
            raise HTTPException(status_code=404)

        return await super().get_response("index.html", scope)


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_driver()
    await init_redis()
    yield
    await close_redis()
    await close_driver()


app = FastAPI(
    title="Project Nexus API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,         prefix="/auth",      tags=["Auth"])
app.include_router(ontology.router,    prefix="/ontology",   tags=["Ontology"])
app.include_router(ingest.router,      prefix="/ingest",    tags=["Ingest"])
app.include_router(query.router,       prefix="/query",     tags=["Query"])
app.include_router(action.router,      prefix="/action",    tags=["Action"])
app.include_router(workspace.router,  prefix="/workspace", tags=["Workspace"])
app.include_router(case_management.router, prefix="/cases", tags=["Cases"])


@app.get("/healthz")
async def health(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict[str, str]:
    neo4j_status = "degraded"
    redis_status = "degraded"

    try:
        result = await session.run("RETURN 1 AS ok")
        record = await result.single()
        if record and record["ok"] == 1:
            neo4j_status = "ok"
    except Exception:
        neo4j_status = "degraded"

    try:
        if await redis.ping():
            redis_status = "ok"
    except Exception:
        redis_status = "degraded"

    overall_status = "ok" if neo4j_status == "ok" and redis_status == "ok" else "degraded"
    return {
        "status": overall_status,
        "version": "1.0.0",
        "neo4j": neo4j_status,
        "redis": redis_status,
    }


if FRONTEND_DIST_DIR.exists():
    app.mount(
        "/",
        SPAStaticFiles(directory=str(FRONTEND_DIST_DIR), html=True),
        name="frontend",
    )
else:
    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "status": "ok",
            "version": "1.0.0",
            "detail": "Frontend bundle not found. Build frontend/dist or run Vite separately.",
        }
