import React, { useEffect, useRef, useState } from "https://esm.sh/react@18.3.1";

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
    wizardHint && React.createElement("p", { style: { color: "darkorange", marginTop: 12 } }, `${wizardHint.title}: ${wizardHint.fix}`),
    React.createElement(LogPanel, { text: wizardLogs, emptyText: "Logs will appear here" }),
  );
}
