import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const target = feedData.matches.find((match) => !match.finished && Array.isArray(match.probs)) || feedData.matches[0];
if (!target) throw new Error("El feed E2E necesita al menos un partido");

const team = target.home;
const rival = target.away;
target.finished = false;
target.kickoff = new Date(Date.now() + 24 * 36e5).toISOString();
target.probs = [.58, .24, .18];
target.xg = [1.86, .92];
target.venue = "Estadio Intelligence";

const style = (offset = 0) => ({
  attack_volume: { label: "Volumen ofensivo", score: 76 + offset, observed: 14.2, unit: "remates" },
  territorial_pressure: { label: "Presión territorial", score: 68 + offset, observed: 5.7, unit: "córners" },
  defensive_exposure: { label: "Exposición defensiva", score: 37 + offset, observed: 9.8, unit: "remates concedidos" },
  finishing_efficiency: { label: "Eficacia de remate", score: 71 + offset, observed: .36, unit: "AP/remate" },
  contact_intensity: { label: "Intensidad de contacto", score: 59 + offset, observed: 13.9, unit: "faltas" },
});

const xiNow = ["Keeper Test", "Def 1", "Def 2", "Def 3", "Def 4", "Mid 1", "Mid 2", "Mid 3", "Álex Team", "Wing Test", "Striker Test"];
target.tactical_matchup = {
  home: { style_vector: style(0), samples: 10 },
  away: { style_vector: style(-8), samples: 10 },
  style_clashes: [{ edge: "attack", label: "Volumen local vs exposición rival", strength: 81 }],
};
target.alineacion = {
  ...(target.alineacion || {}),
  local: xiNow,
  visitante: Array.from({ length: 11 }, (_, i) => `Rival ${i + 1}`),
  bajas_local: [{ jugador: "Baja Confirmada" }],
  status: "probable",
};

let historical = feedData.matches.find((match) => match.id !== target.id && match.finished && (match.home === team || match.away === team));
if (!historical) historical = feedData.matches.find((match) => match.id !== target.id && match.finished) || feedData.matches.find((match) => match.id !== target.id);
if (historical) {
  historical.finished = true;
  historical.home = historical.home === team ? team : "Rival Histórico";
  historical.away = historical.home === team ? "Rival Histórico" : team;
  historical.result = [1, 1];
  historical.kickoff = new Date(Date.now() - 7 * 24 * 36e5).toISOString();
  const isHome = historical.home === team;
  historical.tactical_matchup = {
    home: { style_vector: isHome ? style(-2) : style(-5), samples: 9 },
    away: { style_vector: isHome ? style(-5) : style(4), samples: 9 },
    style_clashes: [],
  };
  historical.alineacion = {
    local: isHome ? xiNow.slice(0, 9).concat(["Old 10", "Old 11"]) : [],
    visitante: isHome ? [] : xiNow.slice(0, 9).concat(["Old 10", "Old 11"]),
  };
}

const squad = Array.from({ length: 6 }, (_, i) => ({
  player: i === 0 ? "Álex Team" : `Player Team ${i + 1}`,
  team,
  position: i === 0 ? "Attacker" : "Midfielder",
  goals: 8 - i,
  assists: 2 + i,
  shots: 30 - i,
  yc: i,
  min: 900,
  rating: 7.4 - i / 10,
  profile: i === 0 ? { age: 24, nationality: "España" } : {},
  season: {
    minutes: 900,
    per90: { g: .5 - i * .03, a: .2, r: 2.5, rp: 1.1, fc: .8, fr: 1.2, t: .08 },
    per90_extended: { key_passes: 1.2, duels_won: 3, tackles: .6, interceptions: .3, dribbles_success: 1.4 },
  },
  rich_source: "API-Football · players",
}));
feedData.players = { laliga: { label: "LaLiga", players: squad, rankings: {} } };
const feed = JSON.stringify(feedData);

async function gotoMatches(page) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) await page.getByRole("button", { name: "Abrir menú" }).click();
  await page.locator(".snav").getByRole("button", { name: "Partidos", exact: true }).click();
}

test("perfil premium de equipo conecta táctica, XI, matchup y jugadores", async ({ page }) => {
  await page.route("**/dashboard.json*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: feed }));
  await page.goto("/");
  await gotoMatches(page);

  const row = page.locator('tr[role="button"]').filter({ hasText: team }).filter({ hasText: rival }).first();
  await expect(row).toBeVisible();
  await row.click();
  await page.getByRole("button", { name: `Ver perfil de ${team}` }).click();

  const intel = page.getByTestId("team-intelligence");
  await expect(intel).toBeVisible();
  await expect(intel.getByText("Identidad táctica", { exact: true })).toBeVisible();
  await expect(intel.getByText("Casa vs fuera", { exact: true })).toBeVisible();
  await expect(intel.getByText("Contexto del XI", { exact: true })).toBeVisible();
  await expect(intel.getByText("Próximo matchup", { exact: true })).toBeVisible();
  await expect(intel.getByText("Baja Confirmada", { exact: false })).toBeVisible();
  await expect(intel.getByText("Volumen local vs exposición rival", { exact: false })).toBeVisible();
  await expect(intel.getByText("58%", { exact: true })).toBeVisible();

  await intel.getByRole("button", { name: "Ver perfil de Álex Team" }).click();
  await expect(page.getByTestId("player-profile")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Álex Team" })).toBeVisible();
});
