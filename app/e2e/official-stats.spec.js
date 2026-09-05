import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = feedData.matches.find((match) => !match.finished && Array.isArray(match.probs));
if (!target) throw new Error("El fixture E2E necesita un partido próximo con predicción");

target.official_context = {
  ...(target.official_context || {}),
  provider: "API-Football",
  referee: "Javier Alberola Rojas, Spain",
  live_or_post_stats: {
    [target.home]: {
      shots: 16, sot: 7, corners: 8, fouls: 11, yellows: 2, reds: 0,
      possession: 58, passes: 512, passes_accurate: 451, pass_accuracy: 88,
    },
    [target.away]: {
      shots: 9, sot: 3, corners: 4, fouls: 15, yellows: 4, reds: 1,
      possession: 42, passes: 386, passes_accurate: 319, pass_accuracy: 83,
    },
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

async function gotoMatches(page) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Partidos", exact: true }).click();
  await expect(page.locator("h1.view-title")).toHaveText("Partidos");
}

test("la ficha muestra estadísticas oficiales live/post separadas del pronóstico", async ({ page }) => {
  await openApp(page);
  await gotoMatches(page);
  const row = page.locator('tr[role="button"]').filter({ hasText: target.home }).filter({ hasText: target.away }).first();
  await row.click();

  const panel = page.locator('[data-source="api-football-live-stats"]');
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Estadísticas oficiales API-Football", { exact: true })).toBeVisible();
  await expect(panel.getByText("EN VIVO", { exact: true })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Remates 16 9/ })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Tiros a puerta 7 3/ })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Córners 8 4/ })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Faltas 11 15/ })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Amarillas 2 4/ })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Rojas 0 1/ })).toBeVisible();
  await expect(panel.getByRole("row", { name: /Posesión 58% 42%/ })).toBeVisible();
  await expect(panel.getByText(/no alimenta retrospectivamente la predicción prepartido/i)).toBeVisible();
  await expect(page.getByText(/Javier Alberola Rojas/)).toBeVisible();
});
