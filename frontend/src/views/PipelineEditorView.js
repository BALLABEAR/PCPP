import React, { useState } from "https://esm.sh/react@18.3.1";

import { API_BASE, getJson } from "../lib/api.js";
import { parseStepParams } from "../lib/utils.js";
import { LogPanel } from "../components/LogPanel.js";
import { ActionBar, Field, InlineHint, SectionCard, StatusBadge } from "../components/UiPrimitives.js";

function supportedParamsText(model) {
  const params = Object.keys(model?.params || {});
  return params.length ? params.join(", ") : "";
}

function stepHasOverrides(text) {
  return Boolean(String(text || "").trim());
}

export function PipelineEditorView({ models, setTemplates, setTemplateId }) {
  const [pipelineDraft, setPipelineDraft] = useState({
    name: "",
    steps: [{ model_id: "", paramsText: "" }],
  });
  const [pipelineValidation, setPipelineValidation] = useState(null);
  const [pipelineMessage, setPipelineMessage] = useState("");

  const modelOptions = models
    .filter((m) => m.ready !== false)
    .map((m) => ({ id: m.id, label: `${m.name} (${m.task_type})` }));
  const unavailableModels = models.filter((m) => m.ready === false);
  const modelById = models.reduce((acc, item) => {
    acc[item.id] = item;
    return acc;
  }, {});

  function updateDraftStep(index, patch) {
    setPipelineDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) => (i === index ? { ...step, ...patch } : step)),
    }));
  }

  function addDraftStep() {
    setPipelineDraft((prev) => ({ ...prev, steps: [...prev.steps, { model_id: "", paramsText: "" }] }));
  }

  function removeDraftStep(index) {
    setPipelineDraft((prev) => {
      const next = prev.steps.filter((_, i) => i !== index);
      return { ...prev, steps: next.length ? next : [{ model_id: "", paramsText: "" }] };
    });
  }

  function moveDraftStep(index, dir) {
    setPipelineDraft((prev) => {
      const target = index + dir;
      if (target < 0 || target >= prev.steps.length) return prev;
      const next = [...prev.steps];
      [next[index], next[target]] = [next[target], next[index]];
      return { ...prev, steps: next };
    });
  }

  function validateStepParamsAgainstModel(step) {
    const model = modelById[step.model_id];
    if (!model?.params) return [];
    const allowed = new Set(Object.keys(model.params || {}));
    const parsed = parseStepParams(step.paramsText);
    const errors = [];
    Object.keys(parsed).forEach((key) => {
      if (!allowed.has(key) && !allowed.has(key.replace(/-/g, "_")) && !allowed.has(key.replace(/_/g, "-"))) {
        errors.push(`Параметр '${key}' не поддерживается моделью '${step.model_id}'.`);
      }
    });
    return errors;
  }

  async function validatePipelineDraft() {
    setPipelineMessage("");
    const localErrors = pipelineDraft.steps.flatMap((step) => validateStepParamsAgainstModel(step));
    if (localErrors.length > 0) {
      setPipelineValidation(null);
      setPipelineMessage(localErrors.join("\n"));
      return false;
    }
    const payload = {
      name: pipelineDraft.name,
      steps: pipelineDraft.steps.map((step) => ({ model_id: step.model_id, params: parseStepParams(step.paramsText) })),
    };
    const resp = await fetch(`${API_BASE}/pipelines/validate-draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      setPipelineMessage(`Ошибка проверки: ${JSON.stringify(data)}`);
      setPipelineValidation(null);
      return false;
    }
    setPipelineValidation(data);
    if (!data.valid) {
      setPipelineMessage((data.errors || []).join("\n") || "Draft невалиден");
      return false;
    }
    setPipelineMessage("Draft валиден");
    return true;
  }

  async function savePipelineDraft() {
    const ok = await validatePipelineDraft();
    if (!ok) return;
    const payload = {
      name: pipelineDraft.name,
      steps: pipelineDraft.steps.map((step) => ({ model_id: step.model_id, params: parseStepParams(step.paramsText) })),
    };
    const resp = await fetch(`${API_BASE}/pipelines/create-draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      setPipelineMessage(`Ошибка сохранения: ${JSON.stringify(data)}`);
      return;
    }
    setPipelineMessage(`Сохранено: ${data.name}`);
    const safe = await getJson("/pipelines/templates");
    const templates = Array.isArray(safe) ? safe : [];
    setTemplates(templates);
    const created = templates.find((item) => item.source === "user" && item.name === data.name);
    if (created?.id) setTemplateId(created.id);
  }

  return React.createElement(
    "div",
    { className: "training-shell editor-shell" },
    React.createElement("div", { className: "training-shell__main" },
      React.createElement("div", { className: "card" },
        React.createElement(SectionCard, {
          title: "Добавить пайплайн",
          subtitle: "Соберите последовательность шагов, проверьте runtime-готовность моделей и сохраните пользовательский шаблон без ручной правки YAML.",
          actions: React.createElement(StatusBadge, { tone: unavailableModels.length ? "warning" : "success" }, unavailableModels.length ? "Есть недоступные модели" : "Каталог готов"),
        },
        React.createElement(Field, {
          label: "Pipeline name",
          hint: "Понятное имя поможет потом быстро найти шаблон во вкладке запуска пайплайна.",
        },
        React.createElement("input", {
          value: pipelineDraft.name,
          onChange: (e) => setPipelineDraft((prev) => ({ ...prev, name: e.target.value })),
          placeholder: "Например: PoinTr + postprocess",
        })),
        React.createElement(InlineHint, null, "Если шагу нужны свои веса или конфиг, задайте overrides в соответствующей карточке шага."),
        ),
      ),
      React.createElement("div", { className: "step-stack" },
        pipelineDraft.steps.map((step, idx) => {
          const model = modelById[step.model_id];
          const stepBadge = model
            ? React.createElement(StatusBadge, { tone: model.ready === false ? "warning" : "success" }, model.ready === false ? "Недоступна" : "Готова")
            : React.createElement(StatusBadge, { tone: "neutral" }, `Шаг ${idx + 1}`);
          return React.createElement("div", { className: "card", key: `draft-step-${idx}` },
            React.createElement(SectionCard, {
              title: `Шаг ${idx + 1}`,
              subtitle: model ? `${model.name} • ${model.task_type}` : "Выберите модель и при необходимости задайте overrides только для этого шага.",
              actions: stepBadge,
            },
            React.createElement(Field, { label: "Модель" },
              React.createElement(
                "select",
                {
                  value: step.model_id,
                  onChange: (e) => updateDraftStep(idx, { model_id: e.target.value }),
                },
                React.createElement("option", { value: "" }, "Выберите модель"),
                modelOptions.map((item) => React.createElement("option", { key: item.id, value: item.id }, item.label)),
              ),
            ),
            React.createElement(Field, {
              label: "Overrides для шага",
              hint: "Формат: KEY=VALUE, по одному параметру на строку. Значения переопределят defaults модели только в этом pipeline step.",
            },
            React.createElement("textarea", {
              value: step.paramsText,
              onChange: (e) => updateDraftStep(idx, { paramsText: e.target.value }),
              rows: 6,
              placeholder: "weights_path=/app/external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth\nconfig_path=/app/external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml\ndevice=cuda:0\nmode=model",
            })),
            model && supportedParamsText(model) && React.createElement(InlineHint, null, `Поддерживаемые параметры: ${supportedParamsText(model)}`),
            stepHasOverrides(step.paramsText) && React.createElement(StatusBadge, { tone: "neutral" }, "Есть overrides"),
            React.createElement(ActionBar, null,
              React.createElement("button", { type: "button", onClick: () => moveDraftStep(idx, -1), disabled: idx === 0 }, "Вверх"),
              React.createElement("button", { type: "button", className: "button-secondary", onClick: () => moveDraftStep(idx, 1), disabled: idx === pipelineDraft.steps.length - 1 }, "Вниз"),
              React.createElement("button", { type: "button", className: "button-secondary", onClick: () => removeDraftStep(idx), disabled: pipelineDraft.steps.length <= 1 }, "Удалить шаг"),
            ),
            ),
          );
        }),
      ),
      React.createElement("div", { className: "card" },
        React.createElement(ActionBar, null,
          React.createElement("button", { type: "button", className: "button-secondary", onClick: addDraftStep }, "+ Добавить шаг"),
          React.createElement("button", { type: "button", className: "button-secondary", onClick: validatePipelineDraft }, "Проверить пайплайн"),
          React.createElement("button", { type: "button", onClick: savePipelineDraft }, "Сохранить пайплайн"),
        ),
      ),
    ),
    React.createElement("div", { className: "training-shell__side" },
      React.createElement("div", { className: "card" },
        React.createElement(SectionCard, {
          title: "Runtime status",
          subtitle: "Для сборки пайплайна используются только модели, которые реально готовы к build/smoke запуску.",
        },
        unavailableModels.length > 0
          ? React.createElement(InlineHint, { tone: "warning" }, `Недоступны: ${unavailableModels.map((m) => `${m.id}:${m.readiness_reason || "unknown"}`).join(", ")}`)
          : React.createElement(InlineHint, null, "Все зарегистрированные модели сейчас доступны для добавления в pipeline."),
        ),
      ),
      React.createElement("div", { className: "card" },
        React.createElement(SectionCard, {
          title: "Validation",
          subtitle: "Нормализованные шаги и сообщения проверки появятся здесь сразу после validate/save.",
        },
        pipelineMessage
          ? React.createElement(LogPanel, { text: pipelineMessage, emptyText: "" })
          : React.createElement(InlineHint, null, "Пока пусто. Нажмите «Проверить пайплайн», чтобы увидеть runtime-ошибки и итоговую нормализацию шагов."),
        pipelineValidation && React.createElement(LogPanel, {
          text: JSON.stringify(pipelineValidation.normalized_steps || [], null, 2),
          emptyText: "",
          style: { maxHeight: 280 },
        }),
        ),
      ),
    ),
  );
}
