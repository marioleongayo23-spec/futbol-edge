import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./premium.css";
import "./lineup-orientation.css";
import "./professional.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);

// La casilla gobierna el tema mediante CSS. Aquí solo guardamos la preferencia;
// no alteramos su estado para evitar dobles activaciones en móvil o PWA.
document.addEventListener("change", (event) => {
  if (!(event.target instanceof HTMLInputElement) || !event.target.matches(".theme-toggle")) return;
  try { localStorage.setItem("theme", event.target.checked ? "light" : "dark"); } catch { /* ignore */ }
});

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
  const swUrl = (import.meta.env.BASE_URL || "/") + "sw.js";
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(swUrl, { updateViaCache: "none" })
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
