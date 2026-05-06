export const API_BASE = "http://localhost:8000";

export async function getJson(path) {
  const resp = await fetch(`${API_BASE}${path}`);
  const payload = await resp.json();
  if (!resp.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
  }
  return payload;
}

export async function postJson(path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await resp.json();
  if (!resp.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
  }
  return payload;
}

export async function deleteJson(path) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
  });
  const payload = await resp.json();
  if (!resp.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
  }
  return payload;
}

