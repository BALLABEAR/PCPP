import React from "https://esm.sh/react@18.3.1";

export function SectionCard({ title, subtitle, actions, children, className = "" }) {
  return React.createElement("section", { className: `section-card ${className}`.trim() },
    (title || subtitle || actions) && React.createElement("div", { className: "section-card__header" },
      React.createElement("div", null,
        title && React.createElement("h3", { className: "section-card__title" }, title),
        subtitle && React.createElement("p", { className: "section-card__subtitle" }, subtitle),
      ),
      actions && React.createElement("div", { className: "section-card__actions" }, actions),
    ),
    children,
  );
}

export function Field({ label, hint, children, compact = false }) {
  return React.createElement("label", { className: compact ? "field field--compact" : "field" },
    label && React.createElement("span", { className: "field__label" }, label),
    children,
    hint && React.createElement("span", { className: "field__hint" }, hint),
  );
}

export function InlineHint({ children, tone = "default" }) {
  const className = tone === "warning"
    ? "inline-hint inline-hint--warning"
    : tone === "error"
      ? "inline-hint inline-hint--error"
      : "inline-hint";
  return React.createElement("p", { className }, children);
}

export function StatusBadge({ tone = "neutral", children }) {
  return React.createElement("span", { className: `status-badge status-badge--${tone}` }, children);
}

export function ActionBar({ children }) {
  return React.createElement("div", { className: "action-bar" }, children);
}

export function CollapsibleSection({ title, subtitle, defaultOpen = false, children }) {
  return React.createElement("details", { className: "collapsible", open: defaultOpen },
    React.createElement("summary", { className: "collapsible__summary" },
      React.createElement("div", null,
        React.createElement("span", { className: "collapsible__title" }, title),
        subtitle && React.createElement("span", { className: "collapsible__subtitle" }, subtitle),
      ),
    ),
    React.createElement("div", { className: "collapsible__body" }, children),
  );
}
