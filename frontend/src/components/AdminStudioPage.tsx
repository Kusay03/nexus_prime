import { useCallback, useEffect, useState, type FormEvent } from "react";
import client from "../api/client";
import type {
  Cardinality,
  CsvIngestResult,
  DataType,
  DlqKeySummary,
  DlqResponse,
  DlqRetryResult,
  EntityTypeDetail,
  EntityTypeSummary,
  RelationshipTypeSummary,
  SavedView,
  WebhookIngestResult,
  WorkspaceSystemStatus,
  WorkspaceSystemSummary,
} from "../types";

const DATA_TYPES: DataType[] = ["STRING", "NUMBER", "DATE", "BOOLEAN"];
const CARDINALITIES: Cardinality[] = ["SINGLE", "MANY"];

function errorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = err as { response?: { data?: { detail?: string } } };
    return response.response?.data?.detail ?? fallback;
  }
  return fallback;
}

function sampleColumnMap(detail: EntityTypeDetail | null): string {
  if (!detail || detail.attributes.length === 0) {
    return '{\n  "CSV Column": "Ontology Attribute"\n}';
  }
  return JSON.stringify(
    Object.fromEntries(detail.attributes.map((attribute) => [attribute.name, attribute.name])),
    null,
    2,
  );
}

function sampleWebhookOperations(detail: EntityTypeDetail | null): string {
  const typeName = detail?.name ?? "Entity";
  const values =
    detail?.attributes.slice(0, 2).map((attribute, index) => {
      if (attribute.data_type === "NUMBER") {
        return { name: attribute.name, value_numeric: index + 1 };
      }
      if (attribute.data_type === "DATE") {
        return { name: attribute.name, value_date: "2026-01-01" };
      }
      return { name: attribute.name, value_string: `${attribute.name.toLowerCase().replace(/\s+/g, "_")}_${index + 1}` };
    }) ?? [{ name: "Name", value_string: "sample_entity" }];

  return JSON.stringify(
    [
      {
        op: "create_entity",
        alias: `${typeName.toLowerCase().replace(/\s+/g, "_")}_1`,
        type_name: typeName,
        values,
      },
    ],
    null,
    2,
  );
}

function statusTone(value: string | boolean): string {
  if (typeof value === "boolean") {
    return value ? "ok" : "degraded";
  }
  return value === "ok" ? "ok" : "degraded";
}

function prettyTimestamp(value?: string | null): string {
  if (!value) {
    return "Unknown";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
}

export default function AdminStudioPage() {
  const [summary, setSummary] = useState<WorkspaceSystemSummary | null>(null);
  const [status, setStatus] = useState<WorkspaceSystemStatus | null>(null);
  const [entityTypes, setEntityTypes] = useState<EntityTypeSummary[]>([]);
  const [selectedTypeName, setSelectedTypeName] = useState("");
  const [selectedType, setSelectedType] = useState<EntityTypeDetail | null>(null);
  const [relationshipTypes, setRelationshipTypes] = useState<RelationshipTypeSummary[]>([]);
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [dlqKeys, setDlqKeys] = useState<DlqKeySummary[]>([]);
  const [selectedDlqKey, setSelectedDlqKey] = useState("");
  const [dlqResponse, setDlqResponse] = useState<DlqResponse | null>(null);
  const [csvResult, setCsvResult] = useState<CsvIngestResult | null>(null);
  const [webhookResult, setWebhookResult] = useState<WebhookIngestResult | null>(null);
  const [dlqRetryResult, setDlqRetryResult] = useState<DlqRetryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const [typeName, setTypeName] = useState("");
  const [typeDescription, setTypeDescription] = useState("");
  const [attributeName, setAttributeName] = useState("");
  const [attributeType, setAttributeType] = useState<DataType>("STRING");
  const [attributeRequired, setAttributeRequired] = useState(false);
  const [attributeCardinality, setAttributeCardinality] = useState<Cardinality>("SINGLE");
  const [relationshipName, setRelationshipName] = useState("");
  const [relationshipSource, setRelationshipSource] = useState("");
  const [relationshipTarget, setRelationshipTarget] = useState("");
  const [csvTypeName, setCsvTypeName] = useState("");
  const [csvColumnMap, setCsvColumnMap] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [webhookSource, setWebhookSource] = useState("admin-studio");
  const [webhookEventType, setWebhookEventType] = useState("entity.created");
  const [webhookEventId, setWebhookEventId] = useState("");
  const [webhookOperations, setWebhookOperations] = useState("");

  const [refreshing, setRefreshing] = useState(false);
  const [seedingCyberThreat, setSeedingCyberThreat] = useState(false);
  const [seedingRevenueOps, setSeedingRevenueOps] = useState(false);
  const [seedingAiLayer, setSeedingAiLayer] = useState(false);
  const [creatingType, setCreatingType] = useState(false);
  const [creatingAttribute, setCreatingAttribute] = useState(false);
  const [creatingRelationship, setCreatingRelationship] = useState(false);
  const [uploadingCsv, setUploadingCsv] = useState(false);
  const [sendingWebhook, setSendingWebhook] = useState(false);
  const [loadingDlq, setLoadingDlq] = useState(false);
  const [retryingDlq, setRetryingDlq] = useState(false);
  const [deletingViewId, setDeletingViewId] = useState("");

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2800);
  }

  const loadStudioData = useCallback(async (withSpinner = true) => {
    if (withSpinner) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError("");

    try {
      const [
        summaryResponse,
        statusResponse,
        entityTypesResponse,
        relationshipTypesResponse,
        savedViewsResponse,
        dlqKeysResponse,
      ] = await Promise.all([
        client.get<WorkspaceSystemSummary>("/workspace/system/summary"),
        client.get<WorkspaceSystemStatus>("/workspace/system/status"),
        client.get<EntityTypeSummary[]>("/ontology/entity-types"),
        client.get<RelationshipTypeSummary[]>("/ontology/relationship-types"),
        client.get<SavedView[]>("/workspace/views"),
        client.get<DlqKeySummary[]>("/ingest/dlq/keys"),
      ]);

      setSummary(summaryResponse.data);
      setStatus(statusResponse.data);
      setEntityTypes(entityTypesResponse.data);
      setRelationshipTypes(relationshipTypesResponse.data);
      setSavedViews(savedViewsResponse.data);
      setDlqKeys(dlqKeysResponse.data);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to load admin studio"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadSelectedType = useCallback(async (typeNameToLoad: string) => {
    if (!typeNameToLoad) {
      setSelectedType(null);
      return;
    }

    try {
      const response = await client.get<EntityTypeDetail>(`/ontology/entity-types/${encodeURIComponent(typeNameToLoad)}`);
      setSelectedType(response.data);
    } catch (err: unknown) {
      setError(errorMessage(err, `Failed to load EntityType '${typeNameToLoad}'`));
    }
  }, []);

  const loadDlq = useCallback(async (key: string) => {
    if (!key) {
      setSelectedDlqKey("");
      setDlqResponse(null);
      setDlqRetryResult(null);
      return;
    }

    setLoadingDlq(true);
    setSelectedDlqKey(key);
    setDlqRetryResult(null);
    try {
      const response = await client.get<DlqResponse>("/ingest/dlq", {
        params: { key },
      });
      setDlqResponse(response.data);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to load DLQ entries"));
    } finally {
      setLoadingDlq(false);
    }
  }, []);

  useEffect(() => {
    void loadStudioData();
  }, [loadStudioData]);

  useEffect(() => {
    if (entityTypes.length === 0) {
      setSelectedTypeName("");
      setSelectedType(null);
      setCsvTypeName("");
      return;
    }

    if (!selectedTypeName || !entityTypes.some((entityType) => entityType.name === selectedTypeName)) {
      setSelectedTypeName(entityTypes[0].name);
    }

    if (!csvTypeName || !entityTypes.some((entityType) => entityType.name === csvTypeName)) {
      setCsvTypeName(entityTypes[0].name);
    }

    if (!relationshipSource) {
      setRelationshipSource(entityTypes[0].name);
    }

    if (!relationshipTarget) {
      setRelationshipTarget(entityTypes[0].name);
    }
  }, [csvTypeName, entityTypes, relationshipSource, relationshipTarget, selectedTypeName]);

  useEffect(() => {
    void loadSelectedType(selectedTypeName);
  }, [loadSelectedType, selectedTypeName]);

  useEffect(() => {
    if (!selectedDlqKey && dlqKeys[0]?.key) {
      void loadDlq(dlqKeys[0].key);
    }
  }, [dlqKeys, loadDlq, selectedDlqKey]);

  async function createEntityType(event: FormEvent) {
    event.preventDefault();
    if (!typeName.trim()) {
      return;
    }

    setCreatingType(true);
    setError("");
    try {
      await client.post("/ontology/entity-types", {
        name: typeName.trim(),
        description: typeDescription.trim() || undefined,
      });
      setTypeName("");
      setTypeDescription("");
      setSelectedTypeName(typeName.trim());
      notify(`EntityType '${typeName.trim()}' created`);
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to create entity type"));
    } finally {
      setCreatingType(false);
    }
  }

  async function createAttribute(event: FormEvent) {
    event.preventDefault();
    if (!selectedTypeName || !attributeName.trim()) {
      return;
    }

    setCreatingAttribute(true);
    setError("");
    try {
      await client.post(`/ontology/entity-types/${encodeURIComponent(selectedTypeName)}/attributes`, {
        name: attributeName.trim(),
        data_type: attributeType,
        required: attributeRequired,
        cardinality: attributeCardinality,
      });
      setAttributeName("");
      setAttributeType("STRING");
      setAttributeRequired(false);
      setAttributeCardinality("SINGLE");
      notify(`Attribute '${attributeName.trim()}' added to ${selectedTypeName}`);
      await Promise.all([loadSelectedType(selectedTypeName), loadStudioData(false)]);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to add attribute"));
    } finally {
      setCreatingAttribute(false);
    }
  }

  async function createRelationship(event: FormEvent) {
    event.preventDefault();
    if (!relationshipName.trim() || !relationshipSource || !relationshipTarget) {
      return;
    }

    setCreatingRelationship(true);
    setError("");
    try {
      await client.post("/ontology/relationship-types", {
        name: relationshipName.trim(),
        source_type: relationshipSource,
        target_type: relationshipTarget,
      });
      setRelationshipName("");
      notify(`Relationship '${relationshipName.trim()}' created`);
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to create relationship type"));
    } finally {
      setCreatingRelationship(false);
    }
  }

  async function seedRevenueOps() {
    setSeedingRevenueOps(true);
    setError("");
    try {
      await client.post("/workspace/verticals/revenue-ops/seed");
      notify("Revenue operations workspace seeded");
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to seed revenue operations workspace"));
    } finally {
      setSeedingRevenueOps(false);
    }
  }

  async function seedCyberThreat() {
    setSeedingCyberThreat(true);
    setError("");
    try {
      await client.post("/workspace/verticals/cyber-threat/seed");
      notify("Cyber threat workspace seeded");
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to seed cyber threat workspace"));
    } finally {
      setSeedingCyberThreat(false);
    }
  }

  async function seedAiLayer() {
    setSeedingAiLayer(true);
    setError("");
    try {
      await client.post("/workspace/verticals/revenue-ops/ai-layer");
      notify("AI ontology layer added");
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to add AI ontology layer"));
    } finally {
      setSeedingAiLayer(false);
    }
  }

  async function uploadCsv(event: FormEvent) {
    event.preventDefault();
    if (!csvFile || !csvTypeName) {
      return;
    }

    setUploadingCsv(true);
    setError("");
    try {
      const payload = new FormData();
      payload.append("file", csvFile);
      payload.append("type_name", csvTypeName);
      payload.append("column_map", csvColumnMap.trim() || sampleColumnMap(selectedType));

      const response = await client.post<CsvIngestResult>("/ingest/csv", payload);
      setCsvResult(response.data);
      notify(`CSV ingest complete: ${response.data.ingested} rows ingested`);
      await loadStudioData(false);
      if (response.data.dlq_key) {
        await loadDlq(response.data.dlq_key);
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to ingest CSV"));
    } finally {
      setUploadingCsv(false);
    }
  }

  async function sendWebhook(event: FormEvent) {
    event.preventDefault();
    if (!webhookSource.trim() || !webhookEventType.trim()) {
      return;
    }

    let operationsPayload: unknown;
    try {
      operationsPayload = JSON.parse(webhookOperations.trim() || sampleWebhookOperations(selectedType));
    } catch {
      setError("Webhook operations must be valid JSON");
      return;
    }

    setSendingWebhook(true);
    setError("");
    try {
      const response = await client.post<WebhookIngestResult>("/ingest/webhook", {
        source: webhookSource.trim(),
        event_type: webhookEventType.trim(),
        event_id: webhookEventId.trim() || undefined,
        operations: operationsPayload,
      });
      setWebhookResult(response.data);
      notify(
        `Webhook ingested: ${response.data.entities_created} entities, ${response.data.connections_created} connections`,
      );
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to ingest webhook payload"));
    } finally {
      setSendingWebhook(false);
    }
  }

  async function retrySelectedDlq() {
    if (!selectedDlqKey) {
      return;
    }

    setRetryingDlq(true);
    setError("");
    try {
      const response = await client.post<DlqRetryResult>("/ingest/dlq/retry", {
        key: selectedDlqKey,
      });
      notify(`DLQ retry complete: ${response.data.recovered} rows recovered`);
      await loadStudioData(false);
      await loadDlq(selectedDlqKey);
      setDlqRetryResult(response.data);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to retry DLQ rows"));
    } finally {
      setRetryingDlq(false);
    }
  }

  async function deleteView(viewId: string) {
    setDeletingViewId(viewId);
    setError("");
    try {
      await client.delete(`/workspace/views/${encodeURIComponent(viewId)}`);
      notify("Saved view deleted");
      await loadStudioData(false);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to delete saved view"));
    } finally {
      setDeletingViewId("");
    }
  }

  const metricCards = summary
    ? [
        { label: "Entity Types", value: summary.entity_types, hint: "Schema nodes currently defined" },
        { label: "Relationships", value: summary.relationship_types, hint: "Edge types analysts can ingest" },
        { label: "Entities", value: summary.entities, hint: "Tenant-scoped graph nodes" },
        { label: "Alerts", value: summary.alerts, hint: "AI signals already in play" },
        { label: "Saved Views", value: summary.saved_views, hint: "Reusable graph lenses" },
        { label: "Cases", value: summary.cases, hint: "Investigation work items" },
      ]
    : [];

  if (loading) {
    return (
      <section className="page admin-page">
        <div className="panel">Loading admin studio…</div>
      </section>
    );
  }

  return (
    <section className="page admin-page">
      <div className="page-header">
        <div>
          <p className="eyebrow">Admin Studio</p>
          <h2>Set up schema, ingest data, and verify the tenant is healthy.</h2>
        </div>
        <div className="studio-inline-actions">
          <button type="button" className="ghost-button" onClick={() => void loadStudioData(false)}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="studio-metric-grid">
        {metricCards.map((metric) => (
          <article key={metric.label} className="metric-card">
            <div className="metric-label">{metric.label}</div>
            <div className="metric-value">{metric.value}</div>
            <p>{metric.hint}</p>
          </article>
        ))}
      </div>

      <div className="studio-layout">
        <article className="panel studio-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Tenant Bootstrap</p>
              <h3>Seed and verify the environment</h3>
            </div>
          </div>

          <div className="studio-status-grid">
            <div className={`status-pill ${statusTone(status?.neo4j ?? "degraded")}`}>
              <span>Neo4j</span>
              <strong>{status?.neo4j ?? "unknown"}</strong>
            </div>
            <div className={`status-pill ${statusTone(status?.redis ?? "degraded")}`}>
              <span>Redis</span>
              <strong>{status?.redis ?? "unknown"}</strong>
            </div>
            <div className={`status-pill ${statusTone(status?.frontend_bundle_present ?? false)}`}>
              <span>Frontend Bundle</span>
              <strong>{status?.frontend_bundle_present ? "present" : "missing"}</strong>
            </div>
            <div className="status-pill neutral">
              <span>Tenant</span>
              <strong>{status?.tenant_id ?? localStorage.getItem("tenant_id") ?? "unknown"}</strong>
            </div>
            <div className="status-pill neutral">
              <span>Version</span>
              <strong>{status?.api_version ?? "1.0.0"}</strong>
            </div>
            <div className="status-pill neutral">
              <span>Origins</span>
              <strong>{status?.allowed_origins.join(", ") ?? "n/a"}</strong>
            </div>
          </div>

          <p className="studio-helper-text">
            Phase 1 uses the cyber-threat graph to prove ontology CRUD and traversal. Revenue Ops remains available as the
            broader product demo path.
          </p>

          <div className="studio-action-row">
            <button type="button" onClick={() => void seedCyberThreat()} disabled={seedingCyberThreat}>
              {seedingCyberThreat ? "Seeding…" : "Seed Cyber Threat"}
            </button>
            <button type="button" onClick={() => void seedRevenueOps()} disabled={seedingRevenueOps}>
              {seedingRevenueOps ? "Seeding…" : "Seed Revenue Ops"}
            </button>
            <button type="button" className="ghost-button" onClick={() => void seedAiLayer()} disabled={seedingAiLayer}>
              {seedingAiLayer ? "Adding…" : "Add AI Layer"}
            </button>
          </div>

          <div className="studio-command-block">
            <p className="eyebrow">Local Verification</p>
            <pre>{`cp .env.example .env
python -m pip install -r api/requirements-dev.txt
make test-stack-up
npm --prefix frontend ci
make frontend-lint
make frontend-build
make test`}</pre>
          </div>
        </article>

        <article className="panel studio-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Ontology</p>
              <h3>Manage entity types, attributes, and edge types</h3>
            </div>
          </div>

          <div className="studio-form-grid">
            <form className="studio-form" onSubmit={createEntityType}>
              <label htmlFor="type-name">Entity type name</label>
              <input
                id="type-name"
                value={typeName}
                onChange={(event) => setTypeName(event.target.value)}
                placeholder="Customer"
              />
              <label htmlFor="type-description">Description</label>
              <textarea
                id="type-description"
                value={typeDescription}
                onChange={(event) => setTypeDescription(event.target.value)}
                rows={4}
                placeholder="Customer account with health, revenue, and renewal metadata"
              />
              <button type="submit" disabled={creatingType}>
                {creatingType ? "Creating…" : "Create Entity Type"}
              </button>
            </form>

            <form className="studio-form" onSubmit={createRelationship}>
              <label htmlFor="relationship-name">Relationship type</label>
              <input
                id="relationship-name"
                value={relationshipName}
                onChange={(event) => setRelationshipName(event.target.value)}
                placeholder="HAS_CONTRACT"
              />
              <label htmlFor="relationship-source">Source type</label>
              <select
                id="relationship-source"
                value={relationshipSource}
                onChange={(event) => setRelationshipSource(event.target.value)}
              >
                {entityTypes.map((entityType) => (
                  <option key={entityType.name} value={entityType.name}>
                    {entityType.name}
                  </option>
                ))}
              </select>
              <label htmlFor="relationship-target">Target type</label>
              <select
                id="relationship-target"
                value={relationshipTarget}
                onChange={(event) => setRelationshipTarget(event.target.value)}
              >
                {entityTypes.map((entityType) => (
                  <option key={entityType.name} value={entityType.name}>
                    {entityType.name}
                  </option>
                ))}
              </select>
              <button type="submit" disabled={creatingRelationship}>
                {creatingRelationship ? "Creating…" : "Create Relationship"}
              </button>
            </form>
          </div>

          <div className="studio-split">
            <div className="studio-list">
              <div className="floating-card-header">
                <h4>Entity types</h4>
                <span className="relationship-count">{entityTypes.length}</span>
              </div>
              <div className="graph-floating-list compact">
                {entityTypes.map((entityType) => (
                  <button
                    key={entityType.name}
                    type="button"
                    className={`list-card list-card-button graph-float-item${selectedTypeName === entityType.name ? " selected" : ""}`}
                    onClick={() => setSelectedTypeName(entityType.name)}
                  >
                    <div className="investigation-card-copy">
                      <strong>{entityType.name}</strong>
                      <p>{entityType.description || "No description yet"}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="studio-detail">
              <div className="floating-card-header">
                <div>
                  <h4>{selectedType?.name ?? "Selected type"}</h4>
                  <p>{selectedType?.description || "Pick an entity type to inspect its attributes."}</p>
                </div>
                <span className="relationship-count">{selectedType?.attributes.length ?? 0}</span>
              </div>

              <div className="studio-attribute-list">
                {selectedType?.attributes.length ? (
                  selectedType.attributes.map((attribute) => (
                    <div key={attribute.name} className="kv-row">
                      <span>{attribute.name}</span>
                      <strong>{attribute.data_type} · {attribute.cardinality}</strong>
                    </div>
                  ))
                ) : (
                  <div className="empty-state compact">No attributes defined yet.</div>
                )}
              </div>

              <form className="studio-form" onSubmit={createAttribute}>
                <label htmlFor="attribute-name">Attribute name</label>
                <input
                  id="attribute-name"
                  value={attributeName}
                  onChange={(event) => setAttributeName(event.target.value)}
                  placeholder="Renewal Date"
                />
                <div className="studio-inline-grid">
                  <div>
                    <label htmlFor="attribute-type">Data type</label>
                    <select
                      id="attribute-type"
                      value={attributeType}
                      onChange={(event) => setAttributeType(event.target.value as DataType)}
                    >
                      {DATA_TYPES.map((dataType) => (
                        <option key={dataType} value={dataType}>
                          {dataType}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="attribute-cardinality">Cardinality</label>
                    <select
                      id="attribute-cardinality"
                      value={attributeCardinality}
                      onChange={(event) => setAttributeCardinality(event.target.value as Cardinality)}
                    >
                      {CARDINALITIES.map((cardinality) => (
                        <option key={cardinality} value={cardinality}>
                          {cardinality}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <label className="studio-checkbox">
                  <input
                    type="checkbox"
                    checked={attributeRequired}
                    onChange={(event) => setAttributeRequired(event.target.checked)}
                  />
                  Required attribute
                </label>
                <button type="submit" disabled={creatingAttribute || !selectedTypeName}>
                  {creatingAttribute ? "Adding…" : "Add Attribute"}
                </button>
              </form>

              <div className="studio-relationship-list">
                <div className="floating-card-header">
                  <h4>Relationship catalog</h4>
                  <span className="relationship-count">{relationshipTypes.length}</span>
                </div>
                <div className="graph-floating-list compact">
                  {relationshipTypes.map((relationshipType) => (
                    <div key={relationshipType.name} className="list-card graph-float-item">
                      <div className="investigation-card-copy">
                        <strong>{relationshipType.name}</strong>
                        <p>{relationshipType.source_type} → {relationshipType.target_type}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </article>

        <article className="panel studio-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">CSV Ingestion</p>
              <h3>Map columns to ontology attributes and ingest tenant data</h3>
            </div>
          </div>

          <form className="studio-form" onSubmit={uploadCsv}>
            <label htmlFor="csv-type">Entity type</label>
            <select
              id="csv-type"
              value={csvTypeName}
              onChange={(event) => {
                setCsvTypeName(event.target.value);
                if (selectedTypeName !== event.target.value) {
                  setSelectedTypeName(event.target.value);
                }
              }}
            >
              {entityTypes.map((entityType) => (
                <option key={entityType.name} value={entityType.name}>
                  {entityType.name}
                </option>
              ))}
            </select>

            <div className="floating-card-header">
              <label htmlFor="csv-map">Column map JSON</label>
              <button type="button" className="text-link" onClick={() => setCsvColumnMap(sampleColumnMap(selectedType))}>
                Autofill from selected type
              </button>
            </div>
            <textarea
              id="csv-map"
              value={csvColumnMap}
              onChange={(event) => setCsvColumnMap(event.target.value)}
              rows={9}
              placeholder={sampleColumnMap(selectedType)}
            />

            <label htmlFor="csv-file">CSV file</label>
            <input
              id="csv-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
            />

            <button type="submit" disabled={uploadingCsv || !csvFile}>
              {uploadingCsv ? "Uploading…" : "Ingest CSV"}
            </button>
          </form>

          {csvResult && (
            <div className="studio-result-strip">
              <div>
                <span>Rows</span>
                <strong>{csvResult.total_rows}</strong>
              </div>
              <div>
                <span>Ingested</span>
                <strong>{csvResult.ingested}</strong>
              </div>
              <div>
                <span>Failed</span>
                <strong>{csvResult.failed}</strong>
              </div>
              <div>
                <span>DLQ Key</span>
                <strong>{csvResult.dlq_key}</strong>
              </div>
            </div>
          )}
        </article>

        <article className="panel studio-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Webhook Ingestion</p>
              <h3>Post structured events directly into the graph</h3>
            </div>
          </div>

          <form className="studio-form" onSubmit={sendWebhook}>
            <div className="studio-inline-grid">
              <div>
                <label htmlFor="webhook-source">Source</label>
                <input
                  id="webhook-source"
                  value={webhookSource}
                  onChange={(event) => setWebhookSource(event.target.value)}
                  placeholder="crm-webhook"
                />
              </div>
              <div>
                <label htmlFor="webhook-event-type">Event type</label>
                <input
                  id="webhook-event-type"
                  value={webhookEventType}
                  onChange={(event) => setWebhookEventType(event.target.value)}
                  placeholder="contact.created"
                />
              </div>
            </div>

            <label htmlFor="webhook-event-id">Event id</label>
            <input
              id="webhook-event-id"
              value={webhookEventId}
              onChange={(event) => setWebhookEventId(event.target.value)}
              placeholder="Optional, autogenerated if omitted"
            />

            <div className="floating-card-header">
              <label htmlFor="webhook-operations">Operations JSON</label>
              <button
                type="button"
                className="text-link"
                onClick={() => setWebhookOperations(sampleWebhookOperations(selectedType))}
              >
                Autofill from selected type
              </button>
            </div>
            <textarea
              id="webhook-operations"
              value={webhookOperations}
              onChange={(event) => setWebhookOperations(event.target.value)}
              rows={11}
              placeholder={sampleWebhookOperations(selectedType)}
            />

            <button type="submit" disabled={sendingWebhook}>
              {sendingWebhook ? "Posting…" : "Post Webhook Payload"}
            </button>
          </form>

          {webhookResult && (
            <div className="studio-result-strip">
              <div>
                <span>Entities</span>
                <strong>{webhookResult.entities_created}</strong>
              </div>
              <div>
                <span>Connections</span>
                <strong>{webhookResult.connections_created}</strong>
              </div>
              <div>
                <span>Event</span>
                <strong>{webhookResult.event_id}</strong>
              </div>
              <div>
                <span>Received</span>
                <strong>{prettyTimestamp(webhookResult.received_at)}</strong>
              </div>
            </div>
          )}
        </article>

        <article className="panel studio-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Views & DLQ</p>
              <h3>Clean up saved views and inspect failed imports</h3>
            </div>
          </div>

          <div className="studio-split">
            <div className="studio-list">
              <div className="floating-card-header">
                <h4>Saved views</h4>
                <span className="relationship-count">{savedViews.length}</span>
              </div>
              <div className="graph-floating-list compact">
                {savedViews.length ? (
                  savedViews.map((view) => (
                    <div key={view.view_id} className="list-card graph-float-item studio-view-card">
                      <div className="investigation-card-copy">
                        <strong>{view.name}</strong>
                        <p>{view.description || "Saved graph view"}</p>
                      </div>
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => void deleteView(view.view_id)}
                        disabled={deletingViewId === view.view_id}
                      >
                        {deletingViewId === view.view_id ? "Deleting…" : "Delete"}
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="empty-state compact">No saved views to manage.</div>
                )}
              </div>
            </div>

            <div className="studio-detail">
              <div className="floating-card-header">
                <h4>Dead-letter queue</h4>
                <span className="relationship-count">{dlqKeys.length}</span>
              </div>

              <div className="graph-floating-list compact">
                {dlqKeys.length ? (
                  dlqKeys.map((dlqKey) => (
                    <button
                      key={dlqKey.key}
                      type="button"
                      className={`list-card list-card-button graph-float-item${selectedDlqKey === dlqKey.key ? " selected" : ""}`}
                      onClick={() => void loadDlq(dlqKey.key)}
                    >
                      <div className="investigation-card-copy">
                        <strong>{dlqKey.key}</strong>
                        <p>{prettyTimestamp(dlqKey.created_at)}</p>
                      </div>
                      <span className="relationship-count">{dlqKey.item_count}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state compact">No failed CSV rows have been recorded.</div>
                )}
              </div>

              <div className="studio-dlq-detail">
                <div className="floating-card-header">
                  <h4>Selected DLQ items</h4>
                  <div className="studio-inline-actions">
                    <span className="relationship-count">{dlqResponse?.count ?? 0}</span>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => void retrySelectedDlq()}
                      disabled={retryingDlq || loadingDlq || !selectedDlqKey || !dlqResponse?.count}
                    >
                      {retryingDlq ? "Retrying…" : "Retry All"}
                    </button>
                  </div>
                </div>
                {dlqRetryResult && dlqRetryResult.key === selectedDlqKey && (
                  <div className="studio-result-strip">
                    <div>
                      <span>Requested</span>
                      <strong>{dlqRetryResult.requested}</strong>
                    </div>
                    <div>
                      <span>Recovered</span>
                      <strong>{dlqRetryResult.recovered}</strong>
                    </div>
                    <div>
                      <span>Remaining</span>
                      <strong>{dlqRetryResult.remaining}</strong>
                    </div>
                    <div>
                      <span>Failed</span>
                      <strong>{dlqRetryResult.failed.length}</strong>
                    </div>
                  </div>
                )}
                {loadingDlq ? (
                  <div className="panel">Loading DLQ entries…</div>
                ) : dlqResponse?.items.length ? (
                  <div className="graph-floating-list compact">
                    {dlqResponse.items.map((item) => (
                      <div key={`${item.row_index}-${item.timestamp}`} className="list-card graph-float-item">
                        <div className="investigation-card-copy">
                          <strong>Row {item.row_index}</strong>
                          <p>{item.type_name ? `${item.type_name} · ${item.error}` : item.error}</p>
                        </div>
                        <span className="pill critical">{Object.keys(item.raw_row).length} cols</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state compact">Select a DLQ key to inspect failed rows.</div>
                )}
                {dlqRetryResult?.failed.length ? (
                  <div className="graph-floating-list compact">
                    {dlqRetryResult.failed.map((failure) => (
                      <div key={`${failure.row_index}-${failure.error}`} className="list-card graph-float-item">
                        <div className="investigation-card-copy">
                          <strong>Retry failed: row {failure.row_index}</strong>
                          <p>{failure.error}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </article>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </section>
  );
}
