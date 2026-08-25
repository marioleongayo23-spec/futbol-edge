import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = feedData.matches.find((match) => match.finished) || feedData.matches[0];
if (!target) throw new Error("El feed E2E necesita al menos un partido");
target.finished = true;
target.status = "FINISHED";
target.result = target.result || [1, 0];
target.closing_odds = {
  source: "football-data.co.uk",
  market_source: "market_average",
  is_real: true,
  capture_kind: "historical_provider_close",
  captured_at: "2026-08-24T20:00:00+02:00",
  "1x2": { "1": 2.2, X: 3.4, "2": 3.5 },
};
const feed = JSON.stringify(feedData);
const bet = {
  id: 999001,
  date: "2026-08-24",
  match: `${target.home} - ${target.away}`,
  matchId: target.id,
  sel: "1",
  odds: 2.5,
  stake: 20,
  result: "won",
};

async function gotoPortfolio(page) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) {
    await page.getByRole("button", { name: "Abrir menú" }).click();
  }
  await page.locator(".snav").getByRole("button", { name: "Mi cartera", exact: true }).click();
}

test("la cartera calcula CLV solo contra un cierre real", async ({ page }) => {
  await page.route("**/dashboard.json?*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: feed,
  }));
  await page.addInitScript((storedBet) => {
    localStorage.setItem("fe_bets_v1", JSON.stringify([storedBet]));
    localStorage.setItem("fe_bank0_v1", JSON.stringify(1000));
  }, bet);
  await page.goto("/");
  await gotoPortfolio(page);

  await expect(page.getByText("CLV histórico", { exact: true })).toBeVisible();
  await expect(page.getByText("+13.64%", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("2.20", { exact: true })).toBeVisible();
  await expect(page.getByText(/media de mercado/)).toBeVisible();
  await expect(page.getByText(/CLV positivo indica que se batió al mercado/)).toBeVisible();
});
