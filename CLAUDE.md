# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this project?

Project Nexus is a domain-agnostic entity-relationship platform — think "Palantir for SMBs." It translates multi-dimensional relational data into physics-based network graphs in real-time. Users can define arbitrary entity types, ingest data from multiple sources, and explore their data as an interactive graph.

## Current State

This is the **v1-production** branch. The `v0-university` tag contains the original university project (PostgreSQL EAV + FastAPI + vanilla JS + Vis.js). **Do not modify v0 code.** v1 is a ground-up rebuild.

## v1 Architecture

### Tech Stack

| Layer | Technology |
|---|---|
| Container runtime | **Podman** (not Docker) — use `podman` and `podman-compose` everywhere |
| Graph database | Neo4j Community Edition (Bolt port 7687, HTTP port 7474) |
| Backend | Python 3.11+, FastAPI, `neo4j` Python driver (not `py2neo`) |
| Cache / sessions | Redis |
| Frontend | React + Cytoscape.js (Phase 4 — not started) |
| Auth | JWT tokens via FastAPI OAuth2 |

### Container Topology

All services run in a Podman pod called `nexus-core` using `--network host` for local development.

```
nexus-core (pod)
├── neo4j   (port 7687 bolt, 7474 http)
├── redis   (port 6379)
└── api     (port 8000) — FastAPI monolith with routers:
    ├── /ontology  — CRUD for entity types, attributes, relationship types
    ├── /ingest    — CSV upload, JSON/REST, webhook receiver
    ├── /query     — Graph traversal with filtering, pagination
    └── /auth      — JWT login, tenant scoping, RBAC
```

### Neo4j Data Model (The Ontology)

The ontology is stored as meta-nodes in Neo4j itself:

```cypher
(:EntityType {name, description, tenant_id})
  -[:HAS_ATTRIBUTE]->
(:Attribute {name, data_type, required, cardinality})

(:RelationshipType {name, source_type, target_type, tenant_id})
```

Data instances follow this pattern:

```cypher
(:Entity {id, tenant_id, created_at})
  -[:INSTANCE_OF]-> (:EntityType)

(:Entity)-[:HAS_VALUE {attribute_id, value_string, value_numeric, value_date}]->(:Attribute)

(:Entity)-[r:CONNECTED_TO {relationship_type, metadata}]->(:Entity)
```

Every node has a `tenant_id` property for multi-tenancy isolation.

### Project Structure (target)

```
project-nexus/
├── CLAUDE.md
├── podman-compose.yml
├── .env.example
├── neo4j/
│   └── init.cypher           # Bootstrap ontology constraints + indexes
├── api/
│   ├── Containerfile         # Podman convention (not Dockerfile)
│   ├── requirements.txt
│   ├── main.py               # FastAPI app with CORS
│   ├── config.py             # Settings from .env via pydantic-settings
│   ├── db.py                 # Neo4j driver singleton
│   ├── routers/
│   │   ├── ontology.py       # Entity type, attribute, relationship type CRUD
│   │   ├── ingest.py         # CSV, JSON, webhook ingestion
│   │   ├── query.py          # Graph traversal + filtering
│   │   └── auth.py           # JWT auth + tenant scoping
│   ├── models/               # Pydantic request/response schemas
│   ├── services/             # Business logic layer
│   └── middleware/
│       └── tenant.py         # Extract tenant_id from JWT, inject into request state
├── frontend/                 # Phase 4 — React + Cytoscape.js (not started)
└── tests/
    ├── test_ontology.py
    ├── test_ingest.py
    └── test_query.py
```

## Build Phases (in priority order)

### Phase 1: Graph database + ontology ← CURRENT
- Neo4j container setup with constraints and indexes
- Ontology CRUD API (entity types, attributes, relationship types)
- Seed the cyber threat domain as a test case via API calls
- Prove it works: recreate v0's graph query as a Cypher traversal

### Phase 2: Data ingestion pipelines
- CSV upload with column-to-attribute mapping
- JSON/REST endpoint for programmatic inserts
- Webhook receiver for event-driven data
- Validation against ontology before writes
- Dead-letter queue in Redis for failed ingestions

### Phase 3: Auth and multi-tenancy
- JWT authentication with FastAPI OAuth2
- `tenant_id` on every node, Cypher queries always filter by it
- Role-based access: admin, analyst, read-only
- Redis for session tokens + rate limiting

### Phase 4: Frontend
- React + Cytoscape.js replacing vanilla JS + Vis.js
- Dynamic filters generated from ontology meta-graph
- Click-to-expand subgraph exploration
- Saved views / perspectives

## Critical Rules

1. **Never flatten the graph.** All data lives in Neo4j as nodes and relationships. No relational tables.
2. **Ontology-first.** All entity types and attributes must be defined in the ontology before data can be ingested. The ontology is the source of truth.
3. **Podman, not Docker.** Use `podman`, `podman-compose`, and `Containerfile` (not `Dockerfile`).
4. **Tenant isolation.** Every node must have `tenant_id`. Every Cypher query must include `WHERE ... tenant_id = $tenant_id`.
5. **No hardcoded credentials.** All secrets come from `.env` via `pydantic-settings`.
6. **Type everything.** Use Pydantic models for all API request/response schemas. Use Python type hints everywhere.
7. **Test with the cyber domain.** The first ontology to create is the cyber threat intelligence domain from v0 (Attacker, Server, Vulnerability entities with `UNAUTHORIZED_ACCESS` relationships).

## Cypher Style Guide

```cypher
// Use MERGE for ontology nodes (idempotent)
MERGE (et:EntityType {name: $name, tenant_id: $tenant_id})
ON CREATE SET et.created_at = datetime()
RETURN et

// Use CREATE for data entities (always new)
CREATE (e:Entity {id: randomUUID(), tenant_id: $tenant_id, created_at: datetime()})
WITH e
MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
CREATE (e)-[:INSTANCE_OF]->(et)
RETURN e

// Always parameterize — never concatenate strings into Cypher
```

## Environment Variables (`.env`)

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<set-locally>
REDIS_URL=redis://localhost:6379
JWT_SECRET=<set-locally>
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
```
