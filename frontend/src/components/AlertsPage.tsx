import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import client from "../api/client";
import type { AlertDecision, AlertDecisionResponse, AlertSummary, EntityDetail } from "../types";

const AI_TYPES = new Set([
  "Document",
  "Observation",
  "Hypothesis",
  "Alert",
  "Recommendation",
  "ModelRun",
  "PromptTemplate",
]);

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertSummary[]>([]);
  const [selectedAlert, setSelectedAlert] = useState<EntityDetail | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [actionLoading, setActionLoading] = useState<AlertDecision | null>(null);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const selectedAlertId = params.get("alertId") ?? "";

  const loadAlerts = useCallback(async (currentAlertId: string) => {
    setError("");
    try {
      const { data } = await client.get("/workspace/alerts");
      setAlerts(data);
      if (!currentAlertId && data[0]?.alert_id) {
        setParams({ alertId: data[0].alert_id });
      }
    } catch {
      setError("Failed to load alerts");
    }
  }, [setParams]);

  const loadAlert = useCallback(async (alertId: string) => {
    try {
      const { data } = await client.get(`/query/entity/${alertId}`);
      setSelectedAlert(data);
    } catch {
      setError("Failed to load alert detail");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadAlerts(selectedAlertId);
    });
  }, [loadAlerts, selectedAlertId]);

  useEffect(() => {
    if (selectedAlertId) {
      queueMicrotask(() => {
        void loadAlert(selectedAlertId);
      });
    }
  }, [loadAlert, selectedAlertId]);

  const activeAlert = selectedAlert?.entity_id === selectedAlertId ? selectedAlert : null;

  async function decideAlert(decision: AlertDecision) {
    if (!activeAlert) return;
    setActionLoading(decision);
    setError("");
    try {
      const { data } = await client.post<AlertDecisionResponse>(
        `/workspace/alerts/${activeAlert.entity_id}/decision`,
        { decision, notes: notes.trim() || undefined },
      );
      setNotes("");
      setToast(
        data.case_id
          ? `Alert escalated and case created`
          : `Alert ${data.alert_status}`,
      );
      setTimeout(() => setToast(""), 3000);
      await loadAlerts(selectedAlertId);
      await loadAlert(activeAlert.entity_id);
      if (data.case_id) {
        navigate(`/cases?caseId=${encodeURIComponent(data.case_id)}`);
      }
    } catch {
      setError("Failed to record alert decision");
    } finally {
      setActionLoading(null);
    }
  }

  const aiContext = activeAlert
    ? activeAlert.related_entities.filter((related) => AI_TYPES.has(related.type_name))
    : [];
  const businessContext = activeAlert
    ? activeAlert.related_entities.filter((related) => !AI_TYPES.has(related.type_name))
    : [];

  return (
    <section className="page">
      <div className="page-header compact">
        <div>
          <p className="eyebrow">Alerts</p>
          <h2>Review prioritized AI signals and write decisions back into the ontology.</h2>
        </div>
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="case-layout">
        <aside className="panel rail">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Queue</p>
              <h3>Prioritized alerts</h3>
            </div>
          </div>
          <div className="list-stack grow">
            {alerts.length ? (
              alerts.map((alert) => (
                <button
                  key={alert.alert_id}
                  className={`list-card list-card-button${activeAlert?.entity_id === alert.alert_id ? " selected" : ""}`}
                  onClick={() => setParams({ alertId: alert.alert_id })}
                >
                  <div>
                    <strong>{alert.label}</strong>
                    <p>{alert.alert_category.replace(/_/g, " ")}</p>
                  </div>
                  <div className="alert-score">
                    <span className="pill critical">{Math.round(alert.risk_score ?? 0)}</span>
                    <span className="pill neutral">{alert.alert_status}</span>
                  </div>
                </button>
              ))
            ) : (
              <div className="empty-state compact">No alerts available for this tenant.</div>
            )}
          </div>
        </aside>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Alert Detail</p>
              <h3>{activeAlert?.label ?? "No alert selected"}</h3>
            </div>
            {activeAlert && <span className="pill accent">{activeAlert.type_name}</span>}
          </div>

          {activeAlert ? (
            <div className="case-detail">
              <p className="muted">{activeAlert.entity_id}</p>

              <div className="detail-section">
                <h4>Signal properties</h4>
                <div className="kv-grid">
                  {Object.entries(activeAlert.properties).map(([key, value]) => (
                    <div key={key} className="kv-row">
                      <span>{key}</span>
                      <strong>{String(value)}</strong>
                    </div>
                  ))}
                </div>
              </div>

              <div className="detail-section">
                <h4>Business context</h4>
                <div className="list-stack">
                  {businessContext.length ? (
                    businessContext.map((related) => (
                      <button
                        key={`${related.entity_id}-${related.relationship_type}`}
                        className="list-card list-card-button"
                        onClick={() => navigate(`/investigate?entityId=${encodeURIComponent(related.entity_id)}&depth=2`)}
                      >
                        <div>
                          <strong>{related.label}</strong>
                          <p>{related.relationship_type}</p>
                        </div>
                        <span className="pill open">{related.type_name}</span>
                      </button>
                    ))
                  ) : (
                    <div className="empty-state compact">No business entities linked yet.</div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <h4>AI context</h4>
                <div className="list-stack">
                  {aiContext.length ? (
                    aiContext.map((related) => (
                      <button
                        key={`${related.entity_id}-${related.relationship_type}`}
                        className="list-card list-card-button"
                        onClick={() => navigate(`/investigate?entityId=${encodeURIComponent(related.entity_id)}&depth=2`)}
                      >
                        <div>
                          <strong>{related.label}</strong>
                          <p>{related.relationship_type}</p>
                        </div>
                        <span className="pill neutral">{related.type_name}</span>
                      </button>
                    ))
                  ) : (
                    <div className="empty-state compact">No AI context linked yet.</div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <h4>Decision history</h4>
                <div className="list-stack">
                  {activeAlert.recent_actions.length ? (
                    activeAlert.recent_actions.map((action) => (
                      <div key={action.log_id} className="list-card">
                        <div>
                          <strong>{action.action_type.replace(/_/g, " ")}</strong>
                          <p>{action.executed_by}</p>
                        </div>
                        <span>{action.status}</span>
                      </div>
                    ))
                  ) : (
                    <div className="empty-state compact">No decisions recorded for this alert.</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-state">Select an alert from the queue.</div>
          )}
        </article>

        <aside className="panel create-case-form">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Decision</p>
              <h3>Write back operator intent</h3>
            </div>
          </div>

          <p className="muted">
            Capture alert review directly in the ontology so downstream users can see whether the signal was acknowledged,
            escalated into a case, or dismissed.
          </p>

          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Add operator notes, rationale, or escalation detail"
            rows={8}
          />

          <button disabled={!activeAlert || actionLoading !== null} onClick={() => void decideAlert("acknowledge")}>
            {actionLoading === "acknowledge" ? "Recording…" : "Acknowledge"}
          </button>
          <button
            className="ghost-button"
            disabled={!activeAlert || actionLoading !== null}
            onClick={() => void decideAlert("open_case")}
          >
            {actionLoading === "open_case" ? "Opening…" : "Open Case"}
          </button>
          <button
            className="ghost-button"
            disabled={!activeAlert || actionLoading !== null}
            onClick={() => void decideAlert("dismiss")}
          >
            {actionLoading === "dismiss" ? "Dismissing…" : "Dismiss"}
          </button>
        </aside>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </section>
  );
}
