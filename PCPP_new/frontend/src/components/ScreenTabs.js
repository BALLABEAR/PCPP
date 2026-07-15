// Возвращает панель вкладок верхнего уровня.
// Неактивные вкладки не переключают экран и показывают подсказку.
export function createScreenTabs({ screens, activeId, onActivate }) {
  const nav = document.createElement("nav");
  nav.className = "screen-tabs";
  nav.setAttribute("aria-label", "Навигация по экранам");

  for (const screen of screens) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "screen-tabs__button";
    button.textContent = screen.label;
    button.dataset.active = String(screen.id === activeId);
    button.disabled = !screen.enabled;

    if (!screen.enabled) {
      button.title = "Будет позже";
    } else {
      button.addEventListener("click", () => onActivate(screen.id));
    }
    nav.appendChild(button);
  }

  return nav;
}
