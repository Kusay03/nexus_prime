import { FormEvent, useState } from "react";
import client from "../api/client";
import { useNavigate } from "react-router-dom";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");

    try {
      // FastAPI OAuth2PasswordRequestForm expects form-encoded data
      const form = new URLSearchParams();
      form.append("username", username);
      form.append("password", password);

      const { data } = await client.post("/auth/token", form, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });

      localStorage.setItem("access_token", data.access_token);
      localStorage.setItem("tenant_id", data.tenant_id);
      localStorage.setItem("role", data.role);
      navigate("/");
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const resp = err as { response?: { data?: { detail?: string } } };
        setError(resp.response?.data?.detail ?? "Login failed");
      } else {
        setError("Login failed");
      }
    }
  }

  return (
    <div style={{ maxWidth: 380, margin: "120px auto", fontFamily: "system-ui" }}>
      <h1>Project Nexus</h1>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </div>
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" style={{ padding: "8px 24px" }}>
          Log in
        </button>
      </form>
    </div>
  );
}
