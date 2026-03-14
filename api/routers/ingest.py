import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from neo4j import AsyncSession
from redis.asyncio import Redis

from db import get_session
from middleware.tenant import get_current_user, require_roles
from models.auth import CurrentUser, Role
from models.ingest import (
    AttributeValue,
    BulkIngestRequest,
    BulkIngestResponse,
    ConnectionCreatedResponse,
    CreateConnectionOp,
    CreateEntityOp,
    CsvIngestResponse,
    EntityCreatedResponse,
)
from redis_client import get_redis

router = APIRouter()


# ── Internal graph helpers ────────────────────────────────────────────────────

async def _create_entity(
    op: CreateEntityOp,
    tenant_id: str,
    session: AsyncSession,
) -> EntityCreatedResponse:
    entity_id = str(uuid.uuid4())

    result = await session.run(
        """
        MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
        CREATE (e:Entity {
            id:         $entity_id,
            tenant_id:  $tenant_id,
            type_name:  $type_name,
            created_at: datetime()
        })
        CREATE (e)-[:INSTANCE_OF]->(et)
        RETURN e.id AS entity_id
        """,
        type_name=op.type_name,
        tenant_id=tenant_id,
        entity_id=entity_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(
            status_code=422,
            detail=f"EntityType '{op.type_name}' not found in ontology for tenant '{tenant_id}'",
        )

    attrs_set: list[str] = []
    if op.values:
        values = [
            {
                "name": v.name,
                "value_string": v.value_string,
                "value_numeric": v.value_numeric,
                "value_date": v.value_date,
            }
            for v in op.values
        ]
        r2 = await session.run(
            """
            MATCH (e:Entity {id: $entity_id})-[:INSTANCE_OF]->(et:EntityType)
            UNWIND $values AS val
            MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: val.name})
            CREATE (e)-[hv:HAS_VALUE]->(a)
            SET
                hv.value_string  = val.value_string,
                hv.value_numeric = val.value_numeric,
                hv.value_date    = val.value_date
            RETURN collect(a.name) AS attributes_set
            """,
            entity_id=entity_id,
            values=values,
        )
        r2_record = await r2.single()
        if r2_record:
            attrs_set = r2_record["attributes_set"]

    return EntityCreatedResponse(
        alias=op.alias,
        entity_id=entity_id,
        type_name=op.type_name,
        tenant_id=tenant_id,
        attributes_set=attrs_set,
    )


async def _create_connection(
    op: CreateConnectionOp,
    entity_map: dict[str, str],
    tenant_id: str,
    session: AsyncSession,
) -> ConnectionCreatedResponse:
    source_id = entity_map.get(op.source_alias)
    target_id = entity_map.get(op.target_alias)

    if not source_id:
        raise HTTPException(status_code=422, detail=f"Alias '{op.source_alias}' not found in this batch")
    if not target_id:
        raise HTTPException(status_code=422, detail=f"Alias '{op.target_alias}' not found in this batch")

    result = await session.run(
        """
        MATCH (src:Entity {id: $source_id, tenant_id: $tenant_id})
        MATCH (tgt:Entity {id: $target_id, tenant_id: $tenant_id})
        MATCH (rt:RelationshipType {name: $rel_type, tenant_id: $tenant_id})
        CREATE (src)-[r:CONNECTED_TO {
            relationship_type: $rel_type,
            tenant_id:         $tenant_id,
            created_at:        datetime()
        }]->(tgt)
        RETURN src.id AS source_id, tgt.id AS target_id
        """,
        source_id=source_id,
        target_id=target_id,
        rel_type=op.relationship_type,
        tenant_id=tenant_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not create connection — verify entity IDs exist and "
                f"RelationshipType '{op.relationship_type}' is defined in the ontology"
            ),
        )

    return ConnectionCreatedResponse(
        source_alias=op.source_alias,
        source_entity_id=record["source_id"],
        target_alias=op.target_alias,
        target_entity_id=record["target_id"],
        relationship_type=op.relationship_type,
        tenant_id=tenant_id,
    )


async def _try_create_entity(
    op: CreateEntityOp,
    tenant_id: str,
    session: AsyncSession,
) -> tuple[EntityCreatedResponse | None, str | None]:
    """Used by CSV ingestion — returns (result, error) instead of raising."""
    try:
        result = await _create_entity(op, tenant_id, session)
        return result, None
    except HTTPException as exc:
        return None, exc.detail
    except Exception as exc:
        return None, str(exc)


# ── POST /json ─────────────────────────────────────────────────────────────────

@router.post("/json", response_model=BulkIngestResponse, status_code=201)
async def ingest_json(
    body: BulkIngestRequest,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> BulkIngestResponse:
    """
    Bulk ingestion via JSON. Operations run in order — create_entity ops
    must appear before any create_connection that references their alias.
    """
    tenant_id = current_user.tenant_id
    entity_map: dict[str, str] = {}
    entities: list[EntityCreatedResponse] = []
    connections: list[ConnectionCreatedResponse] = []

    for op in body.operations:
        if isinstance(op, CreateEntityOp):
            result = await _create_entity(op, tenant_id, session)
            entity_map[op.alias] = result.entity_id
            entities.append(result)
        elif isinstance(op, CreateConnectionOp):
            result = await _create_connection(op, entity_map, tenant_id, session)
            connections.append(result)

    return BulkIngestResponse(
        entities_created=len(entities),
        connections_created=len(connections),
        entity_map=entity_map,
        entities=entities,
        connections=connections,
    )


# ── POST /csv ──────────────────────────────────────────────────────────────────

@router.post("/csv", response_model=CsvIngestResponse, status_code=201)
async def ingest_csv(
    file: UploadFile = File(..., description="UTF-8 CSV file"),
    type_name: str = Form(..., description="EntityType for every row in this file"),
    column_map: str = Form(
        ...,
        description='JSON mapping CSV column → Ontology attribute. e.g. {"csv_col": "Username"}',
    ),
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> CsvIngestResponse:
    tenant_id = current_user.tenant_id

    try:
        col_map: dict[str, str] = json.loads(column_map)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"column_map is not valid JSON: {exc}")

    dlq_key = f"dlq:{tenant_id}:csv:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))

    entity_ids: list[str] = []
    failed = 0
    total_rows = 0

    for row_index, row in enumerate(reader):
        total_rows += 1
        try:
            values: list[AttributeValue] = []
            for csv_col, attr_name in col_map.items():
                raw = row.get(csv_col, "").strip()
                if not raw:
                    continue
                try:
                    values.append(AttributeValue(name=attr_name, value_numeric=float(raw)))
                except ValueError:
                    values.append(AttributeValue(name=attr_name, value_string=raw))

            if not values:
                raise ValueError("No valid attribute values after column_map — row may be empty")

            op = CreateEntityOp(
                op="create_entity",
                alias=f"row_{row_index}",
                type_name=type_name,
                values=values,
            )
            result, error = await _try_create_entity(op, tenant_id, session)
            if error:
                raise ValueError(error)

            entity_ids.append(result.entity_id)  # type: ignore[union-attr]

        except Exception as exc:
            failed += 1
            await redis.rpush(
                dlq_key,
                json.dumps({
                    "row_index": row_index,
                    "raw_row": dict(row),
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
            )

    return CsvIngestResponse(
        total_rows=total_rows,
        ingested=len(entity_ids),
        failed=failed,
        dlq_key=dlq_key,
        entity_ids=entity_ids,
    )


# ── GET /dlq ───────────────────────────────────────────────────────────────────

@router.get("/dlq")
async def get_dlq(
    key: str,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Inspect all failed rows stored in the Dead-Letter Queue for a given key. Admin only."""
    items = await redis.lrange(key, 0, -1)
    return {
        "key": key,
        "count": len(items),
        "items": [json.loads(i) for i in items],
    }
