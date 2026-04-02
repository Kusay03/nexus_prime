# Projet Nexus - Repo Guide

## Purpose

Domain-agnostic entity-relationship platform that models arbitrary relational data as graph structures for exploration and analysis.

## Current Phase

Phase 1 graph database and ontology API.

## Priorities

1. Complete ontology CRUD and entity/relationship modeling
2. Prove graph queries over a seeded cyber threat domain
3. Preserve tenant-aware graph isolation
4. Prepare ingestion pipelines without flattening the graph model
5. Move toward frontend graph exploration once backend contracts stabilize

## Constraints

- Never flatten graph data into a relational substitute.
- Use Podman rather than Docker for local container workflows.
- Every Cypher query must filter by `tenant_id`.
- Keep secrets in env-driven config, not hardcoded files.

## Stack

- Backend: FastAPI + Neo4j + Redis
- Frontend: React
- Infra: Podman-based local workflow

## Source Of Truth

- Read `CLAUDE.md`, `VISION.md`, `BRIEF.md`, and `TASK.md` before making major changes.
- Code and runtime config remain the source of truth for behavior.
- Keep durable scope in `VISION.md`, recent memory in `BRIEF.md`, and active queue state in `TASK.md`.

## Working Defaults

- Prefer one small, measurable improvement per session.
- Treat the working tree as user-owned unless the current task changes those files.
- Keep contracts, routes, schemas, and UI behavior aligned when one side changes.
- Record stable facts in context files, not temporary speculation.

## Verification

- Run the smallest meaningful verification for the files touched.
- Prefer builds, imports, targeted tests, or smoke checks over broad expensive runs.
- Report what was verified and what remains unverified.
