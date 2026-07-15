import { API_BASE_URL } from "../config/runtime.js";

export async function getJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
  }
  return payload;
}

export async function postJson(path, body) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload));
  }
  return payload;
}
