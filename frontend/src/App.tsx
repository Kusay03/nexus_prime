import { Suspense, lazy, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

const Login = lazy(() => import("./components/Login"));
const AppShell = lazy(() => import("./components/AppShell"));
const DashboardPage = lazy(() => import("./components/DashboardPage"));
const InvestigationsPage = lazy(() => import("./components/InvestigationsPage"));
const CasesPage = lazy(() => import("./components/CasesPage"));
const AlertsPage = lazy(() => import("./components/AlertsPage"));
const AdminStudioPage = lazy(() => import("./components/AdminStudioPage"));

function ProtectedRoute({ children }: { children: ReactNode }) {
  const token = localStorage.getItem("access_token");
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminRoute({ children }: { children: ReactNode }) {
  const token = localStorage.getItem("access_token");
  const role = localStorage.getItem("role");
  if (!token) return <Navigate to="/login" replace />;
  if (role !== "admin") return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

function FallbackRoute() {
  const token = localStorage.getItem("access_token");
  return <Navigate to={token ? "/dashboard" : "/login"} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="route-loading"><div className="panel">Loading workspace…</div></div>}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="investigate" element={<InvestigationsPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="cases" element={<CasesPage />} />
            <Route
              path="admin"
              element={
                <AdminRoute>
                  <AdminStudioPage />
                </AdminRoute>
              }
            />
          </Route>
          <Route path="*" element={<FallbackRoute />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
