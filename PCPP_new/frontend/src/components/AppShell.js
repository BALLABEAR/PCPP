import { createScreenTabs } from "./ScreenTabs.js";
import { createPipelineLaunchScreen } from "../screens/PipelineLaunchScreen.js";
import { createModelOnboardingScreen } from "../screens/ModelOnboardingScreen.js";
import { createTrainingScreen } from "../screens/TrainingScreen.js";
import { createPipelineBuilderScreen } from "../screens/PipelineBuilderScreen.js";

const SCREENS = [
  { id: "pipeline", label: "Запустить пайплайн", enabled: true },
  { id: "models", label: "Добавить модель", enabled: true },
  { id: "pipelines", label: "Добавить пайплайн", enabled: false },
  { id: "training", label: "Обучить модель", enabled: false },
];

// Создает главный shell приложения с верхней навигацией и областью контента.
export function createAppShell() {
  let activeScreenId = "pipeline";

  const app = document.createElement("main");
  app.className = "app-shell";

  const header = document.createElement("header");
  header.className = "app-shell__header";

  const title = document.createElement("h1");
  title.className = "app-shell__title";
  title.textContent = "Point Cloud Processing Platform";

  const subtitle = document.createElement("p");
  subtitle.className = "app-shell__subtitle";
  header.append(title, subtitle);

  const content = document.createElement("section");
  content.className = "app-shell__content";

  const render = () => {
    app.replaceChildren(
      header,
      createScreenTabs({
        screens: SCREENS,
        activeId: activeScreenId,
        onActivate: (nextId) => {
          activeScreenId = nextId;
          render();
        },
      }),
      content,
    );
    content.replaceChildren(createScreenById(activeScreenId));
  };

  render();
  return app;
}

// Возвращает экран по идентификатору.
function createScreenById(screenId) {
  if (screenId === "pipeline") {
    return createPipelineLaunchScreen();
  }
  if (screenId === "models") {
    return createModelOnboardingScreen();
  }
  if (screenId === "pipelines") {
    return createPipelineBuilderScreen();
  }
  if (screenId === "training") {
    return createTrainingScreen();
  }
  return createTrainingScreen();
}
