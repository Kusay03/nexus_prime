import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import client from "../api/client";
import type { CaseDetail, CaseSummary, SearchResult } from "../types";

function errorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = err as { response?: { data?: { detail?: string } } };
    return response.response?.data?.detail ?? fallback;
  }
  return fallback;
}

export default function CasesPage() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseDetail | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<CaseSummary["priority"]>("medium");
  const [entityQuery, setEntityQuery] = useState("");
  const [entityResults, setEntityResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");
  const [searchingEntities, setSearchingEntities] = useState(false);
  const [mutatingEntityId, setMutatingEntityId] = useState("");
  const [params, setParams] = useSearchParams();
  const selectedCaseId = params.get("caseId") ?? "";

  const loadCases = useCallback(async (currentCaseId: string) => {
    setError("");
    try {
      const { data } = await client.get("/cases");
      setCases(data);
      if (!currentCaseId && data[0]?.case_id) {
        setParams({ caseId: data[0].case_id });
      }
    } catch {
      setError("Failed to load cases");
    }
  }, [setParams]);

  const loadCase = useCallback(async (caseId: string) => {
    try {
      const { data } = await client.get(`/cases/${caseId}`);
      setSelectedCase(data);
    } catch {
      setError("Failed to load case detail");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadCases(selectedCaseId);
    });
  }, [loadCases, selectedCaseId]);

  useEffect(() => {
    if (selectedCaseId) {
      queueMicrotask(() => {
        void loadCase(selectedCaseId);
      });
    }
  }, [loadCase, selectedCaseId]);

  const activeCase = selectedCase?.case_id === selectedCaseId ? selectedCase : null;
  const linkedEntityIds = new Set(activeCase?.entities.map((entity) => entity.entity_id) ?? []);

  async function createCase(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      const { data } = await client.post("/cases", {
        title: title.trim(),
        description: description.trim() || undefined,
        priority,
        entity_ids: [],
      });
      setTitle("");
      setDescription("");
      await loadCases(selectedCaseId);
      setParams({ caseId: data.case_id });
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to create case"));
    }
  }

  async function updateStatus(status: CaseSummary["status"]) {
    if (!activeCase) return;
    try {
      const { data } = await client.patch(`/cases/${activeCase.case_id}`, { status });
      setSelectedCase(data);
      await loadCases(selectedCaseId);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to update case"));
    }
  }

  async function searchEntities(event: FormEvent) {
    event.preventDefault();
    if (!entityQuery.trim()) {
      setEntityResults([]);
      return;
    }

    setSearchingEntities(true);
    setError("");
    try {
      const { data } = await client.post<{ results: SearchResult[] }>("/query/search", {
        query: entityQuery.trim(),
        limit: 8,
      });
      setEntityResults(data.results);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to search entities"));
    } finally {
      setSearchingEntities(false);
    }
  }

  async function addEntityToCase(entityId: string) {
    if (!activeCase) return;

    setMutatingEntityId(entityId);
    setError("");
    try {
      const { data } = await client.post<CaseDetail>(`/cases/${activeCase.case_id}/entities`, {
        entity_id: entityId,
      });
      setSelectedCase(data);
      await loadCases(activeCase.case_id);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to add entity to case"));
    } finally {
      setMutatingEntityId("");
    }
  }

  async function removeEntityFromCase(entityId: string) {
    if (!activeCase) return;

    setMutatingEntityId(entityId);
    setError("");
    try {
      const { data } = await client.delete<CaseDetail>(`/cases/${activeCase.case_id}/entities/${entityId}`);
      setSelectedCase(data);
      await loadCases(activeCase.case_id);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to remove entity from case"));
    } finally {
      setMutatingEntityId("");
    }
  }

  return (
    <section className="page">
      <div className="page-header compact">
        <div>
          <p className="eyebrow">Case Management</p>
          <h2>Track renewal, collections, and customer-risk investigations.</h2>
        </div>
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="case-layout">
        <aside className="panel rail">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Cases</p>
              <h3>Open and recent work</h3>
            </div>
          </div>
          <div className="list-stack grow">
            {cases.map((item) => (
              <button
                key={item.case_id}
                className={`list-card list-card-button${activeCase?.case_id === item.case_id ? " selected" : ""}`}
                onClick={() => setParams({ caseId: item.case_id })}
              >
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.entity_count} entities</p>
                </div>
                <span className={`pill ${item.priority}`}>{item.priority}</span>
              </button>
            ))}
          </div>
        </aside>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Selected Case</p>
              <h3>{activeCase?.title ?? "No case selected"}</h3>
            </div>
            {activeCase && <span className={`pill ${activeCase.status}`}>{activeCase.status.replace("_", " ")}</span>}
          </div>

          {activeCase ? (
            <div className="case-detail">
              <p>{activeCase.description || "No description provided yet."}</p>
              <div className="detail-actions">
                <button onClick={() => void updateStatus("in_progress")}>Mark In Progress</button>
                <button className="ghost-button" onClick={() => void updateStatus("closed")}>
                  Close Case
                </button>
              </div>

              <div className="detail-section">
                <h4>Linked entities</h4>
                <div className="list-stack">
                  {activeCase.entities.length ? (
                    activeCase.entities.map((entity) => (
                      <div key={entity.entity_id} className="list-card">
                        <div>
                          <strong>{entity.label}</strong>
                          <p>{entity.type_name} · {entity.relationship_type}</p>
                        </div>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => void removeEntityFromCase(entity.entity_id)}
                          disabled={mutatingEntityId === entity.entity_id}
                        >
                          {mutatingEntityId === entity.entity_id ? "Removing…" : "Remove"}
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="empty-state compact">No entities linked to this case yet.</div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <h4>Add linked entities</h4>
                <form className="toolbar" onSubmit={searchEntities}>
                  <input
                    value={entityQuery}
                    onChange={(event) => setEntityQuery(event.target.value)}
                    placeholder="Search by entity label, type, or attribute"
                    disabled={!activeCase}
                  />
                  <button type="submit" disabled={!activeCase || searchingEntities}>
                    {searchingEntities ? "Searching…" : "Search"}
                  </button>
                </form>
                <div className="list-stack">
                  {entityResults.length ? (
                    entityResults.map((entity) => {
                      const alreadyLinked = linkedEntityIds.has(entity.entity_id);
                      return (
                        <div key={entity.entity_id} className="list-card">
                          <div>
                            <strong>{entity.label}</strong>
                            <p>{entity.type_name} · {entity.match_reason}</p>
                          </div>
                          <button
                            type="button"
                            className={alreadyLinked ? "ghost-button" : undefined}
                            onClick={() => void addEntityToCase(entity.entity_id)}
                            disabled={alreadyLinked || mutatingEntityId === entity.entity_id}
                          >
                            {mutatingEntityId === entity.entity_id
                              ? "Adding…"
                              : alreadyLinked
                                ? "Linked"
                                : "Add"}
                          </button>
                        </div>
                      );
                    })
                  ) : (
                    <div className="empty-state compact">
                      {entityQuery.trim()
                        ? "No matching entities found for this tenant."
                        : "Search for existing tenant entities to link to the case."}
                    </div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <h4>Recent actions</h4>
                <div className="list-stack">
                  {activeCase.recent_actions.length ? (
                    activeCase.recent_actions.map((action) => (
                      <div key={action.log_id} className="list-card">
                        <div>
                          <strong>{action.action_type.replace(/_/g, " ")}</strong>
                          <p>{action.executed_by}</p>
                        </div>
                        <span>{action.status}</span>
                      </div>
                    ))
                  ) : (
                    <div className="empty-state compact">No actions tied to this case yet.</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-state">Pick a case from the left rail.</div>
          )}
        </article>

        <form className="panel create-case-form" onSubmit={createCase}>
          <div className="panel-header">
            <div>
              <p className="eyebrow">Create Case</p>
              <h3>Open a new revenue-risk investigation</h3>
            </div>
          </div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Case title"
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe the customer, invoice, renewal, or support issue"
            rows={6}
          />
          <select value={priority} onChange={(e) => setPriority(e.target.value as CaseSummary["priority"])}>
            <option value="low">Low priority</option>
            <option value="medium">Medium priority</option>
            <option value="high">High priority</option>
            <option value="critical">Critical priority</option>
          </select>
          <button type="submit">Create Case</button>
        </form>
      </div>
    </section>
  );
}
