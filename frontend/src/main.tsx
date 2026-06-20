import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { HealthView } from "./components/HealthView";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("missing #root element");
}

createRoot(rootElement).render(
  <StrictMode>
    <HealthView />
  </StrictMode>,
);
