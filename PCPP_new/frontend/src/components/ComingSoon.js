// Возвращает универсальную заглушку для временно неготовых разделов.
export function createComingSoon(message = "Будет позже") {
  const wrap = document.createElement("div");
  wrap.className = "coming-soon";

  const title = document.createElement("p");
  title.className = "coming-soon__title";
  title.textContent = message;

  const hint = document.createElement("p");
  hint.className = "coming-soon__hint";
  hint.textContent = "Раздел будет реализован позже.";

  wrap.append(title, hint);
  return wrap;
}
