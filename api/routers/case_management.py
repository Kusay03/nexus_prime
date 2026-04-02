import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from neo4j import AsyncSession

from db import get_session
from middleware.tenant import get_current_user, require_roles
from models.auth import CurrentUser, Role
from models.workspace import (
    CaseCreate,
    CaseDetailResponse,
    CaseEntityUpdate,
    CaseSummary,
    CaseUpdate,
    RelatedEntity,
    RecentAction,
)

router = APIRouter()


def _pick_label(type_name: str, properties: dict[str, str]) -> str:
    preferred_keys = (
        "Customer Name",
        "Invoice Number",
        "Contract Name",
        "Ticket ID",
        "Owner Name",
        "Document Title",
        "Observation",
        "Hypothesis",
        "Alert Title",
        "Recommendation",
        "Run Label",
        "Template Name",
        "Name",
        "name",
        "Display Name",
        "Username",
        "Hostname",
        "IP Address",
        "Email",
        "Domain",
    )
    for key in preferred_keys:
        value = properties.get(key)
        if value:
            return value
    for value in properties.values():
        if value:
            return value
    return type_name


def _case_summary(record: dict) -> CaseSummary:
    return CaseSummary(
        case_id=record["case_id"],
        title=record["title"],
        priority=record["priority"],
        status=record["status"],
        tenant_id=record["tenant_id"],
        created_by=record["created_by"],
        entity_count=record["entity_count"],
        updated_at=str(record["updated_at"]) if record.get("updated_at") else None,
        created_at=str(record["created_at"]) if record.get("created_at") else None,
    )


async def _get_case_entity_metadata(
    entity_id: str,
    tenant_id: str,
    session: AsyncSession,
) -> tuple[str, str]:
    result = await session.run(
        """
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        WITH
            e,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        WITH e, [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        RETURN e.type_name AS type_name, values
        """,
        entity_id=entity_id,
        tenant_id=tenant_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    properties = {value["name"]: value["value"] for value in record["values"]}
    return record["type_name"], _pick_label(record["type_name"], properties)


async def _write_case_action_log(
    *,
    session: AsyncSession,
    current_user: CurrentUser,
    case_id: str,
    entity_id: str,
    node_label: str,
    action_type: str,
    notes: str,
) -> None:
    result = await session.run(
        """
        MATCH (u:User {user_id: $user_id})
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})
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
        CREATE (log)-[:PART_OF_CASE]->(c)
        RETURN log.id AS log_id
        """,
        user_id=current_user.user_id,
        case_id=case_id,
        entity_id=entity_id,
        tenant_id=current_user.tenant_id,
        action_type=action_type,
        node_label=node_label,
        executed_by=current_user.username,
        notes=notes,
    )
    if not await result.single():
        raise HTTPException(status_code=500, detail="Failed to write case action log")


@router.get("", response_model=list[CaseSummary])
async def list_cases(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 50,
) -> list[CaseSummary]:
    """
    List cases for the current tenant with optional pagination.
    - skip: number of records to skip (default 0)
    - limit: maximum records to return (default 50, max 200)
    """
    capped_limit = min(max(1, limit), 200)
    capped_skip = max(0, skip)

    result = await session.run(
        """
        MATCH (c:Case {tenant_id: $tenant_id})
        OPTIONAL MATCH (c)-[:INVOLVES]->(e:Entity {tenant_id: $tenant_id})
        RETURN
            c.id AS case_id,
            c.title AS title,
            c.priority AS priority,
            c.status AS status,
            c.tenant_id AS tenant_id,
            c.created_by AS created_by,
            c.created_at AS created_at,
            c.updated_at AS updated_at,
            count(DISTINCT e) AS entity_count
        ORDER BY c.updated_at DESC
        SKIP $skip
        LIMIT $limit
        """,
        tenant_id=current_user.tenant_id,
        skip=capped_skip,
        limit=capped_limit,
    )
    return [_case_summary(record) for record in await result.data()]


@router.post("", response_model=CaseDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_case(
    body: CaseCreate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> CaseDetailResponse:
    case_id = str(uuid.uuid4())

    if body.entity_ids:
        check = await session.run(
            """
            MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE e.id IN $entity_ids
            RETURN count(DISTINCT e) AS count
            """,
            tenant_id=current_user.tenant_id,
            entity_ids=body.entity_ids,
        )
        record = await check.single()
        if not record or record["count"] != len(set(body.entity_ids)):
            raise HTTPException(status_code=422, detail="One or more entity_ids are invalid for this tenant")

    await session.run(
        """
        MATCH (u:User {user_id: $user_id})
        CREATE (c:Case {
            id: $case_id,
            title: $title,
            description: $description,
            priority: $priority,
            status: 'open',
            tenant_id: $tenant_id,
            created_by: $created_by,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (u)-[:CREATED_CASE]->(c)
        WITH c
        OPTIONAL MATCH (e:Entity {tenant_id: $tenant_id})
        WHERE e.id IN $entity_ids
        WITH c, collect(DISTINCT e) AS entities
        FOREACH (entity IN entities | CREATE (c)-[:INVOLVES]->(entity))
        """,
        case_id=case_id,
        title=body.title,
        description=body.description,
        priority=body.priority.value,
        tenant_id=current_user.tenant_id,
        created_by=current_user.username,
        user_id=current_user.user_id,
        entity_ids=body.entity_ids,
    )

    return await get_case(case_id, current_user, session)


@router.get("/{case_id}", response_model=CaseDetailResponse)
async def get_case(
    case_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CaseDetailResponse:
    summary_result = await session.run(
        """
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (c)-[:INVOLVES]->(e:Entity {tenant_id: $tenant_id})
        RETURN
            c.id AS case_id,
            c.title AS title,
            c.description AS description,
            c.priority AS priority,
            c.status AS status,
            c.tenant_id AS tenant_id,
            c.created_by AS created_by,
            c.created_at AS created_at,
            c.updated_at AS updated_at,
            count(DISTINCT e) AS entity_count
        """,
        case_id=case_id,
        tenant_id=current_user.tenant_id,
    )
    summary = await summary_result.single()
    if not summary:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")

    entity_result = await session.run(
        """
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})-[:INVOLVES]->(e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        WITH e, collect(
            CASE
                WHEN a IS NULL THEN NULL
                ELSE {
                    name: a.name,
                    value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                }
            END
        ) AS raw_values
        WITH e, [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        RETURN
            e.id AS entity_id,
            e.type_name AS type_name,
            values
        ORDER BY e.type_name, e.id
        """,
        case_id=case_id,
        tenant_id=current_user.tenant_id,
    )
    action_result = await session.run(
        """
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})<-[:PART_OF_CASE]-(log:ActionLog)
        RETURN
            log.id AS log_id,
            log.action_type AS action_type,
            log.status AS status,
            log.timestamp AS timestamp,
            log.executed_by AS executed_by,
            c.id AS case_id
        ORDER BY log.timestamp DESC
        LIMIT 8
        """,
        case_id=case_id,
        tenant_id=current_user.tenant_id,
    )

    entities: list[RelatedEntity] = []
    for row in await entity_result.data():
        properties = {value["name"]: value["value"] for value in row["values"]}
        entities.append(
            RelatedEntity(
                entity_id=row["entity_id"],
                label=_pick_label(row["type_name"], properties),
                type_name=row["type_name"],
                relationship_type="INVOLVES",
                direction="case",
            )
        )

    recent_actions = [
        RecentAction(
            log_id=row["log_id"],
            action_type=row["action_type"],
            status=row["status"],
            timestamp=str(row["timestamp"]) if row["timestamp"] else "",
            executed_by=row["executed_by"],
            case_id=row["case_id"],
        )
        for row in await action_result.data()
    ]

    summary_model = _case_summary(summary)
    return CaseDetailResponse(
        **summary_model.model_dump(),
        description=summary["description"],
        entities=entities,
        recent_actions=recent_actions,
    )


@router.patch("/{case_id}", response_model=CaseDetailResponse)
async def update_case(
    case_id: str,
    body: CaseUpdate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> CaseDetailResponse:
    result = await session.run(
        """
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})
        SET
            c.title = coalesce($title, c.title),
            c.description = coalesce($description, c.description),
            c.priority = coalesce($priority, c.priority),
            c.status = coalesce($status, c.status),
            c.updated_at = datetime()
        RETURN c.id AS case_id
        """,
        case_id=case_id,
        tenant_id=current_user.tenant_id,
        title=body.title,
        description=body.description,
        priority=body.priority.value if body.priority else None,
        status=body.status.value if body.status else None,
    )
    if not await result.single():
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    return await get_case(case_id, current_user, session)


@router.post("/{case_id}/entities", response_model=CaseDetailResponse)
async def add_case_entity(
    case_id: str,
    body: CaseEntityUpdate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> CaseDetailResponse:
    entity_type, entity_label = await _get_case_entity_metadata(
        body.entity_id,
        current_user.tenant_id,
        session,
    )

    result = await session.run(
        """
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (c)-[rel:INVOLVES]->(e)
        WITH c, e, rel IS NULL AS should_link
        FOREACH (_ IN CASE WHEN should_link THEN [1] ELSE [] END |
            CREATE (c)-[:INVOLVES]->(e)
            SET c.updated_at = datetime()
        )
        RETURN c.id AS case_id, should_link AS changed
        """,
        case_id=case_id,
        entity_id=body.entity_id,
        tenant_id=current_user.tenant_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")

    if record["changed"]:
        await _write_case_action_log(
            session=session,
            current_user=current_user,
            case_id=case_id,
            entity_id=body.entity_id,
            node_label=entity_label,
            action_type="case_entity_added",
            notes=f"Added {entity_type} '{entity_label}' to case",
        )

    return await get_case(case_id, current_user, session)


@router.delete("/{case_id}/entities/{entity_id}", response_model=CaseDetailResponse)
async def remove_case_entity(
    case_id: str,
    entity_id: str,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> CaseDetailResponse:
    entity_type, entity_label = await _get_case_entity_metadata(
        entity_id,
        current_user.tenant_id,
        session,
    )

    result = await session.run(
        """
        MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})-[rel:INVOLVES]->(e:Entity {id: $entity_id, tenant_id: $tenant_id})
        DELETE rel
        SET c.updated_at = datetime()
        RETURN c.id AS case_id
        """,
        case_id=case_id,
        entity_id=entity_id,
        tenant_id=current_user.tenant_id,
    )
    if not await result.single():
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity_id}' is not linked to case '{case_id}'",
        )

    await _write_case_action_log(
        session=session,
        current_user=current_user,
        case_id=case_id,
        entity_id=entity_id,
        node_label=entity_label,
        action_type="case_entity_removed",
        notes=f"Removed {entity_type} '{entity_label}' from case",
    )

    return await get_case(case_id, current_user, session)
