from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DataType(str, Enum):
    STRING = "STRING"
    NUMBER = "NUMBER"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"


class Cardinality(str, Enum):
    SINGLE = "SINGLE"
    MANY = "MANY"


# ── Attribute ─────────────────────────────────────────────────────────────────

class AttributeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    data_type: DataType
    required: bool = False
    cardinality: Cardinality = Cardinality.SINGLE


class AttributeUpdate(BaseModel):
    data_type: Optional[DataType] = None
    required: Optional[bool] = None
    cardinality: Optional[Cardinality] = None


class AttributeResponse(BaseModel):
    name: str
    data_type: DataType
    required: bool
    cardinality: Cardinality
    entity_type_name: str
    tenant_id: str


# ── EntityType ────────────────────────────────────────────────────────────────

class EntityTypeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None


class EntityTypeUpdate(BaseModel):
    description: Optional[str] = None


class EntityTypeResponse(BaseModel):
    name: str
    description: Optional[str]
    tenant_id: str
    created_at: Optional[str] = None


class EntityTypeDetail(EntityTypeResponse):
    attributes: list[AttributeResponse] = []


# ── RelationshipType ──────────────────────────────────────────────────────────

class RelationshipTypeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    source_type: str
    target_type: str


class RelationshipTypeUpdate(BaseModel):
    source_type: Optional[str] = None
    target_type: Optional[str] = None


class RelationshipTypeResponse(BaseModel):
    name: str
    source_type: str
    target_type: str
    tenant_id: str
    created_at: Optional[str] = None
