import axios from "axios";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const HEALTH_ENDPOINT = "/healthz";
const HEALTH_TIMEOUT_MS = 600;

function normalizeOrigin(value: string): string | null {
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function buildApiCandidates(): string[] {
  const candidates = [] as string[];
  if (configuredApiUrl) {
    candidates.push(configuredApiUrl);
  }
  if (typeof window !== "undefined") {
    candidates.push(window.location.origin);
  }
  candidates.push("http://localhost:8001");
  candidates.push("http://127.0.0.1:8001");
  candidates.push("http://localhost:8000");
  candidates.push("http://127.0.0.1:8000");

  return Array.from(
    new Set(
      candidates
        .map((candidate) => normalizeOrigin(candidate))
        .filter((candidate): candidate is string => Boolean(candidate)),
    ),
  );
}

async function isHostHealthy(base: string): Promise<boolean> {
  const url = new URL(HEALTH_ENDPOINT, base).toString();
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timeoutId = controller && setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: "GET",
      signal: controller?.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  }
}

let detectedBaseUrl: string | null = null;
let detectionPromise: Promise<void> | null = null;

async function detectApiBaseUrl(): Promise<void> {
  if (detectedBaseUrl) {
    return;
  }
  if (detectionPromise) {
    return detectionPromise;
  }

  detectionPromise = (async () => {
    const candidates = buildApiCandidates();
    for (const candidate of candidates) {
      if (await isHostHealthy(candidate)) {
        detectedBaseUrl = candidate;
        client.defaults.baseURL = candidate;
        return;
      }
    }
    throw new Error("Could not reach the Project Nexus API on any known host.");
  })();

  return detectionPromise;
}

const client = axios.create({
  baseURL: configuredApiUrl || window.location.origin,
});

client.interceptors.request.use(async (config) => {
  await detectApiBaseUrl();
  if (detectedBaseUrl) {
    config.baseURL = detectedBaseUrl;
  }
  return config;
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("tenant_id");
      localStorage.removeItem("role");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  },
);

export default client;
