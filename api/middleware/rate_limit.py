import math
from dataclasses import dataclass

from fastapi import Request
from jose import JWTError, jwt
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from config import settings
from redis_client import get_redis


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    max_requests: int
    window_seconds: int
    detail: str


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.rate_limit_enabled or self._is_exempt(request):
            return await call_next(request)

        policy = self._policy_for(request)
        if policy is None:
            return await call_next(request)

        identifier = await self._identifier_for(request, policy.name)
        try:
            redis = await get_redis()
            allowed, remaining, retry_after = await self._consume(
                redis,
                policy,
                identifier,
            )
        except Exception:
            # Redis is already a dependency for auth/session flows; fail open here so
            # an outage does not turn every API request into a hard failure.
            return await call_next(request)

        headers = {
            "X-RateLimit-Limit": str(policy.max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Window": str(policy.window_seconds),
        }
        if not allowed:
            headers["Retry-After"] = str(retry_after)
            return JSONResponse(
                status_code=429,
                content={"detail": policy.detail},
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response

    def _is_exempt(self, request: Request) -> bool:
        path = request.url.path
        if request.method == "OPTIONS":
            return True
        if path in {"/", "/healthz", "/docs", "/redoc", "/openapi.json"}:
            return True
        if "." in path.rsplit("/", 1)[-1]:
            return True
        return False

    def _policy_for(self, request: Request) -> RateLimitPolicy | None:
        path = request.url.path
        if path == "/auth/token" and request.method == "POST":
            return RateLimitPolicy(
                name="auth_token",
                max_requests=settings.rate_limit_auth_max_requests,
                window_seconds=settings.rate_limit_auth_window_seconds,
                detail="Too many login attempts. Please wait before retrying.",
            )

        if path.startswith("/"):
            return RateLimitPolicy(
                name="api",
                max_requests=settings.rate_limit_api_max_requests,
                window_seconds=settings.rate_limit_api_window_seconds,
                detail="API rate limit exceeded. Please retry later.",
            )

        return None

    async def _identifier_for(self, request: Request, policy_name: str) -> str:
        client_ip = self._client_ip(request)
        if policy_name == "auth_token":
            form = await request.form()
            username = str(form.get("username") or "").strip().lower()
            if username:
                return f"{client_ip}:{username}"
            return client_ip

        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                payload = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                )
                user_id = payload.get("sub")
                tenant_id = payload.get("tenant_id")
                if user_id and tenant_id:
                    return f"{tenant_id}:{user_id}"
            except JWTError:
                pass

        return client_ip

    def _client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    async def _consume(
        self,
        redis: Redis,
        policy: RateLimitPolicy,
        identifier: str,
    ) -> tuple[bool, int, int]:
        bucket = math.floor(request_timestamp() / policy.window_seconds)
        key = f"rate_limit:{policy.name}:{identifier}:{bucket}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, policy.window_seconds)
        ttl = max(await redis.ttl(key), 1)
        remaining = max(policy.max_requests - count, 0)
        return count <= policy.max_requests, remaining, ttl


def request_timestamp() -> int:
    from time import time

    return int(time())
