# Projet Nexus — Vision

## Goal
Domain-agnostic entity-relationship platform — "Palantir for SMBs." Translates multi-dimensional relational data into physics-based network graphs. Users define arbitrary entity types, ingest from multiple sources, explore as interactive graph.

## Current Phase
Phase 1 — Graph database + ontology API (in progress).

## Priorities
1. Complete ontology CRUD API (entity types, attributes, relationship types)
2. Seed cyber threat domain as test case (Attacker, Server, Vulnerability)
3. Prove v0 graph query works as Cypher traversal
4. Phase 2: CSV + JSON/REST + webhook ingestion pipelines
5. Phase 3: JWT auth + multi-tenancy (tenant_id on every node)
6. Phase 4: React + Cytoscape.js frontend

## Constraints
- **Never flatten the graph** — all data stays in Neo4j
- **Podman not Docker** — use `podman`, `podman-compose`, `Containerfile`
- Every Cypher query must filter by `tenant_id`
- All secrets from `.env` via pydantic-settings
- Type hints + Pydantic models everywhere
- Use `neo4j` Python driver (not `py2neo`)

## Escalation Triggers (additions to global policy)
- Neo4j data model changes (new meta-node patterns)
- Adding new ingestion source types
- Multi-tenancy isolation strategy changes
- Frontend graph library switch (Cytoscape.js is decided)
