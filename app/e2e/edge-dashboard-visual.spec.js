import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

// Test a predictable, real-structure fixture without live APIs or added costs.
const feed = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const LEAGUES = ["LaLiga", "LaLiga Hypermotion", "Champions League"];
const candidates = LEAGUES.map(league =>
  feed.matches.find(m => m.league === league && Array.isArray(m.probs)));
if (candidates.some(m => !m)) throw new Error("Real feed fixtures missing for visual QA");

test("redesigned matchday: filter, navigation, spacing and no horizontal overflow", async ({ page }, testInfo) => {
  const kickoff = new Date(Date.now() + 6 * 3600_000);
  const date = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Madrid", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(kickoff);
  const sample = structuredClone(feed);
  sample.generated_at = new Date().toISOString();
  // The production guard intentionally rejects feeds smaller than 20 matches.
  // Retain 20+ realistic historical fixtures while fixing three upcoming matches
  // on the selected date, so the UI is really exercising the normal fetch guard.
  sample.matches = [
    ...feed.matches.slice(0, 21).map(m => ({ ...m, date: "2025-01-01" })),
    ...candidates.map((m, i) => ({
      ...m, id: "e2e-edge-" + i, date, kickoff: kickoff.toISOString(),
      finished: false, result: null, probs: [58, 24, 18], xg: [1.4, 0.9],
    })),
  ];
  sample.counts = { ...(sample.counts || {}), total: sample.matches.length };
  await page.route("**/dashboard.json*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(sample),
  }));
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Partido destacado" })).toBeVisible();
  const leagueFilter = page.getByRole("group", { name: "Filtrar partidos por competición" });
  await expect(leagueFilter.getByRole("button", { name: /^Todos/ })).toBeVisible();
  await expect(page.locator(".day-matches .mrow")).toHaveCount(3);
  const allShot = await page.screenshot({ fullPage: true, animations: "disabled" });
  await testInfo.attach("edge-dashboard-all-" + testInfo.project.name, { body: allShot, contentType: "image/png" });
  await leagueFilter.getByRole("button", { name: /^Segunda/ }).click();
  await expect(page.locator(".day-matches .mrow")).toHaveCount(1);
  await expect(leagueFilter.getByRole("button", { name: /^Segunda/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".day-matches .mrow")).toContainText([sample.matches[1].home]);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "The app must not scroll horizontally at this breakpoint").toBeLessThanOrEqual(1);
  await testInfo.attach("edge-dashboard-filtered-" + testInfo.project.name, {
    body: await page.screenshot({ fullPage: true, animations: "disabled" }), contentType: "image/png",
  });
});
