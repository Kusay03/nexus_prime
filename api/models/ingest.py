from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class AttributeValue(BaseModel):
    name: str = Field(..., min_length=1)
    value_string: Optional[str] = None
    value_numeric: Optional[float] = None
    value_date: Optional[str] = None  # ISO format: "YYYY-MM-DD"
    value_boolean: Optional[bool] = None

    @model_validator(mode="after")
    def at_least_one_value(self) -> "AttributeValue":
        provided_fields = [
            self.value_string is not None,
            self.value_numeric is not None,
            self.value_date is not None,
            self.value_boolean is not None,
        ]
        if sum(provided_fields) == 0:
            raise ValueError(
                "At least one of value_string, value_numeric, value_date, or value_boolean must be set"
            )
        if sum(provided_fields) > 1:
            raise ValueError(
                "Only one of value_string, value_numeric, value_date, or value_boolean may be set"
            )
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


class WebhookIngestRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=80)
    event_type: str = Field(..., min_length=1, max_length=120)
    event_id: Optional[str] = Field(default=None, max_length=120)
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


class WebhookIngestResponse(BulkIngestResponse):
    source: str
    event_type: str
    event_id: str
    received_at: str


# ── CSV ingest ────────────────────────────────────────────────────────────────

class DlqEntry(BaseModel):
    row_index: int
    raw_row: dict[str, str]
    error: str
    timestamp: str
    type_name: str | None = None
    column_map: dict[str, str] | None = None


class DlqKeySummary(BaseModel):
    key: str
    item_count: int
    created_at: str | None = None


class CsvIngestResponse(BaseModel):
    total_rows: int
    ingested: int
    failed: int
    dlq_key: str        # Redis list key — inspect with GET /ingest/dlq?key=...
    entity_ids: list[str]


class DlqRetryRequest(BaseModel):
    key: str = Field(..., min_length=1)
    row_indices: list[int] = Field(default_factory=list, max_length=200)


class DlqRetryFailure(BaseModel):
    row_index: int
    error: str


class DlqRetryResponse(BaseModel):
    key: str
    requested: int
    recovered: int
    remaining: int
    failed: list[DlqRetryFailure] = []
