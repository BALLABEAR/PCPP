import React, { useEffect, useMemo, useState } from "https://esm.sh/react@18.3.1";

import { getJson, postJson } from "../lib/api.js?v=20260508b";
import { startSafePolling } from "../lib/polling.js?v=20260508b";
import { LogPanel } from "../components/LogPanel.js?v=20260508b";
import { MetricChart } from "../components/MetricChart.js?v=20260508b";
import {
  ActionBar,
  CollapsibleSection,
  Field,
  InlineHint,
  SectionCard,
  StatusBadge,
} from "../components/UiPrimitives.js?v=20260508b";

function normalizeWorkspacePath(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.startsWith("./") || text.startsWith("/")) return text;
  if (text.startsWith("training_runs/") || text.startsWith("external_models/") || text.startsWith("data/")) {
    return `./${text}`;
  }
  return text;
}

function toContainerPath(value) {
  const text = normalizeWorkspacePath(value);
  if (!text) return "";
  if (text.startsWith("/app/")) return text;
  if (text.startsWith("./")) return `/app/${text.slice(2)}`;
  return text;
}

function buildEarlyStoppingDefaults(profile) {
  const defaults = profile?.early_stopping_defaults || {};
  const metricKey = String(defaults.metric_key || "validation_curve");
  return {
    early_stopping_enabled: Boolean(defaults.enabled),
    early_stopping_metric_key: metricKey,
    early_stopping_patience: Number.parseInt(String(defaults.patience ?? 10), 10) || 10,
    early_stopping_min_delta: Number.parseFloat(String(defaults.min_delta ?? 0)) || 0,
  };
}

function buildDatasetDefaults(profile) {
  const datasetValues = {};
  const fields = Array.isArray(profile?.form_fields) ? profile.form_fields : [];
  for (const field of fields) {
    const key = String(field?.key || "").trim();
    if (!key) continue;
    datasetValues[key] = String(field?.default || "");
  }
  return datasetValues;
}

function buildInitialTrainingForm(trainingProfiles) {
  const profile = trainingProfiles[0] || null;
  const supportedModes = Array.isArray(profile?.supported_modes) ? profile.supported_modes : [];
  return {
    profile_id: profile?.profile_id || "",
    form_values: {
      partial_root: "./data/datasets",
      target_root: "./data/datasets",
      ...buildDatasetDefaults(profile),
    },
    finetune_epochs: Number.parseInt(String(profile?.finetune_defaults?.default_epochs ?? 50), 10) || 50,
    train_percent: 80,
    val_percent: 10,
    test_percent: 10,
    mode: supportedModes.includes("scratch") ? "scratch" : (supportedModes[0] || "scratch"),
    train_script_override: "",
    config_path_override: "",
    checkpoint_override: "",
    use_gpu: true,
    geometry_normalization: Boolean(profile?.geometry_normalization_default ?? true),
    ...buildEarlyStoppingDefaults(profile),
  };
}

function resolveAutomaticCurveTags(resolvedMetricViews, metricsCatalog, availableMetricTags) {
  const tags = Array.isArray(availableMetricTags) ? availableMetricTags.filter(Boolean) : [];
  const byKey = resolvedMetricViews || {};
  const catalog = Array.isArray(metricsCatalog) ? metricsCatalog : [];

  const primaryResolved = String(byKey?.primary?.resolved_tag || byKey?.train_curve?.resolved_tag || "").trim();
  const secondaryResolved = String(byKey?.secondary?.resolved_tag || byKey?.validation_curve?.resolved_tag || "").trim();
  if (primaryResolved || secondaryResolved) {
    return [primaryResolved, secondaryResolved].filter(Boolean);
  }

  const roleCandidates = [];
  const trainItem = catalog.find((item) => item?.role === "train" || item?.key === "train_curve");
  const validationItem = catalog.find((item) => item?.role === "val" || item?.role === "test" || item?.key === "validation_curve");
  const trainResolved = String(byKey?.[trainItem?.key || ""]?.resolved_tag || "").trim();
  const validationResolved = String(byKey?.[validationItem?.key || ""]?.resolved_tag || "").trim();
  if (trainResolved) roleCandidates.push(trainResolved);
  if (validationResolved && validationResolved !== trainResolved) roleCandidates.push(validationResolved);
  if (roleCandidates.length > 0) {
    return roleCandidates.slice(0, 2);
  }

  const epochOrMetric = tags.filter((tag) => {
    const lower = String(tag || "").toLowerCase();
    return lower.includes("/epoch/") || lower.startsWith("metric/");
  });
  return (epochOrMetric.length > 0 ? epochOrMetric : tags).slice(0, 2);
}

function statusTone(status) {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "warning";
  if (status === "running") return "warning";
  return "neutral";
}

function renderStatTile(label, value) {
  return React.createElement("div", { className: "stat-tile" },
    React.createElement("span", { className: "stat-tile__label" }, label),
    React.createElement("span", { className: "stat-tile__value" }, value),
  );
}

function renderEarlyHint(currentEarlyState) {
  if (!currentEarlyState) return null;
  const props = currentEarlyState.stopped_early ? { tone: "warning" } : {};
  const text = currentEarlyState.stopped_early
    ? (currentEarlyState.stop_reason || "Обучение остановлено по early stopping.")
    : currentEarlyState.monitor_metric
      ? `Мониторимая метрика: ${currentEarlyState.monitor_metric}. Bad epochs: ${currentEarlyState.bad_epochs || 0}.`
      : "Early stopping пока не активен.";
  return React.createElement(InlineHint, props, text);
}

function lastMetricPoint(points) {
  if (!Array.isArray(points) || points.length === 0) return null;
  return points[points.length - 1] || null;
}

export function TrainingView({ trainingProfiles }) {
  const [trainingRunId, setTrainingRunId] = useState("");
  const [trainingRun, setTrainingRun] = useState(null);
  const [trainingMetrics, setTrainingMetrics] = useState(null);
  const [trainingLogs, setTrainingLogs] = useState("");
  const [trainingBusy, setTrainingBusy] = useState(false);
  const [trainingCancelBusy, setTrainingCancelBusy] = useState(false);
  const [trainingError, setTrainingError] = useState("");
  const [trainingCopyStatus, setTrainingCopyStatus] = useState("");
  const [trainingForm, setTrainingForm] = useState(() => buildInitialTrainingForm(trainingProfiles));

  const readyTrainingProfiles = useMemo(() => trainingProfiles.filter((profile) => profile.registered), [trainingProfiles]);
  const selectedTrainingProfile = useMemo(
    () => trainingProfiles.find((profile) => profile.profile_id === trainingForm.profile_id) || null,
    [trainingProfiles, trainingForm.profile_id],
  );
  const normalizedCheckpointPath = useMemo(() => normalizeWorkspacePath(trainingRun?.best_checkpoint_path), [trainingRun]);
  const pipelineCheckpointPath = useMemo(() => String(trainingRun?.best_checkpoint_pipeline_path || "").trim(), [trainingRun]);
  const trainingWeightsHint = useMemo(() => {
    const path = pipelineCheckpointPath || (normalizedCheckpointPath ? toContainerPath(normalizedCheckpointPath) : "");
    return path ? `weights_path=${path}` : "";
  }, [normalizedCheckpointPath, pipelineCheckpointPath]);
  const availableMetricTags = useMemo(
    () => trainingMetrics?.available_metric_tags || trainingRun?.available_metric_tags || [],
    [trainingMetrics, trainingRun],
  );
  const resolvedMetricViews = useMemo(
    () => trainingMetrics?.resolved_metric_views || trainingRun?.resolved_metric_views || {},
    [trainingMetrics, trainingRun],
  );
  const metricsCatalog = useMemo(
    () => trainingMetrics?.metrics_catalog || trainingRun?.metrics_catalog || selectedTrainingProfile?.metrics_catalog || [],
    [trainingMetrics, trainingRun, selectedTrainingProfile],
  );
  const metricSeries = useMemo(() => trainingMetrics?.metric_series || {}, [trainingMetrics]);
  const automaticCurveTags = useMemo(
    () => resolveAutomaticCurveTags(resolvedMetricViews, metricsCatalog, availableMetricTags),
    [resolvedMetricViews, metricsCatalog, availableMetricTags],
  );
  const currentEarlyState = trainingMetrics?.early_stopping_state || trainingRun?.early_stopping_state || null;
  const selectedModeOptions = useMemo(
    () => (Array.isArray(selectedTrainingProfile?.supported_modes) ? selectedTrainingProfile.supported_modes : []),
    [selectedTrainingProfile],
  );
  const datasetFields = useMemo(() => {
    const configured = Array.isArray(selectedTrainingProfile?.form_fields) ? selectedTrainingProfile.form_fields : [];
    const byKey = new Map(configured.map((item) => [String(item?.key || "").trim(), item]));
    const defaults = [
      {
        key: "partial_root",
        label: "Путь к обучающей выборке (partial)",
        required: true,
        default: "./data/datasets",
        placeholder: "./data/datasets",
        hint: "Корень датасета со split train/val/test.",
      },
      {
        key: "target_root",
        label: "Путь к таргетам (full)",
        required: true,
        default: "./data/datasets",
        placeholder: "./data/datasets",
        hint: "Обычно тот же корень; target берутся из подпапки gt/full.",
      },
    ];
    return defaults.map((item) => ({ ...item, ...(byKey.get(item.key) || {}) }));
  }, [selectedTrainingProfile]);
  const resolvedEarlyMetric = useMemo(() => {
    const metricKey = String(trainingForm.early_stopping_metric_key || "validation_curve");
    const metricItem = metricsCatalog.find((item) => String(item?.key || "") === metricKey) || null;
    return String(metricItem?.default_tag || "");
  }, [metricsCatalog, trainingForm.early_stopping_metric_key]);
  const liveMetricRows = useMemo(() => {
    const roleMap = {
      [String(resolvedMetricViews?.primary?.resolved_tag || "")]: String(resolvedMetricViews?.primary?.role || ""),
      [String(resolvedMetricViews?.secondary?.resolved_tag || "")]: String(resolvedMetricViews?.secondary?.role || ""),
      [String(resolvedMetricViews?.train_curve?.resolved_tag || "")]: String(resolvedMetricViews?.train_curve?.role || ""),
      [String(resolvedMetricViews?.validation_curve?.resolved_tag || "")]: String(resolvedMetricViews?.validation_curve?.role || ""),
    };
    return automaticCurveTags.map((tag, index) => {
      const point = lastMetricPoint(metricSeries?.[tag]);
      if (!point) return null;
      const role = String(roleMap[tag] || "");
      const label = role === "train" ? "Train" : (role === "val" || role === "test" ? "Validation" : (index === 0 ? "Train" : "Validation"));
      const step = point.step ?? "n/a";
      const value = Number(point.value);
      return {
        key: tag,
        label,
        tag,
        step,
        value: Number.isFinite(value) ? value.toFixed(6) : String(point.value),
      };
    }).filter(Boolean);
  }, [automaticCurveTags, metricSeries]);

  useEffect(() => {
    if (!trainingForm.profile_id && trainingProfiles[0]?.profile_id) {
      setTrainingForm(buildInitialTrainingForm(trainingProfiles));
    }
  }, [trainingForm.profile_id, trainingProfiles]);

  useEffect(() => {
    if (!trainingRunId) return undefined;
    return startSafePolling(async () => {
      const runPayload = await getJson(`/training/runs/${trainingRunId}`);
      const metricsPayload = await getJson(`/training/runs/${trainingRunId}/metrics`);
      setTrainingRun(runPayload);
      setTrainingMetrics(metricsPayload);
      setTrainingLogs(runPayload.logs || "");
      if (runPayload.status === "completed" || runPayload.status === "failed" || runPayload.status === "cancelled") {
        setTrainingBusy(false);
        setTrainingCancelBusy(false);
        return true;
      }
      return false;
    }, 2000, (e) => {
      setTrainingBusy(false);
      setTrainingCancelBusy(false);
      setTrainingLogs(`Failed to poll training logs: ${e.message}`);
    });
  }, [trainingRunId]);

  async function handleTrainingStart() {
    setTrainingError("");
    setTrainingCopyStatus("");
    setTrainingRun(null);
    setTrainingMetrics(null);
    setTrainingLogs("");
    setTrainingBusy(true);
    try {
      const payload = await postJson("/training/runs", {
        ...trainingForm,
        early_stopping_metric: resolvedEarlyMetric,
      });
      setTrainingRun(payload);
      setTrainingLogs(payload.logs || "");
      setTrainingRunId(payload.run_id);
    } catch (e) {
      setTrainingBusy(false);
      setTrainingError(`Training start failed: ${e.message}`);
    }
  }

  async function copyTrainingWeightsPath() {
    if (!trainingWeightsHint) return;
    try {
      await navigator.clipboard.writeText(trainingWeightsHint);
      setTrainingCopyStatus("Скопировано");
    } catch (e) {
      setTrainingCopyStatus("Не удалось скопировать. Скопируйте путь вручную.");
    }
  }

  async function handleTrainingCancel() {
    if (!trainingRunId || trainingCancelBusy) return;
    setTrainingCancelBusy(true);
    setTrainingError("");
    try {
      await postJson(`/training/runs/${trainingRunId}/cancel`, {});
      const runPayload = await getJson(`/training/runs/${trainingRunId}`);
      setTrainingRun(runPayload);
      setTrainingLogs(runPayload.logs || "");
      if (runPayload.status === "cancelled" || runPayload.status === "failed" || runPayload.status === "completed") {
        setTrainingBusy(false);
        setTrainingCancelBusy(false);
      }
    } catch (e) {
      setTrainingCancelBusy(false);
      setTrainingError(`Training cancel failed: ${e.message}`);
    }
  }

  function handleProfileChange(nextProfileId) {
    const profile = trainingProfiles.find((item) => item.profile_id === nextProfileId) || null;
    const supportedModes = Array.isArray(profile?.supported_modes) ? profile.supported_modes : [];
    setTrainingForm((prev) => ({
      ...prev,
      profile_id: nextProfileId,
      form_values: {
        partial_root: "./data/datasets",
        target_root: "./data/datasets",
        ...buildDatasetDefaults(profile),
      },
      finetune_epochs: Number.parseInt(String(profile?.finetune_defaults?.default_epochs ?? 50), 10) || 50,
      train_percent: 80,
      val_percent: 10,
      test_percent: 10,
      mode: supportedModes.includes(prev.mode) ? prev.mode : (supportedModes.includes("scratch") ? "scratch" : (supportedModes[0] || "scratch")),
      train_script_override: "",
      config_path_override: "",
      checkpoint_override: "",
      geometry_normalization: Boolean(profile?.geometry_normalization_default ?? true),
      ...buildEarlyStoppingDefaults(profile),
    }));
  }

  const splitValid = true;

  const canStart = !trainingBusy
    && Boolean(trainingForm.profile_id)
    && Boolean(selectedTrainingProfile?.ready)
    && splitValid
    && (!trainingForm.early_stopping_enabled || Boolean(String(resolvedEarlyMetric || "").trim()));
  const canCancel = Boolean(trainingRunId)
    && !trainingCancelBusy
    && (trainingRun?.status === "running" || trainingRun?.status === "pending" || trainingBusy);

  const header = React.createElement("div", { className: "section-card__header" },
    React.createElement("div", null,
      React.createElement("h2", null, "Обучение моделей"),
      React.createElement("p", { className: "section-card__subtitle" }, "Соберите run слева, а справа следите за статусом, early stopping, графиками и итоговым checkpoint."),
    ),
    React.createElement("div", { className: "status-stack" },
      selectedTrainingProfile && React.createElement(StatusBadge, { tone: selectedTrainingProfile.ready ? "success" : "warning" }, selectedTrainingProfile.ready ? "Готово к обучению" : "Нужен build/smoke"),
      trainingRun && React.createElement(StatusBadge, { tone: statusTone(trainingRun.status) }, `Run: ${trainingRun.status}`),
    ),
  );

  if (readyTrainingProfiles.length === 0) {
    return React.createElement("div", { className: "card" },
      header,
      React.createElement(InlineHint, { tone: "warning" }, "Training-enabled моделей пока нет. Нужен training preset и зарегистрированная модель."),
    );
  }

  const trainingSection = React.createElement(SectionCard, {
    title: "Training",
    subtitle: "Выберите профиль и базовый режим запуска.",
  },
  React.createElement(Field, { label: "Модель / training profile" },
    React.createElement("select", {
      value: trainingForm.profile_id,
      onChange: (e) => handleProfileChange(e.target.value),
    },
    readyTrainingProfiles.map((profile) => React.createElement("option", { key: profile.profile_id, value: profile.profile_id }, `${profile.name} (${profile.model_id})`)),
    ),
  ),
  selectedTrainingProfile?.default_train_config && React.createElement(InlineHint, null, `Default config: ${selectedTrainingProfile.default_train_config}`),
  React.createElement("div", { className: "split-grid", style: { marginTop: 14 } },
    React.createElement(Field, { label: "Режим обучения", compact: true },
      React.createElement("select", {
        value: trainingForm.mode,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, mode: e.target.value })),
      },
      selectedModeOptions.map((mode) => React.createElement("option", { key: mode, value: mode }, mode === "finetune" ? "Дообучение" : "Обучение с нуля")),
      ),
    ),
    React.createElement(Field, { label: "GPU", compact: true },
      React.createElement("label", { className: "checkbox-line" },
        React.createElement("input", {
          type: "checkbox",
          checked: trainingForm.use_gpu,
          onChange: (e) => setTrainingForm((prev) => ({ ...prev, use_gpu: e.target.checked })),
        }),
        "Использовать GPU",
      ),
    ),
    trainingForm.mode === "finetune" && React.createElement(Field, { label: "Эпох дообучения", compact: true },
      React.createElement("input", {
        type: "number",
        min: 1,
        value: trainingForm.finetune_epochs,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, finetune_epochs: Number.parseInt(e.target.value || "1", 10) || 1 })),
      }),
    ),
    React.createElement(Field, { label: "Нормализация", compact: true },
      React.createElement("label", { className: "checkbox-line" },
        React.createElement("input", {
          type: "checkbox",
          checked: Boolean(trainingForm.geometry_normalization),
          disabled: selectedTrainingProfile?.geometry_normalization_supported === false,
          onChange: (e) => setTrainingForm((prev) => ({ ...prev, geometry_normalization: e.target.checked })),
        }),
        "Нормализовать геометрию",
      ),
    ),
  ),
  React.createElement(InlineHint, null, "Split временно фиксирован: 80/10/10 (ручной ввод отключен)."),
  );

  const datasetSection = React.createElement(SectionCard, {
    title: "Dataset",
    subtitle: "Укажите путь к partial и путь к target.",
  },
  ...datasetFields.map((field) => {
    const key = String(field?.key || "").trim();
    const value = String(trainingForm.form_values?.[key] || "");
    const label = String(field?.label || key);
    const hint = field?.hint ? String(field.hint) : undefined;
    const placeholder = String(field?.placeholder || "");
    if (Array.isArray(field?.options) && field.options.length > 0) {
      return React.createElement(Field, { key, label, hint },
        React.createElement("select", {
          value,
          onChange: (e) => setTrainingForm((prev) => ({
            ...prev,
            form_values: { ...(prev.form_values || {}), [key]: e.target.value },
          })),
        },
        field.options.map((option) => {
          const optionValue = typeof option === "string" ? option : String(option?.value || "");
          const optionLabel = typeof option === "string" ? option : String(option?.label || optionValue);
          return React.createElement("option", { key: `${key}-${optionValue}`, value: optionValue }, optionLabel);
        })),
      );
    }
    return React.createElement(Field, { key, label, hint },
      React.createElement("input", {
        value,
        onChange: (e) => setTrainingForm((prev) => ({
          ...prev,
          form_values: { ...(prev.form_values || {}), [key]: e.target.value },
        })),
        placeholder,
      }),
    );
  }),
  React.createElement(InlineHint, null, selectedTrainingProfile?.dataset_structure_hint || "Partial одного target остаются в одном split."),
  selectedTrainingProfile?.geometry_normalization_supported === false
    ? React.createElement(InlineHint, { tone: "warning" }, "Для этого training profile нормализация геометрии отключена в preset.")
    : null);

  const advancedChildren = [
    React.createElement(Field, { key: "train-script", label: "Train script override", hint: "Обычно оставляют пустым." },
      React.createElement("input", {
        value: trainingForm.train_script_override,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, train_script_override: e.target.value })),
        placeholder: selectedTrainingProfile?.default_train_script || "./external_models/SnowflakeNet/completion/train.py",
      }),
    ),
  ];

  if (selectedTrainingProfile?.supports_config_override !== false) {
    advancedChildren.push(
      React.createElement(Field, { key: "config", label: "Config override", hint: "Например, альтернативный train config." },
        React.createElement("input", {
          value: trainingForm.config_path_override,
          onChange: (e) => setTrainingForm((prev) => ({ ...prev, config_path_override: e.target.value })),
          placeholder: selectedTrainingProfile?.default_train_config || "",
        }),
      ),
    );
  }

  if (trainingForm.mode === "finetune") {
    advancedChildren.push(
      React.createElement(Field, { key: "checkpoint", label: "Checkpoint override", hint: "Используется только в режиме дообучения." },
        React.createElement("input", {
          value: trainingForm.checkpoint_override,
          onChange: (e) => setTrainingForm((prev) => ({ ...prev, checkpoint_override: e.target.value })),
          placeholder: selectedTrainingProfile?.default_finetune_checkpoint || "./external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
        }),
      ),
    );
  }

  advancedChildren.push(
    React.createElement("div", { key: "early-toggle", style: { marginTop: 10 } },
      React.createElement("label", { className: "checkbox-line" },
        React.createElement("input", {
          type: "checkbox",
          checked: trainingForm.early_stopping_enabled,
          onChange: (e) => setTrainingForm((prev) => ({ ...prev, early_stopping_enabled: e.target.checked })),
        }),
        "Включить early stopping",
      ),
    ),
  );

  if (trainingForm.early_stopping_enabled) {
    advancedChildren.push(
      React.createElement(InlineHint, { key: "early-auto" },
        resolvedEarlyMetric
          ? `Validation curve будет мониториться автоматически: ${resolvedEarlyMetric}.`
          : "Автоматическая validation metric пока не определилась для этого training preset.",
      ),
      React.createElement("div", { key: "early-grid", className: "split-grid" },
        React.createElement(Field, { label: "Patience", compact: true },
          React.createElement("input", {
            type: "number",
            min: 0,
            value: trainingForm.early_stopping_patience,
            onChange: (e) => setTrainingForm((prev) => ({ ...prev, early_stopping_patience: Number.parseInt(e.target.value || "0", 10) || 0 })),
          }),
        ),
        React.createElement(Field, { label: "Min delta", compact: true },
          React.createElement("input", {
            type: "number",
            min: 0,
            step: "0.0001",
            value: trainingForm.early_stopping_min_delta,
            onChange: (e) => setTrainingForm((prev) => ({ ...prev, early_stopping_min_delta: Number.parseFloat(e.target.value || "0") || 0 })),
          }),
        ),
      ),
      React.createElement(InlineHint, { key: "direction-hint" }, "Направление метрики берётся из training preset автоматически."),
    );
  }

  advancedChildren.push(
    React.createElement(ActionBar, { key: "actions" },
      React.createElement("button", {
        type: "button",
        onClick: handleTrainingStart,
        disabled: !canStart,
      }, trainingBusy ? "Обучение запущено..." : "Запустить обучение"),
      React.createElement("button", {
        type: "button",
        className: "button-secondary",
        onClick: handleTrainingCancel,
        disabled: !canCancel,
      }, trainingCancelBusy ? "Останавливаем..." : "Остановить обучение"),
    ),
  );

  if (trainingError) {
    advancedChildren.push(React.createElement(InlineHint, { key: "error", tone: "error" }, trainingError));
  }

  const advancedSection = React.createElement(CollapsibleSection, {
    title: "Настройки run",
    subtitle: "Override-пути и базовые параметры early stopping.",
  }, ...advancedChildren);

  const leftColumn = React.createElement("div", { className: "training-main" }, trainingSection, datasetSection, advancedSection);

  const statusChildren = [
    React.createElement("div", { key: "badges", className: "status-stack", style: { marginBottom: 14 } },
      React.createElement(StatusBadge, { tone: trainingForm.geometry_normalization ? "success" : "neutral" }, trainingForm.geometry_normalization ? "Normalization: on" : "Normalization: off"),
      selectedTrainingProfile && React.createElement(StatusBadge, { tone: selectedTrainingProfile.ready ? "success" : "warning" }, selectedTrainingProfile.ready ? "Model ready" : "Model not ready"),
      currentEarlyState && React.createElement(StatusBadge, { tone: currentEarlyState.stopped_early ? "warning" : currentEarlyState.supported ? "success" : "neutral" }, currentEarlyState.enabled ? "Early stopping on" : "Early stopping off"),
    ),
  ];

  if (trainingRun) {
    statusChildren.push(
      React.createElement("div", { key: "stats", className: "stats-grid" },
        renderStatTile("Train targets", trainingRun.split_counts?.train || 0),
        renderStatTile("Val targets", trainingRun.split_counts?.val || 0),
        renderStatTile("Train samples", trainingRun.sample_counts?.train || 0),
        renderStatTile("Val samples", trainingRun.sample_counts?.val || 0),
      ),
    );
  } else {
    statusChildren.push(React.createElement(InlineHint, { key: "empty" }, "После запуска здесь появятся статус run, размеры split и результат early stopping."));
  }

  const earlyHint = renderEarlyHint(currentEarlyState);
  if (earlyHint) statusChildren.push(React.cloneElement(earlyHint, { key: "early-hint" }));

  if (currentEarlyState?.best_metric_value !== null && currentEarlyState?.best_metric_value !== undefined) {
    statusChildren.push(
      React.createElement(InlineHint, { key: "best-metric" }, `Лучшее значение: ${Number(currentEarlyState.best_metric_value).toFixed(6)} на step ${currentEarlyState.best_metric_step ?? "n/a"}.`),
    );
  }

  const statusSection = React.createElement(SectionCard, {
    title: "Status",
    subtitle: "Краткая сводка по текущему run и датасету.",
  }, ...statusChildren);

  const selectedSeriesLabels = {
    [automaticCurveTags[0] || ""]: "Кривая обучения",
    [automaticCurveTags[1] || ""]: "Кривая валидации",
  };
  const selectedSeriesRoles = {
    [automaticCurveTags[0] || ""]: String(
      resolvedMetricViews?.primary?.role
      || resolvedMetricViews?.train_curve?.role
      || "train",
    ),
    [automaticCurveTags[1] || ""]: String(
      resolvedMetricViews?.secondary?.role
      || resolvedMetricViews?.validation_curve?.role
      || "val",
    ),
  };

  const liveCurvesSection = React.createElement(SectionCard, {
    title: "Live curves",
    subtitle: "График автоматически показывает кривые обучения и валидации, когда метрики появляются.",
  },
  React.createElement(MetricChart, {
    metricSeries,
    selectedTags: automaticCurveTags,
    seriesLabels: selectedSeriesLabels,
    seriesRoles: selectedSeriesRoles,
    emptyText: trainingRun?.metrics_history_available
      ? "Метрики уже пишутся, но подходящие кривые ещё не появились."
      : "История метрик пока недоступна. Для моделей без SummaryWriter графики не появятся.",
  }),
  liveMetricRows.length > 0
    ? React.createElement("div", { className: "stats-grid", style: { marginTop: 10 } },
      ...liveMetricRows.map((row) => renderStatTile(`${row.label} step`, row.step)),
      ...liveMetricRows.map((row) => renderStatTile(`${row.label} value`, row.value)),
    )
    : React.createElement(InlineHint, null, "Числовые значения метрик появятся после первых записей в metric history."),
  );

  const outputsChildren = [];
  if (trainingRun?.best_checkpoint_path) {
    outputsChildren.push(
      React.createElement("pre", { key: "weights", className: "weights-box" }, trainingWeightsHint),
    );
    if (trainingCopyStatus) {
      outputsChildren.push(React.createElement(InlineHint, { key: "copy-status" }, trainingCopyStatus));
    }
  } else {
    outputsChildren.push(
      React.createElement(InlineHint, { key: "empty-output" }, "После успешного обучения здесь появится готовый `weights_path` для шага пайплайна."),
    );
  }

  const outputsSection = React.createElement(SectionCard, {
    title: "Outputs",
    subtitle: "Итоговый checkpoint и подсказка для пайплайна.",
    actions: trainingRun?.best_checkpoint_path
      ? React.createElement("button", { type: "button", className: "button-secondary", onClick: copyTrainingWeightsPath }, "Скопировать")
      : null,
  }, ...outputsChildren);

  const logsSection = React.createElement(SectionCard, {
    title: "Logs",
    subtitle: "Поток логов обучения без отдельной вкладки.",
  },
  React.createElement(LogPanel, { text: trainingLogs, emptyText: "Логи обучения появятся здесь", style: { maxHeight: 320 } }));

  const rightColumn = React.createElement("div", { className: "training-side" }, statusSection, liveCurvesSection, outputsSection, logsSection);

  return React.createElement("div", { className: "card" },
    header,
    React.createElement("div", { className: "training-shell" }, leftColumn, rightColumn),
  );
}

