import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
feedData.accuracy = {
  n_partidos: 1,
  aciertos_1x2: 1,
  n_1x2: 1,
  pct_1x2: 100,
  metrics: [
    { key: "shots", label: "Remates", n: 1, mae: 1.0, sesgo: 1.0 },
    { key: "corners", label: "Córners", n: 1, mae: 2.0, sesgo: 2.0 },
  ],
  matches: [{
    id: "finished-1",
    date: "2026-08-24",
    home: "Atlético Madrid",
    away: "Valencia",
    result: [2, 1],
    predicted_sign: "1",
    actual_sign: "1",
    hit_1x2: true,
    stats_source: "API-Football · final",
    stats: [
      { key: "goals", label: "Goles", predicted: { home: 1.8, away: 0.9, total: 2.7 }, actual: { home: 2, away: 1, total: 3 }, delta: { home: 0.2, away: 0.1, total: 0.3 }, abs_error_total: 0.3 },
      { key: "shots", label: "Remates", predicted: { home: 13, away: 9, total: 22 }, actual: { home: 15, away: 8, total: 23 }, delta: { home: 2, away: -1, total: 1 }, abs_error_total: 1 },
      { key: "sot", label: "Tiros a puerta", predicted: { home: 5.2, away: 3.1, total: 8.3 }, actual: { home: 6, away: 2, total: 8 }, delta: { home: 0.8, away: -1.1, total: -0.3 }, abs_error_total: 0.3 },
      { key: "corners", label: "Córners", predicted: { home: 6, away: 4, total: 10 }, actual: { home: 7, away: 5, total: 12 }, delta: { home: 1, away: 1, total: 2 }, abs_error_total: 2 },
      { key: "fouls", label: "Faltas", predicted: { home: 12, away: 14, total: 26 }, actual: { home: 10, away: 16, total: 26 }, delta: { home: -2, away: 2, total: 0 }, abs_error_total: 0 },
      { key: "yellows", label: "Amarillas", predicted: { home: 2, away: 3, total: 5 }, actual: { home: 3, away: 2, total: 5 }, delta: { home: 1, away: -1, total: 0 }, abs_error_total: 0 },
      { key: "reds", label: "Rojas", predicted: { home: 0.1, away: 0.1, total: 0.2 }, actual: { home: 0, away: 1, total: 1 }, delta: { home: -0.1, away: 0.9, total: 0.8 }, abs_error_total: 0.8 },
    ],
  }],
};
const feed = JSON.stringify(feedData);

async function openDatos(page) {
  await page.route("**/dashboard.json?*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: feed,
  }));
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/");
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Datos y modelos", exact: true }).click();
  await expect(page.locator("h1.view-title")).toHaveText("Datos y modelos");
}

test("muestra estadísticas finales predicho vs real por partido", async ({ page }) => {
  await openDatos(page);

  await expect(page.getByText("Partidos finalizados · detalle predicho vs real", { exact: true })).toBeVisible();
  const table = page.locator(".accuracy-detail-table");
  await expect(table).toBeVisible();
  await expect(table.getByText("Atlético Madrid–Valencia", { exact: true })).toBeVisible();
  await expect(table.getByText("1→1 ✓", { exact: true })).toBeVisible();
  await expect(table.getByText("22→23", { exact: true })).toBeVisible();
  await expect(table.getByText("10→12", { exact: true })).toBeVisible();
  await expect(table.getByText("26→26", { exact: true })).toBeVisible();
  await expect(table.getByText("API-Football · final", { exact: false })).toBeVisible();
});
