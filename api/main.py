from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_driver, close_driver
from redis_client import init_redis, close_redis
from routers import auth, ontology, ingest, query


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/auth",     tags=["Auth"])
app.include_router(ontology.router, prefix="/ontology", tags=["Ontology"])
app.include_router(ingest.router,   prefix="/ingest",   tags=["Ingest"])
app.include_router(query.router,    prefix="/query",    tags=["Query"])


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}
