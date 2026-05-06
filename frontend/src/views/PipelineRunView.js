import React, { useEffect, useState } from "https://esm.sh/react@18.3.1";

import { API_BASE, deleteJson, getJson } from "../lib/api.js";
import { startSafePolling } from "../lib/polling.js";
import { LogPanel } from "../components/LogPanel.js";
import { ActionBar, Field, InlineHint, SectionCard } from "../components/UiPrimitives.js";

export function PipelineRunView({
  templates,
  setTemplates,
  templateId,
  setTemplateId,
  models,
  setModels,
}) {
  const [file, setFile] = useState(null);
  const [task, setTask] = useState(null);
  const [status, setStatus] = useState(null);
  const [taskLogs, setTaskLogs] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [forceRebuildImage, setForceRebuildImage] = useState(false);

  const userTemplates = templates.filter((item) => item.source === "user");
  const selectedTemplate = userTemplates.find((item) => item.id === templateId) || null;
  const resultLink = status?.status === "completed" && status?.result_bucket && status?.result_key
    ? `${API_BASE}/files/download?bucket=${encodeURIComponent(status.result_bucket)}&key=${encodeURIComponent(status.result_key)}&expires_seconds=900&redirect=true`
    : null;

  useEffect(() => {
    if (!task?.id) return undefined;
    return startSafePolling(async () => {
      const payload = await getJson(`/tasks/${task.id}`);
      setStatus(payload);
      const logsPayload = await getJson(`/tasks/${task.id}/logs`);
      setTaskLogs(logsPayload.logs || "");
      return payload.status === "completed" || payload.status === "failed" || payload.status === "cancelled";
    }, 3000, (e) => setError(`Status polling failed: ${e.message}`));
  }, [task?.id]);

  async function reloadTemplates() {
    const safe = await getJson("/pipelines/templates");
    setTemplates(Array.isArray(safe) ? safe : []);
  }

  async function reloadModels() {
    const payload = await getJson("/registry/models");
    setModels(Array.isArray(payload) ? payload : []);
  }

  async function handleRun() {
    if (!file || !selectedTemplate) return;
    setError("");
    setIsSubmitting(true);
    setTask(null);
    setStatus(null);
    setTaskLogs("");
    try {
      const form = new FormData();
      form.append("file", file);
      const uploadResp = await fetch(`${API_BASE}/files/upload`, {
        method: "POST",
        body: form,
      });
      if (!uploadResp.ok) throw new Error(await uploadResp.text());
      const upload = await uploadResp.json();

      const flowParams = { ...(selectedTemplate.flow_params || {}) };
      if (forceRebuildImage && Array.isArray(flowParams.pipeline_steps)) {
        flowParams.pipeline_steps = flowParams.pipeline_steps.map((step) => ({
          ...step,
          docker_force_rebuild: true,
        }));
      }

      const createResp = await fetch(`${API_BASE}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_bucket: upload.bucket,
          input_key: upload.key,
          flow_id: selectedTemplate.flow_id,
          flow_params: flowParams,
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

  async function handleDeleteModel(modelId) {
    if (!window.confirm(`Вы уверены, что хотите удалить модель '${modelId}'?`)) return;
    setError("");
    try {
      await deleteJson(`/registry/models/${encodeURIComponent(modelId)}`);
      await reloadModels();
      await reloadTemplates();
    } catch (e) {
      setError(`Delete model failed: ${e.message}`);
    }
  }

  async function handleDeleteTemplate(template) {
    if (!template?.pipeline_id) return;
    if (!window.confirm(`Вы уверены, что хотите удалить пайплайн '${template.name}'?`)) return;
    setError("");
    try {
      await deleteJson(`/pipelines/${encodeURIComponent(template.pipeline_id)}`);
      const safe = await getJson("/pipelines/templates");
      const nextTemplates = Array.isArray(safe) ? safe : [];
      setTemplates(nextTemplates);
      const safeUsers = nextTemplates.filter((item) => item.source === "user");
      if (!safeUsers.find((item) => item.id === templateId)) {
        setTemplateId(safeUsers[0]?.id || "");
      }
    } catch (e) {
      setError(`Delete pipeline failed: ${e.message}`);
    }
  }

  return React.createElement(
    React.Fragment,
    null,
    React.createElement("div", { className: "card" },
      React.createElement(SectionCard, {
        title: "Run Pipeline",
        subtitle: "Загрузите входной файл, выберите пользовательский шаблон и при необходимости форсируйте пересборку model image.",
      },
      React.createElement(Field, { label: "Input file" },
        React.createElement("input", {
          type: "file",
          onChange: (e) => setFile(e.target.files?.[0] ?? null),
        }),
      ),
      React.createElement(Field, { label: "Pipeline template" },
        React.createElement(
          "select",
          {
            value: templateId,
            onChange: (e) => setTemplateId(e.target.value),
          },
          userTemplates.map((t) => React.createElement("option", { key: t.id, value: t.id }, t.name)),
        ),
      ),
      userTemplates.length === 0 && React.createElement(InlineHint, { tone: "warning" }, "Нет пользовательских шаблонов. Создайте пайплайн во вкладке 'Добавить пайплайн'."),
      selectedTemplate?.description && React.createElement(InlineHint, null, selectedTemplate.description),
      React.createElement("div", { className: "toggle-card" },
        React.createElement("label", { className: "checkbox-line toggle-card__label" },
          React.createElement("input", {
            type: "checkbox",
            checked: forceRebuildImage,
            onChange: (e) => setForceRebuildImage(e.target.checked),
          }),
          React.createElement("span", { className: "toggle-card__copy" },
            React.createElement("span", { className: "toggle-card__title" }, "Force rebuild image"),
            React.createElement("span", { className: "toggle-card__hint" }, "Для диагностики и пересборки model image из текущего Dockerfile и runtime manifest."),
          ),
        ),
      ),
      React.createElement(ActionBar, null,
        React.createElement(
          "button",
          { disabled: !file || !selectedTemplate || isSubmitting || userTemplates.length === 0, onClick: handleRun },
          isSubmitting ? "Submitting..." : "Upload and Run",
        ),
        status && (status.status === "running" || status.status === "pending") && React.createElement(
          "button",
          { className: "button-secondary", onClick: handleCancel },
          "Cancel Task",
        ),
      ),
      status && React.createElement("p", { style: { marginTop: 12 } }, `Status: ${status.status}`),
      status && React.createElement(LogPanel, { text: taskLogs, emptyText: "Task logs will appear here" }),
      resultLink && React.createElement(
        "p",
        null,
        React.createElement("a", { href: resultLink, target: "_blank", rel: "noreferrer" }, "Download result"),
      ),
      error && React.createElement("p", { style: { color: "crimson" } }, error),
      ),
    ),
    React.createElement("div", { className: "card" },
      React.createElement("h2", null, "User Pipeline Templates"),
      userTemplates.length === 0 && React.createElement("p", { className: "muted" }, "Пользовательских пайплайнов пока нет."),
      userTemplates.map((tpl) =>
        React.createElement(
          "div",
          {
            key: `user-template-${tpl.id}`,
            style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
          },
          React.createElement("span", null, tpl.name),
          React.createElement("button", { type: "button", onClick: () => handleDeleteTemplate(tpl), title: "Удалить пайплайн" }, "×"),
        )),
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
            React.createElement(
              "div",
              { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } },
              React.createElement("strong", null, m.name),
              React.createElement("button", { type: "button", onClick: () => handleDeleteModel(m.id), title: "Удалить модель" }, "×"),
            ),
            React.createElement("p", { className: "muted" }, m.task_type),
          )),
      ),
    ),
  );
}
