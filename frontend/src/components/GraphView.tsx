import { useCallback, useEffect, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core, ElementDefinition, SingularElementReturnValue, StylesheetJson } from "cytoscape";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import client from "../api/client";

cytoscape.use(dagre);

const AI_TYPES = new Set([
  "Document",
  "Observation",
  "Hypothesis",
  "Alert",
  "Recommendation",
  "ModelRun",
  "PromptTemplate",
]);

const INFERENCE_TYPES = new Set(["Observation", "Hypothesis", "Alert", "Recommendation"]);
const PROVENANCE_TYPES = new Set(["Document", "PromptTemplate", "ModelRun"]);

const SIGNAL_STYLES: Record<SignalKind, { bg: string; border: string; shape: string; labelBg: string; labelColor: string }> = {
  fact: {
    bg: "#d8e3fb",
    border: "#ffffff",
    shape: "ellipse",
    labelBg: "rgba(250,252,255,0.98)",
    labelColor: "#18202e",
  },
  inference: {
    bg: "#6063ee",
    border: "#ffffff",
    shape: "diamond",
    labelBg: "rgba(245,245,255,0.98)",
    labelColor: "#2b2daa",
  },
  provenance: {
    bg: "#89f5e7",
    border: "#ffffff",
    shape: "round-rectangle",
    labelBg: "rgba(243,255,252,0.98)",
    labelColor: "#005049",
  },
};

type SelectedProps = Record<string, unknown> | null;
type ViewMode = "all" | "business" | "ai";
type SignalKind = "fact" | "inference" | "provenance";
type ContextMenuState = {
  visible: boolean;
  x: number;
  y: number;
  target: SelectedProps | null;
};
type ActionTarget = {
  nodeElement: SingularElementReturnValue;
  payload: SelectedProps;
};

const ACTIONS_BY_TYPE: Record<string, { label: string; action_type: string }[]> = {
  Customer: [{ label: "Open Renewal Review", action_type: "OPEN_RENEWAL_REVIEW" }],
  Contract: [{ label: "Prepare Renewal Plan", action_type: "PREPARE_RENEWAL_PLAN" }],
  Invoice: [{ label: "Escalate Collection", action_type: "ESCALATE_COLLECTION" }],
  SupportTicket: [{ label: "Coordinate Recovery", action_type: "COORDINATE_RECOVERY" }],
  AccountManager: [{ label: "Notify Owner", action_type: "NOTIFY_OWNER" }],
};
const DEFAULT_ACTIONS = [{ label: "Flag for Review", action_type: "FLAG_REVIEW" }];
const COURSE_OF_ACTION = "COURSE_OF_ACTION";

function isEdgeData(data: Record<string, unknown>): boolean {
  return "source" in data && "target" in data;
}

function buildActionTarget(element: SingularElementReturnValue, cy: Core): ActionTarget | null {
  const data = element.data() as Record<string, unknown>;
  if (!isEdgeData(data)) {
    return {
      nodeElement: element,
      payload: {
        ...data,
        id: data.id ?? element.id(),
        label: data.label ?? data.graphLabel ?? "Untitled",
        type: data.type ?? "Unknown",
      },
    };
  }

  const targetId = String(data.target ?? "");
  if (!targetId) {
    return null;
  }

  const node = cy.getElementById(targetId);
  if (node.empty()) {
    return null;
  }

  const nodeData = node.data() as Record<string, unknown>;
  return {
    nodeElement: node,
    payload: {
      ...nodeData,
      id: nodeData.id ?? targetId,
      label: nodeData.label ?? nodeData.graphLabel ?? "Untitled",
      type: nodeData.type ?? "Unknown",
    },
  };
}

function prettifyToken(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function prettifyKey(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function humanizeType(value: string): string {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2");
}

function shortenLabel(value: string, maxLength: number): string {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
}

function signalKindForType(type: string): SignalKind {
  if (PROVENANCE_TYPES.has(type)) {
    return "provenance";
  }
  if (INFERENCE_TYPES.has(type)) {
    return "inference";
  }
  return "fact";
}

function buildGraphLabel(label: string, type: string): string {
  const typeLine = shortenLabel(humanizeType(type).toUpperCase(), 18);
  const nameLine = shortenLabel(label, 24);
  return `${typeLine}\n${nameLine}`;
}

function buildStylesheet(showEdgeLabels: boolean): StylesheetJson {
  return [
    {
      selector: "node",
      style: {
        label: "data(graphLabel)",
        "background-color": "#d8e3fb",
        color: "#18202e",
        "text-valign": "bottom",
        "text-halign": "center",
        "font-size": "10px",
        "font-weight": 800,
        "text-wrap": "wrap",
        "text-max-width": "132px",
        "line-height": 1.2,
        "text-margin-y": 18,
        "text-background-opacity": 1,
        "text-background-color": "data(labelBg)",
        "text-background-shape": "round-rectangle",
        "text-background-padding": "10px",
        "text-border-opacity": 0,
        width: "mapData(weight, 1, 8, 46, 68)",
        height: "mapData(weight, 1, 8, 46, 68)",
        "border-width": 4,
        "border-color": "#ffffff",
        "overlay-opacity": 0,
      },
    },
    ...Object.entries(SIGNAL_STYLES).map(([signal, { bg, border, shape, labelColor }]) => ({
      selector: `node[signal = "${signal}"]`,
      style: {
        "background-color": bg,
        "border-color": border,
        shape,
        color: labelColor,
      } as Record<string, unknown>,
    })),
    {
      selector: "node[kind = 'ai']",
      style: {
        "background-opacity": 1,
      },
    },
    {
      selector: "node[kind = 'business']",
      style: {
        "background-opacity": 1,
      },
    },
    {
      selector: "node[root = 1]",
      style: {
        width: 78,
        height: 78,
        "border-width": 4,
        "border-color": "#111c2d",
        "shadow-blur": 24,
        "shadow-color": "rgba(17, 28, 45, 0.18)",
        "shadow-opacity": 1,
      },
    },
    {
      selector: "node:selected, node.highlighted",
      style: {
        "border-width": 4,
        "border-color": "#111c2d",
        "shadow-blur": 28,
        "shadow-color": "rgba(17, 28, 45, 0.18)",
        "shadow-opacity": 1,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
      },
    },
    {
      selector: "node.muted",
      style: {
        opacity: 0.2,
        "text-opacity": 0.18,
      },
    },
    {
      selector: "edge",
      style: {
        label: "data(label)",
        width: 1.6,
        opacity: 0.82,
        "line-color": "rgba(118,119,125,0.48)",
        "target-arrow-color": "rgba(118,119,125,0.48)",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "font-size": "9px",
        color: "#5b6474",
        "text-opacity": showEdgeLabels ? 0.92 : 0,
        "text-background-color": "rgba(255,255,255,0.92)",
        "text-background-opacity": 1,
        "text-background-padding": "3px",
      },
    },
    {
      selector: "edge[domain = 'ai']",
      style: {
        "line-style": "dashed",
        "line-color": "rgba(96,99,238,0.42)",
        "target-arrow-color": "rgba(96,99,238,0.42)",
      },
    },
    {
      selector: "edge.highlighted",
      style: {
        width: 2.6,
        opacity: 1,
        "line-color": "#46536b",
        "target-arrow-color": "#46536b",
        "text-opacity": 1,
      },
    },
    {
      selector: "edge:selected",
      style: {
        width: 2.6,
        "line-color": "#111c2d",
        "target-arrow-color": "#111c2d",
        "text-opacity": 1,
      },
    },
    {
      selector: "edge.muted",
      style: {
        opacity: 0.12,
        "text-opacity": 0,
      },
    },
  ];
}

type GraphViewProps = {
  entityId: string;
  depth: number;
  onOpenEntity?: (entityId: string) => void;
  onSelectEntity?: (entityId: string) => void;
  showSidebar?: boolean;
  showToolbar?: boolean;
};

export default function GraphView({
  entityId,
  depth,
  onOpenEntity,
  onSelectEntity,
  showSidebar = true,
  showToolbar = true,
}: GraphViewProps) {
  const [elements, setElements] = useState<ElementDefinition[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<SelectedProps>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("all");
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [toast, setToast] = useState<string>("");
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    target: null,
  });
  const cyRef = useRef<Core | null>(null);
  const graphSurfaceRef = useRef<HTMLDivElement | null>(null);
  const stylesheet = buildStylesheet(showEdgeLabels);

  useEffect(() => {
    if (!entityId.trim()) return;
    let active = true;
    async function fetchGraph() {
      setLoading(true);
      setError("");
      setSelected(null);

      try {
        const { data } = await client.post("/query/traverse", {
          entity_id: entityId.trim(),
          depth,
        });

        const rawEdges = data.edges.map((edge: { data: Record<string, unknown> }) => edge.data);
        const degreeByNode = new Map<string, number>();
        for (const edge of rawEdges) {
          const source = String(edge.source);
          const target = String(edge.target);
          degreeByNode.set(source, (degreeByNode.get(source) ?? 0) + 1);
          degreeByNode.set(target, (degreeByNode.get(target) ?? 0) + 1);
        }

        const nodeKindById = new Map<string, "ai" | "business">();
        const cyNodes = data.nodes.map((node: { data: Record<string, unknown> }) => {
          const props = (node.data.properties ?? {}) as Record<string, unknown>;
          const flat = { ...node.data, ...props };
          const type = String(node.data.type ?? "");
          const displayLabel =
            (props["Display Name"] as string) ??
            (props["name"] as string) ??
            (props["Name"] as string) ??
            (props["Username"] as string) ??
            (props["Hostname"] as string) ??
            (props["hostname"] as string) ??
            (props["CVE ID"] as string) ??
            (props["IP Address"] as string) ??
            (props["ip"] as string) ??
            (node.data.label as string);
          const kind = AI_TYPES.has(type) ? "ai" : "business";
          const signal = signalKindForType(type);
          const signalStyle = SIGNAL_STYLES[signal];
          nodeKindById.set(String(node.data.id), kind);
          return {
            data: {
              ...flat,
              label: displayLabel,
              graphLabel: buildGraphLabel(displayLabel, type),
              kind,
              signal,
              labelBg: signalStyle.labelBg,
              root: node.data.id === entityId ? 1 : 0,
              weight: Math.max(degreeByNode.get(String(node.data.id)) ?? 1, 1),
            },
          };
        });

        const cyElements: ElementDefinition[] = [
          ...cyNodes,
          ...rawEdges.map((edge: Record<string, unknown>) => ({
            data: {
              ...edge,
              rawLabel: edge.label,
              label: prettifyToken(String(edge.label)),
              domain:
                nodeKindById.get(String(edge.source)) === "ai" ||
                nodeKindById.get(String(edge.target)) === "ai"
                  ? "ai"
                  : "business",
            },
          })),
        ];
        if (active) setElements(cyElements);
      } catch (err: unknown) {
        if (active) {
          if (err && typeof err === "object" && "response" in err) {
            const resp = err as { response?: { data?: { detail?: string } } };
            setError(resp.response?.data?.detail ?? "Query failed");
          } else {
            setError("Query failed");
          }
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void fetchGraph();
    return () => {
      active = false;
    };
  }, [entityId, depth]);

  const closeContextMenu = useCallback(() => {
    setContextMenu((current) =>
      current.visible ? { visible: false, x: 0, y: 0, target: null } : current,
    );
  }, []);

  const applyFocus = useCallback((cy: Core, target?: SingularElementReturnValue) => {
    cy.elements().removeClass("muted highlighted");
    if (!target) {
      return;
    }

    const focus = target.closedNeighborhood();
    cy.elements().difference(focus).addClass("muted");
    focus.addClass("highlighted");
  }, []);

  const bindCyEvents = useCallback(
    (cy: Core) => {
      cyRef.current = cy;
      cy.off("tap", "node, edge");
      cy.off("tap");
      cy.off("cxttap");
      cy.on("tap", "node, edge", (evt) => {
        const data = evt.target.data() as Record<string, unknown>;
        setSelected(data);
        if (!isEdgeData(data) && typeof data.id === "string") {
          onSelectEntity?.(data.id);
        }
        applyFocus(cy, evt.target);
      });
      cy.on("tap", (evt) => {
        if (evt.target === cy) {
          setSelected(null);
          applyFocus(cy);
        }
      });
      cy.on("cxttap", "node, edge", (evt) => {
        evt.originalEvent?.preventDefault();
        const actionTarget = buildActionTarget(evt.target, cy);
        if (!actionTarget) {
          closeContextMenu();
          return;
        }

        setSelected(actionTarget.payload);
        applyFocus(cy, actionTarget.nodeElement);

        const rect = graphSurfaceRef.current?.getBoundingClientRect();
        const clientX = evt.originalEvent?.clientX ?? 0;
        const clientY = evt.originalEvent?.clientY ?? 0;
        const maxX = rect ? rect.width - 192 : clientX;
        const maxY = rect ? rect.height - 120 : clientY;
        const x = rect ? Math.max(8, Math.min(maxX, clientX - rect.left)) : clientX;
        const y = rect ? Math.max(8, Math.min(maxY, clientY - rect.top)) : clientY;

        setContextMenu({
          visible: true,
          x,
          y,
          target: actionTarget.payload,
        });
      });
    },
    [applyFocus, closeContextMenu, onSelectEntity],
  );

  useEffect(() => {
    const handler = () => closeContextMenu();
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [closeContextMenu]);

  useEffect(() => {
    if (cyRef.current && elements.length > 0) {
      cyRef.current
        .layout({
          name: "dagre",
          rankDir: "LR",
          nodeSep: 128,
          rankSep: 190,
          edgeSep: 40,
          padding: 84,
          fit: true,
          animate: true,
          animationDuration: 260,
        } as never)
        .run();
    }
  }, [elements]);

  useEffect(() => {
    setSelected(null);
    if (cyRef.current) {
      applyFocus(cyRef.current);
    }
  }, [viewMode, entityId, applyFocus]);

  const executeAction = async (action_type: string, override?: SelectedProps) => {
    const target = (override ?? selected) as (Record<string, unknown> & { id?: string }) | null;
    if (!target || isEdgeData(target)) {
      setToast("Select a node to execute the action");
      return;
    }

    const nodeId = String(target.id ?? target.node_id ?? "");
    if (!nodeId) {
      setToast("Action target missing");
      return;
    }

    setActionLoading(action_type);
    try {
      await client.post("/action/execute", {
        target_node_id: nodeId,
        node_label: String(target.type ?? target.label ?? "Unknown"),
        action_type,
      });
      setToast(`${action_type.replace(/_/g, " ")} executed successfully`);
    } catch {
      setToast("Action failed; check API logs");
    } finally {
      setActionLoading(null);
      setTimeout(() => setToast(""), 3500);
    }
  };

  const runCourseOfAction = async () => {
    if (!contextMenu.target) {
      return;
    }
    await executeAction(COURSE_OF_ACTION, contextMenu.target);
    closeContextMenu();
  };

  const isEdge = selected && ("source" in selected || "target" in selected);
  const HIDDEN = new Set([
    "domain",
    "graphLabel",
    "id",
    "kind",
    "label",
    "properties",
    "root",
    "source",
    "target",
    "tenant_id",
    "type",
    "weight",
  ]);
  const sidebarRows = selected
    ? Object.entries(selected).filter(([key, value]) => !HIDDEN.has(key) && typeof value !== "object")
    : [];

  const visibleNodes: ElementDefinition[] = [];
  const visibleNodeIds = new Set<string>();
  for (const element of elements) {
    const data = (element.data ?? {}) as Record<string, unknown>;
    if (isEdgeData(data)) {
      continue;
    }
    const shouldInclude =
      viewMode === "all" ||
      data.root === 1 ||
      data.kind === viewMode;
    if (shouldInclude) {
      visibleNodes.push(element);
      visibleNodeIds.add(String(data.id));
    }
  }

  const visibleEdges = elements.filter((element) => {
    const data = (element.data ?? {}) as Record<string, unknown>;
    if (!isEdgeData(data)) {
      return false;
    }
    return visibleNodeIds.has(String(data.source)) && visibleNodeIds.has(String(data.target));
  });

  const renderedElements = [...visibleNodes, ...visibleEdges];
  const rootNode = visibleNodes.find((element) => (element.data as Record<string, unknown>).root === 1);
  const aiNodeCount = visibleNodes.filter((element) => (element.data as Record<string, unknown>).kind === "ai").length;
  const businessNodeCount = visibleNodes.length - aiNodeCount;

  function fitGraph() {
    if (!cyRef.current) {
      return;
    }
    cyRef.current.fit(undefined, 56);
  }

  function focusRoot() {
    if (!cyRef.current) {
      return;
    }
    const rootId = String((rootNode?.data as Record<string, unknown> | undefined)?.id ?? "");
    if (!rootId) {
      return;
    }
    const rootElement = cyRef.current.getElementById(rootId);
    cyRef.current.animate({
      fit: {
        eles: rootElement.closedNeighborhood(),
        padding: 72,
      },
      duration: 260,
    });
  }

  return (
    <div className="graph-workspace">
      {error && <div className="banner error">{error}</div>}

      <div className="graph-surface" ref={graphSurfaceRef}>
        {showToolbar && (
          <div className="graph-toolbar">
            <div className="graph-toolbar-left">
              <div className="graph-stat">
                <span>Root</span>
                <strong>{String((rootNode?.data as Record<string, unknown> | undefined)?.label ?? "Not selected")}</strong>
              </div>
              <div className="graph-stat">
                <span>Visible</span>
                <strong>{visibleNodes.length} nodes</strong>
              </div>
              <div className="graph-stat">
                <span>Links</span>
                <strong>{visibleEdges.length} edges</strong>
              </div>
            </div>
            <div className="graph-toolbar-right">
              <div className="graph-filter-group">
                <button
                  type="button"
                  className={`graph-filter${viewMode === "all" ? " active" : ""}`}
                  onClick={() => setViewMode("all")}
                >
                  All
                </button>
                <button
                  type="button"
                  className={`graph-filter${viewMode === "business" ? " active" : ""}`}
                  onClick={() => setViewMode("business")}
                >
                  Business
                </button>
                <button
                  type="button"
                  className={`graph-filter${viewMode === "ai" ? " active" : ""}`}
                  onClick={() => setViewMode("ai")}
                >
                  AI
                </button>
              </div>
              <button
                type="button"
                className={`graph-control${showEdgeLabels ? " active" : ""}`}
                onClick={() => setShowEdgeLabels((current) => !current)}
              >
                {showEdgeLabels ? "Hide labels" : "Show labels"}
              </button>
              <button type="button" className="graph-control" onClick={fitGraph}>
                Fit graph
              </button>
              <button type="button" className="graph-control" onClick={focusRoot}>
                Center root
              </button>
            </div>
          </div>
        )}

        {entityId ? (
          <CytoscapeComponent
            elements={renderedElements}
            stylesheet={stylesheet}
            layout={{ name: "dagre", rankDir: "LR", animate: true, fit: true, padding: 84 } as never}
            style={{ width: "100%", height: "100%", minHeight: "640px" }}
            cy={bindCyEvents}
          />
        ) : (
          <div className="empty-state">Choose an entity from search results or a saved view.</div>
        )}
        {loading && <div className="graph-loading">Refreshing graph…</div>}

        {contextMenu.visible && (
          <div
            className="graph-context-menu"
            style={{ top: contextMenu.y, left: contextMenu.x }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button type="button" onClick={runCourseOfAction}>
              Create action plan automation
            </button>
          </div>
        )}
      </div>

      {showSidebar && (
        <div className="graph-sidebar">
          <div className="selected-card graph-scene-card">
            <span className="pill neutral">Scene</span>
            <strong>{viewMode === "all" ? "Full investigation map" : `${prettifyToken(viewMode)} focus map`}</strong>
            <p>
              {businessNodeCount} business nodes, {aiNodeCount} AI nodes, {visibleEdges.length} visible relationships.
            </p>
          </div>

          {selected ? (
            <>
              <div className="selected-card">
                <span className={`pill ${isEdge ? "neutral" : "accent"}`}>
                  {isEdge ? "Relationship" : (selected.type as string ?? "Node")}
                </span>
                <strong>{String(selected.label ?? "Untitled")}</strong>
                <p>{selected.id as string}</p>
              </div>

              <div className="kv-grid">
                {sidebarRows.map(([key, value]) => (
                  <div key={key} className="kv-row">
                    <span>{prettifyKey(key)}</span>
                    <strong>{String(value)}</strong>
                  </div>
                ))}
              </div>

              {!isEdge && (
                <div className="detail-section graph-action-list">
                  <button onClick={() => onOpenEntity?.(String(selected.id))}>Open in detail panel</button>
                  {(ACTIONS_BY_TYPE[selected.type as string] ?? DEFAULT_ACTIONS).map(({ label, action_type }) => (
                    <button
                      key={action_type}
                      className="ghost-button"
                      onClick={() => executeAction(action_type)}
                      disabled={actionLoading !== null}
                    >
                      {actionLoading === action_type ? "Executing…" : label}
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state compact">
              Click a node to isolate its neighborhood. Edge labels stay quiet until you focus the graph.
            </div>
          )}

          <div className="legend">
            {Object.entries(SIGNAL_STYLES).map(([signal, { bg }]) => (
              <span key={signal}>
                <i style={{ background: bg }} />
                {prettifyKey(signal)}
              </span>
            ))}
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
