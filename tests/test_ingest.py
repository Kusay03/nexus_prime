"""
Phase 2 tests — data ingestion (JSON bulk + CSV).

Run against a live Neo4j instance:
    cd ~/projects/projet-nexus
    pytest tests/test_ingest.py -v

Tests are isolated per tenant via conftest.py clean_tenant fixture.
Requires admin or analyst role.
"""
import csv
import io

import pytest


async def _seed_cyber_ontology(http_client):
    """Helper: create the cyber ontology types needed by ingest tests."""
    for name, desc, attrs in [
        ("Attacker", "Malicious actor", [
            ("Username", "STRING"),
            ("Threat Level", "NUMBER"),
        ]),
        ("Server", "Network server", [
            ("IP Address", "STRING"),
            ("Hostname", "STRING"),
        ]),
        ("Vulnerability", "Software vulnerability", [
            ("CVE ID", "STRING"),
            ("Severity", "STRING"),
        ]),
    ]:
        await http_client.post("/ontology/entity-types", json={"name": name, "description": desc})
        for attr_name, dtype in attrs:
            await http_client.post(
                f"/ontology/entity-types/{name}/attributes",
                json={"name": attr_name, "data_type": dtype},
            )
    for rel_name, src, tgt in [
        ("UNAUTHORIZED_ACCESS", "Attacker", "Server"),
        ("EXPLOITS", "Attacker", "Vulnerability"),
        ("AFFECTS", "Vulnerability", "Server"),
    ]:
        await http_client.post(
            "/ontology/relationship-types",
            json={"name": rel_name, "source_type": src, "target_type": tgt},
        )


# ── JSON /bulk ingestion ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_json_creates_entities(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "attacker1",
                    "type_name": "Attacker",
                    "values": [
                        {"name": "Username", "value_string": "hacker_99"},
                        {"name": "Threat Level", "value_numeric": 85.5},
                    ],
                },
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entities_created"] == 1
    assert "attacker1" in data["entity_map"]


@pytest.mark.asyncio
async def test_ingest_json_creates_connections(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "attacker1",
                    "type_name": "Attacker",
                    "values": [{"name": "Username", "value_string": "hacker_99"}],
                },
                {
                    "op": "create_entity",
                    "alias": "server1",
                    "type_name": "Server",
                    "values": [{"name": "IP Address", "value_string": "192.168.1.10"}],
                },
                {
                    "op": "create_connection",
                    "alias": "conn1",
                    "source_alias": "attacker1",
                    "target_alias": "server1",
                    "relationship_type": "UNAUTHORIZED_ACCESS",
                },
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["connections_created"] == 1
    assert data["entities_created"] == 2


@pytest.mark.asyncio
async def test_ingest_json_rejects_connection_when_entity_types_do_not_match_relationship(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "server1",
                    "type_name": "Server",
                    "values": [{"name": "IP Address", "value_string": "192.168.1.10"}],
                },
                {
                    "op": "create_entity",
                    "alias": "vuln1",
                    "type_name": "Vulnerability",
                    "values": [{"name": "CVE ID", "value_string": "CVE-2026-0001"}],
                },
                {
                    "op": "create_connection",
                    "source_alias": "server1",
                    "target_alias": "vuln1",
                    "relationship_type": "UNAUTHORIZED_ACCESS",
                },
            ]
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == (
        "RelationshipType 'UNAUTHORIZED_ACCESS' expects Attacker -> Server, "
        "got Server -> Vulnerability"
    )

    search_resp = await http_client.post("/query/search", json={"query": "CVE-2026-0001"})
    assert search_resp.status_code == 200
    assert search_resp.json()["results"] == []


@pytest.mark.asyncio
async def test_ingest_json_rejects_missing_required_attributes(http_client):
    await http_client.post(
        "/ontology/entity-types",
        json={"name": "Incident", "description": "Tracked incident"},
    )
    await http_client.post(
        "/ontology/entity-types/Incident/attributes",
        json={"name": "Title", "data_type": "STRING", "required": True},
    )

    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "incident1",
                    "type_name": "Incident",
                    "values": [],
                },
            ]
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Missing required attributes for EntityType 'Incident': Title"


@pytest.mark.asyncio
async def test_ingest_json_rejects_multiple_values_for_single_cardinality_attribute(http_client):
    await _seed_cyber_ontology(http_client)

    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "attacker1",
                    "type_name": "Attacker",
                    "values": [
                        {"name": "Username", "value_string": "hacker_99"},
                        {"name": "Username", "value_string": "duplicate_alias"},
                    ],
                },
            ]
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == (
        "Attribute 'Username' on EntityType 'Attacker' allows only a single value"
    )


@pytest.mark.asyncio
async def test_ingest_json_rejects_attribute_value_with_wrong_data_type(http_client):
    await _seed_cyber_ontology(http_client)

    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "attacker1",
                    "type_name": "Attacker",
                    "values": [
                        {"name": "Username", "value_string": "hacker_99"},
                        {"name": "Threat Level", "value_string": "high"},
                    ],
                },
            ]
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == (
        "Attribute 'Threat Level' on EntityType 'Attacker' expects NUMBER, got STRING"
    )


@pytest.mark.asyncio
async def test_ingest_json_invalid_type_returns_422(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "bad",
                    "type_name": "GhostType",
                    "values": [],
                },
            ]
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_json_connection_unknown_alias_returns_422(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/json",
        json={
            "operations": [
                {
                    "op": "create_connection",
                    "alias": "orphan",
                    "source_alias": "ghost_src",
                    "target_alias": "ghost_tgt",
                    "relationship_type": "UNAUTHORIZED_ACCESS",
                },
            ]
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_webhook_creates_entities_and_connections(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/webhook",
        json={
            "source": "crowdstrike",
            "event_type": "alert.created",
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "attacker1",
                    "type_name": "Attacker",
                    "values": [{"name": "Username", "value_string": "webhook_actor"}],
                },
                {
                    "op": "create_entity",
                    "alias": "server1",
                    "type_name": "Server",
                    "values": [{"name": "IP Address", "value_string": "10.10.10.10"}],
                },
                {
                    "op": "create_connection",
                    "source_alias": "attacker1",
                    "target_alias": "server1",
                    "relationship_type": "UNAUTHORIZED_ACCESS",
                },
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source"] == "crowdstrike"
    assert data["event_type"] == "alert.created"
    assert data["event_id"]
    assert data["entities_created"] == 2
    assert data["connections_created"] == 1


@pytest.mark.asyncio
async def test_ingest_webhook_rejects_connection_when_relationship_direction_is_wrong(http_client):
    await _seed_cyber_ontology(http_client)
    resp = await http_client.post(
        "/ingest/webhook",
        json={
            "source": "crowdstrike",
            "event_type": "alert.created",
            "operations": [
                {
                    "op": "create_entity",
                    "alias": "server1",
                    "type_name": "Server",
                    "values": [{"name": "IP Address", "value_string": "10.10.10.10"}],
                },
                {
                    "op": "create_entity",
                    "alias": "attacker1",
                    "type_name": "Attacker",
                    "values": [{"name": "Username", "value_string": "reverse_edge_actor"}],
                },
                {
                    "op": "create_connection",
                    "source_alias": "server1",
                    "target_alias": "attacker1",
                    "relationship_type": "UNAUTHORIZED_ACCESS",
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == (
        "RelationshipType 'UNAUTHORIZED_ACCESS' expects Attacker -> Server, "
        "got Server -> Attacker"
    )

    search_resp = await http_client.post("/query/search", json={"query": "reverse_edge_actor"})
    assert search_resp.status_code == 200
    assert search_resp.json()["results"] == []


# ── CSV ingestion ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_csv_creates_entities(http_client):
    await _seed_cyber_ontology(http_client)
    csv_content = csv.StringIO()
    writer = csv.writer(csv_content)
    writer.writerow(["Username", "Threat Level"])
    writer.writerow(["hacker_99", "85.5"])
    writer.writerow(["script_kiddie", "20"])
    csv_content.seek(0)

    resp = await http_client.post(
        "/ingest/csv",
        data={"type_name": "Attacker", "column_map": '{"Username": "Username", "Threat Level": "Threat Level"}'},
        files={"file": ("test.csv", csv_content.read().encode(), "text/csv")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_rows"] == 2
    assert data["ingested"] == 2
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_ingest_csv_invalid_json_column_map(http_client):
    await _seed_cyber_ontology(http_client)
    csv_content = csv.StringIO()
    writer = csv.writer(csv_content)
    writer.writerow(["Username"])
    writer.writerow(["hacker_99"])
    csv_content.seek(0)

    resp = await http_client.post(
        "/ingest/csv",
        data={"type_name": "Attacker", "column_map": "not-valid-json"},
        files={"file": ("test.csv", csv_content.read().encode(), "text/csv")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_csv_failed_rows_go_to_dlq(http_client):
    await _seed_cyber_ontology(http_client)
    csv_content = csv.StringIO()
    writer = csv.writer(csv_content)
    writer.writerow(["Username", "Threat Level"])
    writer.writerow(["valid", "10"])      # valid
    writer.writerow(["", ""])              # empty — will fail (no valid attrs after mapping)
    csv_content.seek(0)

    resp = await http_client.post(
        "/ingest/csv",
        data={"type_name": "Attacker", "column_map": '{"Username": "Username", "Threat Level": "Threat Level"}'},
        files={"file": ("test.csv", csv_content.read().encode(), "text/csv")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["failed"] == 1
    assert "dlq_key" in data


@pytest.mark.asyncio
async def test_ingest_csv_routes_missing_required_attributes_to_dlq(http_client):
    await http_client.post(
        "/ontology/entity-types",
        json={"name": "Incident", "description": "Tracked incident"},
    )
    await http_client.post(
        "/ontology/entity-types/Incident/attributes",
        json={"name": "Title", "data_type": "STRING", "required": True},
    )
    await http_client.post(
        "/ontology/entity-types/Incident/attributes",
        json={"name": "Summary", "data_type": "STRING"},
    )

    csv_content = csv.StringIO()
    writer = csv.writer(csv_content)
    writer.writerow(["Title", "Summary"])
    writer.writerow(["", "Missing title should fail"])
    csv_content.seek(0)

    ingest_resp = await http_client.post(
        "/ingest/csv",
        data={"type_name": "Incident", "column_map": '{"Title": "Title", "Summary": "Summary"}'},
        files={"file": ("incidents.csv", csv_content.read().encode(), "text/csv")},
    )

    assert ingest_resp.status_code == 201
    ingest_data = ingest_resp.json()
    assert ingest_data["ingested"] == 0
    assert ingest_data["failed"] == 1

    dlq_resp = await http_client.get("/ingest/dlq", params={"key": ingest_data["dlq_key"]})
    assert dlq_resp.status_code == 200
    dlq_data = dlq_resp.json()
    assert dlq_data["count"] == 1
    assert dlq_data["items"][0]["error"] == (
        "Missing required attributes for EntityType 'Incident': Title"
    )


@pytest.mark.asyncio
async def test_retry_dlq_recovers_rows_after_schema_fix(http_client):
    await http_client.post(
        "/ontology/entity-types",
        json={"name": "Campaign", "description": "Marketing campaign"},
    )
    await http_client.post(
        "/ontology/entity-types/Campaign/attributes",
        json={"name": "Name", "data_type": "STRING"},
    )

    csv_content = csv.StringIO()
    writer = csv.writer(csv_content)
    writer.writerow(["Name", "Stage"])
    writer.writerow(["Q1 Launch", "planned"])
    writer.writerow(["Q2 Renewal", "active"])
    csv_content.seek(0)

    ingest_resp = await http_client.post(
        "/ingest/csv",
        data={"type_name": "Campaign", "column_map": '{"Name": "Name", "Stage": "Stage"}'},
        files={"file": ("campaigns.csv", csv_content.read().encode(), "text/csv")},
    )
    assert ingest_resp.status_code == 201
    ingest_data = ingest_resp.json()
    assert ingest_data["ingested"] == 0
    assert ingest_data["failed"] == 2

    dlq_key = ingest_data["dlq_key"]
    dlq_resp = await http_client.get("/ingest/dlq", params={"key": dlq_key})
    assert dlq_resp.status_code == 200
    dlq_data = dlq_resp.json()
    assert dlq_data["count"] == 2
    assert all(item["type_name"] == "Campaign" for item in dlq_data["items"])
    assert all(item["column_map"]["Stage"] == "Stage" for item in dlq_data["items"])

    await http_client.post(
        "/ontology/entity-types/Campaign/attributes",
        json={"name": "Stage", "data_type": "STRING"},
    )

    retry_resp = await http_client.post("/ingest/dlq/retry", json={"key": dlq_key})
    assert retry_resp.status_code == 200
    retry_data = retry_resp.json()
    assert retry_data["requested"] == 2
    assert retry_data["recovered"] == 2
    assert retry_data["remaining"] == 0
    assert retry_data["failed"] == []

    after_resp = await http_client.get("/ingest/dlq", params={"key": dlq_key})
    assert after_resp.status_code == 200
    assert after_resp.json()["count"] == 0
