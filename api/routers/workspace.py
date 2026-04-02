import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from neo4j import AsyncSession
from redis.asyncio import Redis

from config import settings
from db import get_session
from middleware.tenant import get_current_user, require_roles
from models.auth import CurrentUser, Role
from models.workspace import (
    AlertDecision,
    AlertDecisionRequest,
    AlertDecisionResponse,
    AlertSummary,
    AiOntologySeedResponse,
    DashboardMetric,
    DashboardSummaryResponse,
    InvestigationBriefItem,
    InvestigationBriefResponse,
    PriorityInvestigation,
    SavedViewCreate,
    SavedViewResponse,
    SearchResult,
    WorkspaceSystemStatus,
    WorkspaceSystemSummary,
    VerticalSeedResponse,
)
from redis_client import get_redis

router = APIRouter()
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def _pick_label(type_name: str, properties: dict[str, str]) -> str:
    preferred_keys = (
        "Display Name",
        "Customer Name",
        "Invoice Number",
        "Contract Name",
        "Ticket ID",
        "Owner Name",
        "Document Title",
        "Observation",
        "Hypothesis",
        "Alert Title",
        "Recommendation",
        "Run Label",
        "Template Name",
        "Name",
        "name",
        "Username",
        "Hostname",
        "IP Address",
        "Email",
        "Domain",
    )
    for key in preferred_keys:
        value = properties.get(key)
        if value:
            return value
    for value in properties.values():
        if value:
            return value
    return type_name


def _highlight_reason(type_name: str, properties: dict[str, str]) -> str:
    if type_name == "Customer":
        renewal = properties.get("Renewal Window")
        health = properties.get("Health Status", "Needs review")
        if renewal:
            return f"{health} • renews in {renewal}"
        return f"Health: {health}"
    if type_name == "Invoice":
        status = properties.get("Payment Status", "Unknown")
        days_late = properties.get("Days Late")
        if days_late not in (None, ""):
            return f"{status} • {days_late} days late"
        return f"Payment: {status}"
    if type_name == "SupportTicket":
        return f"{properties.get('Severity', 'Unspecified')} severity • {properties.get('Status', 'Open')}"
    if type_name == "Contract":
        return f"Renewal due {properties.get('Renewal Date', properties.get('Renewal Window', 'Active'))}"
    if type_name == "Document":
        return f"Source: {properties.get('Source System', 'Analyst input')}"
    if type_name == "Observation":
        return properties.get("Display Name") or f"Confidence: {properties.get('Confidence', 'Pending review')}"
    if type_name == "Hypothesis":
        return properties.get("Display Name") or f"Risk: {properties.get('Risk Level', 'Review')}"
    if type_name == "Alert":
        return properties.get("Display Name") or f"Score: {properties.get('Risk Score', 'Unknown')}"
    if type_name == "Recommendation":
        return properties.get("Display Name") or f"Priority: {properties.get('Priority', 'Review')}"
    if type_name == "ModelRun":
        return properties.get("Display Name") or f"Model: {properties.get('Model Name', 'Unknown')}"
    if type_name == "PromptTemplate":
        return properties.get("Display Name") or f"Prompt: {properties.get('Prompt Version', 'Current')}"
    return "Operational hotspot"


def _map_view(record: dict) -> SavedViewResponse:
    return SavedViewResponse(
        view_id=record["view_id"],
        name=record["name"],
        description=record.get("description"),
        root_entity_id=record["root_entity_id"],
        depth=record["depth"],
        layout=record["layout"],
        tenant_id=record["tenant_id"],
        created_by=record["created_by"],
        created_at=str(record["created_at"]) if record.get("created_at") else None,
    )


def _properties_from_values(values: list[dict[str, str]]) -> dict[str, str]:
    return {value["name"]: value["value"] for value in values}


def _safe_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_count(metric_row: dict, key: str) -> int:
    value = metric_row.get(key)
    return int(value) if value is not None else 0


def _safe_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _humanize_type(type_name: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(type_name):
        if index > 0 and char.isupper() and type_name[index - 1].islower():
            chars.append(" ")
        chars.append(char)
    return "".join(chars).lower()


def _recommended_action(type_name: str, properties: dict[str, str]) -> str:
    if type_name == "Alert":
        return "Review this signal, confirm the evidence, and decide whether to escalate it into a case."
    if type_name == "Hypothesis":
        return "Validate the supporting evidence and decide whether this hypothesis should drive an investigation."
    if type_name == "Invoice":
        return "Check the linked business impact and confirm whether this payment issue changes the investigation priority."
    if type_name == "SupportTicket":
        return "Verify the operational impact, owner, and current status before it spreads to adjacent entities."
    if type_name == "Customer":
        health = properties.get("Health Status")
        if health:
            return f"Review the linked signals around this customer and confirm whether the current {health.lower()} state requires action."
        return "Review the surrounding connected entities and decide whether this customer needs an active investigation."
    if type_name == "Contract":
        return "Confirm the commercial timeline and inspect linked entities that could change the outcome of this contract."
    if type_name in {"Document", "PromptTemplate", "ModelRun"}:
        return "Use this provenance trail to verify the source material behind the investigation narrative."
    return "Inspect the strongest connected signals and decide whether to open or update a case."


def _priority_reason(type_name: str, properties: dict[str, str], open_case_count: int, recent_action_count: int) -> str:
    risk_score = _safe_int(properties.get("Risk Score"))
    if risk_score is not None:
        return f"Risk score {risk_score} with supporting connected evidence."

    days_late = _safe_int(properties.get("Days Late"))
    if days_late is not None and days_late > 0:
        return f"Payment pressure is visible: {days_late} days late."

    health_status = properties.get("Health Status")
    renewal_window = properties.get("Renewal Window") or properties.get("Renewal Date")
    if health_status and renewal_window:
        return f"{health_status} status with timing pressure around {renewal_window}."

    severity = properties.get("Severity")
    status_value = properties.get("Status")
    if severity and status_value:
        return f"{severity} severity item currently marked {status_value.lower()}."

    if open_case_count:
        return f"Already linked to {open_case_count} open case{'s' if open_case_count != 1 else ''}."

    if recent_action_count:
        return f"Recent operator activity suggests this entity is already under review."

    return _highlight_reason(type_name, properties)


def _priority_score(
    *,
    type_name: str,
    properties: dict[str, str],
    relationship_count: int,
    open_case_count: int,
    recent_action_count: int,
) -> int:
    score = relationship_count * 4
    score += open_case_count * 14
    score += recent_action_count * 4

    type_bonus = {
        "Alert": 22,
        "Hypothesis": 18,
        "Customer": 14,
        "Invoice": 12,
        "Contract": 10,
        "SupportTicket": 10,
        "Recommendation": 8,
    }
    score += type_bonus.get(type_name, 0)

    risk_score = _safe_int(properties.get("Risk Score"))
    if risk_score is not None:
        score += min(risk_score // 4, 25)

    days_late = _safe_int(properties.get("Days Late"))
    if days_late is not None and days_late > 0:
        score += min(days_late, 20)

    severity = (properties.get("Severity") or "").lower()
    if severity in {"critical", "high"}:
        score += 12
    elif severity == "medium":
        score += 6

    health_status = (properties.get("Health Status") or "").lower()
    if "risk" in health_status:
        score += 14
    elif "attention" in health_status:
        score += 8

    payment_status = (properties.get("Payment Status") or "").lower()
    if "overdue" in payment_status:
        score += 10
    elif "due" in payment_status:
        score += 4

    if (properties.get("Alert Status") or "").lower() == "open":
        score += 6
    if (properties.get("Review Status") or "").lower() == "pending":
        score += 4

    return score


async def _count_nodes(
    session: AsyncSession,
    tenant_id: str,
    label: str,
    extra_where: str = "",
) -> int:
    result = await session.run(
        f"""
        MATCH (n:{label} {{tenant_id: $tenant_id}})
        {extra_where}
        RETURN count(n) AS count
        """,
        tenant_id=tenant_id,
    )
    record = await result.single()
    return record["count"] if record else 0


async def _set_entity_string_value(
    session: AsyncSession,
    tenant_id: str,
    entity_id: str,
    type_name: str,
    attribute_name: str,
    value: str,
) -> None:
    await session.run(
        """
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})-[:INSTANCE_OF]->(et:EntityType {name: $type_name, tenant_id: $tenant_id})
        MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attribute_name, tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[existing:HAS_VALUE]->(a)
        DELETE existing
        CREATE (e)-[:HAS_VALUE {value_string: $value}]->(a)
        """,
        tenant_id=tenant_id,
        entity_id=entity_id,
        type_name=type_name,
        attribute_name=attribute_name,
        value=value,
    )


async def _highlighted_entities(
    tenant_id: str,
    session: AsyncSession,
) -> list[SearchResult]:
    result = await session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        OPTIONAL MATCH (e)-[r:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        WITH
            e,
            count(DISTINCT r) AS relationship_count,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        WITH
            e,
            relationship_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        RETURN
            e.id AS entity_id,
            e.type_name AS type_name,
            relationship_count,
            values
        ORDER BY relationship_count DESC, e.created_at DESC
        LIMIT 6
        """,
        tenant_id=tenant_id,
    )
    rows = await result.data()
    highlighted: list[SearchResult] = []
    for row in rows:
        properties = {value["name"]: value["value"] for value in row["values"]}
        highlighted.append(
            SearchResult(
                entity_id=row["entity_id"],
                label=_pick_label(row["type_name"], properties),
                type_name=row["type_name"],
                match_reason=_highlight_reason(row["type_name"], properties),
                properties=properties,
                relationship_count=row["relationship_count"],
            )
        )
    return highlighted


async def _entity_snapshot(
    session: AsyncSession,
    tenant_id: str,
    entity_id: str,
) -> dict | None:
    result = await session.run(
        """
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        OPTIONAL MATCH (e)-[r:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)<-[:INVOLVES]-(c:Case {tenant_id: $tenant_id})
        WHERE coalesce(c.status, 'open') <> 'closed'
        OPTIONAL MATCH (e)<-[:TARGETS]-(log:ActionLog {tenant_id: $tenant_id})
        WITH
            e,
            count(DISTINCT r) AS relationship_count,
            count(DISTINCT c) AS open_case_count,
            count(DISTINCT log) AS recent_action_count,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        RETURN
            e.id AS entity_id,
            e.type_name AS type_name,
            relationship_count,
            open_case_count,
            recent_action_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        """,
        entity_id=entity_id,
        tenant_id=tenant_id,
    )
    row = await result.single()
    if not row:
        return None

    properties = _properties_from_values(row["values"])
    return {
        "entity_id": row["entity_id"],
        "type_name": row["type_name"],
        "label": _pick_label(row["type_name"], properties),
        "properties": properties,
        "relationship_count": row["relationship_count"],
        "open_case_count": row["open_case_count"],
        "recent_action_count": row["recent_action_count"],
        "match_reason": _highlight_reason(row["type_name"], properties),
    }


async def _related_entity_snapshots(
    session: AsyncSession,
    tenant_id: str,
    entity_id: str,
    limit: int = 12,
) -> list[dict]:
    result = await session.run(
        """
        MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id})-[r:CONNECTED_TO]-(related:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (related)-[hv:HAS_VALUE]->(a:Attribute)
        OPTIONAL MATCH (related)<-[:INVOLVES]-(c:Case {tenant_id: $tenant_id})
        WHERE coalesce(c.status, 'open') <> 'closed'
        OPTIONAL MATCH (related)<-[:TARGETS]-(log:ActionLog {tenant_id: $tenant_id})
        WITH
            related,
            r.relationship_type AS relationship_type,
            count(DISTINCT c) AS open_case_count,
            count(DISTINCT log) AS recent_action_count,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        OPTIONAL MATCH (related)-[related_edge:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        WITH
            related,
            relationship_type,
            open_case_count,
            recent_action_count,
            count(DISTINCT related_edge) AS relationship_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        RETURN
            related.id AS entity_id,
            related.type_name AS type_name,
            relationship_type,
            open_case_count,
            recent_action_count,
            relationship_count,
            values
        ORDER BY relationship_count DESC, related.created_at DESC
        LIMIT $limit
        """,
        entity_id=entity_id,
        tenant_id=tenant_id,
        limit=limit,
    )
    snapshots: list[dict] = []
    for row in await result.data():
        properties = _properties_from_values(row["values"])
        snapshots.append(
            {
                "entity_id": row["entity_id"],
                "type_name": row["type_name"],
                "relationship_type": row["relationship_type"],
                "properties": properties,
                "label": _pick_label(row["type_name"], properties),
                "relationship_count": row["relationship_count"],
                "open_case_count": row["open_case_count"],
                "recent_action_count": row["recent_action_count"],
                "match_reason": _highlight_reason(row["type_name"], properties),
            }
        )
    return snapshots


def _brief_confidence(signal_count: int, evidence_count: int, open_case_count: int) -> str:
    if signal_count >= 3 or (signal_count >= 2 and evidence_count >= 1) or open_case_count >= 1:
        return "high"
    if signal_count >= 1 or evidence_count >= 1:
        return "medium"
    return "low"


def _brief_title(root: dict) -> str:
    return f"Investigation brief: {root['label']}"


def _build_investigation_brief(root: dict, related_entities: list[dict]) -> InvestigationBriefResponse:
    signal_types = {"Alert", "Hypothesis", "Invoice", "SupportTicket", "Recommendation", "Contract", "Customer"}
    evidence_types = {"Document", "PromptTemplate", "ModelRun", "Observation"}

    ranked_related = sorted(
        related_entities,
        key=lambda item: _priority_score(
            type_name=item["type_name"],
            properties=item["properties"],
            relationship_count=item["relationship_count"],
            open_case_count=item["open_case_count"],
            recent_action_count=item["recent_action_count"],
        ),
        reverse=True,
    )
    top_signals_raw = [item for item in ranked_related if item["type_name"] in signal_types][:4]
    evidence_raw = [item for item in ranked_related if item["type_name"] in evidence_types][:3]

    why_now = _priority_reason(
        root["type_name"],
        root["properties"],
        root["open_case_count"],
        root["recent_action_count"],
    )
    if top_signals_raw:
        why_now = top_signals_raw[0]["match_reason"]

    confidence = _brief_confidence(len(top_signals_raw), len(evidence_raw), root["open_case_count"])
    supporting_labels = ", ".join(item["label"] for item in top_signals_raw[:2])
    if supporting_labels:
        summary = (
            f"{root['label']} is a {_humanize_type(root['type_name'])} connected to {root['relationship_count']} "
            f"linked entities. The strongest signals currently are {supporting_labels}."
        )
    else:
        summary = (
            f"{root['label']} is a {_humanize_type(root['type_name'])} with "
            f"{root['relationship_count']} connected entities available for review."
        )

    recommended_actions = [
        _recommended_action(root["type_name"], root["properties"]),
    ]
    if top_signals_raw:
        recommended_actions.append(
            f"Validate the lead signal '{top_signals_raw[0]['label']}' and confirm whether it changes case priority."
        )
    if evidence_raw:
        recommended_actions.append(
            f"Use '{evidence_raw[0]['label']}' as supporting evidence when sharing the investigation."
        )

    top_signals = [
        InvestigationBriefItem(
            entity_id=item["entity_id"],
            label=item["label"],
            type_name=item["type_name"],
            reason=item["match_reason"],
        )
        for item in top_signals_raw
    ]
    evidence = [
        InvestigationBriefItem(
            entity_id=item["entity_id"],
            label=item["label"],
            type_name=item["type_name"],
            reason=item["match_reason"],
        )
        for item in evidence_raw
    ]

    linked_entity_ids = [root["entity_id"], *[item["entity_id"] for item in top_signals_raw[:7]]]

    return InvestigationBriefResponse(
        entity_id=root["entity_id"],
        title=_brief_title(root),
        type_name=root["type_name"],
        summary=summary,
        why_now=why_now,
        confidence=confidence,
        recommended_actions=recommended_actions,
        top_signals=top_signals,
        evidence=evidence,
        linked_entity_ids=list(dict.fromkeys(linked_entity_ids)),
    )


async def _priority_investigations(
    session: AsyncSession,
    tenant_id: str,
    limit: int = 5,
) -> list[PriorityInvestigation]:
    result = await session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)-[hv:HAS_VALUE]->(a:Attribute)
        OPTIONAL MATCH (e)-[r:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)<-[:INVOLVES]-(c:Case {tenant_id: $tenant_id})
        WHERE coalesce(c.status, 'open') <> 'closed'
        OPTIONAL MATCH (e)<-[:TARGETS]-(log:ActionLog {tenant_id: $tenant_id})
        WITH
            e,
            count(DISTINCT r) AS relationship_count,
            count(DISTINCT c) AS open_case_count,
            count(DISTINCT log) AS recent_action_count,
            collect(
                CASE
                    WHEN a IS NULL THEN NULL
                    ELSE {
                        name: a.name,
                        value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        WITH
            e,
            relationship_count,
            open_case_count,
            recent_action_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        RETURN
            e.id AS entity_id,
            e.type_name AS type_name,
            relationship_count,
            open_case_count,
            recent_action_count,
            values
        ORDER BY relationship_count DESC, e.created_at DESC
        LIMIT 30
        """,
        tenant_id=tenant_id,
    )
    items: list[PriorityInvestigation] = []
    for row in await result.data():
        properties = _properties_from_values(row["values"])
        item = {
            "entity_id": row["entity_id"],
            "type_name": row["type_name"],
            "properties": properties,
            "label": _pick_label(row["type_name"], properties),
            "relationship_count": row["relationship_count"],
            "open_case_count": row["open_case_count"],
            "recent_action_count": row["recent_action_count"],
            "match_reason": _highlight_reason(row["type_name"], properties),
        }
        score = _priority_score(
            type_name=item["type_name"],
            properties=item["properties"],
            relationship_count=item["relationship_count"],
            open_case_count=item["open_case_count"],
            recent_action_count=item["recent_action_count"],
        )
        linked_signal_count = sum(
            1 for key in ("Risk Score", "Severity", "Days Late", "Health Status", "Alert Status", "Review Status")
            if item["properties"].get(key) not in (None, "")
        )
        items.append(
            PriorityInvestigation(
                root_entity_id=item["entity_id"],
                title=item["label"],
                type_name=item["type_name"],
                score=score,
                why_now=_priority_reason(
                    item["type_name"],
                    item["properties"],
                    item["open_case_count"],
                    item["recent_action_count"],
                ),
                recommended_action=_recommended_action(item["type_name"], item["properties"]),
                linked_signal_count=max(linked_signal_count, 1 if item["relationship_count"] > 0 else 0),
                open_case_count=item["open_case_count"],
            )
        )
    items.sort(key=lambda item: (-item.score, item.title.lower()))
    return items[:limit]


@router.get("/dashboard", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummaryResponse:
    tenant_id = current_user.tenant_id
    priority_investigations = await _priority_investigations(session, tenant_id, limit=4)

    metric_result = await session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        WITH e.type_name AS type_name, count(*) AS cnt
        WHERE type_name IN ['Customer', 'Contract', 'Invoice', 'SupportTicket']
        RETURN
            max(CASE type_name WHEN 'Customer'      THEN cnt END) AS customers,
            max(CASE type_name WHEN 'Contract'      THEN cnt END) AS contracts,
            max(CASE type_name WHEN 'Invoice'       THEN cnt END) AS invoices,
            max(CASE type_name WHEN 'SupportTicket' THEN cnt END) AS tickets
        """,
        tenant_id=tenant_id,
    )
    case_result = await session.run(
        """
        MATCH (c:Case {tenant_id: $tenant_id})
        WHERE coalesce(c.status, 'open') <> 'closed'
        RETURN count(*) AS cases
        """,
        tenant_id=tenant_id,
    )
    case_count_record = await case_result.single()
    cases = case_count_record["cases"] if case_count_record else 0

    metric_row = await metric_result.single()
    if not metric_row:
        raise HTTPException(status_code=500, detail="Failed to load dashboard metrics")

    view_result = await session.run(
        """
        MATCH (v:SavedView {tenant_id: $tenant_id})
        RETURN
            v.id AS view_id,
            v.name AS name,
            v.description AS description,
            v.root_entity_id AS root_entity_id,
            v.depth AS depth,
            v.layout AS layout,
            v.tenant_id AS tenant_id,
            v.created_by AS created_by,
            v.created_at AS created_at
        ORDER BY v.created_at DESC
        LIMIT 5
        """,
        tenant_id=tenant_id,
    )
    case_result = await session.run(
        """
        MATCH (c:Case {tenant_id: $tenant_id})
        OPTIONAL MATCH (c)-[:INVOLVES]->(e:Entity {tenant_id: $tenant_id})
        RETURN
            c.id AS case_id,
            c.title AS title,
            c.priority AS priority,
            c.status AS status,
            c.tenant_id AS tenant_id,
            c.created_by AS created_by,
            c.created_at AS created_at,
            c.updated_at AS updated_at,
            count(DISTINCT e) AS entity_count
        ORDER BY c.updated_at DESC
        LIMIT 5
        """,
        tenant_id=tenant_id,
    )

    metrics = [
        DashboardMetric(
            label="Customers",
            value=_metric_count(metric_row, "customers"),
            change_hint="Accounts under active management",
        ),
        DashboardMetric(
            label="Contracts",
            value=_metric_count(metric_row, "contracts"),
            change_hint="Renewals and commercial obligations",
        ),
        DashboardMetric(
            label="Invoices",
            value=_metric_count(metric_row, "invoices"),
            change_hint="Billing objects tied into customer health",
        ),
        DashboardMetric(
            label="Open Tickets",
            value=_metric_count(metric_row, "tickets"),
            change_hint="Support pressure affecting retention",
        ),
        DashboardMetric(
            label="Open Cases",
            value=cases,
            change_hint="Revenue-risk investigations currently tracked",
        ),
    ]

    return DashboardSummaryResponse(
        vertical="Revenue Operations",
        metrics=metrics,
        priority_investigations=priority_investigations,
        recent_views=[_map_view(record) for record in await view_result.data()],
        recent_cases=[
            {
                "case_id": record["case_id"],
                "title": record["title"],
                "priority": record["priority"],
                "status": record["status"],
                "tenant_id": record["tenant_id"],
                "created_by": record["created_by"],
                "entity_count": record["entity_count"],
                "updated_at": str(record["updated_at"]) if record["updated_at"] else None,
                "created_at": str(record["created_at"]) if record["created_at"] else None,
            }
            for record in await case_result.data()
        ],
        highlighted_entities=await _highlighted_entities(tenant_id, session),
    )


@router.get("/priorities", response_model=list[PriorityInvestigation])
async def list_priority_investigations(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PriorityInvestigation]:
    return await _priority_investigations(session, current_user.tenant_id, limit=12)


@router.get("/briefs/{entity_id}", response_model=InvestigationBriefResponse)
async def investigation_brief(
    entity_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InvestigationBriefResponse:
    root = await _entity_snapshot(session, current_user.tenant_id, entity_id)
    if not root:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    related_entities = await _related_entity_snapshots(session, current_user.tenant_id, entity_id, limit=12)
    return _build_investigation_brief(root, related_entities)


@router.get("/alerts", response_model=list[AlertSummary])
async def list_alerts(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AlertSummary]:
    result = await session.run(
        """
        MATCH (a:Entity {tenant_id: $tenant_id, type_name: 'Alert'})
        OPTIONAL MATCH (a)-[r:CONNECTED_TO]-(:Entity {tenant_id: $tenant_id})
        WITH a, count(DISTINCT r) AS relationship_count
        OPTIONAL MATCH (a)-[hv:HAS_VALUE]->(attr:Attribute)
        WITH
            a,
            relationship_count,
            collect(
                CASE
                    WHEN attr IS NULL THEN NULL
                    ELSE {
                        name: attr.name,
                        value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                    }
                END
            ) AS raw_values
        RETURN
            a.id AS alert_id,
            relationship_count,
            [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        """,
        tenant_id=current_user.tenant_id,
    )
    records = await result.data()
    alerts = []
    for record in records:
        properties = _properties_from_values(record["values"])
        alerts.append(
            AlertSummary(
                alert_id=record["alert_id"],
                label=_pick_label("Alert", properties),
                alert_category=properties.get("Alert Category", "unknown"),
                alert_status=properties.get("Alert Status", "open"),
                review_status=properties.get("Review Status"),
                risk_score=_safe_float(properties.get("Risk Score")),
                relationship_count=record["relationship_count"],
            )
        )
    return sorted(
        alerts,
        key=lambda alert: (-(alert.risk_score or 0), alert.label.lower()),
    )


@router.post("/alerts/{alert_id}/decision", response_model=AlertDecisionResponse)
async def decide_alert(
    alert_id: str,
    body: AlertDecisionRequest,
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.ANALYST)),
    session: AsyncSession = Depends(get_session),
) -> AlertDecisionResponse:
    alert_result = await session.run(
        """
        MATCH (a:Entity {id: $alert_id, tenant_id: $tenant_id, type_name: 'Alert'})
        OPTIONAL MATCH (a)-[hv:HAS_VALUE]->(attr:Attribute)
        WITH a, collect(
            CASE
                WHEN attr IS NULL THEN NULL
                ELSE {
                    name: attr.name,
                    value: coalesce(hv.value_string, toString(hv.value_numeric), hv.value_date, '')
                }
            END
        ) AS raw_values
        RETURN
            a.id AS alert_id,
            [value IN raw_values WHERE value IS NOT NULL AND value.value <> ''] AS values
        """,
        alert_id=alert_id,
        tenant_id=current_user.tenant_id,
    )
    alert_row = await alert_result.single()
    if not alert_row:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")

    alert_properties = _properties_from_values(alert_row["values"])
    alert_label = _pick_label("Alert", alert_properties)

    decision_map = {
        AlertDecision.ACKNOWLEDGE: {
            "alert_status": "acknowledged",
            "review_status": "reviewed",
            "action_type": "ACKNOWLEDGE_ALERT",
        },
        AlertDecision.OPEN_CASE: {
            "alert_status": "escalated",
            "review_status": "in_review",
            "action_type": "OPEN_ALERT_CASE",
        },
        AlertDecision.DISMISS: {
            "alert_status": "dismissed",
            "review_status": "dismissed",
            "action_type": "DISMISS_ALERT",
        },
    }
    decision = decision_map[body.decision]

    await _set_entity_string_value(
        session,
        current_user.tenant_id,
        alert_id,
        "Alert",
        "Alert Status",
        decision["alert_status"],
    )
    await _set_entity_string_value(
        session,
        current_user.tenant_id,
        alert_id,
        "Alert",
        "Review Status",
        decision["review_status"],
    )

    case_id: str | None = None
    if body.decision == AlertDecision.OPEN_CASE:
        related_result = await session.run(
            """
            MATCH (a:Entity {id: $alert_id, tenant_id: $tenant_id})-[r:CONNECTED_TO]-(linked:Entity {tenant_id: $tenant_id})
            WHERE linked.type_name IN [
                'Customer', 'Hypothesis', 'Recommendation', 'Contract', 'Invoice',
                'SupportTicket', 'Document', 'Observation', 'ModelRun', 'PromptTemplate'
            ]
            RETURN collect(DISTINCT linked.id)[..8] AS linked_ids
            """,
            alert_id=alert_id,
            tenant_id=current_user.tenant_id,
        )
        related_row = await related_result.single()
        case_entities = [alert_id, *((related_row["linked_ids"] if related_row else []) or [])]
        case_id = str(uuid.uuid4())
        await session.run(
            """
            MATCH (u:User {user_id: $user_id})
            CREATE (c:Case {
                id: $case_id,
                title: $title,
                description: $description,
                priority: 'high',
                status: 'open',
                tenant_id: $tenant_id,
                created_by: $created_by,
                created_at: datetime(),
                updated_at: datetime()
            })
            CREATE (u)-[:CREATED_CASE]->(c)
            WITH c
            OPTIONAL MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE e.id IN $entity_ids
            WITH c, collect(DISTINCT e) AS entities
            FOREACH (entity IN entities | CREATE (c)-[:INVOLVES]->(entity))
            """,
            case_id=case_id,
            title=f"Review {alert_label}",
            description=body.notes or f"Operational review opened from alert: {alert_label}.",
            tenant_id=current_user.tenant_id,
            created_by=current_user.username,
            user_id=current_user.user_id,
            entity_ids=case_entities,
        )

    action_result = await session.run(
        """
        MATCH (u:User {user_id: $user_id})
        MATCH (e:Entity {id: $target_id, tenant_id: $tenant_id})
        CREATE (log:ActionLog {
            id: randomUUID(),
            action_type: $action_type,
            node_label: 'Alert',
            timestamp: datetime(),
            tenant_id: $tenant_id,
            status: 'COMPLETED',
            executed_by: $executed_by,
            notes: $notes
        })
        CREATE (u)-[:EXECUTED {action: $action_type, timestamp: datetime()}]->(log)
        CREATE (log)-[:TARGETS]->(e)
        WITH log
        OPTIONAL MATCH (c:Case {id: $case_id, tenant_id: $tenant_id})
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | CREATE (log)-[:PART_OF_CASE]->(c))
        RETURN log.id AS log_id
        """,
        user_id=current_user.user_id,
        target_id=alert_id,
        tenant_id=current_user.tenant_id,
        action_type=decision["action_type"],
        executed_by=current_user.username,
        notes=body.notes,
        case_id=case_id,
    )
    action_row = await action_result.single()
    if not action_row:
        raise HTTPException(status_code=500, detail="Failed to record alert decision")

    return AlertDecisionResponse(
        alert_id=alert_id,
        decision=body.decision,
        alert_status=decision["alert_status"],
        review_status=decision["review_status"],
        action_log_id=action_row["log_id"],
        case_id=case_id,
    )


@router.get("/views", response_model=list[SavedViewResponse])
async def list_views(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SavedViewResponse]:
    result = await session.run(
        """
        MATCH (v:SavedView {tenant_id: $tenant_id})
        RETURN
            v.id AS view_id,
            v.name AS name,
            v.description AS description,
            v.root_entity_id AS root_entity_id,
            v.depth AS depth,
            v.layout AS layout,
            v.tenant_id AS tenant_id,
            v.created_by AS created_by,
            v.created_at AS created_at
        ORDER BY v.created_at DESC
        """,
        tenant_id=current_user.tenant_id,
    )
    return [_map_view(record) for record in await result.data()]


@router.post("/views", response_model=SavedViewResponse, status_code=status.HTTP_201_CREATED)
async def create_view(
    body: SavedViewCreate,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SavedViewResponse:
    check = await session.run(
        "MATCH (e:Entity {id: $entity_id, tenant_id: $tenant_id}) RETURN e.id AS id",
        entity_id=body.root_entity_id,
        tenant_id=current_user.tenant_id,
    )
    if not await check.single():
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{body.root_entity_id}' not found",
        )

    view_id = str(uuid.uuid4())
    result = await session.run(
        """
        CREATE (v:SavedView {
            id: $view_id,
            name: $name,
            description: $description,
            root_entity_id: $root_entity_id,
            depth: $depth,
            layout: $layout,
            tenant_id: $tenant_id,
            created_by: $created_by,
            created_at: datetime()
        })
        RETURN
            v.id AS view_id,
            v.name AS name,
            v.description AS description,
            v.root_entity_id AS root_entity_id,
            v.depth AS depth,
            v.layout AS layout,
            v.tenant_id AS tenant_id,
            v.created_by AS created_by,
            v.created_at AS created_at
        """,
        view_id=view_id,
        name=body.name,
        description=body.description,
        root_entity_id=body.root_entity_id,
        depth=body.depth,
        layout=body.layout,
        tenant_id=current_user.tenant_id,
        created_by=current_user.username,
    )
    record = await result.single()
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create saved view")
    return _map_view(record)


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_view(
    view_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.run(
        """
        MATCH (v:SavedView {id: $view_id, tenant_id: $tenant_id})
        DETACH DELETE v
        RETURN true AS deleted
        """,
        view_id=view_id,
        tenant_id=current_user.tenant_id,
    )
    if not await result.single():
        raise HTTPException(status_code=404, detail=f"SavedView '{view_id}' not found")


@router.get("/system/summary", response_model=WorkspaceSystemSummary)
async def workspace_system_summary(
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceSystemSummary:
    tenant_id = current_user.tenant_id
    return WorkspaceSystemSummary(
        entity_types=await _count_nodes(session, tenant_id, "EntityType"),
        relationship_types=await _count_nodes(session, tenant_id, "RelationshipType"),
        entities=await _count_nodes(session, tenant_id, "Entity"),
        alerts=await _count_nodes(session, tenant_id, "Entity", "WHERE n.type_name = 'Alert'"),
        saved_views=await _count_nodes(session, tenant_id, "SavedView"),
        cases=await _count_nodes(session, tenant_id, "Case"),
    )


@router.get("/system/status", response_model=WorkspaceSystemStatus)
async def workspace_system_status(
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> WorkspaceSystemStatus:
    neo4j_state = "degraded"
    redis_state = "degraded"

    try:
        neo4j_result = await session.run("RETURN 1 AS ok")
        neo4j_record = await neo4j_result.single()
        if neo4j_record and neo4j_record["ok"] == 1:
            neo4j_state = "ok"
    except Exception:
        neo4j_state = "degraded"

    try:
        if await redis.ping():
            redis_state = "ok"
    except Exception:
        redis_state = "degraded"

    return WorkspaceSystemStatus(
        api_version="1.0.0",
        tenant_id=current_user.tenant_id,
        neo4j=neo4j_state,
        redis=redis_state,
        frontend_bundle_present=FRONTEND_DIST_DIR.exists(),
        allowed_origins=settings.allowed_origins,
    )


@router.post(
    "/verticals/cyber-threat/seed",
    response_model=VerticalSeedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def seed_cyber_threat_demo(
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> VerticalSeedResponse:
    tenant_id = current_user.tenant_id

    entity_types = [
        (
            "Attacker",
            "Malicious actor tracked across campaigns, exploits, and access attempts.",
            [
                ("Display Name", "STRING"),
                ("Username", "STRING"),
                ("Threat Level", "NUMBER"),
                ("Origin", "STRING"),
            ],
        ),
        (
            "Server",
            "Network asset that can be targeted by attackers or impacted by vulnerabilities.",
            [
                ("Display Name", "STRING"),
                ("Hostname", "STRING"),
                ("IP Address", "STRING"),
                ("Environment", "STRING"),
            ],
        ),
        (
            "Vulnerability",
            "Software weakness that attackers can exploit to reach servers.",
            [
                ("Display Name", "STRING"),
                ("CVE ID", "STRING"),
                ("Severity", "STRING"),
                ("CVSS", "NUMBER"),
            ],
        ),
    ]

    for type_name, description, attributes in entity_types:
        await session.run(
            """
            MERGE (et:EntityType {name: $type_name, tenant_id: $tenant_id})
            ON CREATE SET et.description = $description, et.created_at = datetime()
            SET et.description = $description
            """,
            type_name=type_name,
            tenant_id=tenant_id,
            description=description,
        )
        for attribute_name, data_type in attributes:
            await session.run(
                """
                MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
                MERGE (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attribute_name, tenant_id: $tenant_id})
                ON CREATE SET
                    a.data_type = $data_type,
                    a.required = false,
                    a.cardinality = 'SINGLE',
                    a.created_at = datetime()
                SET a.data_type = $data_type
                """,
                type_name=type_name,
                tenant_id=tenant_id,
                attribute_name=attribute_name,
                data_type=data_type,
            )

    relationship_types = [
        ("UNAUTHORIZED_ACCESS", "Attacker", "Server"),
        ("EXPLOITS", "Attacker", "Vulnerability"),
        ("AFFECTS", "Vulnerability", "Server"),
    ]
    for rel_name, source_type, target_type in relationship_types:
        await session.run(
            """
            MERGE (rt:RelationshipType {name: $name, tenant_id: $tenant_id})
            ON CREATE SET
                rt.source_type = $source_type,
                rt.target_type = $target_type,
                rt.created_at = datetime()
            SET
                rt.source_type = $source_type,
                rt.target_type = $target_type
            """,
            name=rel_name,
            tenant_id=tenant_id,
            source_type=source_type,
            target_type=target_type,
        )

    entities = [
        (
            "attacker_apt29",
            "Attacker",
            {
                "Display Name": {"value_string": "APT29 credential access cluster"},
                "Username": {"value_string": "apt29_ops"},
                "Threat Level": {"value_numeric": 92},
                "Origin": {"value_string": "External"},
            },
        ),
        (
            "server_prod_api",
            "Server",
            {
                "Display Name": {"value_string": "prod-api-01"},
                "Hostname": {"value_string": "prod-api-01"},
                "IP Address": {"value_string": "10.20.4.15"},
                "Environment": {"value_string": "Production"},
            },
        ),
        (
            "server_vpn_gateway",
            "Server",
            {
                "Display Name": {"value_string": "vpn-gateway-01"},
                "Hostname": {"value_string": "vpn-gateway-01"},
                "IP Address": {"value_string": "10.20.1.8"},
                "Environment": {"value_string": "Edge"},
            },
        ),
        (
            "vuln_cve_2026_1337",
            "Vulnerability",
            {
                "Display Name": {"value_string": "CVE-2026-1337 remote auth bypass"},
                "CVE ID": {"value_string": "CVE-2026-1337"},
                "Severity": {"value_string": "Critical"},
                "CVSS": {"value_numeric": 9.8},
            },
        ),
    ]

    for seed_key, type_name, values in entities:
        await session.run(
            """
            MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
            MERGE (e:Entity {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                e.id = randomUUID(),
                e.type_name = $type_name,
                e.created_at = datetime()
            SET e.type_name = $type_name
            MERGE (e)-[:INSTANCE_OF]->(et)
            WITH e, et
            OPTIONAL MATCH (e)-[existing:HAS_VALUE]->(:Attribute)
            DELETE existing
            WITH e, et
            UNWIND $values AS val
            MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: val.name, tenant_id: $tenant_id})
            CREATE (e)-[hv:HAS_VALUE]->(a)
            SET
                hv.value_string = val.value_string,
                hv.value_numeric = val.value_numeric,
                hv.value_date = val.value_date
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            type_name=type_name,
            values=[
                {
                    "name": name,
                    "value_string": payload.get("value_string"),
                    "value_numeric": payload.get("value_numeric"),
                    "value_date": payload.get("value_date"),
                }
                for name, payload in values.items()
            ],
        )

    relationships = [
        ("attacker_apt29", "server_prod_api", "UNAUTHORIZED_ACCESS"),
        ("attacker_apt29", "vuln_cve_2026_1337", "EXPLOITS"),
        ("vuln_cve_2026_1337", "server_vpn_gateway", "AFFECTS"),
    ]
    for source_seed, target_seed, relationship_type in relationships:
        await session.run(
            """
            MATCH (src:Entity {tenant_id: $tenant_id, seed_key: $source_seed})
            MATCH (tgt:Entity {tenant_id: $tenant_id, seed_key: $target_seed})
            MERGE (src)-[r:CONNECTED_TO {tenant_id: $tenant_id, relationship_type: $relationship_type}]->(tgt)
            ON CREATE SET r.created_at = datetime()
            """,
            tenant_id=tenant_id,
            source_seed=source_seed,
            target_seed=target_seed,
            relationship_type=relationship_type,
        )

    seeded_views = [
        (
            "cyber_view_intrusion_path",
            "Credential Access Path",
            "Attacker, exploit, and impacted infrastructure stitched into one traversal path.",
            "attacker_apt29",
            2,
        ),
    ]
    for seed_key, name, description, root_seed, depth in seeded_views:
        await session.run(
            """
            MATCH (root:Entity {tenant_id: $tenant_id, seed_key: $root_seed})
            MERGE (v:SavedView {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                v.id = randomUUID(),
                v.created_at = datetime(),
                v.created_by = $created_by
            SET
                v.name = $name,
                v.description = $description,
                v.root_entity_id = root.id,
                v.depth = $depth,
                v.layout = 'dagre'
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            name=name,
            description=description,
            root_seed=root_seed,
            depth=depth,
            created_by=current_user.username,
        )

    return VerticalSeedResponse(
        vertical="Cyber Threat",
        tenant_id=tenant_id,
        seeded=True,
        entities=len(entities),
        saved_views=len(seeded_views),
    )


@router.post(
    "/verticals/revenue-ops/seed",
    response_model=VerticalSeedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def seed_revenue_ops_demo(
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> VerticalSeedResponse:
    tenant_id = current_user.tenant_id

    entity_types = [
        (
            "Customer",
            "Customer account with revenue, health, and renewal metadata.",
            [
                ("Display Name", "STRING"),
                ("Customer Name", "STRING"),
                ("Industry", "STRING"),
                ("Segment", "STRING"),
                ("Health Status", "STRING"),
                ("MRR", "NUMBER"),
                ("Renewal Window", "STRING"),
            ],
        ),
        (
            "Contract",
            "Commercial agreement with renewal timing and value.",
            [
                ("Display Name", "STRING"),
                ("Contract Name", "STRING"),
                ("ARR", "NUMBER"),
                ("Renewal Date", "DATE"),
                ("Renewal Window", "STRING"),
            ],
        ),
        (
            "Invoice",
            "Billing object that can signal collections risk.",
            [
                ("Display Name", "STRING"),
                ("Invoice Number", "STRING"),
                ("Amount", "NUMBER"),
                ("Payment Status", "STRING"),
                ("Days Late", "NUMBER"),
            ],
        ),
        (
            "SupportTicket",
            "Support workload connected to customer health.",
            [
                ("Display Name", "STRING"),
                ("Ticket ID", "STRING"),
                ("Severity", "STRING"),
                ("Topic", "STRING"),
                ("Status", "STRING"),
            ],
        ),
        (
            "AccountManager",
            "Revenue owner responsible for customer outcomes.",
            [
                ("Display Name", "STRING"),
                ("Owner Name", "STRING"),
                ("Region", "STRING"),
                ("Team", "STRING"),
            ],
        ),
    ]

    for type_name, description, attributes in entity_types:
        await session.run(
            """
            MERGE (et:EntityType {name: $type_name, tenant_id: $tenant_id})
            ON CREATE SET et.description = $description, et.created_at = datetime()
            SET et.description = $description
            """,
            type_name=type_name,
            tenant_id=tenant_id,
            description=description,
        )
        for attribute_name, data_type in attributes:
            await session.run(
                """
                MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
                MERGE (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attribute_name, tenant_id: $tenant_id})
                ON CREATE SET
                    a.data_type = $data_type,
                    a.required = false,
                    a.cardinality = 'SINGLE',
                    a.created_at = datetime()
                SET a.data_type = $data_type
                """,
                type_name=type_name,
                tenant_id=tenant_id,
                attribute_name=attribute_name,
                data_type=data_type,
            )

    relationship_types = [
        ("OWNS_ACCOUNT", "AccountManager", "Customer"),
        ("HAS_CONTRACT", "Customer", "Contract"),
        ("HAS_INVOICE", "Customer", "Invoice"),
        ("HAS_TICKET", "Customer", "SupportTicket"),
        ("BLOCKS_RENEWAL", "SupportTicket", "Contract"),
        ("OWNS_INVOICE", "AccountManager", "Invoice"),
    ]
    for rel_name, source_type, target_type in relationship_types:
        await session.run(
            """
            MERGE (rt:RelationshipType {name: $name, tenant_id: $tenant_id})
            ON CREATE SET
                rt.source_type = $source_type,
                rt.target_type = $target_type,
                rt.created_at = datetime()
            SET
                rt.source_type = $source_type,
                rt.target_type = $target_type
            """,
            name=rel_name,
            tenant_id=tenant_id,
            source_type=source_type,
            target_type=target_type,
        )

    entities = [
        (
            "customer_acme",
            "Customer",
            {
                "Display Name": {"value_string": "Acme Manufacturing renewal account"},
                "Customer Name": {"value_string": "Acme Manufacturing"},
                "Industry": {"value_string": "Industrial equipment"},
                "Segment": {"value_string": "Mid-Market"},
                "Health Status": {"value_string": "At Risk"},
                "MRR": {"value_numeric": 18500},
                "Renewal Window": {"value_string": "45 days"},
            },
        ),
        (
            "customer_northstar",
            "Customer",
            {
                "Display Name": {"value_string": "Northstar Retail expansion account"},
                "Customer Name": {"value_string": "Northstar Retail"},
                "Industry": {"value_string": "Retail operations"},
                "Segment": {"value_string": "Growth"},
                "Health Status": {"value_string": "Healthy"},
                "MRR": {"value_numeric": 9600},
                "Renewal Window": {"value_string": "120 days"},
            },
        ),
        (
            "customer_bluewave",
            "Customer",
            {
                "Display Name": {"value_string": "Bluewave Logistics onboarding recovery"},
                "Customer Name": {"value_string": "Bluewave Logistics"},
                "Industry": {"value_string": "Freight and logistics"},
                "Segment": {"value_string": "Enterprise"},
                "Health Status": {"value_string": "Needs Attention"},
                "MRR": {"value_numeric": 27400},
                "Renewal Window": {"value_string": "75 days"},
            },
        ),
        (
            "contract_acme",
            "Contract",
            {
                "Display Name": {"value_string": "Acme renewal due May 8"},
                "Contract Name": {"value_string": "Acme FY26 Renewal"},
                "ARR": {"value_numeric": 222000},
                "Renewal Date": {"value_date": "2026-05-08"},
                "Renewal Window": {"value_string": "45 days"},
            },
        ),
        (
            "invoice_acme_q1",
            "Invoice",
            {
                "Display Name": {"value_string": "Invoice INV-2048 overdue 19 days"},
                "Invoice Number": {"value_string": "INV-2048"},
                "Amount": {"value_numeric": 37000},
                "Payment Status": {"value_string": "Overdue"},
                "Days Late": {"value_numeric": 19},
            },
        ),
        (
            "ticket_acme_escalation",
            "SupportTicket",
            {
                "Display Name": {"value_string": "Critical export-sync ticket"},
                "Ticket ID": {"value_string": "SUP-8821"},
                "Severity": {"value_string": "High"},
                "Topic": {"value_string": "Order export sync failures"},
                "Status": {"value_string": "Escalated"},
            },
        ),
        (
            "manager_lina",
            "AccountManager",
            {
                "Display Name": {"value_string": "Lina Haddad, account owner"},
                "Owner Name": {"value_string": "Lina Haddad"},
                "Region": {"value_string": "North Africa"},
                "Team": {"value_string": "Growth Accounts"},
            },
        ),
        (
            "contract_northstar",
            "Contract",
            {
                "Display Name": {"value_string": "Northstar expansion renewal due Aug 28"},
                "Contract Name": {"value_string": "Northstar Expansion"},
                "ARR": {"value_numeric": 115200},
                "Renewal Date": {"value_date": "2026-08-28"},
                "Renewal Window": {"value_string": "120 days"},
            },
        ),
        (
            "contract_bluewave",
            "Contract",
            {
                "Display Name": {"value_string": "Bluewave renewal due Jun 12"},
                "Contract Name": {"value_string": "Bluewave Enterprise Rollout"},
                "ARR": {"value_numeric": 328800},
                "Renewal Date": {"value_date": "2026-06-12"},
                "Renewal Window": {"value_string": "75 days"},
            },
        ),
        (
            "invoice_northstar_q1",
            "Invoice",
            {
                "Display Name": {"value_string": "Invoice INV-2099 paid on time"},
                "Invoice Number": {"value_string": "INV-2099"},
                "Amount": {"value_numeric": 18400},
                "Payment Status": {"value_string": "Paid"},
                "Days Late": {"value_numeric": 0},
            },
        ),
        (
            "invoice_bluewave_q1",
            "Invoice",
            {
                "Display Name": {"value_string": "Invoice INV-3114 at risk of delay"},
                "Invoice Number": {"value_string": "INV-3114"},
                "Amount": {"value_numeric": 54800},
                "Payment Status": {"value_string": "Due This Week"},
                "Days Late": {"value_numeric": 0},
            },
        ),
        (
            "ticket_northstar_adoption",
            "SupportTicket",
            {
                "Display Name": {"value_string": "Adoption questions on new workflow"},
                "Ticket ID": {"value_string": "SUP-9012"},
                "Severity": {"value_string": "Medium"},
                "Topic": {"value_string": "Reporting workflow enablement"},
                "Status": {"value_string": "Open"},
            },
        ),
        (
            "ticket_bluewave_launch",
            "SupportTicket",
            {
                "Display Name": {"value_string": "Launch blocker on carrier sync"},
                "Ticket ID": {"value_string": "SUP-9134"},
                "Severity": {"value_string": "High"},
                "Topic": {"value_string": "Carrier sync configuration failure"},
                "Status": {"value_string": "Pending engineering"},
            },
        ),
        (
            "manager_omar",
            "AccountManager",
            {
                "Display Name": {"value_string": "Omar Ben Salem, strategic accounts"},
                "Owner Name": {"value_string": "Omar Ben Salem"},
                "Region": {"value_string": "Southern Europe"},
                "Team": {"value_string": "Strategic Accounts"},
            },
        ),
    ]

    for seed_key, type_name, values in entities:
        await session.run(
            """
            MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
            MERGE (e:Entity {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                e.id = randomUUID(),
                e.type_name = $type_name,
                e.created_at = datetime()
            SET e.type_name = $type_name
            MERGE (e)-[:INSTANCE_OF]->(et)
            WITH e, et
            OPTIONAL MATCH (e)-[existing:HAS_VALUE]->(:Attribute)
            DELETE existing
            WITH e, et
            UNWIND $values AS val
            MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: val.name, tenant_id: $tenant_id})
            CREATE (e)-[hv:HAS_VALUE]->(a)
            SET
                hv.value_string = val.value_string,
                hv.value_numeric = val.value_numeric,
                hv.value_date = val.value_date
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            type_name=type_name,
            values=[
                {
                    "name": name,
                    "value_string": payload.get("value_string"),
                    "value_numeric": payload.get("value_numeric"),
                    "value_date": payload.get("value_date"),
                }
                for name, payload in values.items()
            ],
        )

    relationships = [
        ("manager_lina", "customer_acme", "OWNS_ACCOUNT"),
        ("manager_lina", "customer_northstar", "OWNS_ACCOUNT"),
        ("manager_omar", "customer_bluewave", "OWNS_ACCOUNT"),
        ("customer_acme", "contract_acme", "HAS_CONTRACT"),
        ("customer_acme", "invoice_acme_q1", "HAS_INVOICE"),
        ("customer_acme", "ticket_acme_escalation", "HAS_TICKET"),
        ("ticket_acme_escalation", "contract_acme", "BLOCKS_RENEWAL"),
        ("manager_lina", "invoice_acme_q1", "OWNS_INVOICE"),
        ("customer_northstar", "contract_northstar", "HAS_CONTRACT"),
        ("customer_northstar", "invoice_northstar_q1", "HAS_INVOICE"),
        ("customer_northstar", "ticket_northstar_adoption", "HAS_TICKET"),
        ("customer_bluewave", "contract_bluewave", "HAS_CONTRACT"),
        ("customer_bluewave", "invoice_bluewave_q1", "HAS_INVOICE"),
        ("customer_bluewave", "ticket_bluewave_launch", "HAS_TICKET"),
        ("ticket_bluewave_launch", "contract_bluewave", "BLOCKS_RENEWAL"),
        ("manager_omar", "invoice_bluewave_q1", "OWNS_INVOICE"),
    ]
    for source_seed, target_seed, relationship_type in relationships:
        await session.run(
            """
            MATCH (src:Entity {tenant_id: $tenant_id, seed_key: $source_seed})
            MATCH (tgt:Entity {tenant_id: $tenant_id, seed_key: $target_seed})
            MERGE (src)-[r:CONNECTED_TO {tenant_id: $tenant_id, relationship_type: $relationship_type}]->(tgt)
            ON CREATE SET r.created_at = datetime()
            """,
            tenant_id=tenant_id,
            source_seed=source_seed,
            target_seed=target_seed,
            relationship_type=relationship_type,
        )

    seeded_cases = [
        (
            "case_acme_recovery",
            "Acme renewal rescue",
            "Coordinate collections, support escalation, and executive outreach before the May renewal review.",
            "critical",
            "in_progress",
            ["customer_acme", "contract_acme", "invoice_acme_q1", "ticket_acme_escalation"],
        ),
        (
            "case_bluewave_launch",
            "Bluewave launch-risk review",
            "Track onboarding blockers and confirm the launch issue does not spill into the June renewal motion.",
            "high",
            "open",
            ["customer_bluewave", "contract_bluewave", "invoice_bluewave_q1", "ticket_bluewave_launch"],
        ),
    ]
    for seed_key, title, description, priority, status_value, entity_seed_keys in seeded_cases:
        await session.run(
            """
            MATCH (u:User {user_id: $user_id})
            MERGE (c:Case {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                c.id = randomUUID(),
                c.created_at = datetime(),
                c.created_by = $created_by
            SET
                c.title = $title,
                c.description = $description,
                c.priority = $priority,
                c.status = $status_value,
                c.updated_at = datetime()
            MERGE (u)-[:CREATED_CASE]->(c)
            WITH c
            OPTIONAL MATCH (c)-[existing:INVOLVES]->(:Entity {tenant_id: $tenant_id})
            DELETE existing
            WITH c
            MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE e.seed_key IN $entity_seed_keys
            WITH c, collect(DISTINCT e) AS entities
            FOREACH (entity IN entities | CREATE (c)-[:INVOLVES]->(entity))
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            title=title,
            description=description,
            priority=priority,
            status_value=status_value,
            entity_seed_keys=entity_seed_keys,
            user_id=current_user.user_id,
            created_by=current_user.username,
        )

    seeded_action_logs = [
        (
            "log_acme_case_triage",
            "case_status_changed",
            "Case",
            "Acme rescue case moved into active coordination after finance and support review.",
            "case_acme_recovery",
            "customer_acme",
        ),
        (
            "log_bluewave_ticket_review",
            "case_entity_added",
            "SupportTicket",
            "Bluewave launch blocker linked to the case to make the renewal risk explicit.",
            "case_bluewave_launch",
            "ticket_bluewave_launch",
        ),
    ]
    for seed_key, action_type, node_label, notes, case_seed_key, target_seed_key in seeded_action_logs:
        await session.run(
            """
            MATCH (u:User {user_id: $user_id})
            MATCH (c:Case {tenant_id: $tenant_id, seed_key: $case_seed_key})
            MATCH (e:Entity {tenant_id: $tenant_id, seed_key: $target_seed_key})
            MERGE (log:ActionLog {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                log.id = randomUUID(),
                log.timestamp = datetime()
            SET
                log.action_type = $action_type,
                log.node_label = $node_label,
                log.status = 'COMPLETED',
                log.executed_by = $executed_by,
                log.notes = $notes
            MERGE (u)-[exec:EXECUTED]->(log)
            SET
                exec.action = $action_type,
                exec.timestamp = datetime()
            MERGE (log)-[:TARGETS]->(e)
            MERGE (log)-[:PART_OF_CASE]->(c)
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            action_type=action_type,
            node_label=node_label,
            notes=notes,
            case_seed_key=case_seed_key,
            target_seed_key=target_seed_key,
            user_id=current_user.user_id,
            executed_by=current_user.username,
        )

    seeded_views = [
        (
            "revenue_view_acme",
            "Renewal Risk Cluster",
            "Customer, overdue invoice, and escalated ticket tied to the upcoming Acme renewal.",
            "customer_acme",
            2,
        ),
        (
            "revenue_view_collections",
            "Collections Pressure",
            "Accounts and invoices where payment risk is likely to affect expansion or renewal.",
            "invoice_acme_q1",
            2,
        ),
        (
            "revenue_view_launch_risk",
            "Launch Risk Rollup",
            "See how onboarding blockers, billing timing, and contract value compound inside Bluewave's renewal path.",
            "customer_bluewave",
            2,
        ),
    ]
    for seed_key, name, description, root_seed, depth in seeded_views:
        await session.run(
            """
            MATCH (root:Entity {tenant_id: $tenant_id, seed_key: $root_seed})
            MERGE (v:SavedView {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                v.id = randomUUID(),
                v.created_at = datetime(),
                v.created_by = $created_by
            SET
                v.name = $name,
                v.description = $description,
                v.root_entity_id = root.id,
                v.depth = $depth,
                v.layout = 'dagre'
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            name=name,
            description=description,
            root_seed=root_seed,
            depth=depth,
            created_by=current_user.username,
        )

    return VerticalSeedResponse(
        vertical="Revenue Operations",
        tenant_id=tenant_id,
        seeded=True,
        entities=len(entities),
        saved_views=len(seeded_views),
    )


@router.post(
    "/verticals/revenue-ops/ai-layer",
    response_model=AiOntologySeedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def seed_revenue_ops_ai_layer(
    current_user: CurrentUser = Depends(require_roles(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> AiOntologySeedResponse:
    tenant_id = current_user.tenant_id

    required_types = ("Customer", "Contract", "Invoice", "SupportTicket")
    type_check = await session.run(
        """
        UNWIND $required_types AS type_name
        OPTIONAL MATCH (et:EntityType {tenant_id: $tenant_id, name: type_name})
        RETURN collect(et.name) AS present_types
        """,
        tenant_id=tenant_id,
        required_types=list(required_types),
    )
    type_row = await type_check.single()
    present_types = {name for name in (type_row["present_types"] if type_row else []) if name}
    missing_types = sorted(set(required_types) - present_types)
    if missing_types:
        raise HTTPException(
            status_code=422,
            detail=(
                "Seed the revenue ops demo before adding the AI layer. "
                f"Missing entity types: {', '.join(missing_types)}"
            ),
        )

    required_entities = {
        "customer_acme": "Customer",
        "contract_acme": "Contract",
        "invoice_acme_q1": "Invoice",
        "ticket_acme_escalation": "SupportTicket",
    }
    entity_check = await session.run(
        """
        UNWIND $required_entity_keys AS seed_key
        OPTIONAL MATCH (e:Entity {tenant_id: $tenant_id, seed_key: seed_key})
        RETURN collect(e.seed_key) AS present_entities
        """,
        tenant_id=tenant_id,
        required_entity_keys=list(required_entities),
    )
    entity_row = await entity_check.single()
    present_entities = {name for name in (entity_row["present_entities"] if entity_row else []) if name}
    missing_entities = sorted(set(required_entities) - present_entities)
    if missing_entities:
        raise HTTPException(
            status_code=422,
            detail=(
                "Seed the revenue ops demo before adding the AI layer. "
                f"Missing seed entities: {', '.join(missing_entities)}"
            ),
        )

    entity_types = [
        (
            "Document",
            "Source artifact or assembled brief used by AI workflows.",
            [
                ("Display Name", "STRING"),
                ("Document Title", "STRING"),
                ("Source System", "STRING"),
                ("Document Type", "STRING"),
                ("Summary", "STRING"),
                ("Captured At", "DATE"),
            ],
        ),
        (
            "PromptTemplate",
            "Reusable prompt or workflow instruction used by a model run.",
            [
                ("Display Name", "STRING"),
                ("Template Name", "STRING"),
                ("Purpose", "STRING"),
                ("Prompt Version", "STRING"),
            ],
        ),
        (
            "ModelRun",
            "Execution record for an AI model invocation with provenance metadata.",
            [
                ("Display Name", "STRING"),
                ("Run Label", "STRING"),
                ("Model Name", "STRING"),
                ("Model Version", "STRING"),
                ("Task", "STRING"),
                ("Confidence", "NUMBER"),
                ("Run Status", "STRING"),
            ],
        ),
        (
            "Observation",
            "Extracted evidence or grounded fact produced from source material.",
            [
                ("Display Name", "STRING"),
                ("Observation", "STRING"),
                ("Confidence", "NUMBER"),
                ("Severity", "STRING"),
                ("Review Status", "STRING"),
            ],
        ),
        (
            "Hypothesis",
            "AI-generated interpretation or risk narrative built from observations.",
            [
                ("Display Name", "STRING"),
                ("Hypothesis", "STRING"),
                ("Confidence", "NUMBER"),
                ("Risk Level", "STRING"),
                ("Review Status", "STRING"),
            ],
        ),
        (
            "Alert",
            "Actionable AI signal surfaced to operators for triage.",
            [
                ("Display Name", "STRING"),
                ("Alert Title", "STRING"),
                ("Alert Category", "STRING"),
                ("Alert Status", "STRING"),
                ("Review Status", "STRING"),
                ("Risk Score", "NUMBER"),
            ],
        ),
        (
            "Recommendation",
            "AI-suggested next step tied to a customer or investigation.",
            [
                ("Display Name", "STRING"),
                ("Recommendation", "STRING"),
                ("Action Type", "STRING"),
                ("Priority", "STRING"),
                ("Review Status", "STRING"),
            ],
        ),
    ]

    for type_name, description, attributes in entity_types:
        await session.run(
            """
            MERGE (et:EntityType {name: $type_name, tenant_id: $tenant_id})
            ON CREATE SET et.description = $description, et.created_at = datetime()
            SET et.description = $description
            """,
            type_name=type_name,
            tenant_id=tenant_id,
            description=description,
        )
        for attribute_name, data_type in attributes:
            await session.run(
                """
                MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
                MERGE (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: $attribute_name, tenant_id: $tenant_id})
                ON CREATE SET
                    a.data_type = $data_type,
                    a.required = false,
                    a.cardinality = 'SINGLE',
                    a.created_at = datetime()
                SET a.data_type = $data_type
                """,
                type_name=type_name,
                tenant_id=tenant_id,
                attribute_name=attribute_name,
                data_type=data_type,
            )

    relationship_types = [
        ("USES_PROMPT", "ModelRun", "PromptTemplate"),
        ("GENERATED_OBSERVATION", "ModelRun", "Observation"),
        ("GENERATED_HYPOTHESIS", "ModelRun", "Hypothesis"),
        ("GENERATED_RECOMMENDATION", "ModelRun", "Recommendation"),
        ("EXTRACTED_FROM", "Observation", "Document"),
        ("ABOUT_CUSTOMER", "Document", "Customer"),
        ("REFERENCES_INVOICE", "Observation", "Invoice"),
        ("REFERENCES_TICKET", "Observation", "SupportTicket"),
        ("SUPPORTS_HYPOTHESIS", "Observation", "Hypothesis"),
        ("PREDICTS_RISK_FOR", "Hypothesis", "Customer"),
        ("PREDICTS_CONTRACT_RISK", "Hypothesis", "Contract"),
        ("FLAGS_CUSTOMER", "Alert", "Customer"),
        ("BASED_ON_HYPOTHESIS", "Alert", "Hypothesis"),
        ("RECOMMENDS_ACTION_FOR", "Recommendation", "Customer"),
        ("DERIVED_FROM_HYPOTHESIS", "Recommendation", "Hypothesis"),
    ]
    for rel_name, source_type, target_type in relationship_types:
        await session.run(
            """
            MERGE (rt:RelationshipType {name: $name, tenant_id: $tenant_id})
            ON CREATE SET
                rt.source_type = $source_type,
                rt.target_type = $target_type,
                rt.created_at = datetime()
            SET
                rt.source_type = $source_type,
                rt.target_type = $target_type
            """,
            name=rel_name,
            tenant_id=tenant_id,
            source_type=source_type,
            target_type=target_type,
        )

    entities = [
        (
            "ai_doc_acme_signal_brief",
            "Document",
            {
                "Display Name": {"value_string": "Evidence packet for Acme renewal review"},
                "Document Title": {"value_string": "Acme renewal risk signal brief"},
                "Source System": {"value_string": "Billing + Support + CSM notes"},
                "Document Type": {"value_string": "MergedCustomerBrief"},
                "Summary": {
                    "value_string": (
                        "Assembled brief combining overdue invoice data, support escalation "
                        "history, and renewal timing for Acme Manufacturing."
                    )
                },
                "Captured At": {"value_date": "2026-03-24"},
            },
        ),
        (
            "ai_prompt_renewal_risk",
            "PromptTemplate",
            {
                "Display Name": {"value_string": "Prompt: revenue risk triage"},
                "Template Name": {"value_string": "Revenue Risk Triage"},
                "Purpose": {
                    "value_string": "Summarize billing, support, and contract signals into a renewal-risk narrative."
                },
                "Prompt Version": {"value_string": "v1.0"},
            },
        ),
        (
            "ai_modelrun_acme_risk",
            "ModelRun",
            {
                "Display Name": {"value_string": "AI run: Acme renewal-risk analysis"},
                "Run Label": {"value_string": "Acme risk synthesis"},
                "Model Name": {"value_string": "gpt-5.4"},
                "Model Version": {"value_string": "2026-03"},
                "Task": {"value_string": "renewal-risk-triage"},
                "Confidence": {"value_numeric": 0.91},
                "Run Status": {"value_string": "completed"},
            },
        ),
        (
            "ai_obs_invoice_acme",
            "Observation",
            {
                "Display Name": {"value_string": "Invoice is overdue and may block renewal"},
                "Observation": {
                    "value_string": "Invoice INV-2048 is 19 days overdue and is likely to disrupt renewal negotiations."
                },
                "Confidence": {"value_numeric": 0.96},
                "Severity": {"value_string": "high"},
                "Review Status": {"value_string": "pending"},
            },
        ),
        (
            "ai_obs_ticket_acme",
            "Observation",
            {
                "Display Name": {"value_string": "Critical support issue still unresolved"},
                "Observation": {
                    "value_string": "Support ticket SUP-8821 remains escalated around order export sync failures."
                },
                "Confidence": {"value_numeric": 0.93},
                "Severity": {"value_string": "high"},
                "Review Status": {"value_string": "pending"},
            },
        ),
        (
            "ai_hypothesis_acme_risk",
            "Hypothesis",
            {
                "Display Name": {"value_string": "Renewal likely at risk"},
                "Hypothesis": {
                    "value_string": "Acme has elevated renewal risk driven by unresolved product pain and collections friction."
                },
                "Confidence": {"value_numeric": 0.89},
                "Risk Level": {"value_string": "high"},
                "Review Status": {"value_string": "pending"},
            },
        ),
        (
            "ai_alert_acme_risk",
            "Alert",
            {
                "Display Name": {"value_string": "Urgent: Acme renewal may slip"},
                "Alert Title": {"value_string": "AI renewal-risk alert for Acme"},
                "Alert Category": {"value_string": "renewal_risk"},
                "Alert Status": {"value_string": "open"},
                "Review Status": {"value_string": "pending"},
                "Risk Score": {"value_numeric": 87},
            },
        ),
        (
            "ai_recommendation_acme_recovery",
            "Recommendation",
            {
                "Display Name": {"value_string": "Start renewal recovery plan"},
                "Recommendation": {
                    "value_string": (
                        "Escalate collections, assign an executive sponsor, and resolve the export sync issue "
                        "before the next renewal review."
                    )
                },
                "Action Type": {"value_string": "EXECUTE_RENEWAL_RECOVERY"},
                "Priority": {"value_string": "critical"},
                "Review Status": {"value_string": "pending"},
            },
        ),
        (
            "ai_hypothesis_northstar_growth",
            "Hypothesis",
            {
                "Display Name": {"value_string": "Expansion opportunity needs early outreach"},
                "Hypothesis": {
                    "value_string": "Northstar is a credible expansion target, but momentum could slip without early commercial outreach."
                },
                "Confidence": {"value_numeric": 0.78},
                "Risk Level": {"value_string": "medium"},
                "Review Status": {"value_string": "pending"},
            },
        ),
        (
            "ai_alert_northstar_growth",
            "Alert",
            {
                "Display Name": {"value_string": "Watch: Northstar expansion timing"},
                "Alert Title": {"value_string": "AI expansion watch for Northstar"},
                "Alert Category": {"value_string": "expansion_watch"},
                "Alert Status": {"value_string": "open"},
                "Review Status": {"value_string": "pending"},
                "Risk Score": {"value_numeric": 64},
            },
        ),
        (
            "ai_recommendation_northstar_outreach",
            "Recommendation",
            {
                "Display Name": {"value_string": "Book expansion workshop before renewal"},
                "Recommendation": {
                    "value_string": "Schedule an expansion workshop with the account manager 90 days before renewal."
                },
                "Action Type": {"value_string": "SCHEDULE_EXPANSION_REVIEW"},
                "Priority": {"value_string": "medium"},
                "Review Status": {"value_string": "pending"},
            },
        ),
    ]

    for seed_key, type_name, values in entities:
        await session.run(
            """
            MATCH (et:EntityType {name: $type_name, tenant_id: $tenant_id})
            MERGE (e:Entity {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                e.id = randomUUID(),
                e.type_name = $type_name,
                e.created_at = datetime()
            SET e.type_name = $type_name
            MERGE (e)-[:INSTANCE_OF]->(et)
            WITH e, et
            OPTIONAL MATCH (e)-[existing:HAS_VALUE]->(:Attribute)
            DELETE existing
            WITH e, et
            UNWIND $values AS val
            MATCH (et)-[:HAS_ATTRIBUTE]->(a:Attribute {name: val.name, tenant_id: $tenant_id})
            CREATE (e)-[hv:HAS_VALUE]->(a)
            SET
                hv.value_string = val.value_string,
                hv.value_numeric = val.value_numeric,
                hv.value_date = val.value_date
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            type_name=type_name,
            values=[
                {
                    "name": name,
                    "value_string": payload.get("value_string"),
                    "value_numeric": payload.get("value_numeric"),
                    "value_date": payload.get("value_date"),
                }
                for name, payload in values.items()
            ],
        )

    relationships = [
        ("ai_modelrun_acme_risk", "ai_prompt_renewal_risk", "USES_PROMPT"),
        ("ai_modelrun_acme_risk", "ai_obs_invoice_acme", "GENERATED_OBSERVATION"),
        ("ai_modelrun_acme_risk", "ai_obs_ticket_acme", "GENERATED_OBSERVATION"),
        ("ai_modelrun_acme_risk", "ai_hypothesis_acme_risk", "GENERATED_HYPOTHESIS"),
        ("ai_modelrun_acme_risk", "ai_recommendation_acme_recovery", "GENERATED_RECOMMENDATION"),
        ("ai_obs_invoice_acme", "ai_doc_acme_signal_brief", "EXTRACTED_FROM"),
        ("ai_obs_ticket_acme", "ai_doc_acme_signal_brief", "EXTRACTED_FROM"),
        ("ai_doc_acme_signal_brief", "customer_acme", "ABOUT_CUSTOMER"),
        ("ai_obs_invoice_acme", "invoice_acme_q1", "REFERENCES_INVOICE"),
        ("ai_obs_ticket_acme", "ticket_acme_escalation", "REFERENCES_TICKET"),
        ("ai_obs_invoice_acme", "ai_hypothesis_acme_risk", "SUPPORTS_HYPOTHESIS"),
        ("ai_obs_ticket_acme", "ai_hypothesis_acme_risk", "SUPPORTS_HYPOTHESIS"),
        ("ai_hypothesis_acme_risk", "customer_acme", "PREDICTS_RISK_FOR"),
        ("ai_hypothesis_acme_risk", "contract_acme", "PREDICTS_CONTRACT_RISK"),
        ("ai_alert_acme_risk", "customer_acme", "FLAGS_CUSTOMER"),
        ("ai_alert_acme_risk", "ai_hypothesis_acme_risk", "BASED_ON_HYPOTHESIS"),
        ("ai_recommendation_acme_recovery", "customer_acme", "RECOMMENDS_ACTION_FOR"),
        ("ai_recommendation_acme_recovery", "ai_hypothesis_acme_risk", "DERIVED_FROM_HYPOTHESIS"),
        ("ai_hypothesis_northstar_growth", "customer_northstar", "PREDICTS_RISK_FOR"),
        ("ai_hypothesis_northstar_growth", "contract_northstar", "PREDICTS_CONTRACT_RISK"),
        ("ai_alert_northstar_growth", "customer_northstar", "FLAGS_CUSTOMER"),
        ("ai_alert_northstar_growth", "ai_hypothesis_northstar_growth", "BASED_ON_HYPOTHESIS"),
        ("ai_recommendation_northstar_outreach", "customer_northstar", "RECOMMENDS_ACTION_FOR"),
        ("ai_recommendation_northstar_outreach", "ai_hypothesis_northstar_growth", "DERIVED_FROM_HYPOTHESIS"),
    ]
    for source_seed, target_seed, relationship_type in relationships:
        await session.run(
            """
            MATCH (src:Entity {tenant_id: $tenant_id, seed_key: $source_seed})
            MATCH (tgt:Entity {tenant_id: $tenant_id, seed_key: $target_seed})
            MERGE (src)-[r:CONNECTED_TO {tenant_id: $tenant_id, relationship_type: $relationship_type}]->(tgt)
            ON CREATE SET r.created_at = datetime()
            """,
            tenant_id=tenant_id,
            source_seed=source_seed,
            target_seed=target_seed,
            relationship_type=relationship_type,
        )

    saved_views = [
        (
            "ai_view_acme_narrative",
            "AI Risk Narrative",
            "Prompt, evidence, hypothesis, and recommendation chain attached to the Acme renewal risk story.",
            "ai_hypothesis_acme_risk",
            2,
        ),
        (
            "ai_view_acme_provenance",
            "AI Provenance Trail",
            "Trace the document, prompt, and model run behind the Acme risk recommendation.",
            "ai_modelrun_acme_risk",
            2,
        ),
    ]
    for seed_key, name, description, root_seed, depth in saved_views:
        await session.run(
            """
            MATCH (root:Entity {tenant_id: $tenant_id, seed_key: $root_seed})
            MERGE (v:SavedView {tenant_id: $tenant_id, seed_key: $seed_key})
            ON CREATE SET
                v.id = randomUUID(),
                v.created_at = datetime(),
                v.created_by = $created_by
            SET
                v.name = $name,
                v.description = $description,
                v.root_entity_id = root.id,
                v.depth = $depth,
                v.layout = 'dagre'
            """,
            tenant_id=tenant_id,
            seed_key=seed_key,
            name=name,
            description=description,
            root_seed=root_seed,
            depth=depth,
            created_by=current_user.username,
        )

    return AiOntologySeedResponse(
        layer="AI Ontology Layer",
        tenant_id=tenant_id,
        seeded=True,
        entity_types=len(entity_types),
        relationship_types=len(relationship_types),
        entities=len(entities),
        saved_views=len(saved_views),
    )
