/**
 * codevis/api.js
 * --------------
 * Thin fetch wrapper around the backend API. The base URL is resolved at
 * runtime from window.CODEVIS_API_BASE (injected by index.html) so the same
 * static build works against `http://localhost:5001` in development and
 * whatever origin the backend is deployed to in production, without a
 * build step.
 */

const BASE = window.CODEVIS_API_BASE || "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body;
  try {
    body = await res.json();
  } catch {
    throw new ApiError(`Server returned a non-JSON response (HTTP ${res.status}).`, res.status);
  }
  if (!res.ok) {
    throw new ApiError(body.error || `Request failed (HTTP ${res.status}).`, res.status, body);
  }
  return body;
}

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export const api = {
  health: () => request("/api/health"),
  languages: () => request("/api/languages"),
  samples: (language) => request(`/api/samples${language ? `?language=${language}` : ""}`),
  analyze: (language, code, stdin = "") =>
    request("/api/analyze", { method: "POST", body: JSON.stringify({ language, code, stdin }) }),
  execute: (language, code, stdin = "") =>
    request("/api/execute", { method: "POST", body: JSON.stringify({ language, code, stdin }) }),
  flowchart: (language, code) =>
    request("/api/flowchart", { method: "POST", body: JSON.stringify({ language, code }) }),
};
