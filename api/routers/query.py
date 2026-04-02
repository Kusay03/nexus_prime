from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncSession

from db import get_session
from middleware.tenant import get_current_user
from models.auth import CurrentUser
from models.query import (
    CytoscapeEdge,
    CytoscapeEdgeData,
    CytoscapeNode,
    CytoscapeNodeData,
    GraphResponse,
    TraverseRequest,
)
from models.workspace import (
    EntityDetailResponse,
    RecentAction,
    RelatedEntity,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

router = APIRouter()


def _pick_label(type_name: str, values: list[dict[str, str]]) -> str:
    preferred_keys = (
        "Display Name",
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
        "Username",
        "Hostname",
        "IP Address",
        "Email",
        "Domain",
        "CVE ID",
    )
    properties = {
        value["name"]: value["val"]
        for value in values
        if value["name"] and value["val"] not in ("None", "")
    }
    for key in preferred_keys:
        if properties.get(key):
            return properties[key]
    for value in properties.values():
        try:
            float(value)
        except ValueError:
            return value
    return next(iter(properties.values()), type_name)


def _highlight_reason(type_name: str, properties: dict[str, str]) -> str:
    if type_name == "Customer":
        renewal = properties.get("Renewal Window")
        health = properties.get("Health Status", "Needs review")
        if renewal:
            return f"{health} • renews in {renewal}"
        return f"Health: {health}"
    if type_name == "Invoice":
        status = properties.get("Payment Status", "Unknown")
        days_late = properties.get("Days Late")
        if days_late not in (None, ""):
            return f"{status} • {days_late} days late"
        return f"Payment: {status}"
    if type_name == "SupportTicket":
        return f"{properties.get('Severity', 'Unspecified')} severity • {properties.get('Status', 'Open')}"
    if type_name == "Contract":
        return f"Renewal due {properties.get('Renewal Date', properties.get('Renewal Window', 'Active'))}"
    if type_name in {"Observation", "Hypothesis", "Alert", "Recommendation", "ModelRun", "PromptTemplate", "Document"}:
        return properties.get("Display Name") or type_name
    return "Operational hotspot"


@router.post("/traverse", response_model=GraphResponse)
async def traverse(
    body: TraverseRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """
    N-hop graph traversal from a starting entity.
    Returns a Cytoscape.js-ready { nodes, edges } payload.
    Traversal is undirected — CONNECTED_TO is followed in both directions
    so analysts can explore regardless of which end they start from.
    tenant_id is enforced on every node and edge — cross-tenant data is invisible.

    Note: variable-length path bounds cannot be parameterised in Neo4j Cypher.
    body.depth is validated as int(1..6) by Pydantic, making the f-string safe.
    """
    tenant_id = current_user.tenant_id

    check = await session.run(
        "MATCH (e:Entity {id: $id, tenant_id: $tid}) RETURN e.id AS id",
        id=body.entity_id,
        tid=tenant_id,
    )
    if not await check.single():
        raise HTTPException(status_code=404, detail=f"Entity '{body.entity_id}' not found")

    # ── Query 1: all reachable nodes with attribute values ─────────────────────
    nodes_result = await session.run(
        f"""
        MATCH (start:Entity {{id: $entity_id, tenant_id: $tenant_id}})
        OPTIONAL MATCH (start)-[:CONNECTED_TO*1..{body.depth}]-(neighbor:Entity {{tenant_id: $tenant_id}})
        WITH start, collect(DISTINCT neighbor) AS neighbors
        WITH neighbors + [start] AS all_nodes
        UNWIND all_nodes AS node
        OPTIONAL MATCH (node)-[hv:HAS_VALUE]->(a:Attribute)
        RETURN
            node.id        AS id,
            node.type_name AS type_name,
            node.tenant_id AS tenant_id,
            collect({{
                name: a.name,
                val:  coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
            }}) AS values
        """,
        entity_id=body.entity_id,
        tenant_id=tenant_id,
    )
    nodes_data = await nodes_result.data()

    seen_node_ids: set[str] = set()
    cyto_nodes: list[CytoscapeNode] = []

    for row in nodes_data:
        node_id = row["id"]
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)

        properties = {
            v["name"]: v["val"]
            for v in row["values"]
            if v["name"] and v["val"] not in ("None", "")
        }

        cyto_nodes.append(
            CytoscapeNode(
                data=CytoscapeNodeData(
                    id=node_id,
                    label=_pick_label(row["type_name"], row["values"]),
                    type=row["type_name"],
                    tenant_id=row["tenant_id"],
                    properties=properties,
                )
            )
        )

    # ── Query 2: all directed edges between the collected nodes ────────────────
    edges_result = await session.run(
        """
        MATCH (src:Entity)-[r:CONNECTED_TO]->(tgt:Entity)
        WHERE src.id IN $node_ids
          AND tgt.id IN $node_ids
          AND r.tenant_id = $tenant_id
        RETURN
            src.id              AS source,
            tgt.id              AS target,
            r.relationship_type AS label
        """,
        node_ids=list(seen_node_ids),
        tenant_id=tenant_id,
    )
    edges_data = await edges_result.data()

    cyto_edges = [
        CytoscapeEdge(
            data=CytoscapeEdgeData(
                id=f"{row['source']}__{row['target']}__{row['label']}",
                source=row["source"],
                target=row["target"],
                label=row["label"],
            )
        )
        for row in edges_data
    ]

    return GraphResponse(nodes=cyto_nodes, edges=cyto_edges)


@router.post("/search", response_model=SearchResponse)
async def search_entities(
    body: SearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    search_term = body.query.strip().lower()
    result = await session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        OPTIONAL MATCH (e)-[rel:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        WITH
            e,
            count(DISTINCT rel) AS relationship_count,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        val: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        WITH
            e,
            relationship_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.val <> ''] AS values
        WITH
            e,
            relationship_count,
            values,
            [value IN values | toLower(value.val)] AS searchable_values
        WHERE
            toLower(e.id) CONTAINS $search_term
            OR toLower(e.type_name) CONTAINS $search_term
            OR any(value IN searchable_values WHERE value CONTAINS $search_term)
        RETURN
            e.id AS entity_id,
            e.type_name AS type_name,
            relationship_count,
            values
        ORDER BY relationship_count DESC, e.created_at DESC
        LIMIT $limit
        """,
        tenant_id=current_user.tenant_id,
        search_term=search_term,
        limit=body.limit,
    )
    rows = await result.data()
    results = []
    for row in rows:
        properties = {
            value["name"]: value["val"]
            for value in row["values"]
            if value["name"] and value["val"] not in ("None", "")
        }
        results.append(
            SearchResult(
                entity_id=row["entity_id"],
                label=_pick_label(row["type_name"], row["values"]),
                type_name=row["type_name"],
                match_reason=_highlight_reason(row["type_name"], properties),
                properties=properties,
                relationship_count=row["relationship_count"],
            )
        )
    return SearchResponse(results=results)


@router.get("/entity/{entity_id}", response_model=EntityDetailResponse)
async def entity_detail(
    entity_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EntityDetailResponse:
    tenant_id = current_user.tenant_id

    result = await session.run(
        """
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        OPTIONAL MATCH (e)-[rel:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        WITH
            e,
            count(DISTINCT rel) AS relationship_count,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        val: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        RETURN
            e.id AS entity_id,
            e.type_name AS type_name,
            e.tenant_id AS tenant_id,
            relationship_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.val <> ''] AS values
        """,
        entity_id=entity_id,
        tenant_id=tenant_id,
    )
    row = await result.single()
    if not row:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    related_result = await session.run(
        """
        MATCH (src:Entity {id: $entity_id, tenant_id: $tenant_id})-[r:CONNECTED_TO]->(tgt:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (tgt)-[hv:HAS_VALUE]->(a:Attribute)
        WITH
            tgt,
            r,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        val: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        RETURN
            tgt.id AS entity_id,
            tgt.type_name AS type_name,
            r.relationship_type AS relationship_type,
            'outbound' AS direction,
            [value IN raw_values WHERE value IS NOT NULL AND value.val <> ''] AS values
        UNION
        MATCH (src:Entity {tenant_id: $tenant_id})-[r:CONNECTED_TO]->(tgt:Entity {id: $entity_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (src)-[hv:HAS_VALUE]->(a:Attribute)
        WITH
            src,
            r,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        val: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        RETURN
            src.id AS entity_id,
            src.type_name AS type_name,
            r.relationship_type AS relationship_type,
            'inbound' AS direction,
            [value IN raw_values WHERE value IS NOT NULL AND value.val <> ''] AS values
        LIMIT 12
        """,
        entity_id=entity_id,
        tenant_id=tenant_id,
    )
    action_result = await session.run(
        """
        MATCH (log:ActionLog {tenant_id: $tenant_id})-[:TARGETS]->(e:Entity {id: $entity_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (log)-[:PART_OF_CASE]->(c:Case {tenant_id: $tenant_id})
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
        entity_id=entity_id,
        tenant_id=tenant_id,
    )

    properties = {
        value["name"]: value["val"]
        for value in row["values"]
        if value["name"] and value["val"] not in ("None", "")
    }
    related_entities = [
        RelatedEntity(
            entity_id=related["entity_id"],
            label=_pick_label(related["type_name"], related["values"]),
            type_name=related["type_name"],
            relationship_type=related["relationship_type"],
            direction=related["direction"],
        )
        for related in await related_result.data()
    ]
    recent_actions = [
        RecentAction(
            log_id=action["log_id"],
            action_type=action["action_type"],
            status=action["status"],
            timestamp=str(action["timestamp"]) if action["timestamp"] else "",
            executed_by=action["executed_by"],
            case_id=action["case_id"],
        )
        for action in await action_result.data()
    ]

    return EntityDetailResponse(
        entity_id=row["entity_id"],
        label=_pick_label(row["type_name"], row["values"]),
        type_name=row["type_name"],
        tenant_id=row["tenant_id"],
        properties=properties,
        related_entities=related_entities,
        recent_actions=recent_actions,
        relationship_count=row["relationship_count"],
    )
