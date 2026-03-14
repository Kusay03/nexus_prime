from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncSession

from db import get_session
from middleware.tenant import get_current_user, require_roles
from models.auth import CurrentUser, Role
from models.ontology import (
    AttributeCreate,
    AttributeResponse,
    AttributeUpdate,
    EntityTypeCreate,
    EntityTypeDetail,
    EntityTypeResponse,
    EntityTypeUpdate,
    RelationshipTypeCreate,
    RelationshipTypeResponse,
    RelationshipTypeUpdate,
)

router = APIRouter()


# ── Mapping helpers ───────────────────────────────────────────────────────────

def _map_et(node: dict, tenant_id: str) -> EntityTypeResponse:
    return EntityTypeResponse(
        name=node["name"],
        description=node.get("description"),
        tenant_id=node["tenant_id"],
        created_at=str(node["created_at"]) if node.get("created_at") else None,
    )


def _map_attr(node: dict, type_name: str, tenant_id: str) -> AttributeResponse:
    return AttributeResponse(
        name=node["name"],
        data_type=node["data_type"],
        required=node["required"],
        cardinality=node["cardinality"],
        entity_type_name=type_name,
        tenant_id=tenant_id,
    )


def _map_rt(node: dict) -> RelationshipTypeResponse:
    return RelationshipTypeResponse(
        name=node["name"],
        source_type=node["source_type"],
        target_type=node["target_type"],
        tenant_id=node["tenant_id"],
        created_at=str(node["created_at"]) if node.get("created_at") else None,
    )


# ── EntityType ────────────────────────────────────────────────────────────────

@router.post("/entity-types", response_model=EntityTypeResponse, status_code=201)
async def create_entity_type(
    body: EntityTypeCreate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> EntityTypeResponse:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MERGE (et:EntityType {name: $name, tenant_id: $tenant_id})
        ON CREATE SET et.description = $description, et.created_at = datetime()
        RETURN et
        """,
        name=body.name,
        tenant_id=tenant_id,
        description=body.description,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create EntityType")
    return _map_et(dict(record["et"]), tenant_id)


@router.get("/entity-types", response_model=list[EntityTypeResponse])
async def list_entity_types(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EntityTypeResponse]:
    tenant_id = current_user.tenant_id
    result = await session.run(
        "MATCH (et:EntityType {tenant_id: $tenant_id}) RETURN et ORDER BY et.name",
        tenant_id=tenant_id,
    )
    records = await result.data()
    return [_map_et(dict(r["et"]), tenant_id) for r in records]


@router.get("/entity-types/{name}", response_model=EntityTypeDetail)
async def get_entity_type(
    name: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EntityTypeDetail:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (et:EntityType {name: $name, tenant_id: $tenant_id})
        OPTIONAL MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute)
        RETURN et, collect(a) AS attributes
        """,
        name=name,
        tenant_id=tenant_id,
    )
    record = await result.single()
    if not record or not record["et"]:
        raise HTTPException(status_code=404, detail=f"EntityType '{name}' not found")
    et = dict(record["et"])
    attrs = [_map_attr(dict(a), name, tenant_id) for a in record["attributes"] if a]
    return EntityTypeDetail(**_map_et(et, tenant_id).model_dump(), attributes=attrs)


@router.patch("/entity-types/{name}", response_model=EntityTypeResponse)
async def update_entity_type(
    name: str,
    body: EntityTypeUpdate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> EntityTypeResponse:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (et:EntityType {name: $name, tenant_id: $tenant_id})
        SET et.description = coalesce($description, et.description)
        RETURN et
        """,
        name=name,
        tenant_id=tenant_id,
        description=body.description,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"EntityType '{name}' not found")
    return _map_et(dict(record["et"]), tenant_id)


@router.delete("/entity-types/{name}", status_code=204)
async def delete_entity_type(
    name: str,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (et:EntityType {name: $name, tenant_id: $tenant_id})
        DETACH DELETE et
        RETURN true AS deleted
        """,
        name=name,
        tenant_id=tenant_id,
    )
    if not await result.single():
        raise HTTPException(status_code=404, detail=f"EntityType '{name}' not found")


# ── Attribute ──────────────────────────────────────────────────────────────────

@router.post(
    "/entity-types/{type_name}/attributes",
    response_model=AttributeResponse,
    status_code=201,
)
async def add_attribute(
    type_name: str,
    body: AttributeCreate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> AttributeResponse:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
        MERGE (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attr_name, tenant_id: $tenant_id})
        ON CREATE SET
            a.data_type   = $data_type,
            a.required    = $required,
            a.cardinality = $cardinality,
            a.created_at  = datetime()
        RETURN a
        """,
        type_name=type_name,
        tenant_id=tenant_id,
        attr_name=body.name,
        data_type=body.data_type.value,
        required=body.required,
        cardinality=body.cardinality.value,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"EntityType '{type_name}' not found")
    return _map_attr(dict(record["a"]), type_name, tenant_id)


@router.get(
    "/entity-types/{type_name}/attributes",
    response_model=list[AttributeResponse],
)
async def list_attributes(
    type_name: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AttributeResponse]:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})-[:HAS_ATTRIBUTE]->(a:Attribute)
        RETURN a ORDER BY a.name
        """,
        type_name=type_name,
        tenant_id=tenant_id,
    )
    records = await result.data()
    return [_map_attr(dict(r["a"]), type_name, tenant_id) for r in records]


@router.patch(
    "/entity-types/{type_name}/attributes/{attr_name}",
    response_model=AttributeResponse,
)
async def update_attribute(
    type_name: str,
    attr_name: str,
    body: AttributeUpdate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> AttributeResponse:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attr_name})
        SET
            a.data_type   = coalesce($data_type, a.data_type),
            a.required    = coalesce($required, a.required),
            a.cardinality = coalesce($cardinality, a.cardinality)
        RETURN a
        """,
        type_name=type_name,
        tenant_id=tenant_id,
        attr_name=attr_name,
        data_type=body.data_type.value if body.data_type else None,
        required=body.required,
        cardinality=body.cardinality.value if body.cardinality else None,
    )
    record = await result.single()
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Attribute '{attr_name}' not found on EntityType '{type_name}'",
        )
    return _map_attr(dict(record["a"]), type_name, tenant_id)


@router.delete(
    "/entity-types/{type_name}/attributes/{attr_name}",
    status_code=204,
)
async def delete_attribute(
    type_name: str,
    attr_name: str,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (:EntityType {name: $type_name, tenant_id: $tenant_id})-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attr_name})
        DETACH DELETE a
        RETURN true AS deleted
        """,
        type_name=type_name,
        tenant_id=tenant_id,
        attr_name=attr_name,
    )
    if not await result.single():
        raise HTTPException(
            status_code=404,
            detail=f"Attribute '{attr_name}' not found on EntityType '{type_name}'",
        )


# ── RelationshipType ──────────────────────────────────────────────────────────

@router.post("/relationship-types", response_model=RelationshipTypeResponse, status_code=201)
async def create_relationship_type(
    body: RelationshipTypeCreate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> RelationshipTypeResponse:
    tenant_id = current_user.tenant_id
    check = await session.run(
        """
        MATCH (src:EntityType {name: $source_type, tenant_id: $tenant_id})
        MATCH (tgt:EntityType {name: $target_type, tenant_id: $tenant_id})
        RETURN true AS valid
        """,
        source_type=body.source_type,
        target_type=body.target_type,
        tenant_id=tenant_id,
    )
    if not await check.single():
        raise HTTPException(
            status_code=422,
            detail=f"EntityType '{body.source_type}' or '{body.target_type}' not found for this tenant",
        )
    result = await session.run(
        """
        MERGE (rt:RelationshipType {name: $name, tenant_id: $tenant_id})
        ON CREATE SET
            rt.source_type = $source_type,
            rt.target_type = $target_type,
            rt.created_at  = datetime()
        RETURN rt
        """,
        name=body.name,
        tenant_id=tenant_id,
        source_type=body.source_type,
        target_type=body.target_type,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create RelationshipType")
    return _map_rt(dict(record["rt"]))


@router.get("/relationship-types", response_model=list[RelationshipTypeResponse])
async def list_relationship_types(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[RelationshipTypeResponse]:
    tenant_id = current_user.tenant_id
    result = await session.run(
        "MATCH (rt:RelationshipType {tenant_id: $tenant_id}) RETURN rt ORDER BY rt.name",
        tenant_id=tenant_id,
    )
    records = await result.data()
    return [_map_rt(dict(r["rt"])) for r in records]


@router.get("/relationship-types/{name}", response_model=RelationshipTypeResponse)
async def get_relationship_type(
    name: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RelationshipTypeResponse:
    tenant_id = current_user.tenant_id
    result = await session.run(
        "MATCH (rt:RelationshipType {name: $name, tenant_id: $tenant_id}) RETURN rt",
        name=name,
        tenant_id=tenant_id,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"RelationshipType '{name}' not found")
    return _map_rt(dict(record["rt"]))


@router.patch("/relationship-types/{name}", response_model=RelationshipTypeResponse)
async def update_relationship_type(
    name: str,
    body: RelationshipTypeUpdate,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> RelationshipTypeResponse:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (rt:RelationshipType {name: $name, tenant_id: $tenant_id})
        SET
            rt.source_type = coalesce($source_type, rt.source_type),
            rt.target_type = coalesce($target_type, rt.target_type)
        RETURN rt
        """,
        name=name,
        tenant_id=tenant_id,
        source_type=body.source_type,
        target_type=body.target_type,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=404, detail=f"RelationshipType '{name}' not found")
    return _map_rt(dict(record["rt"]))


@router.delete("/relationship-types/{name}", status_code=204)
async def delete_relationship_type(
    name: str,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    tenant_id = current_user.tenant_id
    result = await session.run(
        """
        MATCH (rt:RelationshipType {name: $name, tenant_id: $tenant_id})
        DETACH DELETE rt
        RETURN true AS deleted
        """,
        name=name,
        tenant_id=tenant_id,
    )
    if not await result.single():
        raise HTTPException(status_code=404, detail=f"RelationshipType '{name}' not found")
