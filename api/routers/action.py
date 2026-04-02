import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncSession
from pydantic import BaseModel

from db import get_session
from middleware.tenant import get_current_user, require_roles
from models.auth import CurrentUser, Role

router = APIRouter()


# ── request / response schemas ────────────────────────────────────────────────

class ActionExecuteRequest(BaseModel):
    target_node_id: str
    node_label: str
    action_type: str
    case_id: str | None = None
    notes: str | None = None


class ActionExecuteResponse(BaseModel):
    log_id: str
    action_type: str
    target_node_id: str
    executed_by: str
    timestamp: str
    status: str
    case_id: str | None = None


# ── POST /action/execute ──────────────────────────────────────────────────────

@router.post("/execute", response_model=ActionExecuteResponse)
async def execute_action(
    body: ActionExecuteRequest,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> ActionExecuteResponse:
    """
    Execute a kinetic workflow action against a target entity.

    Simulates the real-world API call, then writes an ActionLog node to Neo4j
    linked to both the executing User and the target Entity for a full audit trail.
    """
    # 1. Verify target entity exists and belongs to the caller's tenant
    check = await session.run(
        "MATCH (e:Entity {id: $id, tenant_id: $tid}) RETURN e.id AS id",
        id=body.target_node_id,
        tid=current_user.tenant_id,
    )
    if not await check.single():
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{body.target_node_id}' not found",
        )

    if body.case_id:
        case_check = await session.run(
            "MATCH (c:Case {id: $case_id, tenant_id: $tenant_id}) RETURN c.id AS id",
            case_id=body.case_id,
            tenant_id=current_user.tenant_id,
        )
        if not await case_check.single():
            raise HTTPException(
                status_code=404,
                detail=f"Case '{body.case_id}' not found",
            )

    # 2. Simulate the real-world action (firewall call, SOAR webhook, etc.)
    await asyncio.sleep(0.5)

    # 3. Write ActionLog node + relationships into Neo4j
    timestamp = datetime.now(timezone.utc).isoformat()
    result = await session.run(
        """
        MATCH (u:User {user_id: $user_id})
        MATCH (e:Entity {id: $target_id, tenant_id: $tenant_id})
        CREATE (log:ActionLog {
            id:          randomUUID(),
            action_type: $action_type,
            node_label:  $node_label,
            timestamp:   datetime(),
            tenant_id:   $tenant_id,
            status:      'COMPLETED',
            executed_by: $executed_by,
            notes:       $notes
        })
        CREATE (u)-[:EXECUTED {action: $action_type, timestamp: datetime()}]->(log)
        CREATE (log)-[:TARGETS]->(e)
        WITH log
        OPTIONAL MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | CREATE (log)-[:PART_OF_CASE]->(c))
        RETURN log.id AS log_id
        """,
        user_id=current_user.user_id,
        target_id=body.target_node_id,
        tenant_id=current_user.tenant_id,
        action_type=body.action_type,
        node_label=body.node_label,
        executed_by=current_user.username,
        notes=body.notes,
        case_id=body.case_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(
            status_code=500,
            detail="Action executed but audit log could not be written",
        )

    return ActionExecuteResponse(
        log_id=record["log_id"],
        action_type=body.action_type,
        target_node_id=body.target_node_id,
        executed_by=current_user.username,
        timestamp=timestamp,
        status="COMPLETED",
        case_id=body.case_id,
    )
