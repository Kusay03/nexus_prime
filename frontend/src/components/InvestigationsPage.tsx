import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import client from "../api/client";
import GraphView from "./GraphView";
import type { EntityDetail, InvestigationBrief, PriorityInvestigation, SavedView, SearchResult } from "../types";

const AI_TYPES = new Set([
  "Document",
  "Observation",
  "Hypothesis",
  "Alert",
  "Recommendation",
  "ModelRun",
  "PromptTemplate",
]);

const AI_FIELD_LABELS: Record<string, string> = {
  Confidence: "Confidence",
  "Risk Level": "Risk",
  "Review Status": "Review",
  "Risk Score": "Risk Score",
  Priority: "Priority",
  "Model Name": "Model",
  "Model Version": "Version",
  "Prompt Version": "Prompt",
  "Source System": "Source",
  Task: "Task",
  "Alert Status": "Alert",
  "Run Status": "Run",
};

const AI_NARRATIVE_KEYS = [
  "Hypothesis",
  "Observation",
  "Recommendation",
  "Summary",
  "Purpose",
  "Alert Title",
  "Document Title",
  "Run Label",
  "Template Name",
];

const INFERENCE_TYPES = new Set(["Observation", "Hypothesis", "Alert", "Recommendation"]);
const PROVENANCE_TYPES = new Set(["Document", "PromptTemplate", "ModelRun"]);

type SignalKind = "fact" | "inference" | "provenance";

function signalKindForType(typeName: string): SignalKind {
  if (PROVENANCE_TYPES.has(typeName)) {
    return "provenance";
  }
  if (INFERENCE_TYPES.has(typeName)) {
    return "inference";
  }
  return "fact";
}

function signalLabelForType(typeName: string): string {
  const signalKind = signalKindForType(typeName);
  if (signalKind === "provenance") {
    return "Provenance";
  }
  if (signalKind === "inference") {
    return "Inference";
  }
  return "Fact";
}

function humanizeToken(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export default function InvestigationsPage() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [views, setViews] = useState<SavedView[]>([]);
  const [priorities, setPriorities] = useState<PriorityInvestigation[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState(params.get("entityId") ?? "");
  const [entityDetail, setEntityDetail] = useState<EntityDetail | null>(null);
  const [brief, setBrief] = useState<InvestigationBrief | null>(null);
  const [depth, setDepth] = useState(Number(params.get("depth") ?? "2"));
  const [error, setError] = useState("");
  const [savingView, setSavingView] = useState(false);
  const [creatingCase, setCreatingCase] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [toast, setToast] = useState("");
  const navigate = useNavigate();

  const loadViews = useCallback(async () => {
    try {
      const { data } = await client.get("/workspace/views");
      setViews(data);
    } catch {
      // Keep investigate flow working even if the saved views request fails.
    }
  }, []);

  const loadPriorities = useCallback(async () => {
    try {
      const { data } = await client.get<PriorityInvestigation[]>("/workspace/priorities");
      setPriorities(data);
    } catch {
      // Keep the page usable even if priorities fail.
    }
  }, []);

  const runSearch = useCallback(async (query: string, syncUrl = true) => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      return;
    }

    setError("");
    try {
      const { data } = await client.post("/query/search", {
        query: trimmed,
        limit: 12,
      });
      setResults(data.results);
      if (syncUrl) {
        setParams((current) => {
          const next = new URLSearchParams(current);
          next.set("q", trimmed);
          return next;
        });
      }
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Search failed");
      } else {
        setError("Search failed");
      }
    }
  }, [setParams]);

  const loadEntity = useCallback(async (entityId: string) => {
    setError("");
    try {
      const { data } = await client.get(`/query/entity/${entityId}`);
      setEntityDetail(data);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Failed to load entity");
      } else {
        setError("Failed to load entity");
      }
    }
  }, []);

  const loadBrief = useCallback(async (entityId: string) => {
    try {
      const { data } = await client.get<InvestigationBrief>(`/workspace/briefs/${entityId}`);
      setBrief(data);
    } catch {
      setBrief(null);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadViews();
      void loadPriorities();
    });
  }, [loadPriorities, loadViews]);

  useEffect(() => {
    const paramEntity = params.get("entityId") ?? "";
    const paramDepth = Number(params.get("depth") ?? "2");
    const paramQuery = params.get("q") ?? "";
    setSearch(paramQuery);
    setSelectedEntityId(paramEntity);
    setDepth(Number.isNaN(paramDepth) ? 2 : paramDepth);
    if (paramQuery) {
      queueMicrotask(() => {
        void runSearch(paramQuery, false);
      });
    } else {
      setResults([]);
    }
  }, [params, runSearch]);

  useEffect(() => {
    if (!selectedEntityId) {
      setEntityDetail(null);
      setBrief(null);
      return;
    }
    queueMicrotask(() => {
      void loadEntity(selectedEntityId);
      void loadBrief(selectedEntityId);
    });
  }, [loadBrief, loadEntity, selectedEntityId]);

  useEffect(() => {
    if (selectedEntityId || views.length === 0) {
      return;
    }
    setParams((current) => {
      if (current.get("entityId")) {
        return current;
      }
      const next = new URLSearchParams(current);
      next.set("entityId", views[0].root_entity_id);
      next.set("depth", String(views[0].depth));
      return next;
    });
  }, [selectedEntityId, setParams, views]);

  async function saveView() {
    if (!selectedEntityId) return;
    setSavingView(true);
    try {
      const resolvedName = saveName.trim() || `${entityDetail?.label ?? "Selected"} graph view`;
      const resolvedDescription =
        saveDescription.trim() || `Saved graph context for ${entityDetail?.label ?? "the selected entity"}.`;
      await client.post("/workspace/views", {
        name: resolvedName,
        description: resolvedDescription,
        root_entity_id: selectedEntityId,
        depth,
        layout: "dagre",
      });
      setSaveName("");
      setSaveDescription("");
      setToast("View saved");
      setTimeout(() => setToast(""), 2500);
      await loadViews();
    } catch {
      setToast("Save failed");
      setTimeout(() => setToast(""), 2500);
    } finally {
      setSavingView(false);
    }
  }

  async function createCaseFromEntity() {
    if (!entityDetail) return;
    setCreatingCase(true);
    try {
      const { data } = await client.post("/cases", {
        title: brief?.title ?? `Review ${entityDetail.label}`,
        description: brief
          ? `${brief.summary}\n\nWhy now: ${brief.why_now}`
          : `Investigation case opened from ${entityDetail.type_name} entity ${entityDetail.entity_id}.`,
        priority: brief?.confidence === "high" ? "high" : "medium",
        entity_ids: brief?.linked_entity_ids?.slice(0, 8) ?? [entityDetail.entity_id],
      });
      setToast(`Case created: ${data.title}`);
      setTimeout(() => setToast(""), 2500);
      navigate(`/cases?caseId=${encodeURIComponent(data.case_id)}`);
    } catch {
      setToast("Case creation failed");
      setTimeout(() => setToast(""), 2500);
    } finally {
      setCreatingCase(false);
    }
  }

  function openEntity(entityId: string) {
    setSelectedEntityId(entityId);
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("entityId", entityId);
      next.set("depth", String(depth));
      return next;
    });
  }

  function updateDepth(nextDepth: number) {
    setDepth(nextDepth);
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("depth", String(nextDepth));
      return next;
    });
  }

  const isAiEntity = entityDetail ? AI_TYPES.has(entityDetail.type_name) : false;
  const aiRelatedEntities = entityDetail
    ? entityDetail.related_entities.filter((related) => AI_TYPES.has(related.type_name))
    : [];
  const aiHighlights = entityDetail
    ? Object.entries(entityDetail.properties).filter(([key]) => key in AI_FIELD_LABELS)
    : [];
  const aiNarrative = entityDetail
    ? AI_NARRATIVE_KEYS.map((key) => entityDetail.properties[key]).find((value) => value)
    : undefined;
  const aiSignals = aiRelatedEntities.filter((related) =>
    ["Hypothesis", "Alert", "Recommendation"].includes(related.type_name),
  );
  const aiProvenance = aiRelatedEntities.filter((related) =>
    ["ModelRun", "PromptTemplate"].includes(related.type_name),
  );
  const showAiPanel = Boolean(entityDetail && (isAiEntity || aiRelatedEntities.length || aiHighlights.length || aiNarrative));
  const entitySignalKind = entityDetail ? signalKindForType(entityDetail.type_name) : "fact";
  const relatedProvenance = entityDetail
    ? entityDetail.related_entities.filter((related) => signalKindForType(related.type_name) === "provenance")
    : [];
  return (
    <section className="page graph-route-page">
      {error && <div className="banner error">{error}</div>}

      <div className="graph-route-stage">
        <div className="graph-route-canvas">
          <GraphView
            entityId={selectedEntityId}
            depth={depth}
            onOpenEntity={openEntity}
            onSelectEntity={openEntity}
            showSidebar={false}
            showToolbar={false}
          />
        </div>

        <div className="graph-route-searchbar">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search customer, invoice, contract, ticket, owner"
            onKeyDown={(e) => e.key === "Enter" && void runSearch(search)}
          />
          <button onClick={() => void runSearch(search)}>Search</button>
        </div>

        <div className="graph-route-left">
          <div className="graph-floating-card graph-legend-card">
            <h3>Node Classification</h3>
            <div className="legend-line-item">
              <span className="legend-shape fact" />
              <div>
                <strong>Facts</strong>
                <p>Customer, contract, invoice, ticket, account owner</p>
              </div>
            </div>
            <div className="legend-line-item">
              <span className="legend-shape inference" />
              <div>
                <strong>AI Inference</strong>
                <p>Observation, hypothesis, alert, recommendation</p>
              </div>
            </div>
            <div className="legend-line-item">
              <span className="legend-shape provenance" />
              <div>
                <strong>Provenance</strong>
                <p>Document, prompt template, model run</p>
              </div>
            </div>
          </div>

          <div className="graph-floating-card graph-rail-card">
            <section className="graph-rail-section">
              <div className="floating-card-header">
                <div>
                  <p className="eyebrow">Search Results</p>
                  <h3>Matched Nodes</h3>
                </div>
                <span className="relationship-count">{results.length}</span>
              </div>
              <div className="graph-floating-list">
                {results.length ? (
                  results.map((result) => (
                    <button
                      key={result.entity_id}
                      className={`list-card list-card-button graph-float-item${selectedEntityId === result.entity_id ? " selected" : ""}`}
                      onClick={() => openEntity(result.entity_id)}
                    >
                      <div className="investigation-card-copy">
                        <span className={`signal-pill ${signalKindForType(result.type_name)}`}>
                          {signalLabelForType(result.type_name)}
                        </span>
                        <strong>{result.label}</strong>
                        <p>{result.match_reason}</p>
                      </div>
                      <span className="relationship-count">{result.relationship_count}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state compact left-rail-empty">Search to find a starting node.</div>
                )}
              </div>
            </section>

            <section className="graph-rail-section">
              <div className="floating-card-header">
                <div>
                  <p className="eyebrow">Priority Queue</p>
                  <h3>Start Here</h3>
                </div>
              </div>
              <div className="graph-floating-list">
                {priorities.length ? (
                  priorities.slice(0, 4).map((item) => (
                    <button
                      key={item.root_entity_id}
                      className={`list-card list-card-button graph-float-item${selectedEntityId === item.root_entity_id ? " selected" : ""}`}
                      onClick={() => openEntity(item.root_entity_id)}
                    >
                      <div className="investigation-card-copy">
                        <span className="signal-pill inference">Priority {item.score}</span>
                        <strong>{item.title}</strong>
                        <p>{item.why_now}</p>
                      </div>
                      <span className="relationship-count">{item.type_name}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state compact left-rail-empty">No ranked investigations yet.</div>
                )}
              </div>
            </section>

            <section className="graph-rail-section">
              <div className="floating-card-header">
                <div>
                  <p className="eyebrow">Saved Graphs</p>
                  <h3>Reusable Views</h3>
                </div>
              </div>
              <div className="graph-floating-list">
                {views.length ? (
                  views.slice(0, 3).map((view) => (
                    <button
                      key={view.view_id}
                      className="list-card list-card-button graph-float-item"
                      onClick={() => {
                        setParams({
                          entityId: view.root_entity_id,
                          depth: String(view.depth),
                          q: search,
                        });
                      }}
                    >
                      <div className="investigation-card-copy">
                        <span className="signal-pill provenance">Saved Lens</span>
                        <strong>{view.name}</strong>
                        <p>{view.description || "Saved graph perspective"}</p>
                      </div>
                      <span className="relationship-count">{view.depth}h</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state compact left-rail-empty">No saved graphs yet.</div>
                )}
              </div>
            </section>
          </div>
        </div>

        <aside className="graph-route-inspector">
          {entityDetail ? (
            <>
              <div className="graph-inspector-header">
                <span className={`signal-pill ${entitySignalKind}`}>{signalLabelForType(entityDetail.type_name)}</span>
                <div>
                  <h2>{entityDetail.label}</h2>
                  <p>{entityDetail.type_name} • ID: {entityDetail.entity_id}</p>
                </div>
              </div>

              {brief && (
                <section className="graph-inspector-section">
                  <div className="floating-card-header">
                    <div>
                      <h3>{brief.title}</h3>
                      <p className="muted">{brief.summary}</p>
                    </div>
                    <span className={`signal-pill ${brief.confidence === "high" ? "inference" : brief.confidence === "medium" ? "fact" : "provenance"}`}>
                      {brief.confidence} confidence
                    </span>
                  </div>
                  <div className="brief-stack">
                    <div className="brief-row">
                      <span className="signal-pill fact">Why Now</span>
                      <p>{brief.why_now}</p>
                    </div>
                    {brief.recommended_actions.map((action) => (
                      <div key={action} className="brief-row">
                        <span className="signal-pill inference">Next Step</span>
                        <p>{action}</p>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {brief && brief.top_signals.length > 0 && (
                <section className="graph-inspector-section">
                  <h3>Top Signals</h3>
                  <div className="graph-floating-list compact">
                    {brief.top_signals.map((item) => (
                      <button
                        key={item.entity_id}
                        className="list-card list-card-button graph-float-item"
                        onClick={() => openEntity(item.entity_id)}
                      >
                        <div className="investigation-card-copy">
                          <span className={`signal-pill ${signalKindForType(item.type_name)}`}>
                            {item.type_name}
                          </span>
                          <strong>{item.label}</strong>
                          <p>{item.reason}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {aiNarrative && (
                <section className="graph-inspector-section">
                  <h3>Observation</h3>
                  <div className="observation-surface">
                    <p>{aiNarrative}</p>
                  </div>
                </section>
              )}

              {((brief && brief.evidence.length > 0) || relatedProvenance.length > 0 || aiProvenance.length > 0) && (
                <section className="graph-inspector-section">
                  <div className="floating-card-header">
                    <h3>Provenance & Evidence</h3>
                    <span className="signal-pill provenance">
                      {brief?.evidence.length ?? Math.max(relatedProvenance.length, aiProvenance.length)} Sources
                    </span>
                  </div>
                  <div className="graph-floating-list compact">
                    {(brief?.evidence.length
                      ? brief.evidence.map((item) => ({
                          entity_id: item.entity_id,
                          label: item.label,
                          type_name: item.type_name,
                          relationship_type: item.reason,
                          direction: "brief",
                        }))
                      : (relatedProvenance.length ? relatedProvenance : aiProvenance)).map((related) => (
                      <button
                        key={`${related.direction}-${related.entity_id}-${related.relationship_type}`}
                        className="list-card list-card-button graph-float-item"
                        onClick={() => openEntity(related.entity_id)}
                      >
                        <div className="investigation-card-copy">
                          <span className="signal-pill provenance">{related.type_name}</span>
                          <strong>{related.label}</strong>
                          <p>{humanizeToken(related.relationship_type)}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              <section className="graph-inspector-section">
                <h3>Metadata</h3>
                <div className="graph-metadata-grid">
                  {Object.entries(entityDetail.properties).slice(0, 6).map(([key, value]) => (
                    <div key={key}>
                      <p>{humanizeToken(key)}</p>
                      <strong>{String(value)}</strong>
                    </div>
                  ))}
                </div>
              </section>

              {showAiPanel && (
                <section className="graph-inspector-section">
                  <h3>AI Context</h3>
                  <div className="graph-floating-list compact">
                    {aiSignals.map((related) => (
                      <button
                        key={`${related.direction}-${related.entity_id}-${related.relationship_type}`}
                        className="list-card list-card-button graph-float-item"
                        onClick={() => openEntity(related.entity_id)}
                      >
                        <div className="investigation-card-copy">
                          <span className="signal-pill inference">{related.type_name}</span>
                          <strong>{related.label}</strong>
                          <p>{humanizeToken(related.relationship_type)}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              <div className="graph-inspector-actions">
                <button onClick={createCaseFromEntity} disabled={creatingCase}>
                  {creatingCase ? "Creating…" : "Open Case from Brief"}
                </button>
                <button className="ghost-button" onClick={saveView} disabled={savingView || !selectedEntityId}>
                  {savingView ? "Saving…" : "Save View"}
                </button>
              </div>
            </>
          ) : (
            <div className="graph-inspector-empty">
              <span className="signal-pill inference">Node Details</span>
              <h2>Select a node</h2>
              <p>Choose a node in the graph or from search results to inspect the business facts, AI reasoning, and provenance.</p>
            </div>
          )}
        </aside>

        <div className="graph-route-dock">
          <button type="button" onClick={() => updateDepth(Math.max(1, depth - 1))}>Zoom Out</button>
          <button type="button" onClick={() => updateDepth(Math.min(6, depth + 1))}>Zoom In</button>
          <button type="button" className="active">Reflow</button>
          <button type="button" onClick={() => setSearch("")}>Clear</button>
        </div>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </section>
  );
}
