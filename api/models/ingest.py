from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class AttributeValue(BaseModel):
    name: str = Field(..., min_length=1)
    value_string: Optional[str] = None
    value_numeric: Optional[float] = None
    value_date: Optional[str] = None  # ISO format: "YYYY-MM-DD"

    @model_validator(mode="after")
    def at_least_one_value(self) -> "AttributeValue":
        if self.value_string is None and self.value_numeric is None and self.value_date is None:
            raise ValueError("At least one of value_string, value_numeric, or value_date must be set")
        return self


# ── Operations (discriminated union on "op") ──────────────────────────────────

class CreateEntityOp(BaseModel):
    op: Literal["create_entity"]
    alias: str = Field(..., description="Client-side label — used to reference this entity in connection ops")
    type_name: str
    values: list[AttributeValue] = []


class CreateConnectionOp(BaseModel):
    op: Literal["create_connection"]
    source_alias: str
    target_alias: str
    relationship_type: str
    metadata: dict[str, str] = {}


Operation = Annotated[
    Union[CreateEntityOp, CreateConnectionOp],
    Field(discriminator="op"),
]


class BulkIngestRequest(BaseModel):
    operations: list[Operation] = Field(..., min_length=1)


# ── Responses ─────────────────────────────────────────────────────────────────

class EntityCreatedResponse(BaseModel):
    alias: str
    entity_id: str
    type_name: str
    tenant_id: str
    attributes_set: list[str]


class ConnectionCreatedResponse(BaseModel):
    source_alias: str
    source_entity_id: str
    target_alias: str
    target_entity_id: str
    relationship_type: str
    tenant_id: str


class BulkIngestResponse(BaseModel):
    entities_created: int
    connections_created: int
    entity_map: dict[str, str]  # alias → entity_id
    entities: list[EntityCreatedResponse]
    connections: list[ConnectionCreatedResponse]


# ── CSV ingest ────────────────────────────────────────────────────────────────

class DlqEntry(BaseModel):
    row_index: int
    raw_row: dict[str, str]
    error: str
    timestamp: str


class CsvIngestResponse(BaseModel):
    total_rows: int
    ingested: int
    failed: int
    dlq_key: str        # Redis list key — inspect with GET /ingest/dlq?key=...
    entity_ids: list[str]
