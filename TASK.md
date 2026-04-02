# Projet Nexus — Task Queue

Agent-maintained. Latest state on top. Completed tasks move to Done.

---

## Queue

- [ ] Add read-only RBAC regression coverage for Phase 3: verify read-only users can use query/search routes but are denied ontology, ingest, and other write endpoints.

## Done

- **[2026-04-01] Transactional ingest + attribute-schema enforcement verified** — JSON and webhook bulk ingest now execute inside a single Neo4j transaction so invalid later operations roll back earlier entity writes, while CSV and DLQ retry rows now use per-row transactions to avoid partial entity persistence. Added regressions for rollback on invalid relationships plus required-attribute, cardinality, data-type, and CSV DLQ validation paths.
- **[2026-03-30] Ontology relationship enforcement added to ingest** — JSON and webhook ingest now reject connections whose entity types do not match the `RelationshipType`'s declared `source_type` and `target_type`. Tightened missing tenant filters in attribute writes and added regression coverage for invalid edge creation.
- **[2026-03-29] Cyber seed UI shipped** — admin users can now trigger `/workspace/verticals/cyber-threat/seed` directly from the Admin Studio, with explicit Phase 1 copy and workspace refresh on completion.
- **[2026-03-29] Cyber threat seed endpoint added** — `/workspace/verticals/cyber-threat/seed` now provisions the canonical Phase 1 ontology (`Attacker`, `Server`, `Vulnerability`), key relationship types, a small connected demo graph, and a saved view. Added an integration test that exercises the seed endpoint through search and traversal.
- **[2026-03-29] Redis-backed API rate limiting added** — middleware now enforces configurable fixed-window limits for `/auth/token` and broader API traffic, keyed by client IP for anonymous traffic and by tenant/user when a valid JWT is present. Added auth regression tests and env-driven limit settings.
- **[2026-03-26] Case entity membership shipped** — backend add/remove endpoints now let analysts link or unlink tenant entities from a case, write action-log audit events, and expose the workflow through the cases UI.
- **[2026-03-26] Webhook ingestion endpoint added** — `/ingest/webhook` now ingests structured operation batches with source, event type, and event id metadata.
- **[2026-03-26] Dead-letter queue retry added** — failed CSV rows now store retry metadata, can be replayed from the admin studio, and are covered by integration tests.
- **[2026-03-25] Admin studio shipped** — frontend now has an `/admin` route for tenant bootstrap, ontology management, CSV ingestion, DLQ inspection, saved-view deletion, and environment status.
- **[2026-03-25] Reproducible verification path added** — root README, Makefile, `podman-compose.test.yml`, `api/requirements-dev.txt`, `pytest.ini`, and GitHub Actions CI now cover local and CI build/test workflows.
- **[2026-03-25] Workspace saved-view delete added** — backend DELETE endpoint implemented and exposed through the admin studio.
- **[2026-03-25] Frontend build pipeline wired into API image** — `api/Containerfile` now performs a multi-stage frontend build, `podman-compose.yml` builds from repo root, and FastAPI serves the bundled SPA with API-safe fallback routing.
- **[2026-03-25] Audit + 5 targeted improvements** — see BRIEF.md for details.
- [2026-03-25] Real tests implemented (ontology CRUD, ingest, query — 33 tests total)
- [2026-03-25] .env.example added
- [2026-03-25] CORS security fix (was "*", now per-origin config)
- [2026-03-25] Dead v0 files removed (root main.py, index.html, init.sql, requirements.txt)
- [2026-03-25] Empty api/services/ directory removed
