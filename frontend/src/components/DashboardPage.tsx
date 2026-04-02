import { Link, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import client from "../api/client";
import type { DashboardSummary } from "../types";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [aiSeeding, setAiSeeding] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    void loadDashboard();
  }, []);

  async function loadDashboard() {
    setLoading(true);
    setError("");
    try {
      const { data } = await client.get("/workspace/dashboard");
      setData(data);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Failed to load dashboard");
      } else {
        setError("Failed to load dashboard");
      }
    } finally {
      setLoading(false);
    }
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    navigate(`/investigate?q=${encodeURIComponent(query.trim())}`);
  }

  async function seedRevenueOps() {
    setSeeding(true);
    setError("");
    try {
      await client.post("/workspace/verticals/revenue-ops/seed");
      await loadDashboard();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Failed to seed revenue ops demo");
      } else {
        setError("Failed to seed revenue ops demo");
      }
    } finally {
      setSeeding(false);
    }
  }

  async function seedAiLayer() {
    setAiSeeding(true);
    setError("");
    try {
      await client.post("/workspace/verticals/revenue-ops/ai-layer");
      await loadDashboard();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Failed to add AI ontology layer");
      } else {
        setError("Failed to add AI ontology layer");
      }
    } finally {
      setAiSeeding(false);
    }
  }

  const isEmpty = (data?.metrics ?? []).every((metric) => metric.value === 0);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h2>{data?.vertical ?? "Revenue Operations"} from customer signal to renewal risk.</h2>
        </div>
        <form className="hero-search" onSubmit={submitSearch}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search customer, invoice, contract, ticket, owner..."
          />
          <button type="submit">Search</button>
        </form>
      </div>

      {error && <div className="banner error">{error}</div>}

      {loading ? (
        <div className="panel">Loading dashboard…</div>
      ) : (
        <>
          {isEmpty && (
            <article className="panel seed-panel">
              <div>
                <p className="eyebrow">Revenue Ops Demo</p>
                <h3>Start with a realistic customer-risk scenario.</h3>
                <p>
                  Seed the tenant with customers, invoices, contracts, support tickets, and saved views
                  for renewal-risk investigations.
                </p>
              </div>
              <button onClick={seedRevenueOps} disabled={seeding || localStorage.getItem("role") !== "admin"}>
                {seeding ? "Seeding…" : "Seed Demo Workspace"}
              </button>
            </article>
          )}

          {!isEmpty && localStorage.getItem("role") === "admin" && (
            <article className="panel seed-panel">
              <div>
                <p className="eyebrow">AI Ontology Layer</p>
                <h3>Add model provenance, evidence, and recommendations to the graph.</h3>
                <p>
                  Seed AI-native entities like documents, observations, hypotheses, alerts, recommendations,
                  prompt templates, and model runs linked to the Acme renewal-risk scenario.
                </p>
              </div>
              <button onClick={seedAiLayer} disabled={aiSeeding}>
                {aiSeeding ? "Adding AI Layer…" : "Add AI Layer"}
              </button>
            </article>
          )}

          <div className="metric-grid">
            {data?.metrics.map((metric) => (
              <article key={metric.label} className="metric-card">
                <div className="metric-label">{metric.label}</div>
                <div className="metric-value">{metric.value}</div>
                <p>{metric.change_hint}</p>
              </article>
            ))}
          </div>

          <article className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Priority Queue</p>
                <h3>Where an analyst should look first</h3>
              </div>
              <Link to="/investigate" className="text-link">
                Investigate
              </Link>
            </div>
            <div className="list-stack">
              {data?.priority_investigations.length ? (
                data.priority_investigations.map((item) => (
                  <button
                    key={item.root_entity_id}
                    className="list-card list-card-button"
                    onClick={() =>
                      navigate(`/investigate?entityId=${encodeURIComponent(item.root_entity_id)}&depth=2`)
                    }
                  >
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.why_now}</p>
                    </div>
                    <div className="alert-score">
                      <span className="pill critical">{item.score}</span>
                      <span className="pill neutral">{item.type_name}</span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="empty-state">No priority investigations yet. Seed data or ingest entities to rank work.</div>
              )}
            </div>
          </article>

          <div className="content-grid">
            <article className="panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Recent Views</p>
                  <h3>Saved revenue workflows</h3>
                </div>
                <Link to="/investigate" className="text-link">
                  Open workspace
                </Link>
              </div>
              <div className="list-stack">
                {data?.recent_views.length ? (
                  data.recent_views.map((view) => (
                    <button
                      key={view.view_id}
                      className="list-card list-card-button"
                      onClick={() =>
                        navigate(
                          `/investigate?entityId=${encodeURIComponent(view.root_entity_id)}&depth=${view.depth}`,
                        )
                      }
                      >
                      <div>
                        <strong>{view.name}</strong>
                        <p>{view.description || "Saved revenue workflow view"}</p>
                      </div>
                      <span>{view.depth} hops</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state">No saved views yet. Save one from the investigate page.</div>
                )}
              </div>
            </article>

            <article className="panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Cases</p>
                  <h3>Revenue-risk investigations</h3>
                </div>
                <Link to="/cases" className="text-link">
                  Manage cases
                </Link>
              </div>
              <div className="list-stack">
                {data?.recent_cases.length ? (
                  data.recent_cases.map((item) => (
                    <button
                      key={item.case_id}
                      className="list-card list-card-button"
                      onClick={() => navigate(`/cases?caseId=${encodeURIComponent(item.case_id)}`)}
                    >
                      <div>
                        <strong>{item.title}</strong>
                        <p>{item.entity_count} linked entities</p>
                      </div>
                      <span className={`pill ${item.status}`}>{item.status.replace("_", " ")}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty-state">No cases yet. Create one from an entity or the cases page.</div>
                )}
              </div>
            </article>
          </div>

          <article className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Highlights</p>
                <h3>Accounts and objects driving revenue pressure</h3>
              </div>
            </div>
            <div className="entity-grid">
              {data?.highlighted_entities.map((entity) => (
                <button
                  key={entity.entity_id}
                  className="entity-card"
                  onClick={() =>
                    navigate(`/investigate?entityId=${encodeURIComponent(entity.entity_id)}&depth=2`)
                  }
                >
                  <div className="entity-card-top">
                    <span className="pill neutral">{entity.type_name}</span>
                    <span>{entity.relationship_count} links</span>
                  </div>
                  <strong>{entity.label}</strong>
                  <p>{entity.match_reason}</p>
                </button>
              ))}
            </div>
          </article>
        </>
      )}
    </section>
  );
}
