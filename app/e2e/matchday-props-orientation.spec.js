import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const baseFeed = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const baseTarget = baseFeed.matches.find((match) => !match.finished && Array.isArray(match.probs)) || baseFeed.matches[0];
if (!baseTarget) throw new Error("El feed E2E necesita al menos un partido");

const positions = ["POR", "LI", "DFC", "DFC", "LD", "MCD", "MC", "MP", "EI", "DC", "ED"];
const homeNames = ["Portero Local", "Lateral Izquierdo Local", "Central Uno Local", "Central Dos Local", "Lateral Derecho Local", "Pivote Local", "Medio Local", "Mediapunta Local", "Extremo Izquierdo Local", "Delantero Local", "Extremo Derecho Local"];
const awayNames = ["Portero Visitante", "Lateral Izquierdo Visitante", "Central Uno Visitante", "Central Dos Visitante", "Lateral Derecho Visitante", "Pivote Visitante", "Medio Visitante", "Mediapunta Visitante", "Extremo Izquierdo Visitante", "Delantero Visitante", "Extremo Derecho Visitante"];

const modelRows = (names) => names.map((jugador, index) => ({
  jugador,
  g: +(0.04 + index * 0.03).toFixed(2),
  a: +(0.03 + index * 0.02).toFixed(2),
  r: +(0.5 + index * 0.15).toFixed(2),
  rp: +(0.2 + index * 0.07).toFixed(2),
  fc: +(0.6 + index * 0.08).toFixed(2),
  fr: +(0.5 + index * 0.08).toFixed(2),
  t: +(0.05 + index * 0.01).toFixed(2),
  min: 82,
  tit: .88,
  sample_minutes: 0,
  source: "Modelo · rol + predicción de equipo",
  evidence_type: "model_estimate",
}));

function matchdayFeed() {
  const feed = structuredClone(baseFeed);
  const target = feed.matches.find((match) => match.id === baseTarget.id);
  target.alineacion = {
    ...(target.alineacion || {}),
    local: homeNames,
    visitante: awayNames,
    posiciones_local: positions,
    posiciones_visitante: positions,
    clave_local: modelRows(homeNames),
    clave_visitante: modelRows(awayNames),
    best_props: [],
    status: "probable",
    provider: "Prensa + modelo",
    source_quality: "media_grounded",
    lineup_kind: "source_grounded_probable",
    evidence_scope: "trusted_media_both_sides",
    lineup_evidence: {
      policy: "both_sides_required_for_probable",
      level: "trusted_media_both_sides",
      local: { grounded: true, sources: [{ source: "Fuente test", published_at: "2026-08-28T10:00:00Z" }] },
      visitante: { grounded: true, sources: [{ source: "Fuente test", published_at: "2026-08-28T10:00:00Z" }] },
    },
    player_props_source: "Predictivo híbrido · 0/22 con muestra individual real",
    quality: { complete: true, predicted_player_props: 22, real_player_props: 0, props_players: 22 },
  };
  return { feed, target };
}

async function gotoMatch(page, target) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Partidos", exact: true }).click();
  const row = page.locator('tr[role="button"]').filter({ hasText: target.home }).filter({ hasText: target.away }).first();
  await row.click();
}

test("las predicciones individuales híbridas aparecen para los 22 jugadores", async ({ page }) => {
  const { feed, target } = matchdayFeed();
  await page.route("**/dashboard.json*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(feed) }));
  await page.goto("/");
  await gotoMatch(page, target);

  const rows = page.locator(".xi-props .props-tbl tbody tr");
  await expect(rows).toHaveCount(22);
  await expect(rows.filter({ hasText: "Delantero Local" }).first()).toContainText("Modelo · rol + predicción de equipo");
  await expect(rows.filter({ hasText: "Lateral Derecho Visitante" }).first()).toContainText("Modelo · rol + predicción de equipo");
});

test("LI queda visualmente a la izquierda y LD a la derecha también en el visitante", async ({ page }) => {
  const { feed, target } = matchdayFeed();
  await page.route("**/dashboard.json*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(feed) }));
  await page.goto("/");
  await gotoMatch(page, target);

  const away = page.locator(".pitch-half.away");
  const li = away.locator('.player[title$="· LI"]').first();
  const ld = away.locator('.player[title$="· LD"]').first();
  await expect(li).toBeVisible();
  await expect(ld).toBeVisible();
  const liBox = await li.boundingBox();
  const ldBox = await ld.boundingBox();
  expect(liBox).not.toBeNull();
  expect(ldBox).not.toBeNull();
  expect(liBox.x).toBeLessThan(ldBox.x);
});
