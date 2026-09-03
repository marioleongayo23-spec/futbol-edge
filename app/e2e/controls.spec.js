import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const feedData = JSON.parse(readFileSync(new URL("../../football/data/dashboard.json", import.meta.url), "utf8"));
const enriched = feedData.matches.find((match) => !match.finished && Array.isArray(match.probs));
if (enriched) {
  const vector = Object.fromEntries(["attack_volume", "territorial_pressure", "defensive_exposure", "finishing_efficiency", "contact_intensity"].map((key, index) => [key, { label: key, score: 55 + index, observed: 10 + index, unit: "por partido" }]));
  enriched.tactical_matchup = { ...(enriched.tactical_matchup || {}), home: { style_vector: vector }, away: { style_vector: vector }, style_clashes: [{ edge: "contact", label: "Cruce de estilos", strength: 72 }] };
  enriched.lineup_impact = { evidence: "media", confidence_penalty_pp: 2, method: "Método auditable", home: { expected_minutes_avg: 76, starter_probability_avg_pct: 81, attack_presence_index: 9.2, official_absences: 0 }, away: { expected_minutes_avg: 74, starter_probability_avg_pct: 79, attack_presence_index: 8.7, official_absences: 1 } };
  enriched.state_simulation = { probabilities: { "1": .47, X: .28, "2": .25 }, simulations: 4000, expected_total_goals: 2.5, total_goals_range_80: [1, 5], over_2_5: .46, btts: .51, assumptions: { pace_multiplier: .92, estimated_goal_delta_vs_neutral: -.2, state_effects: "El equipo que pierde arriesga más." } };
  // Fuerza un value enorme que DEBE quedar bloqueado por la abstención backend.
  enriched.probs = [70, 20, 10];
  enriched.odds = { "1x2": { odds: { "1": 2.0, X: 4.0, "2": 8.0 }, fair: { "1": .50, X: .25, "2": .25 } } };
  enriched.recommendation = { decision: "no_pick", label: "Sin apuesta recomendada", reasons: ["confianza insuficiente", "datos incompletos"] };
}
const feed = JSON.stringify(feedData);
const views = [
  ["Resumen", "Resumen"], ["Partidos", "Partidos"], ["Clasificación", "Clasificación"],
  ["Value bets", "Value bets"], ["Mi cartera", "Mi cartera"], ["Quiniela", "Quiniela"],
  ["Jugadores", "Jugadores"], ["Datos y modelos", "Datos y modelos"],
];

async function openApp(page) {
  await page.route("**/dashboard.json?*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: feed,
  }));
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("e2e-initialised")) {
      localStorage.clear();
      sessionStorage.setItem("e2e-initialised", "1");
    }
    window.confirm = () => true;
  });
  await page.goto("/");
  await expect(page.locator("h1.view-title")).toHaveText("Resumen");
}

async function gotoView(page, label) {
  const mobile = (page.viewportSize()?.width || 1000) <= 860;
  if (mobile) {
    await page.getByRole("button", { name: "Abrir menú" }).click();
    await expect(page.locator(".layout")).toHaveClass(/open/);
  }
  await page.locator(".snav").getByRole("button", { name: label, exact: true }).click();
}

async function expectNamedControls(page) {
  const controls = page.locator('button:visible, input:visible, select:visible, [role="button"]:visible');
  const unnamed = await controls.evaluateAll((elements) => elements.flatMap((element) => {
    const name = (
      element.getAttribute("aria-label")
      || element.getAttribute("placeholder")
      || element.getAttribute("title")
      || element.textContent
      || ""
    ).trim();
    return name ? [] : [element.outerHTML];
  }));
  expect(await controls.count()).toBeGreaterThan(0);
  expect(unnamed).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await openApp(page);
});

test("todos los destinos y controles visibles tienen contrato accesible", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const [label, title] of views) {
    await gotoView(page, label);
    await expect(page.locator("h1.view-title")).toHaveText(title);
    await expectNamedControls(page);
  }
  expect(errors).toEqual([]);
});

test("tema, buscador, calendario y filtros responden", async ({ page }) => {
  const theme = page.getByRole("checkbox", { name: "Alternar tema claro u oscuro" });
  await expect(theme).not.toBeChecked();
  await theme.click();
  await expect(theme).toBeChecked();
  await page.reload();
  await expect(theme).toBeChecked();

  const search = page.getByRole("textbox", { name: "Buscar equipo o competición" });
  await search.fill("Granada");
  await expect(page.locator("h1.view-title")).toHaveText("Partidos");
  await expect(page.getByText("Granada vs Mallorca")).toBeVisible();
  await search.fill("");

  await gotoView(page, "Resumen");
  const activeDay = page.locator(".cal-day.on");
  const previousDay = await activeDay.innerText();
  const day = page.locator(".cal-day:not(.on)").first();
  if (await day.count()) {
    await day.click();
    await expect(page.locator(".cal-day.on")).not.toHaveText(previousDay);
  }

  await gotoView(page, "Partidos");
  const onlyValue = page.getByRole("button", { name: "Solo value" });
  await onlyValue.click();
  await expect(onlyValue).toHaveAttribute("aria-pressed", "true");
});

test("clasificación, quiniela y value modifican sus estados", async ({ page }) => {
  await gotoView(page, "Clasificación");
  const projection = page.getByRole("button", { name: "Proyección", exact: true });
  await projection.click();
  await expect(projection).toHaveAttribute("aria-pressed", "true");

  await gotoView(page, "Quiniela");
  const triples = page.getByRole("slider", { name: "Número de triples" });
  await triples.fill("3");
  await expect(triples).toHaveValue("3");
  await page.getByRole("button", { name: "Copiar quiniela" }).click();

  await gotoView(page, "Value bets");
  const bankroll = page.getByRole("spinbutton", { name: "Bankroll para calcular stakes" });
  await bankroll.fill("1250");
  await expect(bankroll).toHaveValue("1250");
});

test("Value bets respeta no_pick aunque las cuotas generen edge", async ({ page }) => {
  expect(enriched).toBeTruthy();
  await gotoView(page, "Value bets");
  const card = page.locator('.card[data-recommendation="no_pick"]').filter({ hasText: enriched.home }).filter({ hasText: enriched.away }).first();
  await expect(card).toBeVisible();
  await expect(card.getByText(/Sin apuesta recomendada/)).toBeVisible();
  await expect(card.getByText(/confianza insuficiente/)).toBeVisible();
  await expect(card.locator(".edge")).toHaveCount(0);
  await expect(card.getByText(/VALUE/)).toHaveCount(0);
  await expect(card.getByText(/apostar/)).toHaveCount(0);
  await expect(card.getByRole("spinbutton")).toHaveCount(3);
});

test("cartera permite añadir, liquidar y eliminar", async ({ page }) => {
  await gotoView(page, "Mi cartera");
  await page.getByPlaceholder("Partido (o texto libre)").fill("Granada - Mallorca");
  await page.getByPlaceholder("Cuota").fill("2.10");
  await page.getByPlaceholder("Stake €").fill("20");
  await page.getByRole("button", { name: "Añadir", exact: true }).click();
  await expect(page.getByText("Apuesta añadida.")).toBeVisible();
  await page.getByRole("button", { name: /Marcar Granada - Mallorca como ganada/ }).click();
  await expect(page.getByText("Ganada", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Eliminar apuesta Granada - Mallorca/ }).click();
  await expect(page.getByText("Aún no has registrado apuestas.")).toBeVisible();
});

test("la ficha abre, navega por secciones y enlaza el equipo", async ({ page }) => {
  await gotoView(page, "Partidos");
  await page.locator('tr[role="button"]').first().click();
  await expect(page.getByRole("button", { name: "Volver a la lista" })).toBeVisible();
  for (const section of ["Previa", "Onces", "Pronóstico", "Datos"]) {
    await page.locator(".match-nav").getByRole("button", { name: section, exact: true }).click();
  }
  const teamButton = page.locator(".match-hero .team-button").first();
  await teamButton.click();
  await expect(page.locator("button.back")).toHaveText(/Volver/);
  const favourite = page.locator(".fav-btn");
  const before = await favourite.getAttribute("aria-label");
  await favourite.click();
  await expect(favourite).not.toHaveAttribute("aria-label", before);
});

test("la ficha explica táctica, impacto del once y escenarios", async ({ page }) => {
  await gotoView(page, "Partidos");
  const row = page.locator('tr[role="button"]').filter({ hasText: enriched.home }).filter({ hasText: enriched.away }).first();
  await row.click();
  await expect(page.getByText("Impacto del once", { exact: true })).toBeVisible();
  await expect(page.getByText("Simulador de resultados", { exact: true })).toBeVisible();
  await expect(page.getByText("Cruce de estilos", { exact: false })).toBeVisible();
});
