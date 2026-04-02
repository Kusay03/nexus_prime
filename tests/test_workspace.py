"""
Workspace dashboard regression tests.
"""
import pytest


@pytest.mark.asyncio
async def test_dashboard_returns_zero_metrics_for_empty_tenant(http_client):
    resp = await http_client.get("/workspace/dashboard")

    assert resp.status_code == 200

    data = resp.json()
    assert data["vertical"] == "Revenue Operations"
    assert [metric["value"] for metric in data["metrics"]] == [0, 0, 0, 0, 0]
    assert data["priority_investigations"] == []
    assert data["recent_views"] == []
    assert data["recent_cases"] == []
    assert data["highlighted_entities"] == []


@pytest.mark.asyncio
async def test_dashboard_returns_showcase_data_after_revenue_seed(http_client):
    seed_resp = await http_client.post("/workspace/verticals/revenue-ops/seed")
    assert seed_resp.status_code == 201

    resp = await http_client.get("/workspace/dashboard")
    assert resp.status_code == 200

    data = resp.json()
    assert [metric["value"] for metric in data["metrics"]] == [3, 3, 3, 3, 2]
    assert len(data["priority_investigations"]) >= 1
    assert len(data["recent_views"]) == 3
    assert len(data["recent_cases"]) == 2
    assert len(data["highlighted_entities"]) >= 3
    assert any(case["title"] == "Acme renewal rescue" for case in data["recent_cases"])
    assert any(view["name"] == "Launch Risk Rollup" for view in data["recent_views"])


@pytest.mark.asyncio
async def test_workspace_priorities_and_brief_return_ranked_investigation_data(http_client):
    seed_resp = await http_client.post("/workspace/verticals/revenue-ops/seed")
    assert seed_resp.status_code == 201

    priorities_resp = await http_client.get("/workspace/priorities")
    assert priorities_resp.status_code == 200
    priorities = priorities_resp.json()
    assert priorities
    assert priorities[0]["score"] >= priorities[-1]["score"]

    root_entity_id = priorities[0]["root_entity_id"]
    brief_resp = await http_client.get(f"/workspace/briefs/{root_entity_id}")
    assert brief_resp.status_code == 200

    brief = brief_resp.json()
    assert brief["entity_id"] == root_entity_id
    assert brief["title"].startswith("Investigation brief:")
    assert brief["summary"]
    assert brief["why_now"]
    assert brief["confidence"] in {"low", "medium", "high"}
    assert brief["recommended_actions"]
    assert brief["linked_entity_ids"]


@pytest.mark.asyncio
async def test_cyber_threat_seed_creates_phase1_demo_graph(http_client):
    seed_resp = await http_client.post("/workspace/verticals/cyber-threat/seed")
    assert seed_resp.status_code == 201

    seed_data = seed_resp.json()
    assert seed_data["vertical"] == "Cyber Threat"
    assert seed_data["seeded"] is True
    assert seed_data["entities"] == 4
    assert seed_data["saved_views"] == 1

    search_resp = await http_client.post(
        "/query/search",
        json={"query": "CVE-2026-1337", "limit": 10},
    )
    assert search_resp.status_code == 200
    search_results = search_resp.json()["results"]
    assert len(search_results) == 1

    vulnerability = search_results[0]
    assert vulnerability["type_name"] == "Vulnerability"
    assert vulnerability["properties"]["Severity"] == "Critical"
    vulnerability_id = vulnerability["entity_id"]

    traverse_resp = await http_client.post(
        "/query/traverse",
        json={"entity_id": vulnerability_id, "depth": 1},
    )
    assert traverse_resp.status_code == 200

    graph = traverse_resp.json()
    node_types = {node["data"]["type"] for node in graph["nodes"]}
    edge_labels = {edge["data"]["label"] for edge in graph["edges"]}
    assert node_types == {"Attacker", "Vulnerability", "Server"}
    assert edge_labels == {"EXPLOITS", "AFFECTS"}
