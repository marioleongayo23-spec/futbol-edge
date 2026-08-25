import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = feedData.matches.find((match) => !match.finished && Array.isArray(match.probs)) || feedData.matches[0];
if (!target) throw new Error("El feed E2E necesita al menos un partido");

const kickoffMs = new Date(target.kickoff).getTime();
const at = (hoursBefore) => new Date(kickoffMs - hoursBefore * 3600_000).toISOString();
const components = {
  dixon_coles: { "1": 0.50, X: 0.30, "2": 0.20 },
  elo: { "1": 0.57, X: 0.25, "2": 0.18 },
};
const base = (window, hoursBefore, probs) => ({
  window,
  generated_at: at(hoursBefore),
  probs,
  model_probs: probs.map(Number),
  xg: [1.62, 0.94],
  model_version: "edge-2.0",
  model_meta: { version: "edge-2.0", components },
});

const history = [
  base("initial", 36, [48, 31, 21]),
  base("T-24h", 24, [49, 31, 20]),
  base("T-12h", 12, [51, 30, 19]),
  base("T-6h", 6, [52, 29, 19]),
];
const official = {
  ...base("official_lineup", 1.25, [56, 25, 19]),
  model_probs: [52, 28, 20],
  market_calibration: { model_weight: 0.70, market_weight: 0.30, temperature: 1.05 },
  lineup_impact: {
    evidence: "alta",
    confidence_penalty_pp: 3,
    probability_adjustment: "not_applied",
    home: {}, away: {},
  },
  alineacion: { status: "confirmado", provider: "API-Football" },
  weather_adjustment: {
    applied: true,
    multipliers: { goals: 0.95, shots: 0.96, fouls: 1.03, cards: 1.04 },
    xg: { before: [1.70, 1.00], after: [1.62, 0.94], delta: [-0.08, -0.06] },
    one_x_two_adjusted: false,
  },
};

target.probs = [56, 25, 19];
target.model_probs = [52, 28, 20];
target.xg = [1.62, 0.94];
target.model_meta = official.model_meta;
target.market_calibration = official.market_calibration;
target.lineup_impact = official.lineup_impact;
target.alineacion = official.alineacion;
target.weather_adjustment = official.weather_adjustment;
target.prediction_history = [...history, official];
target.prediction_snapshot = official;
target.value = [
  { market: "1x2", selection: "1", odds: 2.05, modelProb: 0.56, edge: 0.148 },
  { market: "1x2", selection: "X", odds: 3.40, modelProb: 0.25, edge: -0.15 },
];
const feed = JSON.stringify(feedData);

async function openApp(page) {
  await page.route("**/dashboard.json?*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: feed }));
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/");
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Partidos", exact: true }).click();
  const row = page.locator('tr[role="button"]').filter({ hasText: target.home }).filter({ hasText: target.away }).first();
  await row.click();
}

test("Match Intelligence enseña solo hitos reales y deltas auditables", async ({ page }) => {
  await openApp(page);
  const panel = page.getByTestId("prediction-timeline-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("5 capturas reales", { exact: true })).toBeVisible();
  await expect(panel.locator(".pt-window")).toHaveText(["Primera captura", "T−24h", "T−12h", "T−6h", "Once oficial"]);
  await expect(panel.getByText("Motor puro · 1", { exact: true })).toBeVisible();
  await expect(panel.getByText("52.0%", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("Publicada", { exact: true })).toBeVisible();
  await expect(panel.getByText("56.0%", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("+4.0 pp", { exact: true })).toBeVisible();
  await expect(panel.getByText("0.0 pp 1X2", { exact: true })).toHaveCount(2);
  await expect(panel.getByText(/Δ xG total -0.14/)).toBeVisible();
  await expect(panel.getByText(/Última revisión:/)).toContainText("T−6h");
  await expect(panel.getByText(/Última revisión:/)).toContainText("Once oficial");
  await expect(panel.locator(".audit-drivers")).not.toContainText("Forma reciente");
  await expect(panel.locator(".audit-drivers")).not.toContainText("Descanso");
});
