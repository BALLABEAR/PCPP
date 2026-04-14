import React, { useEffect, useMemo, useRef, useState } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";

const API_BASE = "http://localhost:8000";

function App() {
  const [file, setFile] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState("");
  const [task, setTask] = useState(null);
  const [status, setStatus] = useState(null);
  const [taskLogs, setTaskLogs] = useState("");
  const [models, setModels] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [onboarding, setOnboarding] = useState({
    model_id: "poin_tr",
    task_type: "completion",
    repo_path: "./external_models/PoinTr",
    weights_path: "./external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth",
    config_path: "./external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml",
    input_data_kind: "point_cloud",
    output_data_kind: "point_cloud",
    input_path: "./data/benchmark_inputs/100k/room_scan1_100k.xyz",
    entry_command: "",
    extra_pip_packages: "",
    pip_requirements_files: "",
    pip_extra_args: "",
    system_packages: "",
    base_image: "",
    extra_build_steps: "",
    env_overrides: "",
    smoke_args: "",
  });
  const [allowOverwrite, setAllowOverwrite] = useState(false);
  const [disableBuildCache, setDisableBuildCache] = useState(false);
  const [scanSuggestions, setScanSuggestions] = useState(null);
  const [dryRunApproved, setDryRunApproved] = useState(false);
  const [wizard, setWizard] = useState({
    validate: "pending",
    scaffold: "pending",
    build: "pending",
    smoke: "pending",
    registry: "pending",
  });
  const [wizardRunId, setWizardRunId] = useState("");
  const [wizardLogs, setWizardLogs] = useState("");
  const [wizardHint, setWizardHint] = useState(null);
  const [wizardBusy, setWizardBusy] = useState(false);
  const [wizardScaffoldCreated, setWizardScaffoldCreated] = useState(false);
  const [aiPromptText, setAiPromptText] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const rollbackDoneRef = useRef(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [activeView, setActiveView] = useState("pipeline");
  const [pipelineDraft, setPipelineDraft] = useState({
    name: "",
    steps: [{ model_id: "", paramsText: "" }],
  });
  const [pipelineValidation, setPipelineValidation] = useState(null);
  const [pipelineMessage, setPipelineMessage] = useState("");
  const [forceRebuildImage, setForceRebuildImage] = useState(false);

  function parseListField(value) {
    return (value || "")
      .split("\n")
      .map((v) => v.trim())
      .filter((v) => v && v.toLowerCase() !== "<empty>");
  }

  function startSafePolling(handler, intervalMs, onError) {
    let inFlight = false;
    const timer = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const shouldStop = await handler();
        if (shouldStop) clearInterval(timer);
      } catch (e) {
        clearInterval(timer);
        if (onError) onError(e);
      } finally {
        inFlight = false;
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }

  useEffect(() => {
    fetch(`${API_BASE}/pipelines/templates`)
      .then((r) => r.json())
      .then((payload) => {
        const safePayload = Array.isArray(payload) ? payload : [];
        setTemplates(safePayload);
        const safeUsers = safePayload.filter((item) => item.source === "user");
        if (safeUsers.length > 0) {
          setTemplateId(safeUsers[0].id);
        } else {
          setTemplateId("");
        }
      })
      .catch((e) => setError(`Failed to load templates: ${e.message}`));

    fetch(`${API_BASE}/registry/models`)
      .then((r) => r.json())
      .then((payload) => setModels(Array.isArray(payload) ? payload : []))
      .catch((e) => setError(`Failed to load model catalog: ${e.message}`));
  }, []);

  useEffect(() => {
    if (!task?.id) return undefined;
    return startSafePolling(async () => {
      const resp = await fetch(`${API_BASE}/tasks/${task.id}`);
      const payload = await resp.json();
      setStatus(payload);
      const logsResp = await fetch(`${API_BASE}/tasks/${task.id}/logs`);
      if (logsResp.ok) {
        const logsPayload = await logsResp.json();
        setTaskLogs(logsPayload.logs || "");
      }
      if (payload.status === "completed" || payload.status === "failed" || payload.status === "cancelled") {
        return true;
      }
      return false;
    }, 3000, (e) => setError(`Status polling failed: ${e.message}`));
  }, [task?.id]);

  const userTemplates = useMemo(
    () => templates.filter((item) => item.source === "user"),
    [templates],
  );
  const selectedTemplate = useMemo(
    () => userTemplates.find((item) => item.id === templateId) || null,
    [userTemplates, templateId],
  );
  const modelOptions = useMemo(
    () => models
      .filter((m) => m.ready !== false)
      .map((m) => ({ id: m.id, label: `${m.name} (${m.task_type})` })),
    [models],
  );
  const unavailableModels = useMemo(
    () => models.filter((m) => m.ready === false),
    [models],
  );
  const modelById = useMemo(
    () => models.reduce((acc, item) => {
      acc[item.id] = item;
      return acc;
    }, {}),
    [models],
  );

  useEffect(() => {
    if (!wizardRunId) return undefined;
    return startSafePolling(async () => {
      const resp = await fetch(`${API_BASE}/onboarding/models/runs/${wizardRunId}`);
      if (!resp.ok) {
        setWizardLogs(`Failed to read run status: HTTP ${resp.status}`);
        setWizardBusy(false);
        return true;
      }
      const payload = await resp.json();
      setWizardLogs(payload.logs || "");
      setWizardHint(payload.error_hint || null);
      if (payload.status === "completed" || payload.status === "failed") {
        setWizardBusy(false);
        return true;
      }
      return false;
    }, 2000, (e) => {
      setWizardBusy(false);
      setWizardLogs(`Failed to poll run logs: ${e.message}`);
    });
  }, [wizardRunId]);

  function updateWizard(step, status) {
    setWizard((prev) => ({ ...prev, [step]: status }));
  }

  function redactSensitive(text) {
    if (!text) return "";
    return text
      .replace(/(token|password|secret|apikey|api_key)\s*[:=]\s*([^\s]+)/gi, "$1=<redacted>")
      .replace(/(AKIA[0-9A-Z]{16})/g, "<redacted-aws-key>");
  }

  function lastLogLines(text, maxLines = 80) {
    const lines = (text || "").split("\n");
    return lines.slice(Math.max(0, lines.length - maxLines)).join("\n");
  }

  function buildAiPrompt() {
    const logs = redactSensitive(lastLogLines(wizardLogs, 80));
    const hintTitle = wizardHint?.title || "нет";
    const hintFix = wizardHint?.fix || "нет";
    return [
      "Ты помогаешь заполнить Advanced-поля в мастере добавления модели PCPP.",
      "Цель: по ошибке сборки/запуска дать пошагово, что вставить в какие поля Advanced.",
      "",
      "Важно:",
      "- Не предлагай изменения вне полей Advanced без объяснения.",
      "- Если данных недостаточно, явно скажи, что спросить/где посмотреть в репозитории.",
      "- Учитывай, что сборка/запуск выполняется в Docker на Ubuntu 22.04.",
      "",
      "Текущее состояние шагов:",
      `- validate: ${wizard.validate}`,
      `- scaffold: ${wizard.scaffold}`,
      `- build: ${wizard.build}`,
      `- smoke: ${wizard.smoke}`,
      `- registry: ${wizard.registry}`,
      "",
      "Контекст модели:",
      `- task_type: ${onboarding.task_type}`,
      `- model_id: ${onboarding.model_id}`,
      `- repo_path: ${onboarding.repo_path}`,
      `- weights_path: ${onboarding.weights_path}`,
      `- config_path: ${onboarding.config_path}`,
      "- target_runtime: ubuntu22.04-docker",
      "",
      "Текущие Advanced-поля:",
      `- entry_command: ${onboarding.entry_command}`,
      `- extra_pip_packages:\\n${onboarding.extra_pip_packages || "<empty>"}`,
      `- pip_requirements_files:\\n${onboarding.pip_requirements_files || "<empty>"}`,
      `- pip_extra_args:\\n${onboarding.pip_extra_args || "<empty>"}`,
      `- system_packages:\\n${onboarding.system_packages || "<empty>"}`,
      `- base_image: ${onboarding.base_image || "<empty>"}`,
      `- extra_build_steps:\\n${onboarding.extra_build_steps || "<empty>"}`,
      `- env_overrides:\\n${onboarding.env_overrides || "<empty>"}`,
      `- smoke_args:\\n${onboarding.smoke_args || "<empty>"}`,
      "",
      "Классификатор ошибки (если есть):",
      `- title: ${hintTitle}`,
      `- fix: ${hintFix}`,
      "",
      "Последние строки лога:",
      logs || "<empty>",
      "",
      "Формат ответа (обязательно в виде шагов):",
      "1) Поле: <имя поля> -> Значение: <что вставить>",
      "2) Почему это нужно",
      "3) Что проверить после повторного запуска",
    ].join("\n");
  }

  function generateAiPrompt() {
    setAiPromptText(buildAiPrompt());
    setCopyStatus("");
  }

  async function copyAiPrompt() {
    if (!aiPromptText) return;
    try {
      await navigator.clipboard.writeText(aiPromptText);
      setCopyStatus("Скопировано");
    } catch (e) {
      setCopyStatus("Не удалось скопировать. Скопируйте вручную из поля ниже.");
    }
  }

  async function rollbackScaffold() {
    if (!wizardScaffoldCreated || rollbackDoneRef.current) return;
    rollbackDoneRef.current = true;
    try {
      await fetch(`${API_BASE}/onboarding/models/cleanup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: onboarding.task_type,
          model_id: onboarding.model_id,
        }),
      });
      setWizardScaffoldCreated(false);
      setWizardLogs((prev) => `${prev}\n[rollback] Scaffold folder removed due to failure.\n`);
    } catch (e) {
      setWizardLogs((prev) => `${prev}\n[rollback] Cleanup failed: ${e.message}\n`);
    }
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

  function parsePrimitive(value) {
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

  function parseStepParams(text) {
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
    const tResp = await fetch(`${API_BASE}/pipelines/templates`);
    const tPayload = await tResp.json();
    const safe = Array.isArray(tPayload) ? tPayload : [];
    setTemplates(safe);
    const created = safe.find((item) => item.source === "user" && item.name === data.name);
    if (created?.id) setTemplateId(created.id);
  }

  async function handleDeleteModel(modelId) {
    if (!window.confirm(`Вы уверены, что хотите удалить модель '${modelId}'?`)) return;
    setError("");
    try {
      const resp = await fetch(`${API_BASE}/registry/models/${encodeURIComponent(modelId)}`, {
        method: "DELETE",
      });
      if (!resp.ok) throw new Error(await resp.text());
      await resp.json();
      const modelsResp = await fetch(`${API_BASE}/registry/models`);
      const modelsPayload = await modelsResp.json();
      setModels(Array.isArray(modelsPayload) ? modelsPayload : []);
      const templatesResp = await fetch(`${API_BASE}/pipelines/templates`);
      const templatesPayload = await templatesResp.json();
      setTemplates(Array.isArray(templatesPayload) ? templatesPayload : []);
    } catch (e) {
      setError(`Delete model failed: ${e.message}`);
    }
  }

  async function handleDeleteTemplate(template) {
    if (!template?.pipeline_id) return;
    if (!window.confirm(`Вы уверены, что хотите удалить пайплайн '${template.name}'?`)) return;
    setError("");
    try {
      const resp = await fetch(`${API_BASE}/pipelines/${encodeURIComponent(template.pipeline_id)}`, {
        method: "DELETE",
      });
      if (!resp.ok) throw new Error(await resp.text());
      const tResp = await fetch(`${API_BASE}/pipelines/templates`);
      const tPayload = await tResp.json();
      const safe = Array.isArray(tPayload) ? tPayload : [];
      setTemplates(safe);
      const safeUsers = safe.filter((item) => item.source === "user");
      if (!safeUsers.find((item) => item.id === templateId)) {
        setTemplateId(safeUsers[0]?.id || "");
      }
    } catch (e) {
      setError(`Delete pipeline failed: ${e.message}`);
    }
  }

  async function wizardValidate() {
    setWizardHint(null);
    setWizardLogs("");
    updateWizard("validate", "running");
    try {
      const resp = await fetch(`${API_BASE}/onboarding/models/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_id: onboarding.model_id,
          task_type: onboarding.task_type,
          repo_path: onboarding.repo_path,
          weights_path: onboarding.weights_path,
          config_path: onboarding.config_path,
          input_data_kind: onboarding.input_data_kind,
          output_data_kind: onboarding.output_data_kind,
        }),
      });
      const payload = await resp.json();
      if (!resp.ok || !payload.valid) {
        throw new Error(JSON.stringify(payload, null, 2));
      }
      updateWizard("validate", "success");
      return true;
    } catch (e) {
      updateWizard("validate", "failed");
      setWizardLogs(String(e.message || e));
      return false;
    }
  }

  async function wizardScaffold() {
    updateWizard("scaffold", "running");
    try {
      const resp = await fetch(`${API_BASE}/onboarding/models/scaffold`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_id: onboarding.model_id,
          task_type: onboarding.task_type,
          repo_path: onboarding.repo_path,
          weights_path: onboarding.weights_path,
          config_path: onboarding.config_path,
          input_data_kind: onboarding.input_data_kind,
          output_data_kind: onboarding.output_data_kind,
          entry_command: onboarding.entry_command,
          extra_pip_packages: parseListField(onboarding.extra_pip_packages),
          pip_requirements_files: parseListField(onboarding.pip_requirements_files),
          pip_extra_args: parseListField(onboarding.pip_extra_args),
          system_packages: parseListField(onboarding.system_packages),
          base_image: onboarding.base_image,
          extra_build_steps: parseListField(onboarding.extra_build_steps),
          env_overrides: onboarding.env_overrides.split("\n").reduce((acc, item) => {
            const idx = item.indexOf("=");
            if (idx > 0) acc[item.slice(0, idx).trim()] = item.slice(idx + 1).trim();
            return acc;
          }, {}),
          overwrite: allowOverwrite,
        }),
      });
      const payload = await resp.json();
      if (!resp.ok) {
        throw new Error(JSON.stringify(payload, null, 2));
      }
      updateWizard("scaffold", "success");
      setWizardScaffoldCreated(true);
      setWizardLogs(payload.stdout || "");
      return true;
    } catch (e) {
      updateWizard("scaffold", "failed");
      setWizardLogs(String(e.message || e));
      return false;
    }
  }

  async function runPreflightScan() {
    setWizardHint(null);
    setWizardLogs("");
    setScanSuggestions(null);
    const resp = await fetch(`${API_BASE}/onboarding/models/preflight-scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: onboarding.model_id,
        task_type: onboarding.task_type,
        repo_path: onboarding.repo_path,
        weights_path: onboarding.weights_path,
        config_path: onboarding.config_path,
        input_data_kind: onboarding.input_data_kind,
        output_data_kind: onboarding.output_data_kind,
      }),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      setWizardLogs(JSON.stringify(payload, null, 2));
      return;
    }
    setScanSuggestions(payload);
    setWizardLogs((payload.notes || []).join("\n"));
  }

  function applyScanSuggestionsToEmpty() {
    if (!scanSuggestions?.suggested) return;
    setOnboarding((prev) => {
      const envSuggested = Object.entries(scanSuggestions.suggested.env_overrides || {})
        .map(([k, v]) => `${k}=${v}`)
        .join("\n");
      return {
        ...prev,
        entry_command: prev.entry_command.trim() || scanSuggestions.suggested.entry_command || "",
        extra_pip_packages: prev.extra_pip_packages.trim() || (scanSuggestions.suggested.extra_pip_packages || []).join("\n"),
        pip_requirements_files: prev.pip_requirements_files.trim() || (scanSuggestions.suggested.pip_requirements_files || []).join("\n"),
        pip_extra_args: prev.pip_extra_args.trim() || (scanSuggestions.suggested.pip_extra_args || []).join("\n"),
        system_packages: prev.system_packages.trim() || (scanSuggestions.suggested.system_packages || []).join("\n"),
        base_image: prev.base_image.trim() || (scanSuggestions.suggested.base_image || ""),
        extra_build_steps: prev.extra_build_steps.trim() || (scanSuggestions.suggested.extra_build_steps || []).join("\n"),
        env_overrides: prev.env_overrides.trim() || envSuggested,
        smoke_args: prev.smoke_args.trim() || (scanSuggestions.suggested.smoke_args || []).join("\n"),
      };
    });
    setDryRunApproved(false);
  }

  async function wizardBuild() {
    updateWizard("build", "running");
    setWizardBusy(true);
    const resp = await fetch(`${API_BASE}/onboarding/models/build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: onboarding.model_id,
        task_type: onboarding.task_type,
        no_cache: disableBuildCache,
      }),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      setWizardBusy(false);
      updateWizard("build", "failed");
      setWizardLogs(JSON.stringify(payload, null, 2));
      await rollbackScaffold();
      return null;
    }
    setWizardRunId(payload.run_id);
    return payload.run_id;
  }

  async function wizardSmoke() {
    updateWizard("smoke", "running");
    setWizardBusy(true);
    const resp = await fetch(`${API_BASE}/onboarding/models/smoke-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: onboarding.model_id,
        task_type: onboarding.task_type,
        input_path: onboarding.input_path,
        input_data_kind: onboarding.input_data_kind,
        smoke_args: parseListField(onboarding.smoke_args).join("\n"),
      }),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      setWizardBusy(false);
      updateWizard("smoke", "failed");
      setWizardLogs(JSON.stringify(payload, null, 2));
      await rollbackScaffold();
      return null;
    }
    setWizardRunId(payload.run_id);
    return payload.run_id;
  }

  async function wizardRegistryCheck() {
    updateWizard("registry", "running");
    const reconcileResp = await fetch(`${API_BASE}/onboarding/models/registry-reconcile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!reconcileResp.ok) {
      updateWizard("registry", "failed");
      setWizardLogs((prev) => `${prev}\n[registry] Reconcile failed: HTTP ${reconcileResp.status}\n`);
      return false;
    }
    const resp = await fetch(`${API_BASE}/onboarding/models/registry-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: onboarding.model_id }),
    });
    const payload = await resp.json();
    if (!resp.ok || !payload.registered || !payload.ready) {
      updateWizard("registry", "failed");
      const reason = payload?.reason ? ` (${payload.reason})` : "";
      setWizardLogs((prev) => `${prev}\n[registry] Model is not ready for pipeline usage${reason}.\n`);
      return false;
    }
    updateWizard("registry", "success");
    return true;
  }

  async function handleWizardRun() {
    if (wizardBusy) return;
    if (!dryRunApproved) {
      setWizardLogs("Сначала подтвердите dry-run: проверьте или примените предложенные Advanced-поля.");
      return;
    }
    setWizard({
      validate: "pending",
      scaffold: "pending",
      build: "pending",
      smoke: "pending",
      registry: "pending",
    });
    rollbackDoneRef.current = false;
    setWizardScaffoldCreated(false);
    setWizardRunId("");
    setDryRunApproved(false);
    const okValidate = await wizardValidate();
    if (!okValidate) return;
    const okScaffold = await wizardScaffold();
    if (!okScaffold) return;
    const buildRunId = await wizardBuild();
    if (!buildRunId) return;
    startSafePolling(async () => {
      const resp = await fetch(`${API_BASE}/onboarding/models/runs/${buildRunId}`);
      if (!resp.ok) {
        setWizardBusy(false);
        updateWizard("build", "failed");
        setWizardLogs(`Failed to read build status: HTTP ${resp.status}`);
        await rollbackScaffold();
        return true;
      }
      const payload = await resp.json();
      if (payload.status === "completed") {
        updateWizard("build", "success");
        await wizardSmoke();
        return true;
      } else if (payload.status === "failed") {
        setWizardBusy(false);
        updateWizard("build", "failed");
        await rollbackScaffold();
        return true;
      }
      return false;
    }, 2500, async (e) => {
      setWizardBusy(false);
      updateWizard("build", "failed");
      setWizardLogs(`Build polling failed: ${e.message}`);
      await rollbackScaffold();
    });
  }

  useEffect(() => {
    if (!wizardRunId) return undefined;
    return startSafePolling(async () => {
      const resp = await fetch(`${API_BASE}/onboarding/models/runs/${wizardRunId}`);
      if (!resp.ok) {
        updateWizard("smoke", "failed");
        setWizardBusy(false);
        await rollbackScaffold();
        return true;
      }
      const payload = await resp.json();
      if (payload.kind === "smoke") {
        if (payload.status === "completed") {
          updateWizard("smoke", "success");
          await wizardRegistryCheck();
          setWizardBusy(false);
          return true;
        } else if (payload.status === "failed") {
          updateWizard("smoke", "failed");
          setWizardBusy(false);
          await rollbackScaffold();
          return true;
        }
      }
      return false;
    }, 2500, async (e) => {
      updateWizard("smoke", "failed");
      setWizardBusy(false);
      setWizardLogs((prev) => `${prev}\n[smoke] Polling failed: ${e.message}\n`);
      await rollbackScaffold();
    });
  }, [wizardRunId]);

  const resultLink = status?.status === "completed" && status?.result_bucket && status?.result_key
    ? `${API_BASE}/files/download?bucket=${encodeURIComponent(status.result_bucket)}&key=${encodeURIComponent(status.result_key)}&expires_seconds=900&redirect=true`
    : null;

  return React.createElement(
    "div",
    { className: "container" },
    React.createElement("h1", null, "Point Cloud Processing Platform"),
    React.createElement("div", { className: "top-menu" },
      React.createElement(
        "button",
        {
          className: activeView === "pipeline" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("pipeline"),
        },
        "Запустить пайплайн",
      ),
      React.createElement(
        "button",
        {
          className: activeView === "add-model" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("add-model"),
        },
        "Добавить модель",
      ),
      React.createElement(
        "button",
        {
          className: activeView === "add-pipeline" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("add-pipeline"),
        },
        "Добавить пайплайн",
      ),
    ),
    activeView === "pipeline" && React.createElement("div", { className: "card" },
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
        userTemplates.map((t) =>
          React.createElement(
            "option",
            { key: t.id, value: t.id },
            t.name,
          ),
        ),
      ),
      userTemplates.length === 0 && React.createElement("p", { className: "muted" }, "Нет пользовательских шаблонов. Создайте пайплайн во вкладке 'Добавить пайплайн'."),
      React.createElement("p", { className: "muted" }, selectedTemplate?.description || ""),
      React.createElement("label", null,
        React.createElement("input", {
          type: "checkbox",
          checked: forceRebuildImage,
          onChange: (e) => setForceRebuildImage(e.target.checked),
          style: { marginRight: 8 },
        }),
        "Force rebuild image (для диагностики, может быть медленно)",
      ),
      React.createElement(
        "button",
        { disabled: !file || !selectedTemplate || isSubmitting || userTemplates.length === 0, onClick: handleRun },
        isSubmitting ? "Submitting..." : "Upload and Run",
      ),
      status && (status.status === "running" || status.status === "pending") && React.createElement(
        "button",
        { style: { marginLeft: 8 }, onClick: handleCancel },
        "Cancel Task",
      ),
      status && React.createElement("p", { style: { marginTop: 12 } }, `Status: ${status.status}`),
      status && React.createElement("pre", { className: "muted", style: { maxHeight: 220, overflow: "auto", background: "#fafafa", padding: 8, borderRadius: 6 } }, taskLogs || "Task logs will appear here"),
      resultLink && React.createElement(
        "p",
        null,
        React.createElement("a", { href: resultLink, target: "_blank", rel: "noreferrer" }, "Download result"),
      ),
      error && React.createElement("p", { style: { color: "crimson" } }, error),
    ),
    activeView === "pipeline" && React.createElement("div", { className: "card" },
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
          React.createElement(
            "button",
            { type: "button", onClick: () => handleDeleteTemplate(tpl), title: "Удалить пайплайн" },
            "×",
          ),
        ),
      ),
    ),
    activeView === "pipeline" && React.createElement("div", { className: "card" },
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
              React.createElement(
                "button",
                { type: "button", onClick: () => handleDeleteModel(m.id), title: "Удалить модель" },
                "×",
              ),
            ),
            React.createElement("p", { className: "muted" }, m.task_type),
          ),
        ),
      ),
    ),
    activeView === "add-model" && React.createElement("div", { className: "card" },
      React.createElement("h2", null, "Добавить модель"),
      React.createElement(
        "p",
        { className: "muted" },
        "Перед запуском скачайте репозиторий модели и распакуйте его в папку external_models.",
      ),
      React.createElement(
        "p",
        { className: "muted" },
        "Scaffold шаг создает шаблонные файлы адаптера (worker/model_card/manifest/Dockerfile). Затем при необходимости подправьте entry-command и runtime.manifest под конкретную модель.",
      ),
      React.createElement("label", null,
        React.createElement("input", {
          type: "checkbox",
          checked: allowOverwrite,
          onChange: (e) => setAllowOverwrite(e.target.checked),
          style: { marginRight: 8 },
        }),
        "Разрешить overwrite (создаст backup-папку .bak_*)",
      ),
      React.createElement("label", null,
        React.createElement("input", {
          type: "checkbox",
          checked: disableBuildCache,
          onChange: (e) => setDisableBuildCache(e.target.checked),
          style: { marginRight: 8 },
        }),
        "Сборка без кэша (для диагностики, обычно выключено)",
      ),
      React.createElement("label", null,
        React.createElement("input", {
          type: "checkbox",
          checked: dryRunApproved,
          onChange: (e) => setDryRunApproved(e.target.checked),
          style: { marginRight: 8 },
        }),
        "Dry-run подтвержден: Advanced-поля проверены",
      ),
      React.createElement("label", null, "Task type"),
      React.createElement("input", {
        value: onboarding.task_type,
        list: "task-type-options",
        onChange: (e) => setOnboarding({ ...onboarding, task_type: e.target.value }),
      }),
      React.createElement(
        "datalist",
        { id: "task-type-options" },
        React.createElement("option", { value: "completion" }),
        React.createElement("option", { value: "segmentation" }),
        React.createElement("option", { value: "meshing" }),
        React.createElement("option", { value: "classification" }),
      ),
      React.createElement(
        "p",
        { className: "muted" },
        "Можно выбрать из списка или ввести новый task type вручную.",
      ),
      React.createElement("label", null, "Model id (lower_snake_case)"),
      React.createElement("input", {
        value: onboarding.model_id,
        onChange: (e) => setOnboarding({ ...onboarding, model_id: e.target.value }),
      }),
      React.createElement("label", null, "Repo path"),
      React.createElement("input", {
        value: onboarding.repo_path,
        onChange: (e) => setOnboarding({ ...onboarding, repo_path: e.target.value }),
      }),
      React.createElement("label", null, "Weights path"),
      React.createElement("input", {
        value: onboarding.weights_path,
        onChange: (e) => setOnboarding({ ...onboarding, weights_path: e.target.value }),
      }),
      React.createElement("label", null, "Config path"),
      React.createElement("input", {
        value: onboarding.config_path,
        onChange: (e) => setOnboarding({ ...onboarding, config_path: e.target.value }),
      }),
      React.createElement("label", null, "Тип входных данных"),
      React.createElement(
        "select",
        {
          value: onboarding.input_data_kind,
          onChange: (e) => setOnboarding({ ...onboarding, input_data_kind: e.target.value }),
        },
        React.createElement("option", { value: "point_cloud" }, "Облако точек"),
        React.createElement("option", { value: "mesh" }, "Меш"),
      ),
      React.createElement("label", null, "Тип выходных данных"),
      React.createElement(
        "select",
        {
          value: onboarding.output_data_kind,
          onChange: (e) => setOnboarding({ ...onboarding, output_data_kind: e.target.value }),
        },
        React.createElement("option", { value: "point_cloud" }, "Облако точек"),
        React.createElement("option", { value: "mesh" }, "Меш"),
      ),
      React.createElement("label", null, "Тестовый входной файл для пробного запуска"),
      React.createElement("input", {
        value: onboarding.input_path,
        onChange: (e) => setOnboarding({ ...onboarding, input_path: e.target.value }),
      }),
      React.createElement(
        "button",
        { type: "button", style: { marginBottom: 8 }, onClick: () => setShowAdvanced((v) => !v) },
        showAdvanced ? "Скрыть Advanced" : "Показать Advanced",
      ),
      showAdvanced && React.createElement("div", { className: "card", style: { background: "#fafafa" } },
        React.createElement("p", { className: "muted" }, "Поля ниже — примеры. Замените их под свою модель перед запуском."),
        React.createElement("label", null, "Entry command (из README модели)"),
        React.createElement("input", {
          value: onboarding.entry_command,
          placeholder: "python tools/inference.py --config cfgs/model.yaml --ckpts weights.pth",
          onChange: (e) => setOnboarding({ ...onboarding, entry_command: e.target.value }),
        }),
        React.createElement("p", { className: "muted" }, "Что это: основная команда запуска инференса. Где искать: README -> Inference / Evaluation / Test / Run."),
        React.createElement("label", null, "Extra pip packages (по одному в строке)"),
        React.createElement("textarea", {
          value: onboarding.extra_pip_packages,
          onChange: (e) => setOnboarding({ ...onboarding, extra_pip_packages: e.target.value }),
          rows: 3,
          placeholder: "einops\ntrimesh==4.4.9",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("p", { className: "muted" }, "Когда нужно: если в логах ModuleNotFoundError. Где искать: requirements.txt, environment.yml, README."),
        React.createElement("label", null, "Pip requirements files (по одному пути в строке, относительно repo)"),
        React.createElement("textarea", {
          value: onboarding.pip_requirements_files,
          onChange: (e) => setOnboarding({ ...onboarding, pip_requirements_files: e.target.value }),
          rows: 2,
          placeholder: "requirements.txt\nrequirements-dev.txt",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("label", null, "Pip extra args (по одному аргументу в строке)"),
        React.createElement("textarea", {
          value: onboarding.pip_extra_args,
          onChange: (e) => setOnboarding({ ...onboarding, pip_extra_args: e.target.value }),
          rows: 2,
          placeholder: "--extra-index-url\nhttps://download.pytorch.org/whl/cu118",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("label", null, "System packages (по одному в строке)"),
        React.createElement("textarea", {
          value: onboarding.system_packages,
          onChange: (e) => setOnboarding({ ...onboarding, system_packages: e.target.value }),
          rows: 2,
          placeholder: "ninja-build\ngit",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("label", null, "Base image"),
        React.createElement("input", {
          value: onboarding.base_image,
          placeholder: "nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04",
          onChange: (e) => setOnboarding({ ...onboarding, base_image: e.target.value }),
        }),
        React.createElement("label", null, "Extra build steps (по одному в строке)"),
        React.createElement("textarea", {
          value: onboarding.extra_build_steps,
          onChange: (e) => setOnboarding({ ...onboarding, extra_build_steps: e.target.value }),
          rows: 3,
          placeholder: "cd /app/external_models/YourModel/extensions/chamfer && python setup.py install",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("p", { className: "muted" }, "Когда нужно: если не собираются CUDA/C++ extensions. Где искать: README -> Build/Compile/Extensions."),
        React.createElement("label", null, "Env overrides (KEY=VALUE по одному в строке)"),
        React.createElement("textarea", {
          value: onboarding.env_overrides,
          onChange: (e) => setOnboarding({ ...onboarding, env_overrides: e.target.value }),
          rows: 3,
          placeholder: "PYTHONPATH=/app/external_models/YourModel\nOMP_NUM_THREADS=1",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("p", { className: "muted" }, "Когда нужно: если README требует переменные окружения. Формат строго KEY=VALUE."),
        React.createElement("label", null, "Smoke args (по одному аргументу в строке)"),
        React.createElement("textarea", {
          value: onboarding.smoke_args,
          onChange: (e) => setOnboarding({ ...onboarding, smoke_args: e.target.value }),
          rows: 3,
          placeholder: "--config\ncfgs/model.yaml\n--ckpts\npretrained/model.pth",
          style: { width: "100%", marginBottom: 12 },
        }),
        React.createElement("p", { className: "muted" }, "Когда нужно: если команда запуска требует обязательные параметры. По одному токену в строке."),
      ),
      React.createElement(
        "p",
        { className: "muted" },
        "Можно оставить пустым: мастер сам создаст минимальный тестовый файл подходящего типа и запустит smoke-проверку.",
      ),
      React.createElement("p", { className: "muted" }, `validate: ${wizard.validate} | scaffold: ${wizard.scaffold} | build: ${wizard.build} | smoke: ${wizard.smoke} | registry: ${wizard.registry}`),
      React.createElement(
        "button",
        { disabled: wizardBusy, onClick: handleWizardRun },
        wizardBusy ? "Выполняется..." : "Добавить модель",
      ),
      React.createElement(
        "button",
        { style: { marginLeft: 8 }, disabled: wizardBusy, onClick: wizardValidate },
        "Повторить проверку",
      ),
      React.createElement(
        "button",
        { style: { marginLeft: 8 }, disabled: wizardBusy, onClick: runPreflightScan },
        "Сканировать и предложить Advanced",
      ),
      React.createElement(
        "button",
        {
          style: { marginLeft: 8 },
          disabled: (!wizardLogs && !wizardHint) || wizardBusy,
          onClick: generateAiPrompt,
        },
        "Сформировать запрос для AI-помощника",
      ),
      aiPromptText && React.createElement(
        "div",
        { className: "card", style: { marginTop: 12, background: "#fafafa" } },
        React.createElement("p", { className: "muted" }, "Скопируйте текст ниже и вставьте во внешнюю нейросеть."),
        React.createElement(
          "button",
          { type: "button", onClick: copyAiPrompt },
          "Копировать запрос",
        ),
        React.createElement(
          "button",
          { type: "button", style: { marginLeft: 8 }, onClick: generateAiPrompt },
          "Обновить",
        ),
        copyStatus && React.createElement("p", { className: "muted", style: { marginTop: 8 } }, copyStatus),
        React.createElement("textarea", {
          value: aiPromptText,
          readOnly: true,
          rows: 18,
          style: { width: "100%", marginTop: 8 },
        }),
      ),
      scanSuggestions && React.createElement(
        "div",
        { className: "card", style: { marginTop: 12, background: "#fafafa" } },
        React.createElement("p", { className: "muted" }, `Preflight confidence: ${scanSuggestions.confidence || "low"}`),
        React.createElement("pre", { className: "muted", style: { maxHeight: 220, overflow: "auto" } }, JSON.stringify(scanSuggestions.suggested || {}, null, 2)),
        React.createElement(
          "button",
          { type: "button", onClick: applyScanSuggestionsToEmpty },
          "Применить только в пустые поля Advanced",
        ),
      ),
      wizardHint && React.createElement("p", { style: { color: "darkorange", marginTop: 12 } }, `${wizardHint.title}: ${wizardHint.fix}`),
      React.createElement("pre", { className: "muted", style: { maxHeight: 220, overflow: "auto", background: "#fafafa", padding: 8, borderRadius: 6 } }, wizardLogs || "Logs will appear here"),
    ),
    activeView === "add-pipeline" && React.createElement("div", { className: "card" },
      React.createElement("h2", null, "Добавить пайплайн"),
      React.createElement("label", null, "Pipeline name"),
      React.createElement("input", {
        value: pipelineDraft.name,
        onChange: (e) => setPipelineDraft((prev) => ({ ...prev, name: e.target.value })),
      }),
      pipelineDraft.steps.map((step, idx) => React.createElement("div", { className: "card", key: `draft-step-${idx}` },
        React.createElement("label", null, `Шаг ${idx + 1}: модель`),
        React.createElement(
          "select",
          {
            value: step.model_id,
            onChange: (e) => updateDraftStep(idx, { model_id: e.target.value }),
          },
          React.createElement("option", { value: "" }, "Выберите модель"),
          modelOptions.map((item) => React.createElement("option", { key: item.id, value: item.id }, item.label)),
        ),
        React.createElement("label", null, "Свои веса/конфиг для этого шага (KEY=VALUE, по одному на строку)"),
        React.createElement(
          "p",
          { className: "muted" },
          "Пример: вставьте свои пути к weights/config. Это переопределит значения модели только в этом шаге пайплайна.",
        ),
        step.model_id && modelById[step.model_id]?.params && React.createElement(
          "p",
          { className: "muted" },
          `Поддерживаемые параметры модели: ${Object.keys(modelById[step.model_id].params || {}).join(", ")}`,
        ),
        React.createElement("textarea", {
          value: step.paramsText,
          onChange: (e) => updateDraftStep(idx, { paramsText: e.target.value }),
          rows: 5,
          placeholder: "weights_path=external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth\nconfig_path=external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml\ndevice=cuda:0\nmode=model",
          style: { width: "100%", marginBottom: 8 },
        }),
        React.createElement("button", { type: "button", onClick: () => moveDraftStep(idx, -1), disabled: idx === 0 }, "Вверх"),
        React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: () => moveDraftStep(idx, 1), disabled: idx === pipelineDraft.steps.length - 1 }, "Вниз"),
        React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: () => removeDraftStep(idx), disabled: pipelineDraft.steps.length <= 1 }, "Удалить шаг"),
      )),
      unavailableModels.length > 0 && React.createElement(
        "p",
        { className: "muted" },
        `Недоступны для пайплайна (нет build/smoke readiness): ${unavailableModels.map((m) => `${m.id}:${m.readiness_reason || "unknown"}`).join(", ")}`,
      ),
      React.createElement("button", { type: "button", onClick: addDraftStep }, "+ Добавить шаг"),
      React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: validatePipelineDraft }, "Проверить пайплайн"),
      React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: savePipelineDraft }, "Сохранить пайплайн"),
      pipelineMessage && React.createElement("pre", { className: "muted", style: { maxHeight: 180, overflow: "auto", background: "#fafafa", padding: 8, borderRadius: 6 } }, pipelineMessage),
      pipelineValidation && React.createElement("div", { className: "card", style: { marginTop: 12, background: "#fafafa" } },
        React.createElement("p", { className: "muted" }, `valid: ${pipelineValidation.valid}`),
        React.createElement("pre", { className: "muted", style: { maxHeight: 240, overflow: "auto" } }, JSON.stringify(pipelineValidation.normalized_steps || [], null, 2)),
      ),
    ),
  );
}

createRoot(document.getElementById("root")).render(React.createElement(App));
