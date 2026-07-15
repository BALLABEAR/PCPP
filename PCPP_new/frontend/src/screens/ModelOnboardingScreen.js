import { createComingSoon } from "../components/ComingSoon.js";
import { getJson, postJson } from "../lib/api.js";

const ONBOARDING_VIEWS = {
  addModel: "add_model",
  trainingYaml: "training_yaml",
};

const STAGE_NAMES = ["validate", "scaffold", "build", "smoke", "registry"];
const TERMINAL_RUN_STATUSES = new Set(["success", "failed"]);

// Возвращает экран добавления модели с внутренним переключением.
export function createModelOnboardingScreen() {
  let activeView = ONBOARDING_VIEWS.addModel;
  const modelOnboardingState = {
    logs: "Будет позже",
    stages: createInitialStageStatuses(),
    running: false,
    pollingHandle: null,
  };

  const section = document.createElement("section");
  section.className = "screen";

  const tabsMount = document.createElement("div");
  const contentMount = document.createElement("div");
  contentMount.className = "model-onboarding-content";

  const render = () => {
    tabsMount.replaceChildren(
      createInnerTabs({
        activeView,
        onSelect: (nextView) => {
          activeView = nextView;
          render();
        },
      }),
    );
    contentMount.replaceChildren(createViewContent(activeView, modelOnboardingState));
  };

  render();
  section.append(tabsMount, contentMount);
  return section;
}

// Возвращает переключатель между подэкранами onboarding.
function createInnerTabs({ activeView, onSelect }) {
  const wrap = document.createElement("div");
  wrap.className = "inner-tabs";
  wrap.appendChild(
    createInnerTabButton({
      text: "Добавить модель",
      active: activeView === ONBOARDING_VIEWS.addModel,
      onClick: () => onSelect(ONBOARDING_VIEWS.addModel),
    }),
  );
  wrap.appendChild(
    createInnerTabButton({
      text: "Создать Training YAML",
      active: activeView === ONBOARDING_VIEWS.trainingYaml,
      onClick: () => onSelect(ONBOARDING_VIEWS.trainingYaml),
    }),
  );
  return wrap;
}

// Возвращает кнопку внутренней вкладки.
function createInnerTabButton({ text, active, onClick }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inner-tabs__button";
  button.dataset.active = String(Boolean(active));
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
}

// Возвращает контент выбранного подэкрана.
function createViewContent(activeView, modelOnboardingState) {
  if (activeView === ONBOARDING_VIEWS.addModel) {
    return createAddModelFormCard(modelOnboardingState);
  }
  return createTrainingYamlCard();
}

// Возвращает карточку формы добавления модели.
function createAddModelFormCard(modelOnboardingState) {
  const card = document.createElement("article");
  card.className = "feature-card feature-card--wide";

  const title = document.createElement("h3");
  title.className = "feature-card__title";
  title.textContent = "Добавить модель";

  const form = document.createElement("form");
  form.className = "pipeline-form";

  const taskTypeField = createSelectField("Тип задачи", [
    { value: "", label: "Выберите тип задачи" },
    { value: "completion", label: "completion" },
    { value: "meshing", label: "meshing" },
    { value: "upsampling", label: "upsampling" },
  ]);
  const modelIdField = createTextField("Имя модели", "Например: poin_tr");
  const repoPathField = createTextField("Путь к папке с моделью", "./external_models/<model_name>");
  const weightsPathField = createTextField("Путь к весам модели", "./external_models/<model_name>/weights/model.pth");
  const configPathField = createTextField("Путь к конфигам модели", "./external_models/<model_name>/configs");
  const smokeInputField = createTextField(
    "Путь к тестовому входному файлу для пробного запуска",
    "./data/smoke_test/lamp_post.ply",
    "",
    "./data/smoke_test/lamp_post.ply",
  );

  const advancedTitle = document.createElement("h4");
  advancedTitle.className = "subsection-title";
  advancedTitle.textContent = "Advanced";

  const entryCommandField = createTextField("Entry command", "python tools/inference.py", "Команда запуска модели внутри контейнера.");
  const extraPipPackagesField = createTextareaField("Extra pip packages", "numpy\nopen3d", "Дополнительные pip-пакеты (по одному на строку).");
  const pipRequirementsFilesField = createTextareaField("Pip requirements files", "requirements.txt", "Список requirements-файлов относительно repo_path.");
  const pipExtraArgsField = createTextareaField("Pip extra args", "--no-cache-dir", "Дополнительные аргументы для pip install.");
  const systemPackagesField = createTextareaField("System packages", "libgl1\nlibglib2.0-0", "Системные apt-пакеты, нужные модели.");
  const baseImageField = createTextField("Base image", "nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04", "Базовый Docker-образ для worker-контейнера.");
  const extraBuildStepsField = createTextareaField("Extra build steps", "python setup.py build_ext --inplace", "Дополнительные команды сборки образа.");
  const envOverridesField = createTextareaField("Env overrides", "PYTHONPATH=/app/external_models/PoinTr", "Переменные окружения в формате KEY=VALUE.");
  const smokeArgsField = createTextareaField("Smoke args", "--help", "Аргументы для smoke-запуска модели.");

  form.append(
    taskTypeField,
    modelIdField,
    repoPathField,
    weightsPathField,
    configPathField,
    smokeInputField,
    advancedTitle,
    entryCommandField,
    extraPipPackagesField,
    pipRequirementsFilesField,
    pipExtraArgsField,
    systemPackagesField,
    baseImageField,
    extraBuildStepsField,
    envOverridesField,
    smokeArgsField,
  );

  const logsSection = createLogsSection(modelOnboardingState.logs);
  const logsPlaceholder = logsSection.querySelector(".run-logs__placeholder");

  const stageGrid = createStagesGrid(modelOnboardingState.stages);
  const stagesWrap = createStagesSection(stageGrid);

  const submitButton = document.createElement("button");
  submitButton.type = "button";
  submitButton.className = "ui-button";
  submitButton.textContent = modelOnboardingState.running ? "Добавление..." : "Добавить модель";
  submitButton.disabled = modelOnboardingState.running;

  const buildPromptButton = document.createElement("button");
  buildPromptButton.type = "button";
  buildPromptButton.className = "ui-button ui-button--secondary";
  buildPromptButton.textContent = "Сформировать промпт для AI-помощника";
  buildPromptButton.disabled = modelOnboardingState.running;

  submitButton.addEventListener("click", async () => {
    if (modelOnboardingState.running) return;
    await startScaffoldRun({
      modelOnboardingState,
      submitButton,
      buildPromptButton,
      stageGrid,
      logsPlaceholder,
      payload: {
        task_type: getFieldValue(taskTypeField),
        model_id: getFieldValue(modelIdField),
        repo_path: getFieldValue(repoPathField),
        weights_path: getFieldValue(weightsPathField),
        config_path: getFieldValue(configPathField),
        smoke_input_path: getFieldValue(smokeInputField),
        entry_command: getFieldValue(entryCommandField),
        extra_pip_packages: normalizeMultiline(getFieldValue(extraPipPackagesField)),
        pip_requirements_files: normalizeMultiline(getFieldValue(pipRequirementsFilesField)),
        pip_extra_args: normalizeMultiline(getFieldValue(pipExtraArgsField)),
        system_packages: normalizeMultiline(getFieldValue(systemPackagesField)),
        base_image: getFieldValue(baseImageField),
        extra_build_steps: normalizeMultiline(getFieldValue(extraBuildStepsField)),
        env_overrides: normalizeMultiline(getFieldValue(envOverridesField)),
        smoke_args: normalizeMultiline(getFieldValue(smokeArgsField)),
      },
    });
  });

  buildPromptButton.addEventListener("click", async () => {
    const prompt = buildAiPrompt({
      stages: modelOnboardingState.stages,
      logs: modelOnboardingState.logs,
      task_type: getFieldValue(taskTypeField),
      model_id: getFieldValue(modelIdField),
      repo_path: getFieldValue(repoPathField),
      weights_path: getFieldValue(weightsPathField),
      config_path: getFieldValue(configPathField),
      smoke_input_path: getFieldValue(smokeInputField),
      entry_command: getFieldValue(entryCommandField),
      extra_pip_packages: normalizeMultiline(getFieldValue(extraPipPackagesField)),
      pip_requirements_files: normalizeMultiline(getFieldValue(pipRequirementsFilesField)),
      pip_extra_args: normalizeMultiline(getFieldValue(pipExtraArgsField)),
      system_packages: normalizeMultiline(getFieldValue(systemPackagesField)),
      base_image: getFieldValue(baseImageField),
      extra_build_steps: normalizeMultiline(getFieldValue(extraBuildStepsField)),
      env_overrides: normalizeMultiline(getFieldValue(envOverridesField)),
      smoke_args: normalizeMultiline(getFieldValue(smokeArgsField)),
    });
    try {
      await navigator.clipboard.writeText(prompt);
      buildPromptButton.textContent = "Скопировано";
    } catch (_error) {
      buildPromptButton.textContent = "Ошибка копирования";
    }
    setTimeout(() => {
      buildPromptButton.textContent = "Сформировать промпт для AI-помощника";
    }, 1400);
  });

  const promptButtonWrap = document.createElement("div");
  promptButtonWrap.className = "button-with-help";
  promptButtonWrap.append(
    buildPromptButton,
    createHelpIcon("Генерирует промпт из текущих полей и сразу копирует его в буфер обмена."),
  );

  const buttonsRow = document.createElement("div");
  buttonsRow.className = "button-row";
  buttonsRow.append(submitButton, promptButtonWrap);

  form.append(buttonsRow, stagesWrap, logsSection);
  card.append(title, form);
  return card;
}

// Запускает scaffold-run и обновляет UI статусов.
async function startScaffoldRun({ modelOnboardingState, submitButton, buildPromptButton, stageGrid, logsPlaceholder, payload }) {
  modelOnboardingState.running = true;
  submitButton.disabled = true;
  buildPromptButton.disabled = true;
  submitButton.textContent = "Добавление...";

  try {
    const validation = await postJson("/onboarding/models/validate", payload);
    if (!validation.valid) {
      modelOnboardingState.stages = createInitialStageStatuses();
      modelOnboardingState.stages.validate = "failed";
      renderStageStatuses(stageGrid, modelOnboardingState.stages);
      modelOnboardingState.logs = `[validate] failed\n${validation.errors.join("\n")}`;
      logsPlaceholder.textContent = modelOnboardingState.logs;
      finishRunUi(modelOnboardingState, submitButton, buildPromptButton);
      return;
    }

    const scaffoldRun = await postJson("/onboarding/models/scaffold", payload);
    applyRunState(modelOnboardingState, scaffoldRun, stageGrid, logsPlaceholder);
    if (scaffoldRun.status === "failed") {
      finishRunUi(modelOnboardingState, submitButton, buildPromptButton);
      return;
    }
    startRunPolling({
      modelOnboardingState,
      runId: scaffoldRun.run_id,
      stageGrid,
      logsPlaceholder,
      submitButton,
      buildPromptButton,
    });
  } catch (error) {
    modelOnboardingState.logs = `Ошибка запуска:\n${error.message}`;
    logsPlaceholder.textContent = modelOnboardingState.logs;
    modelOnboardingState.stages = createInitialStageStatuses();
    modelOnboardingState.stages.validate = "failed";
    renderStageStatuses(stageGrid, modelOnboardingState.stages);
    finishRunUi(modelOnboardingState, submitButton, buildPromptButton);
  }
}

// Запускает polling статусов onboarding-run.
function startRunPolling({ modelOnboardingState, runId, stageGrid, logsPlaceholder, submitButton, buildPromptButton }) {
  stopRunPolling(modelOnboardingState);
  modelOnboardingState.pollingHandle = setInterval(async () => {
    try {
      const run = await getJson(`/onboarding/models/runs/${runId}`);
      applyRunState(modelOnboardingState, run, stageGrid, logsPlaceholder);
      if (!TERMINAL_RUN_STATUSES.has(run.status)) return;
      stopRunPolling(modelOnboardingState);
      finishRunUi(modelOnboardingState, submitButton, buildPromptButton);
    } catch (error) {
      stopRunPolling(modelOnboardingState);
      modelOnboardingState.logs = `${modelOnboardingState.logs || ""}\n[polling-error] ${error.message}`.trim();
      logsPlaceholder.textContent = modelOnboardingState.logs;
      finishRunUi(modelOnboardingState, submitButton, buildPromptButton);
    }
  }, 1500);
}

// Останавливает polling run-статусов.
function stopRunPolling(modelOnboardingState) {
  if (!modelOnboardingState.pollingHandle) return;
  clearInterval(modelOnboardingState.pollingHandle);
  modelOnboardingState.pollingHandle = null;
}

// Применяет состояние run к UI.
function applyRunState(modelOnboardingState, run, stageGrid, logsPlaceholder) {
  modelOnboardingState.stages = {
    validate: run.stages?.validate || "pending",
    scaffold: run.stages?.scaffold || "pending",
    build: run.stages?.build || "pending",
    smoke: run.stages?.smoke || "pending",
    registry: run.stages?.registry || "pending",
  };
  modelOnboardingState.logs = run.logs || "";
  renderStageStatuses(stageGrid, modelOnboardingState.stages);
  logsPlaceholder.textContent = modelOnboardingState.logs || "Будет позже";
}

// Возвращает кнопки в idle-состояние.
function finishRunUi(modelOnboardingState, submitButton, buildPromptButton) {
  modelOnboardingState.running = false;
  submitButton.disabled = false;
  buildPromptButton.disabled = false;
  submitButton.textContent = "Добавить модель";
}

// Возвращает секцию этапов onboarding.
function createStagesSection(stageGrid) {
  const stagesWrap = document.createElement("div");
  stagesWrap.className = "stages-wrap";
  const stagesHeader = document.createElement("div");
  stagesHeader.className = "stages-wrap__header";
  const stagesTitle = document.createElement("h4");
  stagesTitle.className = "subsection-title";
  stagesTitle.textContent = "Этапы добавления";
  stagesHeader.append(
    stagesTitle,
    createHelpIcon("validate — проверка данных; scaffold — генерация worker-файлов; build — сборка docker image; smoke — пробный запуск контейнера на тестовом входе; registry — регистрация карточки модели в БД."),
  );
  stagesWrap.append(stagesHeader, stageGrid);
  return stagesWrap;
}

// Возвращает секцию логов onboarding.
function createLogsSection(logText) {
  const logsSection = document.createElement("div");
  logsSection.className = "run-logs";
  const logsTitle = document.createElement("h4");
  logsTitle.className = "run-logs__title";
  logsTitle.textContent = "Логи добавления модели";
  const logsPlaceholder = document.createElement("pre");
  logsPlaceholder.className = "run-logs__placeholder";
  logsPlaceholder.textContent = logText || "Будет позже";
  logsSection.append(logsTitle, logsPlaceholder);
  return logsSection;
}

// Возвращает карточку для подэкрана создания Training YAML.
function createTrainingYamlCard() {
  const card = document.createElement("article");
  card.className = "feature-card feature-card--wide";

  const title = document.createElement("h3");
  title.className = "feature-card__title";
  title.textContent = "Создать Training YAML";

  card.append(title, createComingSoon("Будет позже"));
  return card;
}

// Возвращает текстовое поле формы.
function createTextField(labelText, placeholderText, hintText = "", initialValue = "") {
  const wrap = document.createElement("label");
  wrap.className = "form-field";
  const label = createFieldLabel(labelText, hintText);
  const input = document.createElement("input");
  input.type = "text";
  input.className = "ui-input";
  input.placeholder = placeholderText;
  input.value = initialValue;
  wrap.append(label, input);
  return wrap;
}

// Возвращает многострочное поле формы.
function createTextareaField(labelText, placeholderText, hintText = "") {
  const wrap = document.createElement("label");
  wrap.className = "form-field";
  const label = createFieldLabel(labelText, hintText);
  const textarea = document.createElement("textarea");
  textarea.className = "ui-input ui-textarea";
  textarea.placeholder = placeholderText;
  wrap.append(label, textarea);
  return wrap;
}

// Возвращает select-поле формы.
function createSelectField(labelText, options, hintText = "") {
  const wrap = document.createElement("label");
  wrap.className = "form-field";
  const label = createFieldLabel(labelText, hintText);
  const select = document.createElement("select");
  select.className = "ui-input";
  for (const optionItem of options) {
    const option = document.createElement("option");
    option.value = optionItem.value;
    option.textContent = optionItem.label;
    select.appendChild(option);
  }
  wrap.append(label, select);
  return wrap;
}

// Возвращает label поля с optional tooltip-иконкой.
function createFieldLabel(labelText, hintText) {
  const label = document.createElement("span");
  label.className = "form-field__label";
  label.textContent = labelText;
  if (!hintText) return label;
  const row = document.createElement("span");
  row.className = "field-label-row";
  row.append(label, createHelpIcon(hintText));
  return row;
}

// Возвращает help-иконку с hover-подсказкой.
function createHelpIcon(text) {
  const wrap = document.createElement("span");
  wrap.className = "help-icon";
  wrap.tabIndex = 0;
  wrap.setAttribute("role", "button");
  wrap.setAttribute("aria-label", "Показать подсказку");
  const badge = document.createElement("span");
  badge.className = "help-icon__badge";
  badge.textContent = "i";
  const tooltip = document.createElement("span");
  tooltip.className = "help-icon__tooltip";
  tooltip.textContent = text;
  wrap.append(badge, tooltip);
  return wrap;
}

// Создает дефолтное состояние стадий.
function createInitialStageStatuses() {
  return {
    validate: "pending",
    scaffold: "pending",
    build: "pending",
    smoke: "pending",
    registry: "pending",
  };
}

// Возвращает сетку из пяти этапов.
function createStagesGrid(stageStatuses) {
  const grid = document.createElement("div");
  grid.className = "stages-grid";
  for (const stageName of STAGE_NAMES) {
    const cell = document.createElement("div");
    cell.className = "stage-cell";
    cell.dataset.stage = stageName;
    cell.dataset.status = String(stageStatuses[stageName] || "pending");
    cell.textContent = stageName;
    grid.appendChild(cell);
  }
  return grid;
}

// Перерисовывает статусы этапов в UI.
function renderStageStatuses(stageGrid, stageStatuses) {
  for (const child of stageGrid.children) {
    const stageName = String(child.dataset.stage || "");
    child.dataset.status = String(stageStatuses[stageName] || "pending");
  }
}

// Возвращает значение input/select/textarea из form-field.
function getFieldValue(fieldWrap) {
  const control = fieldWrap.querySelector("input, select, textarea");
  return String(control?.value || "").trim();
}

// Нормализует многострочные поля в строки без пустых значений.
function normalizeMultiline(value) {
  return String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

// Собирает промпт для AI-помощника из данных формы.
function buildAiPrompt(formData) {
  const stages = formData.stages || createInitialStageStatuses();
  const logsTail = lastLogLines(formData.logs || "", 80);
  return [
    "Ты помогаешь настроить onboarding модели.",
    "",
    "Цель: предложи конкретные правки полей перед повторным запуском build/smoke.",
    "",
    "Текущее состояние этапов:",
    `- validate: ${stages.validate || "pending"}`,
    `- scaffold: ${stages.scaffold || "pending"}`,
    `- build: ${stages.build || "pending"}`,
    `- smoke: ${stages.smoke || "pending"}`,
    `- registry: ${stages.registry || "pending"}`,
    "",
    "Основные поля:",
    `- task_type: ${formData.task_type || "<empty>"}`,
    `- model_id: ${formData.model_id || "<empty>"}`,
    `- repo_path: ${formData.repo_path || "<empty>"}`,
    `- weights_path: ${formData.weights_path || "<empty>"}`,
    `- config_path: ${formData.config_path || "<empty>"}`,
    `- smoke_input_path: ${formData.smoke_input_path || "<empty>"}`,
    "",
    "Advanced:",
    `- entry_command: ${formData.entry_command || "<empty>"}`,
    `- extra_pip_packages:\n${formData.extra_pip_packages || "<empty>"}`,
    `- pip_requirements_files:\n${formData.pip_requirements_files || "<empty>"}`,
    `- pip_extra_args:\n${formData.pip_extra_args || "<empty>"}`,
    `- system_packages:\n${formData.system_packages || "<empty>"}`,
    `- base_image: ${formData.base_image || "<empty>"}`,
    `- extra_build_steps:\n${formData.extra_build_steps || "<empty>"}`,
    `- env_overrides:\n${formData.env_overrides || "<empty>"}`,
    `- smoke_args:\n${formData.smoke_args || "<empty>"}`,
    "",
    "Последние строки логов:",
    logsTail || "<empty>",
    "",
    "Формат ответа:",
    "1) Поле: <имя поля> -> Значение: <что поставить>",
    "2) Почему это нужно",
    "3) Что проверить после перезапуска",
  ].join("\n");
}

// Возвращает последние строки лога.
function lastLogLines(text, limit) {
  const lines = String(text || "").split("\n");
  return lines.slice(-Math.max(1, limit)).join("\n").trim();
}
