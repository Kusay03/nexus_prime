from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    limit: int = Field(default=12, ge=1, le=50)


class SearchResult(BaseModel):
    entity_id: str
    label: str
    type_name: str
    match_reason: str
    properties: dict[str, Any]
    relationship_count: int


class SearchResponse(BaseModel):
    results: list[SearchResult]


class RelatedEntity(BaseModel):
    entity_id: str
    label: str
    type_name: str
    relationship_type: str
    direction: str


class RecentAction(BaseModel):
    log_id: str
    action_type: str
    status: str
    timestamp: str
    executed_by: str
    case_id: Optional[str] = None


class EntityDetailResponse(BaseModel):
    entity_id: str
    label: str
    type_name: str
    tenant_id: str
    properties: dict[str, Any]
    related_entities: list[RelatedEntity]
    recent_actions: list[RecentAction]
    relationship_count: int


class SavedViewCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=80)
    description: Optional[str] = Field(default=None, max_length=240)
    root_entity_id: str
    depth: int = Field(default=2, ge=1, le=6)
    layout: str = Field(default="dagre", min_length=2, max_length=40)


class SavedViewResponse(BaseModel):
    view_id: str
    name: str
    description: Optional[str] = None
    root_entity_id: str
    depth: int
    layout: str
    tenant_id: str
    created_by: str
    created_at: Optional[str] = None


class WorkspaceSystemSummary(BaseModel):
    entity_types: int
    relationship_types: int
    entities: int
    alerts: int
    saved_views: int
    cases: int


class WorkspaceSystemStatus(BaseModel):
    api_version: str
    tenant_id: str
    neo4j: str
    redis: str
    frontend_bundle_present: bool
    allowed_origins: list[str]


class DashboardMetric(BaseModel):
    label: str
    value: int
    change_hint: str


class PriorityInvestigation(BaseModel):
    root_entity_id: str
    title: str
    type_name: str
    score: int
    why_now: str
    recommended_action: str
    linked_signal_count: int
    open_case_count: int


class InvestigationBriefItem(BaseModel):
    entity_id: str
    label: str
    type_name: str
    reason: str


class InvestigationBriefResponse(BaseModel):
    entity_id: str
    title: str
    type_name: str
    summary: str
    why_now: str
    confidence: str
    recommended_actions: list[str]
    top_signals: list[InvestigationBriefItem]
    evidence: list[InvestigationBriefItem]
    linked_entity_ids: list[str]


class DashboardSummaryResponse(BaseModel):
    vertical: str
    metrics: list[DashboardMetric]
    priority_investigations: list[PriorityInvestigation]
    recent_views: list[SavedViewResponse]
    recent_cases: list["CaseSummary"]
    highlighted_entities: list[SearchResult]


class VerticalSeedResponse(BaseModel):
    vertical: str
    tenant_id: str
    seeded: bool
    entities: int
    saved_views: int


class AiOntologySeedResponse(BaseModel):
    layer: str
    tenant_id: str
    seeded: bool
    entity_types: int
    relationship_types: int
    entities: int
    saved_views: int


class AlertSummary(BaseModel):
    alert_id: str
    label: str
    alert_category: str
    alert_status: str
    review_status: str | None = None
    risk_score: float | None = None
    relationship_count: int


class AlertDecision(str, Enum):
    ACKNOWLEDGE = "acknowledge"
    OPEN_CASE = "open_case"
    DISMISS = "dismiss"


class AlertDecisionRequest(BaseModel):
    decision: AlertDecision
    notes: Optional[str] = Field(default=None, max_length=1000)


class AlertDecisionResponse(BaseModel):
    alert_id: str
    decision: AlertDecision
    alert_status: str
    review_status: str
    action_log_id: str
    case_id: Optional[str] = None


class CasePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CaseStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class CaseCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    priority: CasePriority = CasePriority.MEDIUM
    entity_ids: list[str] = Field(default_factory=list, max_length=12)


class CaseUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    priority: Optional[CasePriority] = None
    status: Optional[CaseStatus] = None


class CaseEntityUpdate(BaseModel):
    entity_id: str = Field(..., min_length=1)


class CaseSummary(BaseModel):
    case_id: str
    title: str
    priority: CasePriority
    status: CaseStatus
    tenant_id: str
    created_by: str
    entity_count: int
    updated_at: Optional[str] = None
    created_at: Optional[str] = None


class CaseDetailResponse(CaseSummary):
    description: Optional[str] = None
    entities: list[RelatedEntity]
    recent_actions: list[RecentAction]


DashboardSummaryResponse.model_rebuild()
