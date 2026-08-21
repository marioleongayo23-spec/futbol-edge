import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import App from "./App.jsx";

// Aplica el tema guardado antes del primer render para evitar parpadeo.
try {
  document.documentElement.dataset.theme = localStorage.getItem("theme") || "dark";
} catch { /* ignore */ }

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);

// Registro del service worker (PWA / offline). Solo en producción.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* ignore */ });
  });
}
