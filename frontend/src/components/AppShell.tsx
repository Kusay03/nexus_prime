import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import client from "../api/client";

type MeResponse = {
  username: string;
  role: string;
  tenant_id: string;
};

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", eyebrow: "Overview" },
  { to: "/investigate", label: "Graph View", eyebrow: "Explore" },
  { to: "/alerts", label: "Alerts", eyebrow: "Review" },
  { to: "/cases", label: "Cases", eyebrow: "Track" },
];

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/dashboard"))  return "Dashboard";
  if (pathname.startsWith("/investigate")) return "Graph View";
  if (pathname.startsWith("/alerts"))      return "Alerts";
  if (pathname.startsWith("/cases"))       return "Cases";
  if (pathname.startsWith("/admin"))       return "Admin Studio";
  return "Project Nexus";
}

function initialsFor(username: string | undefined): string {
  if (!username) {
    return "NX";
  }
  return username
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export default function AppShell() {
  const [user, setUser] = useState<MeResponse | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const currentRole = user?.role ?? localStorage.getItem("role") ?? "";
  const navItems = currentRole === "admin"
    ? [...NAV_ITEMS, { to: "/admin", label: "Admin Studio", eyebrow: "Setup" }]
    : NAV_ITEMS;

  useEffect(() => {
    let active = true;
    async function loadMe() {
      try {
        const { data } = await client.get("/auth/me");
        if (active) setUser(data);
      } catch {
        if (active) setUser(null);
      }
    }
    void loadMe();
    return () => {
      active = false;
    };
  }, []);

  async function logout() {
    try {
      await client.post("/auth/logout");
    } catch {
      // Ignore logout network failures and clear client state.
    } finally {
      localStorage.removeItem("access_token");
      localStorage.removeItem("tenant_id");
      localStorage.removeItem("role");
      navigate("/login");
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-title">
          <div className="topbar-mark">NX</div>
          <div>
            <p className="eyebrow">Project Nexus</p>
            <h1>{pageTitle(location.pathname)}</h1>
          </div>
        </div>

        <div className="topbar-actions">
          <button type="button" className="icon-button" aria-label="Export workspace">
            Export
          </button>
          <div className="user-badge">
            <div className="user-avatar">{initialsFor(user?.username)}</div>
            <div>
              <strong>{user?.username ?? "Analyst"}</strong>
              <p>{currentRole || "role"}</p>
            </div>
          </div>
        </div>
      </header>

      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="sidebar-kicker">Project Nexus</span>
          <p>Explore the graph, review alerts, and track investigation cases.</p>
        </div>

        <nav className="nav" aria-label="Primary">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <span>{item.eyebrow}</span>
              <strong>{item.label}</strong>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-card">
            <div className="user-name">{user?.tenant_id ?? localStorage.getItem("tenant_id") ?? "tenant"}</div>
            <div className="user-meta">
              <span>Workspace context</span>
              <span>{currentRole || "role"}</span>
            </div>
          </div>
          <button className="ghost-button" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>

      <main className="page-shell">
        <Outlet />
      </main>
    </div>
  );
}
