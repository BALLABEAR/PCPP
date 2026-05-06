import React, { useEffect, useState } from "https://esm.sh/react@18.3.1";

import { getJson } from "./lib/api.js";
import { PipelineRunView } from "./views/PipelineRunView.js";
import { OnboardingView } from "./views/OnboardingView.js";
import { PipelineEditorView } from "./views/PipelineEditorView.js";
import { TrainingView } from "./views/TrainingView.js";

export function RootApp() {
  const [activeView, setActiveView] = useState("pipeline");
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState("");
  const [models, setModels] = useState([]);
  const [trainingProfiles, setTrainingProfiles] = useState([]);
  const [trainingError, setTrainingError] = useState("");
  const [error, setError] = useState("");

  async function refreshSharedData() {
    try {
      const templatePayload = await getJson("/pipelines/templates");
      const safeTemplates = Array.isArray(templatePayload) ? templatePayload : [];
      setTemplates(safeTemplates);
      setTemplateId((prev) => {
        const safeUsers = safeTemplates.filter((item) => item.source === "user");
        return prev || safeUsers[0]?.id || "";
      });
    } catch (e) {
      setError(`Failed to load templates: ${e.message}`);
    }

    try {
      const modelPayload = await getJson("/registry/models");
      setModels(Array.isArray(modelPayload) ? modelPayload : []);
    } catch (e) {
      setError(`Failed to load model catalog: ${e.message}`);
    }

    try {
      const profilePayload = await getJson("/training/profiles");
      const profiles = Array.isArray(profilePayload?.profiles) ? profilePayload.profiles : [];
      setTrainingProfiles(profiles);
    } catch (e) {
      setTrainingError(`Failed to load training profiles: ${e.message}`);
    }
  }

  useEffect(() => {
    refreshSharedData();
  }, []);

  return React.createElement(
    "div",
    { className: "container" },
    React.createElement("header", { className: "app-header" },
      React.createElement("p", { className: "eyebrow" }, "PCPP Workspace"),
      React.createElement("h1", { className: "page-title" }, "Point Cloud Processing Platform"),
      React.createElement("p", { className: "page-subtitle" }, "Единая рабочая панель для пайплайнов, онбординга моделей и запуска обучения без переключения между разрозненными утилитами."),
    ),
    React.createElement("div", { className: "workspace-shell" },
      React.createElement("div", { className: "top-menu" },
        React.createElement("button", {
          className: activeView === "pipeline" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("pipeline"),
        }, "Запустить пайплайн"),
        React.createElement("button", {
          className: activeView === "add-model" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("add-model"),
        }, "Добавить модель"),
        React.createElement("button", {
          className: activeView === "add-pipeline" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("add-pipeline"),
        }, "Добавить пайплайн"),
        React.createElement("button", {
          className: activeView === "train-model" ? "menu-button active" : "menu-button",
          onClick: () => setActiveView("train-model"),
        }, "Обучение моделей"),
      ),
      React.createElement("div", { className: "view-stage" },
        error && React.createElement("p", { style: { color: "crimson" } }, error),
        trainingError && activeView === "train-model" && React.createElement("p", { style: { color: "crimson" } }, trainingError),
        activeView === "pipeline" && React.createElement(PipelineRunView, {
          templates,
          setTemplates,
          templateId,
          setTemplateId,
          models,
          setModels,
        }),
        activeView === "add-model" && React.createElement(OnboardingView, { onRefreshData: refreshSharedData }),
        activeView === "add-pipeline" && React.createElement(PipelineEditorView, {
          models,
          setTemplates,
          setTemplateId,
        }),
        activeView === "train-model" && React.createElement(TrainingView, { trainingProfiles }),
      ),
    ),
  );
}
