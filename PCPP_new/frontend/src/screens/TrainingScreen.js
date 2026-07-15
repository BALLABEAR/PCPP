import { createComingSoon } from "../components/ComingSoon.js";

// Возвращает экран обучения моделей.
export function createTrainingScreen() {
  const section = document.createElement("section");
  section.className = "screen";

  const heading = document.createElement("h2");
  heading.className = "screen__title";
  heading.textContent = "Обучение моделей";

  section.append(heading, createComingSoon("Будет позже"));
  return section;
}
