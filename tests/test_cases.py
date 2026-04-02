"""
Phase 3 tests — case management and case entity membership.

Run against a live Neo4j instance:
    cd ~/projects/projet-nexus
    pytest tests/test_cases.py -v

Tests are isolated per tenant via conftest.py clean_tenant fixture.
"""
import pytest


async def _seed_case_graph(http_client):
    await http_client.post("/ontology/entity-types", json={"name": "Customer"})
    await http_client.post(
        "/ontology/entity-types/Customer/attributes",
        json={"name": "Customer Name", "data_type": "STRING"},
    )
    await http_client.post("/ontology/entity-types", json={"name": "Contract"})
    await http_client.post(
        "/ontology/entity-types/Contract/attributes",
        json={"name": "Contract Name", "data_type": "STRING"},
    )

    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "customer1",
                    "type_name": "Customer",
                    "values": [{"name": "Customer Name", "value_string": "Acme Corp"}],
                },
                {
                    "op": "create_entity",
                    "alias": "contract1",
                    "type_name": "Contract",
                    "values": [{"name": "Contract Name", "value_string": "Acme FY26"}],
                },
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["entity_map"]["customer1"], data["entity_map"]["contract1"]


@pytest.mark.asyncio
async def test_add_case_entity_links_entity_and_writes_action_log(http_client):
    customer_id, contract_id = await _seed_case_graph(http_client)
    case_resp = await http_client.post(
        "/cases",
        json={
            "title": "Renewal risk",
            "description": "Track commercial exposure",
            "priority": "high",
            "entity_ids": [customer_id],
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    add_resp = await http_client.post(
        f"/cases/{case_id}/entities",
        json={"entity_id": contract_id},
    )
    assert add_resp.status_code == 200
    data = add_resp.json()
    entity_ids = {entity["entity_id"] for entity in data["entities"]}
    assert entity_ids == {customer_id, contract_id}
    assert any(action["action_type"] == "case_entity_added" for action in data["recent_actions"])


@pytest.mark.asyncio
async def test_remove_case_entity_unlinks_entity_and_writes_action_log(http_client):
    customer_id, contract_id = await _seed_case_graph(http_client)
    case_resp = await http_client.post(
        "/cases",
        json={
            "title": "Renewal risk",
            "description": "Track commercial exposure",
            "priority": "high",
            "entity_ids": [customer_id, contract_id],
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    remove_resp = await http_client.delete(f"/cases/{case_id}/entities/{contract_id}")
    assert remove_resp.status_code == 200
    data = remove_resp.json()
    entity_ids = {entity["entity_id"] for entity in data["entities"]}
    assert entity_ids == {customer_id}
    assert any(action["action_type"] == "case_entity_removed" for action in data["recent_actions"])


@pytest.mark.asyncio
async def test_remove_case_entity_requires_existing_membership(http_client):
    customer_id, contract_id = await _seed_case_graph(http_client)
    case_resp = await http_client.post(
        "/cases",
        json={
            "title": "Renewal risk",
            "priority": "medium",
            "entity_ids": [customer_id],
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    remove_resp = await http_client.delete(f"/cases/{case_id}/entities/{contract_id}")
    assert remove_resp.status_code == 404
    assert "not linked" in remove_resp.json()["detail"]
