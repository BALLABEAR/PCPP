import React, { useEffect, useMemo, useState } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";

const API_BASE = window.location.hostname === "localhost" ? "http://localhost:8000" : `${window.location.origin}`;

function App() {
  const [file, setFile] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState("");
  const [task, setTask] = useState(null);
  const [status, setStatus] = useState(null);
  const [models, setModels] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/pipelines/templates`)
      .then((r) => r.json())
      .then((payload) => {
        setTemplates(payload);
        if (payload.length > 0) {
          setTemplateId(payload[0].id);
        }
      })
      .catch((e) => setError(`Failed to load templates: ${e.message}`));

    fetch(`${API_BASE}/registry/models`)
      .then((r) => r.json())
      .then(setModels)
      .catch((e) => setError(`Failed to load model catalog: ${e.message}`));
  }, []);

  useEffect(() => {
    if (!task?.id) return undefined;
    const timer = setInterval(async () => {
      const resp = await fetch(`${API_BASE}/tasks/${task.id}`);
      const payload = await resp.json();
      setStatus(payload);
      if (payload.status === "completed" || payload.status === "failed" || payload.status === "cancelled") {
        clearInterval(timer);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [task?.id]);

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === templateId) || null,
    [templates, templateId],
  );

  async function handleRun() {
    if (!file || !selectedTemplate) return;
    setError("");
    setIsSubmitting(true);
    setTask(null);
    setStatus(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const uploadResp = await fetch(`${API_BASE}/files/upload`, {
        method: "POST",
        body: form,
      });
      if (!uploadResp.ok) throw new Error(await uploadResp.text());
      const upload = await uploadResp.json();

      const createResp = await fetch(`${API_BASE}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_bucket: upload.bucket,
          input_key: upload.key,
          flow_id: selectedTemplate.flow_id,
          flow_params: selectedTemplate.flow_params || {},
        }),
      });
      if (!createResp.ok) throw new Error(await createResp.text());
      const created = await createResp.json();
      setTask(created);
      setStatus(created);
    } catch (e) {
      setError(`Run failed: ${e.message}`);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCancel() {
    if (!task?.id) return;
    setError("");
    try {
      const resp = await fetch(`${API_BASE}/tasks/${task.id}/cancel`, { method: "POST" });
      if (!resp.ok) throw new Error(await resp.text());
      const payload = await resp.json();
      setStatus(payload);
    } catch (e) {
      setError(`Cancel failed: ${e.message}`);
    }
  }

  const resultLink = status?.status === "completed" && status?.result_bucket && status?.result_key
    ? `${API_BASE}/files/download?bucket=${encodeURIComponent(status.result_bucket)}&key=${encodeURIComponent(status.result_key)}&expires_seconds=900&redirect=true`
    : null;

  return React.createElement(
    "div",
    { className: "container" },
    React.createElement("h1", null, "PCPP Minimal Frontend (Stage 6)"),
    React.createElement("div", { className: "card" },
      React.createElement("h2", null, "Run Pipeline"),
      React.createElement("label", null, "Input file"),
      React.createElement("input", {
        type: "file",
        onChange: (e) => setFile(e.target.files?.[0] ?? null),
      }),
      React.createElement("label", null, "Pipeline template"),
      React.createElement(
        "select",
        {
          value: templateId,
          onChange: (e) => setTemplateId(e.target.value),
        },
        templates.map((t) =>
          React.createElement("option", { key: t.id, value: t.id }, `${t.name} (${t.flow_id})`),
        ),
      ),
      React.createElement("p", { className: "muted" }, selectedTemplate?.description || ""),
      React.createElement(
        "button",
        { disabled: !file || !selectedTemplate || isSubmitting, onClick: handleRun },
        isSubmitting ? "Submitting..." : "Upload and Run",
      ),
      status && (status.status === "running" || status.status === "pending") && React.createElement(
        "button",
        { style: { marginLeft: 8 }, onClick: handleCancel },
        "Cancel Task",
      ),
      status && React.createElement("p", { style: { marginTop: 12 } }, `Status: ${status.status}`),
      resultLink && React.createElement(
        "p",
        null,
        React.createElement("a", { href: resultLink, target: "_blank", rel: "noreferrer" }, "Download result"),
      ),
      error && React.createElement("p", { style: { color: "crimson" } }, error),
    ),
    React.createElement("div", { className: "card" },
      React.createElement("h2", null, "Model Catalog"),
      React.createElement(
        "div",
        { className: "grid" },
        models.map((m) =>
          React.createElement(
            "div",
            { className: "card", key: m.id },
            React.createElement("strong", null, m.name),
            React.createElement("p", { className: "muted" }, `${m.task_type} / ${m.id}`),
            React.createElement("p", null, m.description || "No description"),
          ),
        ),
      ),
    ),
  );
}

createRoot(document.getElementById("root")).render(React.createElement(App));
