import { useCallback, useEffect, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type { ElementDefinition, Stylesheet } from "cytoscape";
import client from "../api/client";

const CYTO_STYLE: Stylesheet[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "background-color": "#4a90d9",
      color: "#fff",
      "text-valign": "center",
      "text-halign": "center",
      "font-size": "10px",
      width: 40,
      height: 40,
    },
  },
  {
    selector: "edge",
    style: {
      label: "data(label)",
      "line-color": "#aaa",
      "target-arrow-color": "#aaa",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "font-size": "8px",
      color: "#666",
    },
  },
];

export default function GraphView() {
  const [elements, setElements] = useState<ElementDefinition[]>([]);
  const [entityId, setEntityId] = useState("");
  const [depth, setDepth] = useState(2);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const fetchGraph = useCallback(async () => {
    if (!entityId.trim()) return;
    setLoading(true);
    setError("");

    try {
      const { data } = await client.post("/query/traverse", {
        entity_id: entityId.trim(),
        depth,
      });

      // API already returns Cytoscape.js-ready {data: {...}} objects
      const cyElements: ElementDefinition[] = [
        ...data.nodes.map((n: { data: Record<string, unknown> }) => ({ data: n.data })),
        ...data.edges.map((e: { data: Record<string, unknown> }) => ({ data: e.data })),
      ];
      setElements(cyElements);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Query failed");
      } else {
        setError("Query failed");
      }
    } finally {
      setLoading(false);
    }
  }, [entityId, depth]);

  useEffect(() => {
    // Auto-fetch if entityId was provided via URL params, etc.
  }, []);

  return (
    <div style={{ fontFamily: "system-ui", padding: 20 }}>
      <h1>Graph Explorer</h1>

      <div style={{ display: "flex", gap: 12, alignItems: "end", marginBottom: 16 }}>
        <div>
          <label htmlFor="entityId">Entity ID</label>
          <input
            id="entityId"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            placeholder="paste an entity UUID"
            style={{ display: "block", padding: 8, width: 320, marginTop: 4 }}
          />
        </div>
        <div>
          <label htmlFor="depth">Depth</label>
          <input
            id="depth"
            type="number"
            min={1}
            max={6}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            style={{ display: "block", padding: 8, width: 60, marginTop: 4 }}
          />
        </div>
        <button onClick={fetchGraph} disabled={loading} style={{ padding: "8px 24px" }}>
          {loading ? "Loading…" : "Traverse"}
        </button>
      </div>

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <div style={{ width: "100%", height: "70vh", border: "1px solid #ddd", borderRadius: 4 }}>
        <CytoscapeComponent
          elements={elements}
          stylesheet={CYTO_STYLE}
          layout={{ name: "cose", animate: true }}
          style={{ width: "100%", height: "100%" }}
        />
      </div>
    </div>
  );
}
