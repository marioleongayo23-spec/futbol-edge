import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
feedData.performance ||= {};
feedData.performance.probability_quality = {
  published: { n: 12, log_loss: 0.91, brier: 0.188, rps: 0.201, accuracy: 50.0 },
  model_only: { n: 12, log_loss: 0.99, brier: 0.204, rps: 0.223, accuracy: 41.7 },
  market: { n: 8, log_loss: 0.88, brier: 0.181, rps: 0.194, accuracy: 50.0 },
  published_vs_model: {
    baseline: "model_only", n: 12,
    log_loss_delta: -0.08, brier_delta: -0.016, rps_delta: -0.022,
    improved_both: true,
  },
  published_vs_market: {
    baseline: "market", n: 8,
    log_loss_delta: 0.03, brier_delta: 0.007, rps_delta: 0.007,
    improved_both: false,
  },
};
const feed = JSON.stringify(feedData);

async function openApp(page) {
  await page.route("**/dashboard.json*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: feed,
  }));
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/");
  await expect(page.locator("h1.view-title")).toHaveText("Resumen");
}

async function gotoDatos(page) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) {
    await page.getByRole("button", { name: "Abrir menú" }).click();
  }
  await page.locator(".snav").getByRole("button", { name: "Datos y modelos", exact: true }).click();
  await expect(page.locator("h1.view-title")).toHaveText("Datos y modelos");
}

test("muestra modelo puro, publicada y mercado con cautela por tamaño de muestra", async ({ page }) => {
  await openApp(page);
  await gotoDatos(page);

  const panel = page.getByTestId("probability-quality-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Probabilidad publicada", { exact: true })).toBeVisible();
  await expect(panel.getByText("Modelo puro", { exact: true })).toBeVisible();
  await expect(panel.getByText("Mercado sin margen", { exact: true })).toBeVisible();
  await expect(panel.getByText("muestra preliminar", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("muestra insuficiente", { exact: true }).first()).toBeVisible();

  await expect(panel.getByText("Publicada vs modelo puro", { exact: true })).toBeVisible();
  await expect(panel.getByText("-0.0800", { exact: true })).toBeVisible();
  await expect(panel.getByText(
    "La publicada mejora simultáneamente LogLoss y RPS en esta muestra pareada.",
    { exact: true },
  )).toBeVisible();

  await expect(panel.getByText("Publicada vs mercado", { exact: true })).toBeVisible();
  await expect(panel.getByText("+0.0300", { exact: true })).toBeVisible();
  await expect(panel.getByText(
    "La publicada todavía no mejora simultáneamente LogLoss y RPS frente a esta referencia.",
    { exact: true },
  )).toBeVisible();
});
