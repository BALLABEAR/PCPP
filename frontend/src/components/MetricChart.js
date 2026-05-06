import React from "https://esm.sh/react@18.3.1";

const CHART_COLORS = ["#c2410c", "#0f766e", "#1d4ed8", "#7c3aed"];

function buildPath(points, width, height, minValue, maxValue, maxStep) {
  if (points.length === 0) return "";
  const safeRange = maxValue > minValue ? (maxValue - minValue) : 1;
  const safeStep = maxStep > 0 ? maxStep : Math.max(points.length - 1, 1);
  return points.map((point, index) => {
    const x = (Number(point.step ?? index) / safeStep) * width;
    const y = height - (((point.value - minValue) / safeRange) * height);
    return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
}

export function MetricChart({ metricSeries, selectedTags, emptyText, seriesLabels = {} }) {
  const activeTags = selectedTags.filter((tag) => tag && Array.isArray(metricSeries?.[tag]) && metricSeries[tag].length > 0);
  if (activeTags.length === 0) {
    return React.createElement("p", { className: "muted" }, emptyText || "Метрики пока недоступны.");
  }

  const allPoints = activeTags.flatMap((tag) => metricSeries[tag].map((point, index) => ({
    ...point,
    _step: Number(point.step ?? index),
  })));
  const values = allPoints.map((point) => Number(point.value));
  const steps = allPoints.map((point) => point._step);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const maxStep = Math.max(...steps, 1);
  const width = 560;
  const height = 220;

  return React.createElement("div", { style: { border: "1px solid #d9e1ea", borderRadius: 16, padding: 14, background: "#fdfefe" } },
    React.createElement("svg", { viewBox: `0 0 ${width} ${height}`, style: { width: "100%", height: 220, display: "block" } },
      React.createElement("line", { x1: 0, y1: height - 1, x2: width, y2: height - 1, stroke: "#cbd5e1", strokeWidth: 1 }),
      React.createElement("line", { x1: 1, y1: 0, x2: 1, y2: height, stroke: "#cbd5e1", strokeWidth: 1 }),
      activeTags.map((tag, index) => {
        const points = metricSeries[tag] || [];
        const path = buildPath(points, width, height, minValue, maxValue, maxStep);
        return React.createElement("path", {
          key: tag,
          d: path,
          fill: "none",
          stroke: CHART_COLORS[index % CHART_COLORS.length],
          strokeWidth: 2,
          strokeLinejoin: "round",
          strokeLinecap: "round",
        });
      }),
    ),
    React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 12, marginTop: 8 } },
      activeTags.map((tag, index) => React.createElement("span", { key: tag, className: "muted" },
        React.createElement("span", {
          style: {
            display: "inline-block",
            width: 10,
            height: 10,
            background: CHART_COLORS[index % CHART_COLORS.length],
            borderRadius: "50%",
            marginRight: 6,
          },
        }),
        seriesLabels[tag] || tag,
      )),
    ),
    React.createElement("p", { className: "muted", style: { marginTop: 8 } }, `Диапазон: ${minValue.toFixed(4)} .. ${maxValue.toFixed(4)}. Max step: ${maxStep}.`),
  );
}
