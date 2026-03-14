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

router = APIRouter()


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

        # Prefer string attribute values for the display label (not numeric)
        label: str = row["type_name"]
        for v in row["values"]:
            if v["name"] and v["val"] and v["val"] not in ("None", ""):
                try:
                    float(v["val"])
                except ValueError:
                    label = v["val"]
                    break
        else:
            for v in row["values"]:
                if v["name"] and v["val"] and v["val"] not in ("None", ""):
                    label = v["val"]
                    break

        properties = {
            v["name"]: v["val"]
            for v in row["values"]
            if v["name"] and v["val"] not in ("None", "")
        }

        cyto_nodes.append(
            CytoscapeNode(
                data=CytoscapeNodeData(
                    id=node_id,
                    label=label,
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
