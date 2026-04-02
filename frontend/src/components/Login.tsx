import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import client from "../api/client";

type BootstrapStatusResponse = {
  needs_bootstrap: boolean;
};

type TokenResponse = {
  access_token: string;
  tenant_id: string;
  role: string;
};

function errorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = err as { response?: { data?: { detail?: string } } };
    return response.response?.data?.detail ?? fallback;
  }
  return fallback;
}

function persistSession(data: TokenResponse) {
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("tenant_id", data.tenant_id);
  localStorage.setItem("role", data.role);
}

export default function Login() {
  const [needsBootstrap, setNeedsBootstrap] = useState<boolean | null>(null);
  const [statusError, setStatusError] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  const [tenantId, setTenantId] = useState("");
  const [bootstrapUsername, setBootstrapUsername] = useState("");
  const [bootstrapEmail, setBootstrapEmail] = useState("");
  const [bootstrapPassword, setBootstrapPassword] = useState("");

  const navigate = useNavigate();

  useEffect(() => {
    let active = true;

    async function loadBootstrapStatus() {
      setStatusError("");

      try {
        const { data } = await client.get<BootstrapStatusResponse>("/auth/bootstrap/status");
        if (active) {
          setNeedsBootstrap(data.needs_bootstrap);
        }
      } catch (err: unknown) {
        if (active) {
          setNeedsBootstrap(false);
          setStatusError(errorMessage(err, "Failed to check authentication status"));
        }
      }
    }

    void loadBootstrapStatus();

    return () => {
      active = false;
    };
  }, []);

  async function loginWithCredentials(username: string, password: string) {
    const form = new URLSearchParams();
    form.append("username", username);
    form.append("password", password);

    const { data } = await client.post<TokenResponse>("/auth/token", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });

    persistSession(data);
  }

  async function handleLoginSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await loginWithCredentials(loginUsername, loginPassword);
      navigate("/dashboard");
    } catch (err: unknown) {
      setError(errorMessage(err, "Login failed"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleBootstrapSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await client.post("/auth/bootstrap", {
        username: bootstrapUsername,
        email: bootstrapEmail,
        password: bootstrapPassword,
        tenant_id: tenantId,
      });

      await loginWithCredentials(bootstrapUsername, bootstrapPassword);
      navigate("/dashboard");
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to create the first admin account"));
      if (errorMessage(err, "").includes("Bootstrap is no longer available")) {
        setNeedsBootstrap(false);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const checkingStatus = needsBootstrap === null;

  return (
    <div className="login-page">
      <div className="login-panel">
        <div>
          <p className="eyebrow">{needsBootstrap ? "Bootstrap Access" : "Operational Intelligence"}</p>
          <h1>{needsBootstrap ? "Create the first admin account" : "Project Nexus"}</h1>
          <p className="login-copy">
            {needsBootstrap
              ? "Initialize the workspace tenant and primary administrator. After this step, additional users must be created by an authenticated admin."
              : "Model customers, contracts, invoices, and support pressure in one shared revenue workspace."}
          </p>
        </div>

        {statusError && <p className="form-error">{statusError}</p>}

        {checkingStatus ? (
          <div className="auth-note">Checking authentication status…</div>
        ) : needsBootstrap ? (
          <form onSubmit={handleBootstrapSubmit} className="login-form auth-form-grid">
            <div>
              <label htmlFor="tenant_id">Tenant ID</label>
              <input
                id="tenant_id"
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value)}
                required
                placeholder="acme-prod"
              />
            </div>
            <div>
              <label htmlFor="bootstrap_email">Email</label>
              <input
                id="bootstrap_email"
                type="email"
                value={bootstrapEmail}
                onChange={(event) => setBootstrapEmail(event.target.value)}
                required
                placeholder="admin@acme.com"
              />
            </div>
            <div>
              <label htmlFor="bootstrap_username">Username</label>
              <input
                id="bootstrap_username"
                value={bootstrapUsername}
                onChange={(event) => setBootstrapUsername(event.target.value)}
                required
                placeholder="admin"
              />
            </div>
            <div>
              <label htmlFor="bootstrap_password">Password</label>
              <input
                id="bootstrap_password"
                type="password"
                value={bootstrapPassword}
                onChange={(event) => setBootstrapPassword(event.target.value)}
                required
                minLength={8}
                placeholder="At least 8 characters"
              />
            </div>
            {error && <p className="form-error">{error}</p>}
            <button type="submit" disabled={submitting}>
              {submitting ? "Creating account…" : "Create Admin Account"}
            </button>
          </form>
        ) : (
          <>
            <form onSubmit={handleLoginSubmit} className="login-form">
              <div>
                <label htmlFor="username">Username</label>
                <input
                  id="username"
                  value={loginUsername}
                  onChange={(event) => setLoginUsername(event.target.value)}
                  required
                  placeholder="analyst"
                />
              </div>
              <div>
                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  value={loginPassword}
                  onChange={(event) => setLoginPassword(event.target.value)}
                  required
                  placeholder="password"
                />
              </div>
              {error && <p className="form-error">{error}</p>}
              <button type="submit" disabled={submitting}>
                {submitting ? "Signing in…" : "Log in"}
              </button>
            </form>
            <p className="auth-note">Need access? Ask a tenant admin to create your account.</p>
          </>
        )}
      </div>
    </div>
  );
}
