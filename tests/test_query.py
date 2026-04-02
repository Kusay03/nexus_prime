"""
Phase 2 tests — graph query and traversal.

Run against a live Neo4j instance:
    cd ~/projects/projet-nexus
    pytest tests/test_query.py -v

Tests are isolated per tenant via conftest.py clean_tenant fixture.
"""
import pytest


async def _seed_minimal_graph(http_client):
    """Seed a minimal ontology + two connected entities for query tests."""
    # Create ontology
    await http_client.post("/ontology/entity-types", json={"name": "Customer"})
    await http_client.post("/ontology/entity-types/Customer/attributes",
        json={"name": "Customer Name", "data_type": "STRING"})
    await http_client.post("/ontology/entity-types", json={"name": "Contract"})
    await http_client.post("/ontology/entity-types/Contract/attributes",
        json={"name": "Contract Name", "data_type": "STRING"})
    await http_client.post("/ontology/relationship-types",
        json={"name": "HAS_CONTRACT", "source_type": "Customer", "target_type": "Contract"})

    # Ingest entities
    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "cust1",
                    "type_name": "Customer",
                    "values": [{"name": "Customer Name", "value_string": "Acme Corp"}],
                },
                {
                    "op": "create_entity",
                    "alias": "contract1",
                    "type_name": "Contract",
                    "values": [{"name": "Contract Name", "value_string": "Acme FY26"}],
                },
                {
                    "op": "create_connection",
                    "source_alias": "cust1",
                    "target_alias": "contract1",
                    "relationship_type": "HAS_CONTRACT",
                },
            ]
        },
    )
    return resp.json()


@pytest.mark.asyncio
async def test_traverse_returns_graph(http_client):
    seed = await _seed_minimal_graph(http_client)
    entity_id = seed["entity_map"]["cust1"]

    resp = await http_client.post(
        "/query/traverse",
        json={"entity_id": entity_id, "depth": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) >= 1  # at least the root node


@pytest.mark.asyncio
async def test_traverse_not_found_returns_404(http_client):
    resp = await http_client.post(
        "/query/traverse",
        json={"entity_id": "00000000-0000-0000-0000-000000000000", "depth": 2},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_returns_matching_entity(http_client):
    seed = await _seed_minimal_graph(http_client)
    entity_id = seed["entity_map"]["cust1"]

    resp = await http_client.post(
        "/query/search",
        json={"query": "Acme", "limit": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = {r["entity_id"] for r in data["results"]}
    assert entity_id in ids


@pytest.mark.asyncio
async def test_search_returns_empty_for_no_match(http_client):
    await _seed_minimal_graph(http_client)
    resp = await http_client.post(
        "/query/search",
        json={"query": "zzzz_no_match_zzzz", "limit": 10},
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_entity_detail_returns_properties(http_client):
    seed = await _seed_minimal_graph(http_client)
    entity_id = seed["entity_map"]["cust1"]

    resp = await http_client.get(f"/query/entity/{entity_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_id"] == entity_id
    assert "properties" in data
    assert "related_entities" in data
    assert "recent_actions" in data


@pytest.mark.asyncio
async def test_entity_detail_not_found_returns_404(http_client):
    resp = await http_client.get("/query/entity/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_limit_respected(http_client):
    await _seed_minimal_graph(http_client)
    resp = await http_client.post(
        "/query/search",
        json={"query": "Acme", "limit": 1},
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 1
