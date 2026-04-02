export type DashboardMetric = {
  label: string;
  value: number;
  change_hint: string;
};

export type PriorityInvestigation = {
  root_entity_id: string;
  title: string;
  type_name: string;
  score: number;
  why_now: string;
  recommended_action: string;
  linked_signal_count: number;
  open_case_count: number;
};

export type InvestigationBriefItem = {
  entity_id: string;
  label: string;
  type_name: string;
  reason: string;
};

export type InvestigationBrief = {
  entity_id: string;
  title: string;
  type_name: string;
  summary: string;
  why_now: string;
  confidence: string;
  recommended_actions: string[];
  top_signals: InvestigationBriefItem[];
  evidence: InvestigationBriefItem[];
  linked_entity_ids: string[];
};

export type DataType = "STRING" | "NUMBER" | "DATE" | "BOOLEAN";
export type Cardinality = "SINGLE" | "MANY";

export type SavedView = {
  view_id: string;
  name: string;
  description?: string | null;
  root_entity_id: string;
  depth: number;
  layout: string;
  tenant_id: string;
  created_by: string;
  created_at?: string | null;
};

export type SearchResult = {
  entity_id: string;
  label: string;
  type_name: string;
  match_reason: string;
  properties: Record<string, string>;
  relationship_count: number;
};

export type DashboardSummary = {
  vertical: string;
  metrics: DashboardMetric[];
  priority_investigations: PriorityInvestigation[];
  recent_views: SavedView[];
  recent_cases: CaseSummary[];
  highlighted_entities: SearchResult[];
};

export type AlertSummary = {
  alert_id: string;
  label: string;
  alert_category: string;
  alert_status: string;
  review_status?: string | null;
  risk_score?: number | null;
  relationship_count: number;
};

export type AlertDecision =
  | "acknowledge"
  | "open_case"
  | "dismiss";

export type AlertDecisionResponse = {
  alert_id: string;
  decision: AlertDecision;
  alert_status: string;
  review_status: string;
  action_log_id: string;
  case_id?: string | null;
};

export type RelatedEntity = {
  entity_id: string;
  label: string;
  type_name: string;
  relationship_type: string;
  direction: string;
};

export type RecentAction = {
  log_id: string;
  action_type: string;
  status: string;
  timestamp: string;
  executed_by: string;
  case_id?: string | null;
};

export type EntityDetail = {
  entity_id: string;
  label: string;
  type_name: string;
  tenant_id: string;
  properties: Record<string, string>;
  related_entities: RelatedEntity[];
  recent_actions: RecentAction[];
  relationship_count: number;
};

export type CaseSummary = {
  case_id: string;
  title: string;
  priority: "low" | "medium" | "high" | "critical";
  status: "open" | "in_progress" | "closed";
  tenant_id: string;
  created_by: string;
  entity_count: number;
  updated_at?: string | null;
  created_at?: string | null;
};

export type CaseDetail = CaseSummary & {
  description?: string | null;
  entities: RelatedEntity[];
  recent_actions: RecentAction[];
};

export type EntityTypeSummary = {
  name: string;
  description?: string | null;
  tenant_id: string;
  created_at?: string | null;
};

export type AttributeSchema = {
  name: string;
  data_type: DataType;
  required: boolean;
  cardinality: Cardinality;
  entity_type_name: string;
  tenant_id: string;
};

export type EntityTypeDetail = EntityTypeSummary & {
  attributes: AttributeSchema[];
};

export type RelationshipTypeSummary = {
  name: string;
  source_type: string;
  target_type: string;
  tenant_id: string;
  created_at?: string | null;
};

export type CsvIngestResult = {
  total_rows: number;
  ingested: number;
  failed: number;
  dlq_key: string;
  entity_ids: string[];
};

export type IngestEntityResult = {
  alias: string;
  entity_id: string;
  type_name: string;
  tenant_id: string;
  attributes_set: string[];
};

export type IngestConnectionResult = {
  source_alias: string;
  source_entity_id: string;
  target_alias: string;
  target_entity_id: string;
  relationship_type: string;
  tenant_id: string;
};

export type BulkIngestResult = {
  entities_created: number;
  connections_created: number;
  entity_map: Record<string, string>;
  entities: IngestEntityResult[];
  connections: IngestConnectionResult[];
};

export type WebhookIngestResult = BulkIngestResult & {
  source: string;
  event_type: string;
  event_id: string;
  received_at: string;
};

export type DlqEntry = {
  row_index: number;
  raw_row: Record<string, string>;
  error: string;
  timestamp: string;
  type_name?: string | null;
  column_map?: Record<string, string> | null;
};

export type DlqKeySummary = {
  key: string;
  item_count: number;
  created_at?: string | null;
};

export type DlqResponse = {
  key: string;
  count: number;
  items: DlqEntry[];
};

export type DlqRetryFailure = {
  row_index: number;
  error: string;
};

export type DlqRetryResult = {
  key: string;
  requested: number;
  recovered: number;
  remaining: number;
  failed: DlqRetryFailure[];
};

export type WorkspaceSystemSummary = {
  entity_types: number;
  relationship_types: number;
  entities: number;
  alerts: number;
  saved_views: number;
  cases: number;
};

export type WorkspaceSystemStatus = {
  api_version: string;
  tenant_id: string;
  neo4j: string;
  redis: string;
  frontend_bundle_present: boolean;
  allowed_origins: string[];
};

export type GraphNode = {
  data: Record<string, unknown>;
};

export type GraphEdge = {
  data: Record<string, unknown>;
};

export type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};
