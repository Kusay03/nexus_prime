from typing import AsyncGenerator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from config import settings

_driver: AsyncDriver | None = None


async def init_driver() -> None:
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized. Call init_driver() first.")
    async with _driver.session() as session:
        yield session
