import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const baseFeed = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = baseFeed.matches.find((match) => !match.finished) || baseFeed.matches[0];
if (!target) throw new Error("El feed E2E necesita al menos un partido");

const richPlayers = Array.from({ length: 6 }, (_, index) => ({
  player: index === 5 ? "Álex Intelligence" : `Atacante Peer ${index + 1}`,
  team: index === 5 ? target.home : `Club Peer ${index + 1}`,
  position: "Attacker",
  goals: index + 1,
  assists: index,
  shots: 20 + index,
  yc: 1,
  min: 900,
  source: "Understat",
  player_id: 9000 + index,
  profile: index === 5 ? {
    photo: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Crect width='120' height='120' fill='%23222'/%3E%3C/svg%3E",
    age: 24,
    nationality: "España",
    height: "181 cm",
    weight: "75 kg",
  } : {},
  rating: 6.5 + index / 10,
  pass_accuracy_pct: 78 + index,
  expected_minutes: 82,
  starter_probability: 1,
  sample_minutes: 900,
  season: {
    minutes: 900,
    appearances: 12,
    starts: 10,
    starter_rate: 10 / 12,
    expected_start_minutes: 82,
    per90: {
      g: 0.1 + index * 0.08,
      a: 0.05 + index * 0.03,
      r: 1.5 + index * 0.3,
      rp: 0.5 + index * 0.15,
      fc: 1.2 - index * 0.05,
      fr: 0.8 + index * 0.12,
      t: 0.08,
    },
    per90_extended: {
      passes: 24 + index,
      key_passes: 0.4 + index * 0.2,
      tackles: 0.3 + index * 0.08,
      interceptions: 0.15 + index * 0.05,
      duels: 4 + index * 0.4,
      duels_won: 2 + index * 0.3,
      dribbles_success: 0.5 + index * 0.2,
      saves: 0,
    },
  },
  expected_match: index === 5 ? { g: 0.42, a: 0.18, r: 3.1, rp: 1.4, fc: 0.8, fr: 1.5, t: 0.07 } : {},
  rich_source: "API-Football · players",
}));

const feedData = structuredClone(baseFeed);
feedData.players = {
  laliga: {
    label: "LaLiga",
    players: richPlayers,
    rankings: {
      goals: {
        label: "Goleadores",
        players: [{ rank: 1, player: "Álex Intelligence", team: target.home, value: 6 }],
      },
    },
  },
};
const feed = JSON.stringify(feedData);

async function openPlayers(page) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Jugadores", exact: true }).click();
}

test("abre una ficha premium de jugador con datos reales y percentiles posicionales", async ({ page }) => {
  await page.route("**/dashboard.json*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: feed }));
  await page.goto("/");
  await openPlayers(page);

  const row = page.locator('.players-grid tr[role="button"]').filter({ hasText: "Álex Intelligence" }).first();
  await expect(row).toBeVisible();
  await row.click();

  const profile = page.getByTestId("player-profile");
  await expect(profile).toBeVisible();
  await expect(profile.getByRole("heading", { name: "Álex Intelligence" })).toBeVisible();
  await expect(profile.getByText("España", { exact: true })).toBeVisible();
  await expect(profile.getByText("Percentiles por posición", { exact: true })).toBeVisible();
  await expect(profile.getByText(/P\d+ de su posición/).first()).toBeVisible();
  await expect(profile.getByText("API-Football · players", { exact: false })).toBeVisible();
  await expect(profile.getByText("3.10", { exact: false })).toBeVisible();

  await profile.getByRole("button", { name: "← Volver" }).click();
  await expect(page.getByText("Ranking de jugadores", { exact: false })).toBeVisible();
});
