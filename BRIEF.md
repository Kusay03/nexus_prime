# Projet Nexus — Agent Brief

Latest session on top.

---

## Session 2026-04-01
### Done
- Wrapped JSON and webhook bulk ingest in a single Neo4j transaction in [ingest.py](/home/kousay/projects/projet-nexus/api/routers/ingest.py) so a failed later operation now rolls back earlier entity writes instead of leaving partial batch state behind.
- Wrapped CSV ingest and DLQ retry row writes in per-row Neo4j transactions in [ingest.py](/home/kousay/projects/projet-nexus/api/routers/ingest.py) so a mid-write failure cannot leave a partially created entity.
- Extended [test_ingest.py](/home/kousay/projects/projet-nexus/tests/test_ingest.py) with rollback assertions for invalid JSON/webhook relationship batches plus explicit required-field, cardinality, data-type, and CSV DLQ regression coverage.
- Updated [TASK.md](/home/kousay/projects/projet-nexus/TASK.md) to mark ingest schema enforcement complete and queue the next Phase 3 RBAC coverage task.
- Verified with `python -m compileall api tests` and `pytest -q tests/test_ingest.py --collect-only`. A live `pytest -q tests/test_ingest.py` run remains blocked in this sandbox because Neo4j/Redis socket access is denied.

### Decisions Made (auto)
- Treated transactional ingest as the real remaining Phase 2 correctness gap because the queued attribute-schema task was already largely implemented in code, but invalid later operations could still leave earlier writes committed.
- Kept the change scoped to transaction boundaries and regression coverage rather than changing the Neo4j data model, which stays below the Vision escalation triggers.
- Chose the next queue item around read-only RBAC coverage because Phase 3 explicitly calls for role-based access and the current tests only lightly exercise the `read-only` role.

### Escalations Required
- None.

### Next Session
- Add read-only RBAC regression coverage across query/search and write endpoints so Phase 3 access control is explicitly verified end to end.
- Re-run `pytest -q tests/test_ingest.py` against a reachable local Neo4j/Redis stack outside the sandbox to validate the new transaction-backed ingest behavior live.

## Session 2026-03-29
### Done
- Added a cyber-threat seed action to [AdminStudioPage.tsx](/home/kousay/projects/projet-nexus/frontend/src/components/AdminStudioPage.tsx) so admins can trigger `/workspace/verticals/cyber-threat/seed` without leaving the product.
- Added Phase 1-oriented bootstrap copy in [AdminStudioPage.tsx](/home/kousay/projects/projet-nexus/frontend/src/components/AdminStudioPage.tsx) and supporting helper-text styling in [index.css](/home/kousay/projects/projet-nexus/frontend/src/index.css).
- Updated [TASK.md](/home/kousay/projects/projet-nexus/TASK.md) to mark the cyber seed UI gap complete.

### Decisions Made (auto)
- Treated admin-studio exposure of the existing cyber seed endpoint as the top remaining Phase 1 task because `VISION.md` explicitly prioritizes the cyber threat domain and the backend contract already existed.
- Reused the existing Admin Studio seeding pattern instead of introducing new frontend API abstractions so the change stayed small, visible, and low risk.
- Kept both verticals visible in the bootstrap panel: cyber threat for Phase 1 proof, revenue ops for the broader product demo path already present in the UI.

### Escalations Required
- None.

### Next Session
- Split `InvestigationsPage` further; the current production build still emits `dist/assets/InvestigationsPage-lhF3t-Qx.js` at 548.94 kB, which remains the largest frontend chunk.
- Turn `Export` and graph `Reflow` from UI placeholders into real workflows with backend support where needed.

## 2026-03-26 — case membership workflow

**What was improved**:

1. **Case membership endpoints added** — cases now support explicit add/remove entity operations instead of freezing membership at case creation time.
2. **Case audit trail got more useful** — case membership changes now write `ActionLog` records, so the recent-actions panel reflects analyst actions rather than staying mostly empty.
3. **Cases UI became operational** — analysts can search tenant entities, link them to a case, and remove linked entities directly from the case detail screen.
4. **Case regression coverage added** — new integration tests now cover linking, unlinking, and invalid unlink attempts.

**Verification**:
- `python -m compileall api tests` — passed
- `pytest -q tests/test_cases.py` — passed (`3 passed`)

## 2026-03-25 — admin studio + verification path

**What was improved**:

1. **Admin studio added** — the frontend now has an `/admin` route for admin users with tenant bootstrap actions, ontology/entity schema management, CSV ingestion, DLQ inspection, saved-view cleanup, and system status.
2. **Backend support endpoints added** — workspace system summary/status, saved-view deletion, and DLQ key listing are now exposed so the studio can manage real tenant state instead of hand-entered keys.
3. **Frontend route splitting improved** — major app screens now lazy-load, which split the previous monolith bundle into route chunks and reduced the main entry bundle materially.
4. **Test harness made reproducible** — added `api/requirements-dev.txt`, `pytest.ini`, real test-user setup in `tests/conftest.py`, and FastAPI lifespan handling so integration tests run against the actual app wiring.
5. **Local + CI verification shipped** — added `README.md`, `Makefile`, `podman-compose.test.yml`, and a GitHub Actions workflow that lints/builds the frontend, runs integration tests, and validates the Podman image build.

**Verification**:
- `npm run lint` — passed
- `npm run build` — passed
- `python -m compileall api tests` — passed
- `pytest -q` — passed (`35 passed`) against the active local Neo4j/Redis stack with project `.env` loaded

## 2026-03-25 — frontend image packaging

**What was improved**:

1. **Container build fixed** — `podman-compose.yml` now builds from the repository root and targets `api/Containerfile`, which matches the project convention and actually resolves to an existing file.
2. **Frontend bundled into the API image** — `api/Containerfile` is now a multi-stage build that runs `npm ci && npm run build` in `frontend/` and copies the resulting `dist/` into the runtime image.
3. **FastAPI now serves the SPA bundle** — when `frontend/dist/` exists, the API serves static assets and falls back to `index.html` for client-side routes while preserving 404s for API prefixes.
4. **Build context trimmed** — root `.containerignore` excludes `node_modules`, caches, and generated output so Podman does not ship unnecessary context into the image build.

**Tradeoffs**:
- The runtime image now depends on a frontend build during container creation, so container builds will be slower than the previous API-only image.
- Health checks should use `/healthz`; `/` is reserved for the SPA whenever a frontend bundle is present.

## 2026-03-25 — nexus-prime audit sweep

**What the project does**: Domain-agnostic entity-relationship graph platform (Neo4j + FastAPI + React/Cytoscape.js) for revenue operations. Users define arbitrary entity types/attributes, ingest data from CSV/JSON, explore as interactive graph, triage AI-generated alerts, manage cases.

**What was improved**:

1. **Tests implemented** — all three test files were empty stubs. Added:
   - `tests/conftest.py` — shared fixtures (clean-tenant isolation, JWT helpers, AsyncClient)
   - `tests/test_ontology.py` — 19 real tests covering entity types, attributes, relationship types CRUD
   - `tests/test_ingest.py` — 7 real tests covering JSON bulk ingest and CSV upload with DLQ
   - `tests/test_query.py` — 7 real tests covering traverse, search, and entity detail

2. **`.env.example` added** — onboarding friction reduced; new developers have a complete template with Neo4j, Redis, JWT, and CORS settings.

3. **CORS security fix** — `allow_origins=["*"]` was a security risk for a multi-tenant platform. Replaced with `allowed_origins` config field (defaults to `localhost:5173, localhost:3000`), configurable via `.env`.

4. **Dead v0 files removed** — `main.py`, `index.html`, `init.sql`, `requirements.txt` at root were university-era PostgreSQL artifacts from v0. They had nothing to do with the Neo4j-based v1. Removed.

5. **Empty `api/services/` removed** — existed in the target CLAUDE.md structure but was never populated.

**Tradeoffs**:
- Tests require a live Neo4j + Redis instance to run (no mocking). This is intentional — real integration tests validate the actual Cypher queries.
- CORS defaults to localhost only; production deployments need to add their domain to `ALLOWED_ORIGINS`.

---

_No sessions prior to 2026-03-25.]

## Session 2026-03-29
### Done
- Added Redis-backed fixed-window rate limiting middleware in [api/middleware/rate_limit.py](/home/kousay/projects/projet-nexus/api/middleware/rate_limit.py) and wired it into [api/main.py](/home/kousay/projects/projet-nexus/api/main.py).
- Added env-configurable rate-limit settings in [api/config.py](/home/kousay/projects/projet-nexus/api/config.py), [.env.example](/home/kousay/projects/projet-nexus/.env.example), and [api/.env.example](/home/kousay/projects/projet-nexus/api/.env.example).
- Extended [tests/test_auth.py](/home/kousay/projects/projet-nexus/tests/test_auth.py) with coverage for login throttling and authenticated API throttling.
- Updated [TASK.md](/home/kousay/projects/projet-nexus/TASK.md) to mark rate limiting complete.

### Decisions Made (auto)
- Treated Phase 1 as materially complete because ontology CRUD, cyber-domain coverage, and traversal already exist in the codebase and tests.
- Implemented rate limiting as a fixed-window Redis counter to keep the change small, observable, and aligned with the existing Redis dependency.
- Scoped the stricter policy to `POST /auth/token` and used a broader API bucket for the rest of the HTTP surface.
- Used client IP for anonymous requests and `tenant_id:user_id` for valid JWT-authenticated traffic so tenant-aware isolation remains intact in limiter keys.
- Chose fail-open behavior when Redis is unavailable to avoid turning a Redis outage into a total API outage on top of the platform's existing Redis dependency.

### Escalations Required
- None.

### Next Session
- Split the `InvestigationsPage` bundle further so the graph route is no longer the dominant frontend chunk.
- Turn `Export` and graph `Reflow` from UI placeholders into real workflows with backend contracts where needed.
- Re-run `pytest -q tests/test_auth.py` against a reachable local Neo4j/Redis stack because sandboxed verification stalled on live service access.

## Session 2026-03-29
### Done
- Added a dedicated Phase 1 cyber-threat seed endpoint in [workspace.py](/home/kousay/projects/projet-nexus/api/routers/workspace.py) at `/workspace/verticals/cyber-threat/seed`.
- Seeded the canonical ontology and demo graph for `Attacker`, `Server`, and `Vulnerability`, including `UNAUTHORIZED_ACCESS`, `EXPLOITS`, and `AFFECTS`, plus a saved view rooted on the attacker path.
- Added integration coverage in [test_workspace.py](/home/kousay/projects/projet-nexus/tests/test_workspace.py) that seeds the cyber graph, searches for the seeded CVE, and traverses the resulting subgraph.
- Updated [TASK.md](/home/kousay/projects/projet-nexus/TASK.md) to mark the backend cyber seed work complete and queue the admin-studio follow-up.

### Decisions Made (auto)
- Treated the missing first-class cyber demo seed as the top remaining Phase 1 gap because `VISION.md` names it explicitly, while the repo previously only had revenue-ops seeding and ad hoc cyber setup inside tests.
- Kept the patch backend-only so the new contract is testable and tenant-scoped before expanding the admin UI surface.
- Made the seed idempotent per tenant by using `MERGE` on ontology nodes, relationship types, entities, relationships, and saved views keyed by `tenant_id` plus stable seed keys.

### Escalations Required
- None.

### Next Session
- Expose `/workspace/verticals/cyber-threat/seed` in the admin studio so the new Phase 1 demo path is reachable from the product UI.
- If a reachable local Neo4j/Redis stack is available outside the sandbox restrictions, run `pytest -q tests/test_workspace.py::test_cyber_threat_seed_creates_phase1_demo_graph` to validate the full live integration path.

## Session 2026-03-30
### Done
- Enforced ontology relationship modeling during ingest in [ingest.py](/home/kousay/projects/projet-nexus/api/routers/ingest.py) so `create_connection` now verifies that the source and target entities' `INSTANCE_OF` types match the declared `source_type` and `target_type` on the requested `RelationshipType`.
- Tightened missing tenant filters in [ingest.py](/home/kousay/projects/projet-nexus/api/routers/ingest.py) for attribute attachment writes, keeping the attribute lookup tenant-scoped during entity creation.
- Added regression coverage in [test_ingest.py](/home/kousay/projects/projet-nexus/tests/test_ingest.py) for JSON and webhook payloads that try to create graph edges with the wrong entity types or reversed direction.
- Updated [TASK.md](/home/kousay/projects/projet-nexus/TASK.md) to replace the stale generic queue with the next concrete ontology-enforcement gap.

### Decisions Made (auto)
- Treated write-time enforcement of `RelationshipType.source_type` and `target_type` as the top remaining Vision-aligned task because the ontology API already existed, but ingestion still allowed structurally invalid graph edges.
- Kept the change on the ingest boundary instead of redesigning the graph model, which preserves the current Neo4j schema and stays below the Vision escalation triggers.
- Recorded attribute data-type/cardinality enforcement as the next task because the current ingest path still validates attribute names only, not the full ontology schema.

### Escalations Required
- None.

### Next Session
- Enforce attribute data types, required fields, and cardinality during JSON, webhook, and CSV ingest so the ontology becomes fully prescriptive instead of partially descriptive.
- Re-run `pytest -q tests/test_ingest.py` once the local Python environment has the real `neo4j` driver installed and a reachable Neo4j/Redis test stack is available; this session could only verify with `python -m compileall api tests`.
