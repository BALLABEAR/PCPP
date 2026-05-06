import React from "https://esm.sh/react@18.3.1";

const DEFAULT_STYLE = {
  maxHeight: 220,
  overflow: "auto",
  background: "#f8fafc",
  padding: 14,
  borderRadius: 14,
  border: "1px solid #d9e1ea",
  color: "#445467",
  lineHeight: 1.5,
};

export function LogPanel({ text, emptyText, style }) {
  return React.createElement(
    "pre",
    { className: "muted", style: { ...DEFAULT_STYLE, ...(style || {}) } },
    text || emptyText,
  );
}
