import { createComingSoon } from "../components/ComingSoon.js";
import { getJson } from "../lib/api.js";

// Возвращает экран запуска пайплайна.
export function createPipelineLaunchScreen() {
  const section = document.createElement("section");
  section.className = "screen";

  const cardsWrap = document.createElement("div");
  cardsWrap.className = "cards-grid";

  cardsWrap.appendChild(createRunPipelineCard());
  cardsWrap.appendChild(createTemplatesCard());
  cardsWrap.appendChild(createModelCatalogCard());

  section.append(cardsWrap);
  return section;
}

// Возвращает карточку Run Pipeline с финальным UI-каркасом.
function createRunPipelineCard() {
  const card = document.createElement("article");
  card.className = "feature-card feature-card--wide";

  const title = document.createElement("h3");
  title.className = "feature-card__title";
  title.textContent = "Запустить пайплайн";

  const form = createRunPipelineForm();
  const logs = createRunLogsSection();

  card.append(title, form, logs);
  return card;
}

// Возвращает форму запуска без backend-интеграции.
function createRunPipelineForm() {
  const form = document.createElement("form");
  form.className = "pipeline-form";

  const fileField = createFieldShell("Input file");
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = ".ply,.pcd,.xyz,.pts,.txt,.npy";
  fileInput.className = "ui-input";
  fileField.appendChild(fileInput);

  const pipelineField = createFieldShell("Пайплайн");
  const pipelineSelect = document.createElement("select");
  pipelineSelect.className = "ui-input";
  pipelineSelect.disabled = true;
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "Будет позже";
  pipelineSelect.appendChild(option);
  pipelineField.appendChild(pipelineSelect);

  const optionsWrap = document.createElement("div");
  optionsWrap.className = "checkbox-list";
  optionsWrap.appendChild(createCheckbox("force_rebuild_image", "Force rebuild image"));
  optionsWrap.appendChild(createCheckbox("prepare_model_for_pipeline", "Подготовить модель к пайплайну"));

  const submitButton = document.createElement("button");
  submitButton.type = "button";
  submitButton.className = "ui-button";
  submitButton.textContent = "Запустить";
  submitButton.addEventListener("click", () => {
    alert("Будет позже");
  });

  const note = document.createElement("p");
  note.className = "pipeline-form__note";

  form.append(fileField, pipelineField, optionsWrap, submitButton, note);
  return form;
}

// Возвращает блок логов запуска.
function createRunLogsSection() {
  const wrap = document.createElement("section");
  wrap.className = "run-logs";

  const title = document.createElement("h4");
  title.className = "run-logs__title";
  title.textContent = "Run Logs";

  const placeholder = createComingSoon("Будет позже");
  placeholder.classList.add("run-logs__placeholder");

  wrap.append(title, placeholder);
  return wrap;
}

// Возвращает карточку шаблонов пользователя.
function createTemplatesCard() {
  const card = document.createElement("article");
  card.className = "feature-card feature-card--wide";

  const title = document.createElement("h3");
  title.className = "feature-card__title";
  title.textContent = "Каталог пайпланов";

  // TODO: добавить список шаблонов и подтверждение удаления после появления API.
  card.append(title, createComingSoon("Будет позже"));
  return card;
}

// Возвращает карточку каталога моделей.
function createModelCatalogCard() {
  const card = document.createElement("article");
  card.className = "feature-card feature-card--wide";

  const title = document.createElement("h3");
  title.className = "feature-card__title";
  title.textContent = "Каталог моделей";

  const content = document.createElement("div");
  content.className = "model-catalog";
  content.textContent = "Загрузка...";

  void loadModelCatalog(content);

  card.append(title, content);
  return card;
}

// Загружает модели из backend и рендерит карточки каталога.
async function loadModelCatalog(mountNode) {
  try {
    const models = await getJson("/onboarding/models");
    mountNode.replaceChildren(createModelCatalogContent(models));
  } catch (_error) {
    mountNode.replaceChildren(createModelCatalogMessage("Нет добавленных моделей"));
  }
}

// Возвращает контент каталога моделей.
function createModelCatalogContent(models) {
  if (!Array.isArray(models) || models.length === 0) {
    return createModelCatalogMessage("Нет добавленных моделей");
  }

  const list = document.createElement("div");
  list.className = "model-catalog__list";
  for (const model of models) {
    list.appendChild(createModelCatalogItem(model));
  }
  return list;
}

// Возвращает карточку одной модели.
function createModelCatalogItem(model) {
  const item = document.createElement("article");
  item.className = "model-catalog__item";

  const modelId = document.createElement("h4");
  modelId.className = "model-catalog__model-id";
  modelId.textContent = String(model?.model_id || "<unknown>");

  const taskType = document.createElement("p");
  taskType.className = "model-catalog__task-type";
  taskType.textContent = `task_type: ${String(model?.task_type || "<unknown>")}`;

  item.append(modelId, taskType);
  return item;
}

// Возвращает текстовый блок статуса каталога моделей.
function createModelCatalogMessage(text) {
  const message = document.createElement("p");
  message.className = "model-catalog__message";
  message.textContent = text;
  return message;
}

// Возвращает shell поля формы с заголовком.
function createFieldShell(labelText) {
  const wrap = document.createElement("label");
  wrap.className = "form-field";

  const label = document.createElement("span");
  label.className = "form-field__label";
  label.textContent = labelText;

  wrap.appendChild(label);
  return wrap;
}

// Возвращает строку чекбокса.
function createCheckbox(inputId, text) {
  const label = document.createElement("label");
  label.className = "checkbox-line";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = inputId;

  const caption = document.createElement("span");
  caption.textContent = text;

  label.append(input, caption);
  return label;
}
