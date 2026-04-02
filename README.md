# Projet Nexus

Projet Nexus is a graph-native investigation workspace built with FastAPI, Neo4j, Redis, and React. It supports ontology management, CSV/JSON ingestion, graph exploration, AI alert review, case management, and saved investigation views.

## Quick Start

1. Copy the runtime environment:
   `cp .env.example .env`
2. Install API test dependencies:
   `python -m pip install -r api/requirements-dev.txt`
3. Install frontend dependencies:
   `npm --prefix frontend ci`

## Local Verification

Bring up the dedicated integration-test stack:

```bash
make test-stack-up
```

Run the checks:

```bash
make frontend-lint
make frontend-build
make test
```

Tear the stack down when you are done:

```bash
make test-stack-down
```

The test stack uses:

- Neo4j at `bolt://localhost:7687`
- Redis at `redis://localhost:6379`
- Neo4j credentials `neo4j/password`

## Full Application Stack

To run the main Podman stack:

```bash
podman-compose up -d
```

The API serves the bundled SPA when `frontend/dist` exists. Admin users can access the new setup surface at `/admin` to seed demo data, manage ontology, ingest CSVs, inspect DLQ entries, and delete saved views.

## Authentication

Project Nexus does not ship with a default username/password.

- On a fresh deployment, the login screen exposes a one-time bootstrap form that creates the first admin account for the tenant.
- Once the first user exists, bootstrap is disabled and the UI falls back to standard login.
- Authenticated admins can create additional tenant-scoped users through the `POST /auth/register` API.

## CI

GitHub Actions now runs:

- frontend lint
- frontend production build
- backend integration tests against Neo4j + Redis services
- `podman build -f api/Containerfile .`
