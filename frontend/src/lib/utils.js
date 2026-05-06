export function parseListField(value) {
  return (value || "")
    .split("\n")
    .map((v) => v.trim())
    .filter((v) => v && v.toLowerCase() !== "<empty>");
}

export function parsePrimitive(value) {
  const text = String(value || "").trim();
  const low = text.toLowerCase();
  if (low === "true") return true;
  if (low === "false") return false;
  if (low === "null" || low === "none") return null;
  if (/^-?\d+$/.test(text)) return Number.parseInt(text, 10);
  if (/^-?\d+\.\d+$/.test(text)) return Number.parseFloat(text);
  if (text.startsWith("[") || text.startsWith("{")) {
    try {
      return JSON.parse(text);
    } catch (_) {
      return text;
    }
  }
  return text;
}

export function parseStepParams(text) {
  const params = {};
  (text || "").split("\n").forEach((line) => {
    const raw = line.trim();
    if (!raw || raw.toLowerCase() === "<empty>") return;
    const idx = raw.indexOf("=");
    if (idx <= 0) return;
    const key = raw.slice(0, idx).trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(key)) return;
    params[key] = parsePrimitive(raw.slice(idx + 1).trim());
  });
  return params;
}

export function redactSensitive(text) {
  if (!text) return "";
  return text
    .replace(/(token|password|secret|apikey|api_key)\s*[:=]\s*([^\s]+)/gi, "$1=<redacted>")
    .replace(/(AKIA[0-9A-Z]{16})/g, "<redacted-aws-key>");
}

export function lastLogLines(text, maxLines = 80) {
  const lines = (text || "").split("\n");
  return lines.slice(Math.max(0, lines.length - maxLines)).join("\n");
}

export function envOverridesTextToObject(value) {
  return String(value || "").split("\n").reduce((acc, item) => {
    const idx = item.indexOf("=");
    if (idx > 0) {
      acc[item.slice(0, idx).trim()] = item.slice(idx + 1).trim();
    }
    return acc;
  }, {});
}

