import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = feedData.matches.find((match) => !match.finished && Array.isArray(match.probs)) || feedData.matches[0];
if (!target) throw new Error("El feed E2E necesita al menos un partido");

const makeProps = (prefix) => Array.from({ length: 11 }, (_, index) => ({
  jugador: `${prefix} ${index + 1}`,
  g: +(0.05 * index).toFixed(2),
  a: +(0.03 * index).toFixed(2),
  r: +(1.0 + 0.2 * index).toFixed(2),
  rp: +(0.4 + 0.1 * index).toFixed(2),
  fc: +(0.8 + 0.1 * index).toFixed(2),
  fr: +(0.7 + 0.1 * index).toFixed(2),
  t: +(0.05 + 0.02 * index).toFixed(2),
  min: 81,
  tit: 1,
  sample_minutes: 900,
  source: "API-Football · players",
}));

const localProps = makeProps("Local Real");
const awayProps = makeProps("Visitante Real");
target.alineacion = {
  ...(target.alineacion || {}),
  local: localProps.map((row) => row.jugador),
  visitante: awayProps.map((row) => row.jugador),
  posiciones_local: ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"],
  posiciones_visitante: ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"],
  clave_local: localProps,
  clave_visitante: awayProps,
  best_props: [
    { jugador: "Local Real 11", lado: "local", motivo: "muestra real" },
    { jugador: "Visitante Real 11", lado: "visitante", motivo: "muestra real" },
  ],
  status: "confirmado",
  provider: "API-Football",
  player_props_source: "API-Football · players",
  quality: { complete: true, real_player_props: 22, props_players: 22, score: 1 },
};
const feed = JSON.stringify(feedData);

async function gotoMatches(page) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Partidos", exact: true }).click();
}

test("la ficha muestra props reales de los 22 titulares cuando existe muestra", async ({ page }) => {
  await page.route("**/dashboard.json?*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: feed }));
  await page.goto("/");
  await gotoMatches(page);
  const row = page.locator('tr[role="button"]').filter({ hasText: target.home }).filter({ hasText: target.away }).first();
  await row.click();

  await expect(page.getByText(`${target.home} · titulares con muestra real 11/11`, { exact: true })).toBeVisible();
  await expect(page.getByText(`${target.away} · titulares con muestra real 11/11`, { exact: true })).toBeVisible();
  await expect(page.locator(".xi-props .props-tbl tbody tr")).toHaveCount(22);
  await expect(page.getByText("Local Real 1", { exact: true })).toBeVisible();
  await expect(page.getByText("Local Real 11", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Visitante Real 11", { exact: false }).first()).toBeVisible();
});
