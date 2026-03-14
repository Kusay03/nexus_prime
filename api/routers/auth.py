import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from neo4j import AsyncSession
from passlib.context import CryptContext
from redis.asyncio import Redis

from config import settings
from db import get_session
from middleware.tenant import get_current_user
from models.auth import CurrentUser, Role, TokenResponse, UserCreate, UserResponse
from redis_client import get_redis

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(plain: str) -> str:
    return pwd_context.hash(plain)


def _verify(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(user_id: str, username: str, tenant_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _node_to_response(u: dict) -> UserResponse:
    return UserResponse(
        user_id=u["user_id"],
        username=u["username"],
        email=u["email"],
        role=Role(u["role"]),
        tenant_id=u["tenant_id"],
        created_at=str(u.get("created_at")) if u.get("created_at") else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """
    Public registration endpoint (Phase 3 prototype).
    In production: gate this behind an admin token for subsequent users.
    """
    # Reject duplicate usernames (globally unique, not just per-tenant)
    check = await session.run(
        "MATCH (u:User {username: $username}) RETURN u.user_id AS id",
        username=body.username,
    )
    if await check.single():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken",
        )

    user_id = str(uuid.uuid4())
    result = await session.run(
        """
        CREATE (u:User {
            user_id:         $user_id,
            username:        $username,
            email:           $email,
            hashed_password: $hashed_password,
            role:            $role,
            tenant_id:       $tenant_id,
            is_active:       true,
            created_at:      datetime()
        })
        RETURN u
        """,
        user_id=user_id,
        username=body.username,
        email=body.email,
        hashed_password=_hash(body.password),
        role=body.role.value,
        tenant_id=body.tenant_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create user")

    return _node_to_response(dict(record["u"]))


@router.post("/token", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """Standard OAuth2 password flow. Returns a signed JWT."""
    result = await session.run(
        """
        MATCH (u:User {username: $username, is_active: true})
        RETURN u.user_id AS user_id, u.hashed_password AS hashed_password,
               u.role AS role, u.tenant_id AS tenant_id
        """,
        username=form.username,
    )
    record = await result.single()

    if not record or not _verify(form.password, record["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _create_token(
        user_id=record["user_id"],
        username=form.username,
        tenant_id=record["tenant_id"],
        role=record["role"],
    )

    # Store active session in Redis — visible for admin auditing, cleaned on logout
    await redis.set(
        f"session:{record['user_id']}",
        token,
        ex=settings.jwt_expiry_minutes * 60,
    )

    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
        tenant_id=record["tenant_id"],
        role=record["role"],
    )


@router.post("/logout", status_code=204)
async def logout(
    current_user: CurrentUser = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> None:
    """
    Blacklists the current token in Redis so it is rejected on all future requests.
    The blacklist key TTL mirrors the JWT's remaining lifetime — self-cleaning.
    """
    try:
        payload = jwt.decode(
            current_user.token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        remaining_ttl = max(
            int(payload["exp"] - datetime.now(timezone.utc).timestamp()), 1
        )
    except JWTError:
        remaining_ttl = settings.jwt_expiry_minutes * 60

    await redis.set(f"blacklist:{current_user.token}", "1", ex=remaining_ttl)
    await redis.delete(f"session:{current_user.user_id}")


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Returns the authenticated user's profile."""
    result = await session.run(
        "MATCH (u:User {user_id: $user_id}) RETURN u",
        user_id=current_user.user_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return _node_to_response(dict(record["u"]))
