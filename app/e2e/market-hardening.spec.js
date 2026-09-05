import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = feedData.matches.find((match) => !match.finished && Array.isArray(match.probs)) || feedData.matches[0];
if (!target) throw new Error("El feed E2E necesita al menos un partido");

target.weather_adjustment = {
  applied: true,
  reasons: ["viento 30 km/h", "lluvia probable/intensa"],
  multipliers: { goals: 0.93, shots: 0.93, fouls: 1.05, cards: 1.07 },
  xg: { before: [1.8, 1.1], after: [1.67, 1.02], delta: [-0.13, -0.08] },
  one_x_two_adjusted: false,
};
feedData.value_ranking = [
  { match_id: target.id, home: target.home, away: target.away, league: target.league, market: "btts", selection: "Yes", odds: 2.15, modelProb: 0.55, edge: 0.1825, bookmaker: "Book A" },
  { match_id: target.id, home: target.home, away: target.away, league: target.league, market: "alternate_totals_corners", selection: "Over", line: 9.5, odds: 2.05, modelProb: 0.54, edge: 0.107, bookmaker: "Book B" },
  { match_id: target.id, home: target.home, away: target.away, league: target.league, market: "player_shots", selection: "Over", line: 2.5, player: "Jugador Real", odds: 2.30, modelProb: 0.49, edge: 0.127, bookmaker: "Book C" },
];
feedData.historical_seed = {
  laliga: {
    scope: "historical_seed", evaluation_season: 2025, current_season: 2026,
    market_calibration: { accepted: true, n: 320, production: { model_weight: 0.63, market_weight: 0.37, temperature: 1.02 } },
    probability_quality: {
      model_only: { n: 320, log_loss: 0.99, brier: 0.205, rps: 0.222, accuracy: 45.3 },
      market: { n: 320, log_loss: 0.95, brier: 0.198, rps: 0.214, accuracy: 47.5 },
      published_seed: { n: 320, log_loss: 0.93, brier: 0.194, rps: 0.209, accuracy: 48.1 },
    },
  },
};
const feed = JSON.stringify(feedData);

async function openApp(page) {
  await page.route("**/dashboard.json*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: feed }));
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/");
}

async function nav(page, name) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name, exact: true }).click();
}

test("ranking global muestra solo señales con cuota real", async ({ page }) => {
  await openApp(page);
  await nav(page, "Value bets");
  const panel = page.getByTestId("global-value-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Ambos marcan", { exact: true })).toBeVisible();
  await expect(panel.getByText("Córners", { exact: true })).toBeVisible();
  await expect(panel.getByText("Remates jugador", { exact: true })).toBeVisible();
  await expect(panel.getByText("+18.3%", { exact: true })).toBeVisible();
  await expect(panel.getByText("Book A", { exact: true })).toBeVisible();
});

test("datos separa la semilla histórica de la temporada actual", async ({ page }) => {
  await openApp(page);
  await nav(page, "Datos y modelos");
  const panel = page.getByTestId("historical-quality-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("2025/26 · histórico", { exact: true })).toBeVisible();
  await expect(panel.getByText("Publicada sembrada", { exact: true })).toBeVisible();
  await expect(panel.getByText("320", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("aceptado", { exact: true })).toBeVisible();
});

test("detalle enseña delta cuantificado del clima", async ({ page }) => {
  await openApp(page);
  await nav(page, "Partidos");
  const row = page.locator('tr[role="button"]').filter({ hasText: target.home }).filter({ hasText: target.away }).first();
  await row.click();
  const panel = page.getByTestId("weather-adjustment-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Goles/xG", { exact: true })).toBeVisible();
  await expect(panel.getByText("-7.0%", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText(/xG:/)).toBeVisible();
  await expect(panel.getByText(/viento 30 km\/h/)).toBeVisible();
});
