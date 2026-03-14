from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from neo4j import AsyncSession
from redis.asyncio import Redis

from config import settings
from db import get_session
from redis_client import get_redis
from models.auth import CurrentUser, Role

# Points to the login endpoint so Swagger UI can auto-fill the "Authorize" dialog
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> CurrentUser:
    """
    Core auth dependency. Validates the Bearer JWT, checks the Redis blacklist,
    and confirms the user is still active in Neo4j.
    Injects a CurrentUser (with tenant_id + role) into every protected endpoint.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 1. Fast path: token on the blacklist → reject immediately
    if await redis.exists(f"blacklist:{token}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Decode and validate JWT signature + expiry
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str | None = payload.get("sub")
        username: str | None = payload.get("username")
        tenant_id: str | None = payload.get("tenant_id")
        role_str: str | None = payload.get("role")

        if not all([user_id, username, tenant_id, role_str]):
            raise unauthorized
    except JWTError:
        raise unauthorized

    # 3. Verify user still exists and is active in Neo4j (catches deleted/deactivated accounts)
    result = await session.run(
        "MATCH (u:User {user_id: $user_id, is_active: true}) RETURN u.user_id AS id",
        user_id=user_id,
    )
    if not await result.single():
        raise unauthorized

    return CurrentUser(
        user_id=user_id,        # type: ignore[arg-type]
        username=username,      # type: ignore[arg-type]
        tenant_id=tenant_id,    # type: ignore[arg-type]
        role=Role(role_str),
        token=token,
    )


def require_roles(*roles: Role):
    """
    Dependency factory for role-based access control.

    Usage:
        current_user: CurrentUser = Depends(require_roles(Role.ADMIN))
        current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST))
    """
    async def _enforce(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{current_user.role}' is not permitted for this action. "
                    f"Required: {[r.value for r in roles]}"
                ),
            )
        return current_user

    return _enforce
