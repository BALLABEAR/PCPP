import { createComingSoon } from "../components/ComingSoon.js";

// Возвращает экран добавления пайплайна.
export function createPipelineBuilderScreen() {
  const section = document.createElement("section");
  section.className = "screen";

  const heading = document.createElement("h2");
  heading.className = "screen__title";
  heading.textContent = "Добавить пайплайн";

  section.append(heading, createComingSoon("Будет позже"));
  return section;
}
