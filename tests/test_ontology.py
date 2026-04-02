"""
Phase 1 tests — ontology CRUD (entity types, attributes, relationship types).

Run against a live Neo4j instance:
    cd ~/projects/projet-nexus
    pytest tests/test_ontology.py -v

The conftest.py fixture clean_tenant gives each test a unique tenant_id
and wipes it after the test so runs are fully isolated.
"""
import pytest


# ── EntityType ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_entity_type(http_client):
    resp = await http_client.post(
        "/ontology/entity-types",
        json={"name": "Server", "description": "Network server"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Server"
    assert data["description"] == "Network server"
    assert "tenant_id" in data


@pytest.mark.asyncio
async def test_create_entity_type_duplicate(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.post("/ontology/entity-types", json={"name": "Server"})
    # MERGE is idempotent — second call returns existing node, not an error
    assert resp.status_code == 201
    assert resp.json()["name"] == "Server"


@pytest.mark.asyncio
async def test_list_entity_types(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post("/ontology/entity-types", json={"name": "Attacker"})
    resp = await http_client.get("/ontology/entity-types")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    assert names >= {"Server", "Attacker"}


@pytest.mark.asyncio
async def test_list_entity_types_empty(http_client):
    resp = await http_client.get("/ontology/entity-types")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_entity_type_detail(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.get("/ontology/entity-types/Server")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Server"
    assert "attributes" in resp.json()


@pytest.mark.asyncio
async def test_get_entity_type_not_found(http_client):
    resp = await http_client.get("/ontology/entity-types/NonExistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_entity_type(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.patch(
        "/ontology/entity-types/Server",
        json={"description": "Updated description"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


@pytest.mark.asyncio
async def test_update_entity_type_not_found(http_client):
    resp = await http_client.patch(
        "/ontology/entity-types/DoesNotExist",
        json={"description": "won't matter"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_entity_type(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.delete("/ontology/entity-types/Server")
    assert resp.status_code == 204
    # Verify it's gone
    assert (await http_client.get("/ontology/entity-types/Server")).status_code == 404


@pytest.mark.asyncio
async def test_delete_entity_type_not_found(http_client):
    resp = await http_client.delete("/ontology/entity-types/NonExistent")
    assert resp.status_code == 404


# ── Attribute ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_attribute(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.post(
        "/ontology/entity-types/Server/attributes",
        json={
            "name": "IP Address",
            "data_type": "STRING",
            "required": True,
            "cardinality": "SINGLE",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "IP Address"
    assert data["data_type"] == "STRING"
    assert data["required"] is True
    assert data["entity_type_name"] == "Server"


@pytest.mark.asyncio
async def test_add_attribute_on_nonexistent_type(http_client):
    resp = await http_client.post(
        "/ontology/entity-types/NonExistent/attributes",
        json={"name": "IP Address", "data_type": "STRING"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_attributes(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post(
        "/ontology/entity-types/Server/attributes",
        json={"name": "IP Address", "data_type": "STRING"},
    )
    await http_client.post(
        "/ontology/entity-types/Server/attributes",
        json={"name": "Hostname", "data_type": "STRING"},
    )
    resp = await http_client.get("/ontology/entity-types/Server/attributes")
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()}
    assert names >= {"IP Address", "Hostname"}


@pytest.mark.asyncio
async def test_update_attribute(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post(
        "/ontology/entity-types/Server/attributes",
        json={"name": "IP Address", "data_type": "STRING", "required": False},
    )
    resp = await http_client.patch(
        "/ontology/entity-types/Server/attributes/IP Address",
        json={"required": True, "cardinality": "MANY"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["required"] is True
    assert data["cardinality"] == "MANY"


@pytest.mark.asyncio
async def test_delete_attribute(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post(
        "/ontology/entity-types/Server/attributes",
        json={"name": "IP Address", "data_type": "STRING"},
    )
    resp = await http_client.delete("/ontology/entity-types/Server/attributes/IP Address")
    assert resp.status_code == 204


# ── RelationshipType ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_relationship_type(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Attacker"})
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.post(
        "/ontology/relationship-types",
        json={
            "name": "UNAUTHORIZED_ACCESS",
            "source_type": "Attacker",
            "target_type": "Server",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "UNAUTHORIZED_ACCESS"
    assert data["source_type"] == "Attacker"
    assert data["target_type"] == "Server"


@pytest.mark.asyncio
async def test_create_relationship_type_missing_source(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    resp = await http_client.post(
        "/ontology/relationship-types",
        json={"name": "UNAUTHORIZED_ACCESS", "source_type": "Ghost", "target_type": "Server"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_relationship_types(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Attacker"})
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post(
        "/ontology/relationship-types",
        json={"name": "UNAUTHORIZED_ACCESS", "source_type": "Attacker", "target_type": "Server"},
    )
    resp = await http_client.get("/ontology/relationship-types")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    assert "UNAUTHORIZED_ACCESS" in names


@pytest.mark.asyncio
async def test_get_relationship_type(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Attacker"})
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post(
        "/ontology/relationship-types",
        json={"name": "UNAUTHORIZED_ACCESS", "source_type": "Attacker", "target_type": "Server"},
    )
    resp = await http_client.get("/ontology/relationship-types/UNAUTHORIZED_ACCESS")
    assert resp.status_code == 200
    assert resp.json()["name"] == "UNAUTHORIZED_ACCESS"


@pytest.mark.asyncio
async def test_update_relationship_type(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Attacker"})
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post("/ontology/entity-types", json={"name": "Vulnerability"})
    await http_client.post(
        "/ontology/relationship-types",
        json={"name": "EXPLOITS", "source_type": "Attacker", "target_type": "Server"},
    )
    resp = await http_client.patch(
        "/ontology/relationship-types/EXPLOITS",
        json={"target_type": "Vulnerability"},
    )
    assert resp.status_code == 200
    assert resp.json()["target_type"] == "Vulnerability"


@pytest.mark.asyncio
async def test_delete_relationship_type(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Attacker"})
    await http_client.post("/ontology/entity-types", json={"name": "Server"})
    await http_client.post(
        "/ontology/relationship-types",
        json={"name": "UNAUTHORIZED_ACCESS", "source_type": "Attacker", "target_type": "Server"},
    )
    resp = await http_client.delete("/ontology/relationship-types/UNAUTHORIZED_ACCESS")
    assert resp.status_code == 204
