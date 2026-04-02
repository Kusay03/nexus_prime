import csv
import io
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from neo4j import AsyncSession
from redis.asyncio import Redis

from db import get_session
from middleware.tenant import require_roles
from models.auth import CurrentUser, Role
from models.ingest import (
    AttributeValue,
    BulkIngestRequest,
    BulkIngestResponse,
    ConnectionCreatedResponse,
    CreateConnectionOp,
    CreateEntityOp,
    CsvIngestResponse,
    DlqEntry,
    DlqKeySummary,
    DlqRetryFailure,
    DlqRetryRequest,
    DlqRetryResponse,
    EntityCreatedResponse,
    WebhookIngestRequest,
    WebhookIngestResponse,
)
from models.ontology import Cardinality, DataType
from redis_client import get_redis

router = APIRouter()


# ── Internal graph helpers ────────────────────────────────────────────────────

BOOLEAN_TRUE_VALUES = {"true", "1", "yes", "y", "on"}
BOOLEAN_FALSE_VALUES = {"false", "0", "no", "n", "off"}

def _attribute_value_storage_field(data_type: DataType) -> str:
    return {
        DataType.STRING: "value_string",
        DataType.NUMBER: "value_numeric",
        DataType.DATE: "value_date",
        DataType.BOOLEAN: "value_boolean",
    }[data_type]


def _attribute_value_payload(value: AttributeValue) -> dict[str, Any]:
    return {
        "name": value.name,
        "value_string": value.value_string,
        "value_numeric": value.value_numeric,
        "value_date": value.value_date,
        "value_boolean": value.value_boolean,
    }


def _attribute_value_to_python(value: AttributeValue) -> tuple[str, Any]:
    if value.value_string is not None:
        return "value_string", value.value_string
    if value.value_numeric is not None:
        return "value_numeric", value.value_numeric
    if value.value_date is not None:
        return "value_date", value.value_date
    if value.value_boolean is not None:
        return "value_boolean", value.value_boolean
    raise HTTPException(status_code=422, detail=f"Attribute '{value.name}' does not include a value")


def _coerce_csv_attribute_value(attribute_name: str, raw_value: str, data_type: DataType) -> AttributeValue:
    normalized = raw_value.strip()
    if data_type == DataType.STRING:
        return AttributeValue(name=attribute_name, value_string=normalized)

    if data_type == DataType.NUMBER:
        try:
            return AttributeValue(name=attribute_name, value_numeric=float(normalized))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Attribute '{attribute_name}' expects NUMBER, got '{raw_value}'",
            ) from exc

    if data_type == DataType.DATE:
        try:
            parsed_date = date.fromisoformat(normalized)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Attribute '{attribute_name}' expects DATE in YYYY-MM-DD format, got '{raw_value}'",
            ) from exc
        return AttributeValue(name=attribute_name, value_date=parsed_date.isoformat())

    lowered = normalized.lower()
    if lowered in BOOLEAN_TRUE_VALUES:
        return AttributeValue(name=attribute_name, value_boolean=True)
    if lowered in BOOLEAN_FALSE_VALUES:
        return AttributeValue(name=attribute_name, value_boolean=False)
    raise HTTPException(
        status_code=422,
        detail=f"Attribute '{attribute_name}' expects BOOLEAN, got '{raw_value}'",
    )


async def _get_entity_type_attribute_schema(
    type_name: str,
    tenant_id: str,
    runner: Any,
) -> dict[str, dict[str, Any]] | None:
    result = await runner.run(
        """
        MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
        OPTIONAL MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute)
        RETURN et.name AS entity_type_name, collect({
            name: a.name,
            data_type: a.data_type,
            required: a.required,
            cardinality: a.cardinality
        }) AS attributes
        """,
        type_name=type_name,
        tenant_id=tenant_id,
    )
    record = await result.single()
    if not record or record["entity_type_name"] is None:
        return None

    schema: dict[str, dict[str, Any]] = {}
    for attribute in record["attributes"]:
        if not attribute["name"]:
            continue
        schema[attribute["name"]] = {
            "data_type": DataType(attribute["data_type"]),
            "required": bool(attribute["required"]),
            "cardinality": Cardinality(attribute["cardinality"]),
        }
    return schema


def _build_dlq_entry(
    row_index: int,
    raw_row: dict[str, str],
    error: str,
    type_name: str | None = None,
    column_map: dict[str, str] | None = None,
) -> DlqEntry:
    return DlqEntry(
        row_index=row_index,
        raw_row=raw_row,
        error=error,
        timestamp=datetime.now(timezone.utc).isoformat(),
        type_name=type_name,
        column_map=column_map,
    )


def _normalize_csv_row(row: dict[str | None, str | list[str] | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if not key:
            continue
        if isinstance(value, list):
            normalized[key] = ", ".join(item.strip() for item in value if item)
        else:
            normalized[key] = value.strip() if value else ""
    return normalized


def _parse_column_map(column_map: str) -> dict[str, str]:
    try:
        parsed = json.loads(column_map)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"column_map is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict) or not parsed:
        raise HTTPException(status_code=422, detail="column_map must be a non-empty JSON object")

    normalized: dict[str, str] = {}
    for csv_column, attribute_name in parsed.items():
        if not isinstance(csv_column, str) or not csv_column.strip():
            raise HTTPException(status_code=422, detail="column_map keys must be non-empty strings")
        if not isinstance(attribute_name, str) or not attribute_name.strip():
            raise HTTPException(status_code=422, detail="column_map values must be non-empty strings")
        normalized[csv_column.strip()] = attribute_name.strip()

    return normalized


def _mapped_csv_values(raw_row: dict[str, str], column_map: dict[str, str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for csv_column, attribute_name in column_map.items():
        raw_value = raw_row.get(csv_column, "").strip()
        if raw_value:
            values.append((attribute_name, raw_value))

    if not values:
        raise ValueError("No valid attribute values after column_map — row may be empty")

    return values


def _build_csv_entity_op(
    row_index: int,
    raw_row: dict[str, str],
    type_name: str,
    column_map: dict[str, str],
    attribute_schema: dict[str, dict[str, Any]],
) -> CreateEntityOp:
    mapped_values = _mapped_csv_values(raw_row, column_map)
    return CreateEntityOp(
        op="create_entity",
        alias=f"csv_row_{row_index}",
        type_name=type_name,
        values=[
            _coerce_csv_attribute_value(
                attribute_name,
                raw_value,
                attribute_schema[attribute_name]["data_type"],
            )
            for attribute_name, raw_value in mapped_values
        ],
    )


def _validate_dlq_key(key: str, tenant_id: str) -> None:
    if not key.startswith(f"dlq:{tenant_id}:csv:"):
        raise HTTPException(status_code=404, detail="DLQ key not found")


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        return detail if isinstance(detail, str) else str(detail)
    return str(exc)


async def _create_entity(
    op: CreateEntityOp,
    tenant_id: str,
    runner: Any,
    attribute_schema: dict[str, dict[str, Any]] | None = None,
) -> EntityCreatedResponse:
    if attribute_schema is None:
        attribute_schema = await _get_entity_type_attribute_schema(op.type_name, tenant_id, runner)

    if attribute_schema is None:
        raise HTTPException(
            status_code=422,
            detail=f"EntityType '{op.type_name}' not found in ontology for tenant '{tenant_id}'",
        )

    unknown_attributes = sorted({value.name for value in op.values} - set(attribute_schema))
    if unknown_attributes:
        missing_attrs_text = ", ".join(unknown_attributes)
        raise HTTPException(
            status_code=422,
            detail=f"Attributes not defined on EntityType '{op.type_name}': {missing_attrs_text}",
        )

    values_by_attribute: dict[str, list[AttributeValue]] = {}
    for value in op.values:
        values_by_attribute.setdefault(value.name, []).append(value)

    required_attributes = sorted(
        attribute_name
        for attribute_name, schema in attribute_schema.items()
        if schema["required"] and attribute_name not in values_by_attribute
    )
    if required_attributes:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Missing required attributes for EntityType '{op.type_name}': "
                f"{', '.join(required_attributes)}"
            ),
        )

    for attribute_name, attribute_values in values_by_attribute.items():
        schema = attribute_schema[attribute_name]
        if schema["cardinality"] == Cardinality.SINGLE and len(attribute_values) > 1:
            raise HTTPException(
                status_code=422,
                detail=f"Attribute '{attribute_name}' on EntityType '{op.type_name}' allows only a single value",
            )

        expected_field = _attribute_value_storage_field(schema["data_type"])
        for attribute_value in attribute_values:
            actual_field, actual_value = _attribute_value_to_python(attribute_value)
            if actual_field != expected_field:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Attribute '{attribute_name}' on EntityType '{op.type_name}' expects "
                        f"{schema['data_type'].value}, got {actual_field.replace('value_', '').upper()}"
                    ),
                )
            if schema["data_type"] == DataType.DATE:
                try:
                    date.fromisoformat(actual_value)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Attribute '{attribute_name}' on EntityType '{op.type_name}' expects "
                            "DATE in YYYY-MM-DD format"
                        ),
                    ) from exc

    entity_id = str(uuid.uuid4())

    result = await runner.run(
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
        values = [_attribute_value_payload(value) for value in op.values]
        values_result = await runner.run(
            """
            MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})-[:INSTANCE_OF]->(et:EntityType {tenant_id: $tenant_id})
            UNWIND $values AS val
            MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: val.name, tenant_id: $tenant_id})
            CREATE (e)-[hv:HAS_VALUE]->(a)
            SET
                hv.value_string  = val.value_string,
                hv.value_numeric = val.value_numeric,
                hv.value_date    = val.value_date,
                hv.value_boolean = val.value_boolean
            RETURN collect(a.name) AS attributes_set
            """,
            entity_id=entity_id,
            tenant_id=tenant_id,
            values=values,
        )
        values_record = await values_result.single()
        if values_record:
            attrs_set = values_record["attributes_set"]

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
    runner: Any,
) -> ConnectionCreatedResponse:
    source_id = entity_map.get(op.source_alias)
    target_id = entity_map.get(op.target_alias)

    if not source_id:
        raise HTTPException(status_code=422, detail=f"Alias '{op.source_alias}' not found in this batch")
    if not target_id:
        raise HTTPException(status_code=422, detail=f"Alias '{op.target_alias}' not found in this batch")

    validation_result = await runner.run(
        """
        MATCH (src:Entity {id: $source_id, tenant_id: $tenant_id})-[:INSTANCE_OF]->(src_type:EntityType {tenant_id: $tenant_id})
        MATCH (tgt:Entity {id: $target_id, tenant_id: $tenant_id})-[:INSTANCE_OF]->(tgt_type:EntityType {tenant_id: $tenant_id})
        OPTIONAL MATCH (rt:RelationshipType {name: $rel_type, tenant_id: $tenant_id})
        RETURN
            src.id AS source_id,
            tgt.id AS target_id,
            src_type.name AS actual_source_type,
            tgt_type.name AS actual_target_type,
            rt.source_type AS expected_source_type,
            rt.target_type AS expected_target_type
        """,
        source_id=source_id,
        target_id=target_id,
        rel_type=op.relationship_type,
        tenant_id=tenant_id,
    )
    record = await validation_result.single()
    if not record:
        raise HTTPException(
            status_code=422,
            detail="Could not create connection — verify entity IDs exist for this tenant",
        )

    if record["expected_source_type"] is None or record["expected_target_type"] is None:
        raise HTTPException(
            status_code=422,
            detail=f"RelationshipType '{op.relationship_type}' is not defined in the ontology",
        )

    if (
        record["actual_source_type"] != record["expected_source_type"]
        or record["actual_target_type"] != record["expected_target_type"]
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"RelationshipType '{op.relationship_type}' expects "
                f"{record['expected_source_type']} -> {record['expected_target_type']}, got "
                f"{record['actual_source_type']} -> {record['actual_target_type']}"
            ),
        )

    result = await runner.run(
        """
        MATCH (src:Entity {id: $source_id, tenant_id: $tenant_id})
        MATCH (tgt:Entity {id: $target_id, tenant_id: $tenant_id})
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
        raise HTTPException(status_code=500, detail="Failed to create connection")

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
    attribute_schema: dict[str, dict[str, Any]] | None = None,
) -> tuple[EntityCreatedResponse | None, str | None]:
    try:
        async with session.begin_transaction() as tx:
            result = await _create_entity(op, tenant_id, tx, attribute_schema=attribute_schema)
            await tx.commit()
        return result, None
    except HTTPException as exc:
        return None, exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    except Exception as exc:
        return None, str(exc)


async def _execute_operations(
    operations: list[CreateEntityOp | CreateConnectionOp],
    tenant_id: str,
    runner: Any,
) -> tuple[dict[str, str], list[EntityCreatedResponse], list[ConnectionCreatedResponse]]:
    entity_map: dict[str, str] = {}
    entities: list[EntityCreatedResponse] = []
    connections: list[ConnectionCreatedResponse] = []

    for op in operations:
        if isinstance(op, CreateEntityOp):
            if op.alias in entity_map:
                raise HTTPException(status_code=422, detail=f"Alias '{op.alias}' is duplicated in this batch")
            result = await _create_entity(op, tenant_id, runner)
            entity_map[op.alias] = result.entity_id
            entities.append(result)
        elif isinstance(op, CreateConnectionOp):
            result = await _create_connection(op, entity_map, tenant_id, runner)
            connections.append(result)

    return entity_map, entities, connections


async def _execute_operations_transactional(
    operations: list[CreateEntityOp | CreateConnectionOp],
    tenant_id: str,
    session: AsyncSession,
) -> tuple[dict[str, str], list[EntityCreatedResponse], list[ConnectionCreatedResponse]]:
    async with session.begin_transaction() as tx:
        entity_map, entities, connections = await _execute_operations(operations, tenant_id, tx)
        await tx.commit()
        return entity_map, entities, connections


def _dlq_created_at(key: str) -> str | None:
    raw_timestamp = key.rsplit(":", 1)[-1]
    try:
        return datetime.strptime(raw_timestamp, "%Y%m%dT%H%M%S").replace(
            tzinfo=timezone.utc
        ).isoformat()
    except ValueError:
        return None


# ── POST /json ─────────────────────────────────────────────────────────────────

@router.post("/json", response_model=BulkIngestResponse, status_code=201)
async def ingest_json(
    body: BulkIngestRequest,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> BulkIngestResponse:
    tenant_id = current_user.tenant_id
    entity_map, entities, connections = await _execute_operations_transactional(
        body.operations,
        tenant_id,
        session,
    )

    return BulkIngestResponse(
        entities_created=len(entities),
        connections_created=len(connections),
        entity_map=entity_map,
        entities=entities,
        connections=connections,
    )


# ── POST /webhook ──────────────────────────────────────────────────────────────

@router.post("/webhook", response_model=WebhookIngestResponse, status_code=201)
async def ingest_webhook(
    body: WebhookIngestRequest,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> WebhookIngestResponse:
    tenant_id = current_user.tenant_id
    entity_map, entities, connections = await _execute_operations_transactional(
        body.operations,
        tenant_id,
        session,
    )

    return WebhookIngestResponse(
        source=body.source,
        event_type=body.event_type,
        event_id=body.event_id or f"evt_{uuid.uuid4().hex}",
        received_at=datetime.now(timezone.utc).isoformat(),
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
    col_map = _parse_column_map(column_map)

    dlq_key = f"dlq:{tenant_id}:csv:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    content = await file.read()
    try:
        decoded_content = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV file must be valid UTF-8") from exc

    reader = csv.DictReader(io.StringIO(decoded_content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=422, detail="CSV file must include a header row")

    parsed_rows: dict[int, dict[str, str]] = {}
    dlq_entries: list[DlqEntry] = []

    for row_index, row in enumerate(reader):
        raw_row = _normalize_csv_row(row)
        try:
            _mapped_csv_values(raw_row, col_map)
            parsed_rows[row_index] = raw_row
        except Exception as exc:
            dlq_entries.append(
                _build_dlq_entry(
                    row_index=row_index,
                    raw_row=raw_row,
                    error=str(exc),
                    type_name=type_name,
                    column_map=col_map,
                )
            )

    total_rows = len(parsed_rows) + len(dlq_entries)
    entity_ids: list[str] = []
    failed = len(dlq_entries)

    attribute_schema = await _get_entity_type_attribute_schema(type_name, tenant_id, session)
    if attribute_schema is None:
        schema_error = f"EntityType '{type_name}' not found in ontology for tenant '{tenant_id}'"
    else:
        missing_attributes = sorted(set(col_map.values()) - set(attribute_schema))
        schema_error = (
            f"Attributes not defined on EntityType '{type_name}': {', '.join(missing_attributes)}"
            if missing_attributes
            else None
        )

    if schema_error:
        for row_index, raw_row in parsed_rows.items():
            dlq_entries.append(
                _build_dlq_entry(
                    row_index=row_index,
                    raw_row=raw_row,
                    error=schema_error,
                    type_name=type_name,
                    column_map=col_map,
                )
            )
        failed = len(dlq_entries)
    else:
        for row_index, raw_row in sorted(parsed_rows.items()):
            try:
                row_result, row_error = await _try_create_entity(
                    _build_csv_entity_op(row_index, raw_row, type_name, col_map, attribute_schema),
                    tenant_id,
                    session,
                    attribute_schema=attribute_schema,
                )
                if row_result:
                    entity_ids.append(row_result.entity_id)
                else:
                    failed += 1
                    dlq_entries.append(
                        _build_dlq_entry(
                            row_index=row_index,
                            raw_row=raw_row,
                            error=row_error or "CSV row failed to ingest",
                            type_name=type_name,
                            column_map=col_map,
                        )
                    )
            except Exception as exc:
                failed += 1
                dlq_entries.append(
                    _build_dlq_entry(
                        row_index=row_index,
                        raw_row=raw_row,
                        error=_error_detail(exc),
                        type_name=type_name,
                        column_map=col_map,
                    )
                )

    if dlq_entries:
        await redis.rpush(dlq_key, *[json.dumps(entry.model_dump()) for entry in dlq_entries])

    return CsvIngestResponse(
        total_rows=total_rows,
        ingested=len(entity_ids),
        failed=failed,
        dlq_key=dlq_key,
        entity_ids=entity_ids,
    )


# ── GET /dlq ───────────────────────────────────────────────────────────────────

@router.get("/dlq/keys", response_model=list[DlqKeySummary])
async def list_dlq_keys(
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    redis: Redis = Depends(get_redis),
    limit: int = 10,
) -> list[DlqKeySummary]:
    capped_limit = min(max(limit, 1), 50)
    keys: list[str] = []
    async for key in redis.scan_iter(match=f"dlq:{current_user.tenant_id}:csv:*"):
        keys.append(key)

    summaries: list[DlqKeySummary] = []
    for key in sorted(keys, reverse=True)[:capped_limit]:
        summaries.append(
            DlqKeySummary(
                key=key,
                item_count=await redis.llen(key),
                created_at=_dlq_created_at(key),
            )
        )
    return summaries


@router.get("/dlq")
async def get_dlq(
    key: str,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    redis: Redis = Depends(get_redis),
) -> dict:
    _validate_dlq_key(key, current_user.tenant_id)
    items = await redis.lrange(key, 0, -1)
    return {
        "key": key,
        "count": len(items),
        "items": [json.loads(item) for item in items],
    }


@router.post("/dlq/retry", response_model=DlqRetryResponse)
async def retry_dlq(
    body: DlqRetryRequest,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> DlqRetryResponse:
    tenant_id = current_user.tenant_id
    _validate_dlq_key(body.key, tenant_id)

    raw_items = await redis.lrange(body.key, 0, -1)
    if not raw_items:
        raise HTTPException(status_code=404, detail="DLQ key not found or empty")

    entries = [DlqEntry.model_validate(json.loads(item)) for item in raw_items]
    selected_row_indices = set(body.row_indices) if body.row_indices else None

    selected_entries: list[DlqEntry] = []
    remaining_entries: list[DlqEntry] = []
    for entry in entries:
        if selected_row_indices is None or entry.row_index in selected_row_indices:
            selected_entries.append(entry)
        else:
            remaining_entries.append(entry)

    if not selected_entries:
        raise HTTPException(status_code=404, detail="No DLQ rows matched the retry request")

    recovered = 0
    failed: list[DlqRetryFailure] = []
    attribute_schema_cache: dict[str, dict[str, dict[str, Any]] | None] = {}

    for entry in selected_entries:
        retry_error: str
        if not entry.type_name or not entry.column_map:
            retry_error = "DLQ entry does not include retry metadata"
        else:
            if entry.type_name not in attribute_schema_cache:
                attribute_schema_cache[entry.type_name] = await _get_entity_type_attribute_schema(
                    entry.type_name,
                    tenant_id,
                    session,
                )

            try:
                schema = attribute_schema_cache[entry.type_name]
                if schema is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"EntityType '{entry.type_name}' not found in ontology for tenant '{tenant_id}'",
                    )
                missing_attributes = sorted(set(entry.column_map.values()) - set(schema))
                if missing_attributes:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Attributes not defined on EntityType '{entry.type_name}': "
                            f"{', '.join(missing_attributes)}"
                        ),
                    )
                retry_result, retry_error = await _try_create_entity(
                    _build_csv_entity_op(
                        entry.row_index,
                        entry.raw_row,
                        entry.type_name,
                        entry.column_map,
                        schema,
                    ),
                    tenant_id,
                    session,
                    attribute_schema=schema,
                )
                if retry_result:
                    recovered += 1
                    continue
                retry_error = retry_error or "Retry failed"
            except Exception as exc:
                retry_error = _error_detail(exc)

        failed.append(DlqRetryFailure(row_index=entry.row_index, error=retry_error))
        remaining_entries.append(
            _build_dlq_entry(
                row_index=entry.row_index,
                raw_row=entry.raw_row,
                error=retry_error,
                type_name=entry.type_name,
                column_map=entry.column_map,
            )
        )

    await redis.delete(body.key)
    if remaining_entries:
        await redis.rpush(body.key, *[json.dumps(entry.model_dump()) for entry in remaining_entries])

    return DlqRetryResponse(
        key=body.key,
        requested=len(selected_entries),
        recovered=recovered,
        remaining=len(remaining_entries),
        failed=failed,
    )
