import React, { useEffect, useRef, useState } from "https://esm.sh/react@18.3.1";
import yaml from "https://esm.sh/js-yaml@4.1.0";

import { API_BASE, getJson } from "../lib/api.js";
import { startSafePolling } from "../lib/polling.js";
import { envOverridesTextToObject, lastLogLines, parseListField, redactSensitive } from "../lib/utils.js";
import { LogPanel } from "../components/LogPanel.js";

export function OnboardingView({ onRefreshData }) {
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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [trainingPresetModelId, setTrainingPresetModelId] = useState("poin_tr");
  const [trainingPresetSaveAsProfileId, setTrainingPresetSaveAsProfileId] = useState("");
  const [trainingPresetStatus, setTrainingPresetStatus] = useState("");
  const [trainingPresetFieldRows, setTrainingPresetFieldRows] = useState([]);
  const [trainingPresetForm, setTrainingPresetForm] = useState({
    profile_id: "poin_tr_training",
    name: "poin_tr Training",
    model_id: "poin_tr",
    task_type: "completion",
    image_tag: "pcpp-completion-poin_tr:gpu",
    repo_path: "./external_models/PoinTr",
    working_dir: "./external_models/PoinTr",
    default_train_script: "",
    default_train_config: "",
    default_finetune_checkpoint: "",
    finetune_checkpoint_epoch_path: "",
    finetune_config_epoch_path: "",
    finetune_config_resume_path: "",
    finetune_config_model_path: "",
    finetune_config_eval_model_path: "",
    finetune_config_save_freq_path: "",
    dataset_export_format: "completion3d_h5",
    pairing_rule: "prefix_before_delimiter",
    pairing_delimiter: "_partial_",
    config_patch_rules_text: "",
    command_template_text: "python\n{train_script_container}\n--config\n{resolved_config_path_container}",
    args_template_text: "",
    env_text: "",
    form_fields_text: "",
    modes_text: "{\"scratch\": {}, \"finetune\": {}}",
    artifacts_dir: "{run_dir}/artifacts",
    checkpoint_priority_text: "**/ckpt-best*.pth\n**/*.pth",
    checkpoint_search_roots_text: "{run_dir}\n{artifacts_dir}",
    metrics_catalog_text: "",
    recommended_curves_text: "{}",
    early_stopping_defaults_text: "{\"enabled\": false, \"metric_key\": \"validation_curve\", \"mode\": \"min\", \"patience\": 10, \"min_delta\": 0.0}",
  });
  const rollbackDoneRef = useRef(false);

  useEffect(() => {
    if (!wizardRunId) return undefined;
    return startSafePolling(async () => {
      const payload = await getJson(`/onboarding/models/runs/${wizardRunId}`);
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

  useEffect(() => {
    if (!wizardRunId) return undefined;
    return startSafePolling(async () => {
      const payload = await getJson(`/onboarding/models/runs/${wizardRunId}`);
      if (payload.kind === "smoke") {
        if (payload.status === "completed") {
          updateWizard("smoke", "success");
          await wizardRegistryCheck();
          setWizardBusy(false);
          if (onRefreshData) await onRefreshData();
          return true;
        }
        if (payload.status === "failed") {
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

  function updateWizard(step, status) {
    setWizard((prev) => ({ ...prev, [step]: status }));
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
          env_overrides: envOverridesTextToObject(onboarding.env_overrides),
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
      const payload = await getJson(`/onboarding/models/runs/${buildRunId}`);
      if (payload.status === "completed") {
        updateWizard("build", "success");
        await wizardSmoke();
        return true;
      }
      if (payload.status === "failed") {
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

  async function loadTrainingPresetByModel() {
    setTrainingPresetStatus("");
    try {
      const payload = await getJson(`/training/presets/${encodeURIComponent(trainingPresetModelId)}`);
      if (!payload?.exists) {
        const defaultPatchRules = String(trainingPresetModelId || "").toLowerCase().includes("snowflake")
          ? [
            { key: "dataset.name", value: "Completion3D" },
            { key: "dataset.category_file_path", value: "{export_category_file_path}" },
            { key: "dataset.partial_points_path", value: "{export_partial_points_path_pattern}" },
            { key: "dataset.complete_points_path", value: "{export_complete_points_path_pattern}" },
          ]
          : [
            { key: "dataset.train._base_", value: "{export_dataset_config_path}" },
            { key: "dataset.val._base_", value: "{export_dataset_config_path}" },
            { key: "dataset.test._base_", value: "{export_dataset_config_path}" },
          ];
        applyTrainingPresetPayload({
          profile_id: `${trainingPresetModelId}_training`,
          name: `${trainingPresetModelId} Training`,
          model_id: trainingPresetModelId,
          task_type: onboarding.task_type || "completion",
          image_tag: `pcpp-${onboarding.task_type || "completion"}-${trainingPresetModelId}:gpu`,
          repo_path: onboarding.repo_path || "",
          working_dir: onboarding.repo_path || "",
          form_fields: [
            { key: "partial_root", label: "Путь к обучающей выборке (partial)", required: true, default: "./data/datasets/Partial_Clouds", hint: "Папка с Partial_Clouds." },
            { key: "target_root", label: "Путь к таргетам (full)", required: true, default: "./data/datasets/Full_Clouds", hint: "Папка с Full_Clouds." },
          ],
          dataset_contract: {
            source_type: "paired_cloud_dirs",
            partial_root_key: "partial_root",
            target_root_key: "target_root",
            pairing_mode: "parent_dir_name",
            partial_delimiter: "__",
          },
          dataset_export: { format: "completion3d_h5" },
          config_patch_rules: defaultPatchRules,
        });
        setTrainingPresetStatus("Preset не найден: создан шаблон для заполнения.");
        return;
      }
      applyTrainingPresetPayload(payload.payload || {});
      setTrainingPresetStatus(`Загружен preset: ${payload.profile_id}`);
    } catch (e) {
      setTrainingPresetStatus(`Ошибка загрузки preset: ${e.message}`);
    }
  }

  async function validateTrainingPreset() {
    setTrainingPresetStatus("");
    try {
      const parsed = buildTrainingPresetPayload();
      const resp = await fetch(`${API_BASE}/training/presets/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: parsed }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || JSON.stringify(data));
      }
      setTrainingPresetStatus("Preset валиден.");
    } catch (e) {
      setTrainingPresetStatus(`Ошибка валидации preset: ${e.message}`);
    }
  }

  async function saveTrainingPreset() {
    setTrainingPresetStatus("");
    try {
      const parsed = buildTrainingPresetPayload();
      const profileId = String(parsed.profile_id || "").trim();
      if (!profileId) {
        throw new Error("profile_id обязателен");
      }
      const resp = await fetch(`${API_BASE}/training/presets/${encodeURIComponent(profileId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: parsed, overwrite: true }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || JSON.stringify(data));
      }
      setTrainingPresetStatus(`Preset сохранен: ${data.profile_id}`);
      if (onRefreshData) await onRefreshData();
    } catch (e) {
      setTrainingPresetStatus(`Ошибка сохранения preset: ${e.message}`);
    }
  }

  async function saveTrainingPresetAsNew() {
    setTrainingPresetStatus("");
    try {
      const parsed = buildTrainingPresetPayload();
      const nextProfileId = String(trainingPresetSaveAsProfileId || "").trim();
      if (!nextProfileId) {
        throw new Error("Укажите новый profile_id для клонирования.");
      }
      parsed.profile_id = nextProfileId;
      const resp = await fetch(`${API_BASE}/training/presets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: parsed, overwrite: false }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || JSON.stringify(data));
      }
      setTrainingPresetStatus(`Preset сохранен как новый: ${data.profile_id}`);
      setTrainingPresetSaveAsProfileId("");
      if (onRefreshData) await onRefreshData();
    } catch (e) {
      setTrainingPresetStatus(`Ошибка сохранения как нового: ${e.message}`);
    }
  }

  return React.createElement("div", { className: "card" },
    React.createElement("h2", null, "Добавить модель"),
    React.createElement("p", { className: "muted" }, "Перед запуском скачайте репозиторий модели и распакуйте его в папку external_models."),
    React.createElement("p", { className: "muted" }, "Scaffold шаг создает шаблонные файлы адаптера (worker/model_card/manifest/Dockerfile). Затем при необходимости подправьте entry-command и runtime.manifest под конкретную модель."),
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
    React.createElement("datalist", { id: "task-type-options" },
      React.createElement("option", { value: "completion" }),
      React.createElement("option", { value: "segmentation" }),
      React.createElement("option", { value: "meshing" }),
      React.createElement("option", { value: "classification" }),
    ),
    React.createElement("p", { className: "muted" }, "Можно выбрать из списка или ввести новый task type вручную."),
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
    React.createElement("select", {
      value: onboarding.input_data_kind,
      onChange: (e) => setOnboarding({ ...onboarding, input_data_kind: e.target.value }),
    },
    React.createElement("option", { value: "point_cloud" }, "Облако точек"),
    React.createElement("option", { value: "mesh" }, "Меш")),
    React.createElement("label", null, "Тип выходных данных"),
    React.createElement("select", {
      value: onboarding.output_data_kind,
      onChange: (e) => setOnboarding({ ...onboarding, output_data_kind: e.target.value }),
    },
    React.createElement("option", { value: "point_cloud" }, "Облако точек"),
    React.createElement("option", { value: "mesh" }, "Меш")),
    React.createElement("label", null, "Тестовый входной файл для пробного запуска"),
    React.createElement("input", {
      value: onboarding.input_path,
      onChange: (e) => setOnboarding({ ...onboarding, input_path: e.target.value }),
    }),
    React.createElement("button", { type: "button", style: { marginBottom: 8 }, onClick: () => setShowAdvanced((v) => !v) }, showAdvanced ? "Скрыть Advanced" : "Показать Advanced"),
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
    React.createElement("p", { className: "muted" }, "Можно оставить пустым: мастер сам создаст минимальный тестовый файл подходящего типа и запустит smoke-проверку."),
    React.createElement("p", { className: "muted" }, `validate: ${wizard.validate} | scaffold: ${wizard.scaffold} | build: ${wizard.build} | smoke: ${wizard.smoke} | registry: ${wizard.registry}`),
    React.createElement("button", { disabled: wizardBusy, onClick: handleWizardRun }, wizardBusy ? "Выполняется..." : "Добавить модель"),
    React.createElement("button", { style: { marginLeft: 8 }, disabled: wizardBusy, onClick: wizardValidate }, "Повторить проверку"),
    React.createElement("button", { style: { marginLeft: 8 }, disabled: wizardBusy, onClick: runPreflightScan }, "Сканировать и предложить Advanced"),
    React.createElement("button", { style: { marginLeft: 8 }, disabled: (!wizardLogs && !wizardHint) || wizardBusy, onClick: generateAiPrompt }, "Сформировать запрос для AI-помощника"),
    aiPromptText && React.createElement("div", { className: "card", style: { marginTop: 12, background: "#fafafa" } },
      React.createElement("p", { className: "muted" }, "Скопируйте текст ниже и вставьте во внешнюю нейросеть."),
      React.createElement("button", { type: "button", onClick: copyAiPrompt }, "Копировать запрос"),
      React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: generateAiPrompt }, "Обновить"),
      copyStatus && React.createElement("p", { className: "muted", style: { marginTop: 8 } }, copyStatus),
      React.createElement("textarea", {
        value: aiPromptText,
        readOnly: true,
        rows: 18,
        style: { width: "100%", marginTop: 8 },
      }),
    ),
    scanSuggestions && React.createElement("div", { className: "card", style: { marginTop: 12, background: "#fafafa" } },
      React.createElement("p", { className: "muted" }, `Preflight confidence: ${scanSuggestions.confidence || "low"}`),
      React.createElement(LogPanel, {
        text: JSON.stringify(scanSuggestions.suggested || {}, null, 2),
        emptyText: "",
        style: { maxHeight: 220, background: "transparent", padding: 0 },
      }),
      React.createElement("button", { type: "button", onClick: applyScanSuggestionsToEmpty }, "Применить только в пустые поля Advanced"),
    ),
    React.createElement("div", { className: "card", style: { marginTop: 12, background: "#fafafa" } },
      React.createElement("h3", null, "Training YAML Builder"),
      React.createElement("p", { className: "muted" }, "Отдельный конструктор training preset. Не является шагом onboarding-мастера."),
      React.createElement("label", null, "Model id (для загрузки существующего preset)"),
      React.createElement("input", {
        value: trainingPresetModelId,
        onChange: (e) => setTrainingPresetModelId(e.target.value),
      }),
      React.createElement("div", { style: { marginTop: 8, marginBottom: 8 } },
        React.createElement("button", { type: "button", onClick: loadTrainingPresetByModel }, "Загрузить/Создать шаблон"),
        React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: validateTrainingPreset }, "Проверить"),
        React.createElement("button", { type: "button", style: { marginLeft: 8 }, onClick: saveTrainingPreset }, "Сохранить"),
      ),
      React.createElement("div", { style: { marginBottom: 8 } },
        React.createElement("label", null, "Сохранить как новый profile_id"),
        React.createElement("input", {
          value: trainingPresetSaveAsProfileId,
          placeholder: "например, poin_tr_training_v2",
          onChange: (e) => setTrainingPresetSaveAsProfileId(e.target.value),
        }),
        React.createElement("button", { type: "button", style: { marginTop: 8 }, onClick: saveTrainingPresetAsNew }, "Сохранить как новый"),
      ),
      trainingPresetStatus && React.createElement("p", { className: "muted" }, trainingPresetStatus),
      React.createElement("h4", null, "Идентификация"),
      React.createElement("label", null, "model_id"),
      React.createElement("input", { value: trainingPresetForm.model_id, placeholder: "poin_tr", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, model_id: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Связь с зарегистрированной моделью."),
      React.createElement("label", null, "task_type"),
      React.createElement("input", { value: trainingPresetForm.task_type, placeholder: "completion", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, task_type: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Тип задачи модели (completion/upsampling/meshing и т.д.)."),
      React.createElement("label", null, "image_tag (опционально override)"),
      React.createElement("input", { value: trainingPresetForm.image_tag, placeholder: "если пусто, подставится автоматически", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, image_tag: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Обычно подставляется автоматически по model_id/task_type."),
      React.createElement("h4", null, "Пути запуска"),
      React.createElement("label", null, "repo_path"),
      React.createElement("input", { value: trainingPresetForm.repo_path, placeholder: "./external_models/PoinTr", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, repo_path: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Путь к репозиторию модели."),
      React.createElement("label", null, "working_dir (опционально)"),
      React.createElement("input", { value: trainingPresetForm.working_dir, placeholder: "если пусто, равен repo_path", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, working_dir: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "По умолчанию совпадает с repo_path."),
      React.createElement("label", null, "default_train_script"),
      React.createElement("input", { value: trainingPresetForm.default_train_script, placeholder: "./external_models/PoinTr/main.py", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, default_train_script: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Скрипт обучения по умолчанию."),
      React.createElement("label", null, "default_train_config"),
      React.createElement("input", { value: trainingPresetForm.default_train_config, placeholder: "./external_models/PoinTr/cfgs/train.yaml", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, default_train_config: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Конфиг обучения по умолчанию (если нужен)."),
      React.createElement("label", null, "default_finetune_checkpoint"),
      React.createElement("input", { value: trainingPresetForm.default_finetune_checkpoint, placeholder: "./external_models/PoinTr/pretrained/model.pth", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, default_finetune_checkpoint: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Checkpoint по умолчанию для finetune."),
      React.createElement("h4", null, "Команда"),
      React.createElement("p", { className: "muted" }, "Команда формируется автоматически: python + train script + --config."),
      React.createElement("h4", null, "Пользовательские параметры run"),
      trainingPresetFieldRows.map((row, idx) => React.createElement("div", { key: `ff-${idx}`, className: "card", style: { padding: 10, marginBottom: 8 } },
        React.createElement("label", null, "key"),
        React.createElement("input", { value: row.key, placeholder: "partial_root", onChange: (e) => setTrainingPresetFieldRows((prev) => prev.map((it, i) => i === idx ? { ...it, key: e.target.value } : it)) }),
        React.createElement("label", null, "label"),
        React.createElement("input", { value: row.label, placeholder: "Путь к обучающей выборке", onChange: (e) => setTrainingPresetFieldRows((prev) => prev.map((it, i) => i === idx ? { ...it, label: e.target.value } : it)) }),
        React.createElement("label", null, "default"),
        React.createElement("input", { value: row.default, placeholder: "./data/datasets/Partial_Clouds", onChange: (e) => setTrainingPresetFieldRows((prev) => prev.map((it, i) => i === idx ? { ...it, default: e.target.value } : it)) }),
        React.createElement("label", null, "hint"),
        React.createElement("input", { value: row.hint, placeholder: "Короткая подсказка к полю", onChange: (e) => setTrainingPresetFieldRows((prev) => prev.map((it, i) => i === idx ? { ...it, hint: e.target.value } : it)) }),
        React.createElement("label", { className: "checkbox-line" },
          React.createElement("input", { type: "checkbox", checked: row.required !== false, onChange: (e) => setTrainingPresetFieldRows((prev) => prev.map((it, i) => i === idx ? { ...it, required: e.target.checked } : it)) }),
          "Обязательное поле",
        ),
        React.createElement("button", { type: "button", onClick: () => setTrainingPresetFieldRows((prev) => prev.filter((_, i) => i !== idx)) }, "Удалить поле"),
      )),
      React.createElement("button", { type: "button", onClick: () => setTrainingPresetFieldRows((prev) => ([...prev, { key: "", label: "", required: true, default: "", hint: "" }])) }, "Добавить поле"),
      React.createElement("p", { className: "muted" }, "Эти поля появятся в окне запуска обучения. Для стандартного UX используйте ключи partial_root и target_root."),
      React.createElement("h4", null, "Формат датасета"),
      React.createElement("label", null, "dataset_export.format"),
      React.createElement("select", {
        value: trainingPresetForm.dataset_export_format,
        onChange: (e) => setTrainingPresetForm((p) => ({ ...p, dataset_export_format: e.target.value })),
      },
      React.createElement("option", { value: "completion3d_h5" }, "completion3d_h5"),
      ),
      React.createElement("p", { className: "muted" }, "Пока доступен один формат (v1), но блок расширяемый."),
      React.createElement("label", null, "pairing_rule"),
      React.createElement("select", {
        value: trainingPresetForm.pairing_rule,
        onChange: (e) => setTrainingPresetForm((p) => ({ ...p, pairing_rule: e.target.value })),
      },
      React.createElement("option", { value: "parent_dir_name" }, "parent_dir_name"),
      React.createElement("option", { value: "prefix_before_delimiter" }, "prefix_before_delimiter"),
      React.createElement("option", { value: "exact_stem" }, "exact_stem"),
      ),
      React.createElement("label", null, "pairing delimiter"),
      React.createElement("input", {
        value: trainingPresetForm.pairing_delimiter,
        placeholder: "__",
        onChange: (e) => setTrainingPresetForm((p) => ({ ...p, pairing_delimiter: e.target.value })),
      }),
      React.createElement("label", null, "config_patch_rules (key=value по одному в строке)"),
      React.createElement("textarea", {
        value: trainingPresetForm.config_patch_rules_text,
        rows: 5,
        placeholder: "dataset.category_file_path={export_category_file_path}\ndataset.partial_points_path={export_partial_points_path_pattern}\ndataset.complete_points_path={export_complete_points_path_pattern}",
        onChange: (e) => setTrainingPresetForm((p) => ({ ...p, config_patch_rules_text: e.target.value })),
      }),
      React.createElement("p", { className: "muted" }, "Правила патча train config после экспорта датасета."),
      React.createElement("h4", null, "Артефакты и чекпоинт"),
      React.createElement("label", null, "checkpoint_rules.priority (по одному pattern в строке)"),
      React.createElement("textarea", { value: trainingPresetForm.checkpoint_priority_text, rows: 3, placeholder: "**/ckpt-best*.pth\n**/*.pth", onChange: (e) => setTrainingPresetForm((p) => ({ ...p, checkpoint_priority_text: e.target.value })) }),
      React.createElement("p", { className: "muted" }, "Порядок выбора лучшего checkpoint."),
      React.createElement("h4", null, "Метрики"),
      React.createElement("p", { className: "muted" }, "Базовый каталог метрик и early stopping defaults будут созданы автоматически."),
      React.createElement("h4", null, "YAML Preview"),
      React.createElement("textarea", {
        value: trainingPresetPreviewText(),
        readOnly: true,
        rows: 16,
        style: { width: "100%" },
      }),
    ),
    wizardHint && React.createElement("p", { style: { color: "darkorange", marginTop: 12 } }, `${wizardHint.title}: ${wizardHint.fix}`),
    React.createElement(LogPanel, { text: wizardLogs, emptyText: "Logs will appear here" }),
  );

  function parseJsonObject(text, fallback) {
    const raw = String(text || "").trim();
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    throw new Error("Ожидается JSON-объект.");
  }

  function parseJsonArray(text, fallback) {
    const raw = String(text || "").trim();
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed;
    throw new Error("Ожидается JSON-массив.");
  }

  function parseKeyValueLines(text) {
    const out = {};
    const lines = String(text || "").split("\n").map((line) => line.trim()).filter(Boolean);
    for (const line of lines) {
      const idx = line.indexOf("=");
      if (idx <= 0) throw new Error(`Неверный формат env: ${line}. Ожидается KEY=VALUE.`);
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim();
      if (!key) throw new Error(`Пустой ключ в env: ${line}`);
      out[key] = value;
    }
    return out;
  }

  function linesToArray(text) {
    return String(text || "").split("\n").map((line) => line.trim()).filter(Boolean);
  }

  function inferTrainingDefaults(modelIdRaw) {
    const modelId = String(modelIdRaw || "").trim().toLowerCase();
    if (modelId === "snowflake") {
      return {
        finetune_contract: {
          checkpoint_epoch_path: "epoch_index",
          config_epoch_path: "train.epochs",
          config_resume_path: "train.resume",
          config_model_path: "train.model_path",
          config_eval_model_path: "test.model_path",
          config_save_freq_path: "train.save_freq",
        },
        config_patch_rules: [
          { key: "dataset.name", value: "Completion3D" },
          { key: "dataset.category_file_path", value: "{export_category_file_path}" },
          { key: "dataset.partial_points_path", value: "{export_partial_points_path_pattern}" },
          { key: "dataset.complete_points_path", value: "{export_complete_points_path_pattern}" },
          { key: "train.out_path", value: "{artifacts_dir_container}" },
        ],
        metrics_catalog: [
          {
            key: "train_curve",
            label: "Train curve",
            role: "train",
            direction: "min",
            default_tag: "Loss/Epoch/cd_p3",
            preferred_tag_patterns: ["loss/epoch/cd_p3", "loss/epoch/loss_3"],
            default_slot: "primary",
          },
          {
            key: "validation_curve",
            label: "Validation curve",
            role: "val",
            direction: "min",
            default_tag: "Metric/cd_l2",
            preferred_tag_patterns: ["metric/cd", "loss/epoch/loss_3"],
            default_slot: "secondary",
          },
        ],
        native_extensions: [],
      };
    }
    if (modelId === "poin_tr") {
      return {
        finetune_contract: {
          checkpoint_epoch_path: "epoch",
          config_epoch_path: "max_epoch",
          epoch_target_mode: "relative",
          config_resume_path: "resume",
          config_model_path: "start_ckpts",
          cli_checkpoint_arg: "--start_ckpts",
          resume_via_experiment: true,
          cli_resume_arg: "--resume",
          config_eval_model_path: "",
          config_save_freq_path: "",
        },
        config_patch_rules: [
          { key: "dataset.train._base_", value: "{export_dataset_config_path}" },
          { key: "dataset.val._base_", value: "{export_dataset_config_path}" },
          { key: "dataset.test._base_", value: "{export_dataset_config_path}" },
          { key: "dataset.train.others.subset", value: "train" },
          { key: "dataset.val.others.subset", value: "val" },
          { key: "dataset.test.others.subset", value: "test" },
        ],
        metrics_catalog: [
          {
            key: "train_curve",
            label: "Train curve",
            role: "train",
            direction: "min",
            default_tag: "Loss/Epoch/Dense",
            preferred_tag_patterns: ["loss/epoch/dense", "loss/epoch"],
            default_slot: "primary",
          },
          {
            key: "validation_curve",
            label: "Validation curve",
            role: "val",
            direction: "min",
            default_tag: "Metric/CDL2",
            preferred_tag_patterns: ["metric/cdl2", "metric/cd"],
            default_slot: "secondary",
          },
        ],
        native_extensions: [
          {
            name: "chamfer",
            module_dir: "./external_models/PoinTr/extensions/chamfer_dist",
            artifact_glob: "chamfer*.so",
            build: ["python", "setup.py", "build_ext", "--inplace"],
          },
          {
            name: "emd",
            module_dir: "./external_models/PoinTr/extensions/emd",
            artifact_glob: "emd*.so",
            build: ["python", "setup.py", "build_ext", "--inplace"],
          },
          {
            name: "gridding",
            module_dir: "./external_models/PoinTr/extensions/gridding",
            artifact_glob: "gridding*.so",
            build: ["python", "setup.py", "build_ext", "--inplace"],
          },
          {
            name: "gridding_loss",
            module_dir: "./external_models/PoinTr/extensions/gridding_loss",
            artifact_glob: "gridding*.so",
            build: ["python", "setup.py", "build_ext", "--inplace"],
          },
          {
            name: "cubic_feature_sampling",
            module_dir: "./external_models/PoinTr/extensions/cubic_feature_sampling",
            artifact_glob: "cubic_feature_sampling*.so",
            build: ["python", "setup.py", "build_ext", "--inplace"],
          },
        ],
      };
    }
    return {
      finetune_contract: {
        checkpoint_epoch_path: "",
        config_epoch_path: "",
        config_resume_path: "",
        config_model_path: "",
        config_eval_model_path: "",
        config_save_freq_path: "",
      },
      config_patch_rules: [],
      metrics_catalog: [
        { key: "train_curve", label: "Train curve", role: "train", direction: "min", default_tag: "train/loss", default_slot: "primary" },
        { key: "validation_curve", label: "Validation curve", role: "val", direction: "min", default_tag: "val/loss", default_slot: "secondary" },
      ],
      native_extensions: [],
    };
  }

  function buildTrainingPresetPayload() {
    const normalizedModelId = String(trainingPresetForm.model_id || trainingPresetModelId || onboarding.model_id || "").trim();
    const normalizedTaskType = String(trainingPresetForm.task_type || onboarding.task_type || "completion").trim();
    const normalizedProfileId = `${normalizedModelId}_training`;
    const normalizedName = `${normalizedModelId} Training`;
    const normalizedRepoPath = String(trainingPresetForm.repo_path || onboarding.repo_path || "").trim();
    const normalizedWorkingDir = String(trainingPresetForm.working_dir || normalizedRepoPath || "").trim();
    const inferredDefaults = inferTrainingDefaults(normalizedModelId);
    const checkpointEpochPath = String(trainingPresetForm.finetune_checkpoint_epoch_path || inferredDefaults.finetune_contract.checkpoint_epoch_path || "").trim();
    const configEpochPath = String(trainingPresetForm.finetune_config_epoch_path || inferredDefaults.finetune_contract.config_epoch_path || "").trim();
    const configResumePath = String(trainingPresetForm.finetune_config_resume_path || inferredDefaults.finetune_contract.config_resume_path || "").trim();
    const configModelPath = String(trainingPresetForm.finetune_config_model_path || inferredDefaults.finetune_contract.config_model_path || "").trim();
    const configEvalModelPath = String(trainingPresetForm.finetune_config_eval_model_path || inferredDefaults.finetune_contract.config_eval_model_path || "").trim();
    const configSaveFreqPath = String(trainingPresetForm.finetune_config_save_freq_path || inferredDefaults.finetune_contract.config_save_freq_path || "").trim();
    const derivedFormFields = trainingPresetFieldRows
      .map((item) => ({
        key: String(item.key || "").trim(),
        label: String(item.label || "").trim(),
        required: item.required !== false,
        default: String(item.default || "").trim(),
        hint: String(item.hint || "").trim(),
      }))
      .filter((item) => item.key);
    const userPatchRules = linesToArray(trainingPresetForm.config_patch_rules_text)
      .map((line) => {
        const idx = line.indexOf("=");
        if (idx <= 0) return null;
        return {
          key: line.slice(0, idx).trim(),
          value: line.slice(idx + 1).trim(),
        };
      })
      .filter(Boolean);
    const mergedPatchRulesByKey = new Map();
    for (const item of (inferredDefaults.config_patch_rules || [])) {
      const key = String(item?.key || "").trim();
      const value = String(item?.value || "").trim();
      if (!key || !value) continue;
      mergedPatchRulesByKey.set(key, { key, value });
    }
    for (const item of userPatchRules) {
      const key = String(item?.key || "").trim();
      const value = String(item?.value || "").trim();
      if (!key || !value) continue;
      mergedPatchRulesByKey.set(key, { key, value });
    }
    const payload = {
      profile_id: normalizedProfileId,
      name: normalizedName,
      model_id: normalizedModelId,
      task_type: normalizedTaskType,
      image_tag: String(trainingPresetForm.image_tag || `pcpp-${normalizedTaskType}-${normalizedModelId}:gpu`).trim(),
      repo_path: normalizedRepoPath,
      working_dir: normalizedWorkingDir,
      default_train_script: String(trainingPresetForm.default_train_script || "").trim(),
      default_train_config: String(trainingPresetForm.default_train_config || "").trim(),
      default_finetune_checkpoint: String(trainingPresetForm.default_finetune_checkpoint || "").trim(),
      dataset_contract: {
        source_type: "paired_cloud_dirs",
        partial_root_key: "partial_root",
        target_root_key: "target_root",
        pairing_mode: String(trainingPresetForm.pairing_rule || "prefix_before_delimiter").trim(),
        partial_delimiter: String(trainingPresetForm.pairing_delimiter || "_partial_").trim(),
      },
      dataset_export: {
        format: String(trainingPresetForm.dataset_export_format || "completion3d_h5").trim() || "completion3d_h5",
      },
      config_patch_rules: Array.from(mergedPatchRulesByKey.values()),
      command_template: ["python", "{train_script_container}", "--config", "{resolved_config_path_container}"],
      args_template: [],
      env: {},
      form_fields: derivedFormFields,
      modes: { scratch: {}, finetune: {} },
      finetune_contract: {
        checkpoint_epoch_path: checkpointEpochPath,
        config_epoch_path: configEpochPath,
        epoch_target_mode: String(inferredDefaults?.finetune_contract?.epoch_target_mode || "relative").trim(),
        config_resume_path: configResumePath,
        config_model_path: configModelPath,
        cli_checkpoint_arg: String(inferredDefaults?.finetune_contract?.cli_checkpoint_arg || "").trim(),
        resume_via_experiment: Boolean(inferredDefaults?.finetune_contract?.resume_via_experiment),
        cli_resume_arg: String(inferredDefaults?.finetune_contract?.cli_resume_arg || "").trim(),
        config_eval_model_path: configEvalModelPath,
        config_save_freq_path: configSaveFreqPath,
      },
      artifacts_dir: "{run_dir}/artifacts",
      checkpoint_rules: {
        priority: linesToArray(trainingPresetForm.checkpoint_priority_text),
        search_roots: (() => {
          const roots = linesToArray(trainingPresetForm.checkpoint_search_roots_text);
          return roots.length > 0 ? roots : ["{run_dir}", "{artifacts_dir}"];
        })(),
      },
      metrics_catalog: inferredDefaults.metrics_catalog,
      native_extensions: Array.isArray(inferredDefaults.native_extensions) ? inferredDefaults.native_extensions : [],
      recommended_curves: { primary: "train_curve", secondary: "validation_curve" },
      early_stopping_defaults: { enabled: false, metric_key: "validation_curve", mode: "min", patience: 10, min_delta: 0.0 },
      geometry_normalization_supported: true,
      geometry_normalization_default: true,
    };
    if (!payload.default_train_script) delete payload.default_train_script;
    if (!payload.default_train_config) delete payload.default_train_config;
    if (!payload.default_finetune_checkpoint) delete payload.default_finetune_checkpoint;
    if (!payload.finetune_contract.checkpoint_epoch_path || !payload.finetune_contract.config_epoch_path) {
      delete payload.finetune_contract;
    }
    return payload;
  }

  function applyTrainingPresetPayload(payload) {
    const safe = payload || {};
    const sourceFields = (Array.isArray(safe.form_fields) && safe.form_fields.length > 0)
      ? safe.form_fields
      : [
        { key: "partial_root", label: "Путь к обучающей выборке (partial)", required: true, default: "./data/datasets/Partial_Clouds", hint: "Папка с Partial_Clouds." },
        { key: "target_root", label: "Путь к таргетам (full)", required: true, default: "./data/datasets/Full_Clouds", hint: "Папка с Full_Clouds." },
      ];
    setTrainingPresetFieldRows(sourceFields.map((field) => ({
      key: String(field?.key || ""),
      label: String(field?.label || ""),
      required: field?.required !== false,
      default: String(field?.default || ""),
      hint: String(field?.hint || ""),
    })));
    setTrainingPresetForm({
      profile_id: String(safe.profile_id || `${trainingPresetModelId}_training`),
      name: String(safe.name || `${trainingPresetModelId} Training`),
      model_id: String(safe.model_id || trainingPresetModelId),
      task_type: String(safe.task_type || onboarding.task_type || "completion"),
      image_tag: String(safe.image_tag || `pcpp-${onboarding.task_type || "completion"}-${trainingPresetModelId}:gpu`),
      repo_path: String(safe.repo_path || onboarding.repo_path || ""),
      working_dir: String(safe.working_dir || onboarding.repo_path || ""),
      default_train_script: String(safe.default_train_script || ""),
      default_train_config: String(safe.default_train_config || ""),
      default_finetune_checkpoint: String(safe.default_finetune_checkpoint || ""),
      finetune_checkpoint_epoch_path: String(safe?.finetune_contract?.checkpoint_epoch_path || inferTrainingDefaults(safe.model_id || trainingPresetModelId).finetune_contract.checkpoint_epoch_path || ""),
      finetune_config_epoch_path: String(safe?.finetune_contract?.config_epoch_path || inferTrainingDefaults(safe.model_id || trainingPresetModelId).finetune_contract.config_epoch_path || ""),
      finetune_config_resume_path: String(safe?.finetune_contract?.config_resume_path || inferTrainingDefaults(safe.model_id || trainingPresetModelId).finetune_contract.config_resume_path || ""),
      finetune_config_model_path: String(safe?.finetune_contract?.config_model_path || inferTrainingDefaults(safe.model_id || trainingPresetModelId).finetune_contract.config_model_path || ""),
      finetune_config_eval_model_path: String(safe?.finetune_contract?.config_eval_model_path || inferTrainingDefaults(safe.model_id || trainingPresetModelId).finetune_contract.config_eval_model_path || ""),
      finetune_config_save_freq_path: String(safe?.finetune_contract?.config_save_freq_path || inferTrainingDefaults(safe.model_id || trainingPresetModelId).finetune_contract.config_save_freq_path || ""),
      dataset_export_format: String(safe?.dataset_export?.format || "completion3d_h5"),
      pairing_rule: String(safe?.dataset_contract?.pairing_mode || "prefix_before_delimiter"),
      pairing_delimiter: String(safe?.dataset_contract?.partial_delimiter || "_partial_"),
      config_patch_rules_text: Array.isArray(safe?.config_patch_rules)
        ? safe.config_patch_rules
          .map((item) => `${String(item?.key || "").trim()}=${String(item?.value || "").trim()}`)
          .filter(Boolean)
          .join("\n")
        : "",
      command_template_text: "",
      args_template_text: "",
      env_text: "",
      form_fields_text: "",
      modes_text: "",
      artifacts_dir: String(safe.artifacts_dir || "{run_dir}/artifacts"),
      checkpoint_priority_text: Array.isArray(safe?.checkpoint_rules?.priority) ? safe.checkpoint_rules.priority.join("\n") : "**/ckpt-best*.pth\n**/*.pth",
      checkpoint_search_roots_text: Array.isArray(safe?.checkpoint_rules?.search_roots)
        ? safe.checkpoint_rules.search_roots.join("\n")
        : "{run_dir}\n{artifacts_dir}",
      metrics_catalog_text: "",
      recommended_curves_text: "",
      early_stopping_defaults_text: "",
    });
  }

  function trainingPresetPreviewText() {
    try {
      return yaml.dump(buildTrainingPresetPayload(), { noRefs: true, lineWidth: 120 });
    } catch (e) {
      return `Ошибка формирования preview: ${e.message}`;
    }
  }
}
