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
  let reloaded = false;
  // Si el SW controlador cambia (llega una versión nueva), recarga una vez para
  // servir el index.html y los assets frescos del último deploy.
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloaded) return;
    reloaded = true;
    window.location.reload();
  });
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" })
      .then((reg) => {
        reg.update();
        if (reg.waiting) reg.waiting.postMessage("skipWaiting");
        reg.addEventListener("updatefound", () => {
          const nw = reg.installing;
          if (nw) nw.addEventListener("statechange", () => {
            if (nw.state === "installed" && navigator.serviceWorker.controller) nw.postMessage("skipWaiting");
          });
        });
      })
      .catch(() => { /* ignore */ });
  });
}
