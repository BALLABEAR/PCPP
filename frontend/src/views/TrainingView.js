import React, { useEffect, useMemo, useState } from "https://esm.sh/react@18.3.1";

import { getJson, postJson } from "../lib/api.js";
import { startSafePolling } from "../lib/polling.js";
import { LogPanel } from "../components/LogPanel.js";
import { MetricChart } from "../components/MetricChart.js";
import {
  ActionBar,
  CollapsibleSection,
  Field,
  InlineHint,
  SectionCard,
  StatusBadge,
} from "../components/UiPrimitives.js";

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
  return {
    early_stopping_enabled: Boolean(defaults.enabled),
    early_stopping_metric: String(defaults.metric || ""),
    early_stopping_mode: String(defaults.mode || "min"),
    early_stopping_patience: Number.parseInt(String(defaults.patience ?? 10), 10) || 10,
    early_stopping_min_delta: Number.parseFloat(String(defaults.min_delta ?? 0)) || 0,
  };
}

function buildInitialTrainingForm(trainingProfiles) {
  const profile = trainingProfiles[0] || null;
  return {
    profile_id: profile?.profile_id || "",
    target_root: "./data/datasets/Full_Clouds",
    training_data_root: "./data/datasets/Partial_Clouds",
    train_percent: 80,
    val_percent: 10,
    test_percent: 10,
    geometry_normalization: true,
    mode: "scratch",
    train_script_override: "",
    config_path_override: "",
    checkpoint_override: "",
    use_gpu: true,
    ...buildEarlyStoppingDefaults(profile),
  };
}

function pickDefaultCurveSelection(resolvedMetricViews, currentSelected) {
  const primary = resolvedMetricViews?.primary?.resolved_tag || resolvedMetricViews?.train_curve?.resolved_tag || "";
  const secondary = resolvedMetricViews?.secondary?.resolved_tag || resolvedMetricViews?.validation_curve?.resolved_tag || "";
  if (currentSelected?.primary && currentSelected?.secondary) {
    return currentSelected;
  }
  return {
    primary: currentSelected?.primary || primary || "",
    secondary: currentSelected?.secondary || secondary || "",
  };
}

function statusTone(status) {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
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

export function TrainingView({ trainingProfiles }) {
  const [trainingRunId, setTrainingRunId] = useState("");
  const [trainingRun, setTrainingRun] = useState(null);
  const [trainingMetrics, setTrainingMetrics] = useState(null);
  const [selectedMetricTags, setSelectedMetricTags] = useState({ primary: "", secondary: "" });
  const [trainingLogs, setTrainingLogs] = useState("");
  const [trainingBusy, setTrainingBusy] = useState(false);
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
  const splitSum = Number(trainingForm.train_percent || 0) + Number(trainingForm.val_percent || 0) + Number(trainingForm.test_percent || 0);
  const currentEarlyState = trainingMetrics?.early_stopping_state || trainingRun?.early_stopping_state || null;

  useEffect(() => {
    if (!trainingForm.profile_id && trainingProfiles[0]?.profile_id) {
      setTrainingForm(buildInitialTrainingForm(trainingProfiles));
    }
  }, [trainingForm.profile_id, trainingProfiles]);

  useEffect(() => {
    setSelectedMetricTags((prev) => pickDefaultCurveSelection(resolvedMetricViews, prev));
  }, [resolvedMetricViews]);

  useEffect(() => {
    if (!trainingRunId) return undefined;
    return startSafePolling(async () => {
      const runPayload = await getJson(`/training/runs/${trainingRunId}`);
      const metricsPayload = await getJson(`/training/runs/${trainingRunId}/metrics`);
      setTrainingRun(runPayload);
      setTrainingMetrics(metricsPayload);
      setTrainingLogs(runPayload.logs || "");
      if (runPayload.status === "completed" || runPayload.status === "failed") {
        setTrainingBusy(false);
        return true;
      }
      return false;
    }, 2000, (e) => {
      setTrainingBusy(false);
      setTrainingLogs(`Failed to poll training logs: ${e.message}`);
    });
  }, [trainingRunId]);

  async function handleTrainingStart() {
    setTrainingError("");
    setTrainingCopyStatus("");
    setTrainingRun(null);
    setTrainingMetrics(null);
    setSelectedMetricTags(["", ""]);
    setTrainingLogs("");
    setTrainingBusy(true);
    try {
      const payload = await postJson("/training/runs", trainingForm);
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

  function handleProfileChange(nextProfileId) {
    const profile = trainingProfiles.find((item) => item.profile_id === nextProfileId) || null;
    setTrainingForm((prev) => ({
      ...prev,
      profile_id: nextProfileId,
      ...buildEarlyStoppingDefaults(profile),
    }));
  }

  const canStart = !trainingBusy
    && Boolean(trainingForm.profile_id)
    && Boolean(selectedTrainingProfile?.ready)
    && splitSum === 100
    && (!trainingForm.early_stopping_enabled || Boolean(String(trainingForm.early_stopping_metric || "").trim()));

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
  selectedTrainingProfile && React.createElement(InlineHint, null, `Default config: ${selectedTrainingProfile.default_train_config}`),
  React.createElement("div", { className: "split-grid", style: { marginTop: 14 } },
    React.createElement(Field, { label: "Режим обучения", compact: true },
      React.createElement("select", {
        value: trainingForm.mode,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, mode: e.target.value })),
      },
      React.createElement("option", { value: "scratch" }, "Обучение с нуля"),
      React.createElement("option", { value: "finetune" }, "Дообучение"),
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
    React.createElement(Field, { label: "Геометрия", compact: true },
      React.createElement("label", { className: "checkbox-line" },
        React.createElement("input", {
          type: "checkbox",
          checked: trainingForm.geometry_normalization,
          onChange: (e) => setTrainingForm((prev) => ({ ...prev, geometry_normalization: e.target.checked })),
        }),
        selectedTrainingProfile?.dataset_fields?.geometry_normalization_label || "Нормализовать геометрию",
      ),
    ),
  ));

  const datasetSection = React.createElement(SectionCard, {
    title: "Dataset",
    subtitle: "Укажите target, partial dataset и разбиение по объектам.",
  },
  React.createElement(Field, { label: "Путь к target", hint: "Обычно это Full_Clouds." },
    React.createElement("input", {
      value: trainingForm.target_root,
      onChange: (e) => setTrainingForm((prev) => ({ ...prev, target_root: e.target.value })),
      placeholder: "./data/datasets/Full_Clouds",
    }),
  ),
  React.createElement(Field, { label: "Путь к обучающей выборке", hint: "Обычно это Partial_Clouds." },
    React.createElement("input", {
      value: trainingForm.training_data_root,
      onChange: (e) => setTrainingForm((prev) => ({ ...prev, training_data_root: e.target.value })),
      placeholder: "./data/datasets/Partial_Clouds",
    }),
  ),
  React.createElement(InlineHint, null, selectedTrainingProfile?.dataset_structure_hint || "Partial одного target остаются в одном split."),
  React.createElement("div", { className: "split-grid", style: { marginTop: 14 } },
    React.createElement(Field, { label: "Train %", compact: true },
      React.createElement("input", {
        type: "number",
        min: 0,
        max: 100,
        value: trainingForm.train_percent,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, train_percent: Number.parseInt(e.target.value || "0", 10) || 0 })),
      }),
    ),
    React.createElement(Field, { label: "Val %", compact: true },
      React.createElement("input", {
        type: "number",
        min: 0,
        max: 100,
        value: trainingForm.val_percent,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, val_percent: Number.parseInt(e.target.value || "0", 10) || 0 })),
      }),
    ),
    React.createElement(Field, { label: "Test %", compact: true },
      React.createElement("input", {
        type: "number",
        min: 0,
        max: 100,
        value: trainingForm.test_percent,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, test_percent: Number.parseInt(e.target.value || "0", 10) || 0 })),
      }),
    ),
  ),
  React.createElement(InlineHint, { tone: splitSum === 100 ? "default" : "warning" }, `Сумма split: ${splitSum}%. Нужно ровно 100%.`));

  const advancedChildren = [
    React.createElement(Field, { key: "train-script", label: "Train script override", hint: "Обычно оставляют пустым." },
      React.createElement("input", {
        value: trainingForm.train_script_override,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, train_script_override: e.target.value })),
        placeholder: selectedTrainingProfile?.default_train_script || "./external_models/SnowflakeNet/completion/train.py",
      }),
    ),
    React.createElement(Field, { key: "config", label: "Config override", hint: "Например, 8192-конфиг для fine-tune." },
      React.createElement("input", {
        value: trainingForm.config_path_override,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, config_path_override: e.target.value })),
        placeholder: selectedTrainingProfile?.default_train_config || "./external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
      }),
    ),
  ];

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
      React.createElement(Field, {
        key: "metric-tag",
        label: "Metric tag",
        hint: availableMetricTags.length > 0 ? `Доступно сейчас: ${availableMetricTags.join(", ")}` : "Если тег пока неизвестен, сначала запустите run и посмотрите доступные метрики справа.",
      },
      React.createElement("input", {
        value: trainingForm.early_stopping_metric,
        onChange: (e) => setTrainingForm((prev) => ({ ...prev, early_stopping_metric: e.target.value })),
        placeholder: selectedTrainingProfile?.early_stopping_defaults?.metric || "Loss/Epoch/cd_p3",
      })),
      React.createElement("div", { key: "early-grid", className: "split-grid" },
        React.createElement(Field, { label: "Mode", compact: true },
          React.createElement("select", {
            value: trainingForm.early_stopping_mode,
            onChange: (e) => setTrainingForm((prev) => ({ ...prev, early_stopping_mode: e.target.value })),
          },
          React.createElement("option", { value: "min" }, "min"),
          React.createElement("option", { value: "max" }, "max"),
          ),
        ),
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
    );
  }

  advancedChildren.push(
    React.createElement(ActionBar, { key: "actions" },
      React.createElement("button", {
        type: "button",
        onClick: handleTrainingStart,
        disabled: !canStart,
      }, trainingBusy ? "Обучение запущено..." : "Запустить обучение"),
    ),
  );

  if (trainingError) {
    advancedChildren.push(React.createElement(InlineHint, { key: "error", tone: "error" }, trainingError));
  }

  const advancedSection = React.createElement(CollapsibleSection, {
    title: "Advanced",
    subtitle: "Редкие override-настройки и тонкая настройка early stopping.",
  }, ...advancedChildren);

  const leftColumn = React.createElement("div", { className: "training-main" }, trainingSection, datasetSection, advancedSection);

  const statusChildren = [
    React.createElement("div", { key: "badges", className: "status-stack", style: { marginBottom: 14 } },
      React.createElement(StatusBadge, { tone: splitSum === 100 ? "success" : "warning" }, `Split: ${splitSum}%`),
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

  const chartControls = availableMetricTags.length > 0
    ? React.createElement("div", { className: "metric-picker-grid" },
      React.createElement(Field, { label: "Кривая обучения", compact: true },
        React.createElement("select", {
          value: selectedMetricTags.primary || "",
          onChange: (e) => setSelectedMetricTags((prev) => ({ ...prev, primary: e.target.value })),
        },
        React.createElement("option", { value: "" }, "Недоступно"),
        metricsCatalog
          .filter((item) => item.role === "train" || item.key === "train_curve")
          .map((item) => {
            const view = resolvedMetricViews[item.key] || {};
            return React.createElement(
              "option",
              {
                key: `primary-${item.key}`,
                value: view.resolved_tag || "",
                disabled: !view.resolved_tag,
              },
              item.label,
            );
          }),
        ),
      ),
      React.createElement(Field, { label: "Кривая валидации", compact: true },
        React.createElement("select", {
          value: selectedMetricTags.secondary || "",
          onChange: (e) => setSelectedMetricTags((prev) => ({ ...prev, secondary: e.target.value })),
        },
        React.createElement("option", { value: "" }, "Недоступно"),
        metricsCatalog
          .filter((item) => item.role === "val" || item.role === "test" || item.key === "validation_curve")
          .map((item) => {
            const view = resolvedMetricViews[item.key] || {};
            return React.createElement(
              "option",
              {
                key: `secondary-${item.key}`,
                value: view.resolved_tag || "",
                disabled: !view.resolved_tag,
              },
              item.label,
            );
          }),
        ),
      ),
    )
    : null;

  const selectedSeriesLabels = {
    [selectedMetricTags.primary]: "Кривая обучения",
    [selectedMetricTags.secondary]: "Кривая валидации",
  };

  const rawMetricsSection = availableMetricTags.length > 0
    ? React.createElement(CollapsibleSection, {
      title: "Advanced metrics",
      subtitle: "Сырые internal metric tags для диагностики и ручного выбора.",
    },
    React.createElement(Field, { label: "Raw tag: левая кривая", compact: true },
      React.createElement("select", {
        value: selectedMetricTags.primary || "",
        onChange: (e) => setSelectedMetricTags((prev) => ({ ...prev, primary: e.target.value })),
      },
      React.createElement("option", { value: "" }, "Выберите raw tag"),
      availableMetricTags.map((tag) => React.createElement("option", { key: `raw-primary-${tag}`, value: tag }, tag)),
      ),
    ),
    React.createElement(Field, { label: "Raw tag: правая кривая", compact: true },
      React.createElement("select", {
        value: selectedMetricTags.secondary || "",
        onChange: (e) => setSelectedMetricTags((prev) => ({ ...prev, secondary: e.target.value })),
      },
      React.createElement("option", { value: "" }, "Выберите raw tag"),
      availableMetricTags.map((tag) => React.createElement("option", { key: `raw-secondary-${tag}`, value: tag }, tag)),
      ),
    ))
    : null;

  const liveCurvesSection = React.createElement(SectionCard, {
    title: "Live curves",
    subtitle: "По умолчанию показываются понятные кривые обучения и валидации.",
  },
  chartControls,
  (!resolvedMetricViews?.primary?.resolved_tag || !resolvedMetricViews?.secondary?.resolved_tag) && React.createElement(
    InlineHint,
    { tone: "warning" },
    "Не для всех метрик удалось автоматически подобрать понятные alias-имена. Ниже доступны raw tags.",
  ),
  React.createElement(MetricChart, {
    metricSeries,
    selectedTags: [selectedMetricTags.primary, selectedMetricTags.secondary],
    seriesLabels: selectedSeriesLabels,
    emptyText: trainingRun?.metrics_history_available
      ? "История метрик есть, выберите теги сверху."
      : "История метрик пока недоступна. Для моделей без SummaryWriter графики не появятся.",
  }),
  rawMetricsSection);

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
