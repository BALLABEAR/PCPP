import React from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";

import { RootApp } from "./RootApp.js";

function renderBootstrapError(message, detail = "") {
  const root = document.getElementById("root");
  if (!root) return;
  root.innerHTML = `
    <div style="font-family: monospace; padding: 24px; color: #7f1d1d; background: #fff5f5;">
      <h2 style="margin-top: 0;">Frontend runtime error</h2>
      <pre style="white-space: pre-wrap;">${String(message || "Unknown error")}</pre>
      ${detail ? `<pre style="white-space: pre-wrap; color: #444;">${String(detail)}</pre>` : ""}
    </div>
  `;
}

window.addEventListener("error", (event) => {
  renderBootstrapError(event.message, event.error?.stack || "");
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  renderBootstrapError(reason?.message || String(reason || "Unhandled rejection"), reason?.stack || "");
});

try {
  createRoot(document.getElementById("root")).render(React.createElement(RootApp));
} catch (error) {
  renderBootstrapError(error?.message || String(error), error?.stack || "");
}
