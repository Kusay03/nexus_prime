"""
Pytest shared fixtures for Project Nexus tests.
Requires a live Neo4j + Redis instance. Set env vars or use the defaults below.
"""
import uuid

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

# Use the same settings import path used by the API
import sys
sys.path.insert(0, "api")

# Override settings before importing anything that reads them
import os
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod-32chars")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRY_MINUTES", "60")

from config import settings
from main import app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def neo4j_driver():
    from neo4j import AsyncGraphDatabase
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await driver.verify_connectivity()
    except Exception as exc:
        raise RuntimeError(
            "Neo4j is not ready for tests. Start the local stack with "
            "`podman-compose -f podman-compose.test.yml up -d` and ensure "
            "NEO4J_PASSWORD matches the test defaults."
        ) from exc
    yield driver
    await driver.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def initialized_app():
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def clean_tenant(neo4j_driver):
    """Isolate each test to a fresh tenant so they never interfere."""
    tenant_id = f"test_{uuid.uuid4().hex[:12]}"
    async with neo4j_driver.session() as session:
        # Wipe all tenant data
        await session.run(
            """
            MATCH (n {tenant_id: $tid})
            DETACH DELETE n
            """,
            tid=tenant_id,
        )
    yield tenant_id
    async with neo4j_driver.session() as session:
        await session.run(
            """
            MATCH (n {tenant_id: $tid})
            DETACH DELETE n
            """,
            tid=tenant_id,
        )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def admin_token(clean_tenant, neo4j_driver) -> str:
    """Return a valid JWT for the test tenant (admin role)."""
    import sys
    sys.path.insert(0, "api")
    from routers.auth import _create_token
    user_id = f"{clean_tenant}-admin"
    username = f"test-admin-{clean_tenant}"

    async with neo4j_driver.session() as session:
        await session.run(
            """
            CREATE (u:User {
                user_id: $user_id,
                username: $username,
                email: $email,
                role: 'admin',
                tenant_id: $tenant_id,
                is_active: true,
                hashed_password: 'test-hash',
                created_at: datetime()
            })
            """,
            user_id=user_id,
            username=username,
            email=f"{username}@example.com",
            tenant_id=clean_tenant,
        )

    return _create_token(
        user_id=user_id,
        username=username,
        tenant_id=clean_tenant,
        role="admin",
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def analyst_token(clean_tenant, neo4j_driver) -> str:
    """Return a valid JWT for the test tenant (analyst role)."""
    import sys
    sys.path.insert(0, "api")
    from routers.auth import _create_token
    user_id = f"{clean_tenant}-analyst"
    username = f"test-analyst-{clean_tenant}"

    async with neo4j_driver.session() as session:
        await session.run(
            """
            CREATE (u:User {
                user_id: $user_id,
                username: $username,
                email: $email,
                role: 'analyst',
                tenant_id: $tenant_id,
                is_active: true,
                hashed_password: 'test-hash',
                created_at: datetime()
            })
            """,
            user_id=user_id,
            username=username,
            email=f"{username}@example.com",
            tenant_id=clean_tenant,
        )

    return _create_token(
        user_id=user_id,
        username=username,
        tenant_id=clean_tenant,
        role="analyst",
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def http_client(initialized_app, admin_token):
    transport = ASGITransport(app=initialized_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def anonymous_client(initialized_app):
    transport = ASGITransport(app=initialized_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client
