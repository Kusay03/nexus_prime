from typing import Any

from pydantic import BaseModel, Field


class TraverseRequest(BaseModel):
    entity_id: str
    depth: int = Field(default=2, ge=1, le=6)


# ── Cytoscape.js-ready graph format ──────────────────────────────────────────
# Matches the Cytoscape.js element spec:
# https://js.cytoscape.org/#notation/elements-json

class CytoscapeNodeData(BaseModel):
    id: str
    label: str            # display value (first string attribute, or type_name)
    type: str             # EntityType name
    tenant_id: str
    properties: dict[str, Any] = {}   # all HAS_VALUE attribute values


class CytoscapeNode(BaseModel):
    data: CytoscapeNodeData


class CytoscapeEdgeData(BaseModel):
    id: str               # "{source}__{target}__{label}" — stable & unique
    source: str
    target: str
    label: str            # relationship_type


class CytoscapeEdge(BaseModel):
    data: CytoscapeEdgeData


class GraphResponse(BaseModel):
    nodes: list[CytoscapeNode]
    edges: list[CytoscapeEdge]
