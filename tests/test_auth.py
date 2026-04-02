"""
Authentication tests covering bootstrap, login, and admin-managed registration.
"""
import uuid

import pytest
from redis.asyncio import Redis

from config import settings
from redis_client import get_redis


async def _delete_tenant(neo4j_driver, tenant_id: str) -> None:
    async with neo4j_driver.session() as session:
        await session.run(
            """
            MATCH (n {tenant_id: $tenant_id})
            DETACH DELETE n
            """,
            tenant_id=tenant_id,
        )


async def _clear_rate_limit_keys(redis: Redis) -> None:
    keys = [key async for key in redis.scan_iter(match="rate_limit:*")]
    if keys:
        await redis.delete(*keys)


@pytest.mark.asyncio
async def test_bootstrap_creates_first_admin_and_disables_further_bootstrap(
    anonymous_client,
    neo4j_driver,
):
    tenant_id = f"bootstrap_{uuid.uuid4().hex[:12]}"
    username = f"bootstrap_admin_{uuid.uuid4().hex[:8]}"
    password = "bootstrap-pass"

    try:
        status_resp = await anonymous_client.get("/auth/bootstrap/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["needs_bootstrap"] is True

        bootstrap_resp = await anonymous_client.post(
            "/auth/bootstrap",
            json={
                "tenant_id": tenant_id,
                "username": username,
                "email": f"{username}@example.com",
                "password": password,
            },
        )
        assert bootstrap_resp.status_code == 201
        bootstrap_data = bootstrap_resp.json()
        assert bootstrap_data["tenant_id"] == tenant_id
        assert bootstrap_data["role"] == "admin"

        status_after_resp = await anonymous_client.get("/auth/bootstrap/status")
        assert status_after_resp.status_code == 200
        assert status_after_resp.json()["needs_bootstrap"] is False

        second_bootstrap_resp = await anonymous_client.post(
            "/auth/bootstrap",
            json={
                "tenant_id": "other-tenant",
                "username": "other-admin",
                "email": "other@example.com",
                "password": password,
            },
        )
        assert second_bootstrap_resp.status_code == 409

        token_resp = await anonymous_client.post(
            "/auth/token",
            data={"username": username, "password": password},
        )
        assert token_resp.status_code == 200
        token_data = token_resp.json()
        assert token_data["tenant_id"] == tenant_id
        assert token_data["role"] == "admin"

        me_resp = await anonymous_client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["username"] == username
        assert me_data["tenant_id"] == tenant_id
        assert me_data["role"] == "admin"
    finally:
        await _delete_tenant(neo4j_driver, tenant_id)


@pytest.mark.asyncio
async def test_admin_register_creates_user_in_same_tenant(
    anonymous_client,
    clean_tenant,
    http_client,
):
    username = f"analyst_{clean_tenant[-6:]}"
    password = "analyst-pass"

    register_resp = await http_client.post(
        "/auth/register",
        json={
            "tenant_id": clean_tenant,
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "role": "analyst",
        },
    )
    assert register_resp.status_code == 201
    register_data = register_resp.json()
    assert register_data["username"] == username
    assert register_data["tenant_id"] == clean_tenant
    assert register_data["role"] == "analyst"

    token_resp = await anonymous_client.post(
        "/auth/token",
        data={"username": username, "password": password},
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert token_data["tenant_id"] == clean_tenant
    assert token_data["role"] == "analyst"

    me_resp = await anonymous_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == username


@pytest.mark.asyncio
async def test_admin_register_rejects_different_tenant(clean_tenant, http_client):
    resp = await http_client.post(
        "/auth/register",
        json={
            "tenant_id": f"{clean_tenant}-other",
            "username": f"user_{clean_tenant[-6:]}",
            "email": "other-tenant@example.com",
            "password": "another-pass",
            "role": "read-only",
        },
    )
    assert resp.status_code == 403
    assert "own tenant" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_repeated_attempts(anonymous_client):
    redis = await get_redis()
    original_max = settings.rate_limit_auth_max_requests
    original_window = settings.rate_limit_auth_window_seconds
    settings.rate_limit_auth_max_requests = 2
    settings.rate_limit_auth_window_seconds = 60

    try:
        await _clear_rate_limit_keys(redis)

        for _ in range(2):
            resp = await anonymous_client.post(
                "/auth/token",
                data={"username": "missing-user", "password": "wrong-pass"},
            )
            assert resp.status_code == 401

        blocked = await anonymous_client.post(
            "/auth/token",
            data={"username": "missing-user", "password": "wrong-pass"},
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        assert "Too many login attempts" in blocked.json()["detail"]
    finally:
        settings.rate_limit_auth_max_requests = original_max
        settings.rate_limit_auth_window_seconds = original_window
        await _clear_rate_limit_keys(redis)


@pytest.mark.asyncio
async def test_authenticated_requests_are_rate_limited(http_client):
    redis = await get_redis()
    original_max = settings.rate_limit_api_max_requests
    original_window = settings.rate_limit_api_window_seconds
    settings.rate_limit_api_max_requests = 2
    settings.rate_limit_api_window_seconds = 60

    try:
        await _clear_rate_limit_keys(redis)

        for _ in range(2):
            resp = await http_client.get("/auth/me")
            assert resp.status_code == 200

        blocked = await http_client.get("/auth/me")
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        assert "API rate limit exceeded" in blocked.json()["detail"]
    finally:
        settings.rate_limit_api_max_requests = original_max
        settings.rate_limit_api_window_seconds = original_window
        await _clear_rate_limit_keys(redis)
