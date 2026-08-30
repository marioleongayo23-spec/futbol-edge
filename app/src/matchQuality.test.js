import assert from "node:assert/strict";
import test from "node:test";
import { qualityView, qualitySummary, QUALITY_TIERS } from "./matchQuality.js";

test("qualityView devuelve null sin señal utilizable", () => {
  assert.equal(qualityView(null), null);
  assert.equal(qualityView(undefined), null);
  assert.equal(qualityView({}), null);
  assert.equal(qualityView("x"), null);
  assert.equal(qualityView({ required_missing: ["odds"] }), null);
});

test("qualityView normaliza score, tier y fuentes que faltan", () => {
  const view = qualityView({
    score: 80,
    tier: "limited",
    required_missing: ["lineup_official"],
    components: { fixture: 100, players: 50, odds: 100 },
  });
  assert.equal(view.score, 80);
  assert.equal(view.tier, "limited");
  assert.equal(view.label, "Limitada");
  assert.equal(view.cls, "mq-limited");
  assert.deepEqual(view.missing, ["XI oficial"]);
  const fixture = view.components.find((c) => c.key === "fixture");
  assert.equal(fixture.pct, 100);
  assert.equal(fixture.label, "Partido");
});

test("qualityView redondea el score y cae a 'limited' con tier desconocido", () => {
  const view = qualityView({ score: 42.6, tier: "???" });
  assert.equal(view.score, 43);
  assert.equal(view.tier, "limited");
  assert.equal(view.cls, "mq-limited");
});

test("qualityView acota porcentajes fuera de rango o no numéricos", () => {
  const view = qualityView({ tier: "high", components: { fixture: 140, odds: -10, weather: "x" } });
  assert.equal(view.components.find((c) => c.key === "fixture").pct, 100);
  assert.equal(view.components.find((c) => c.key === "odds").pct, 0);
  assert.equal(view.components.find((c) => c.key === "weather").pct, 0);
});

test("qualitySummary describe la cobertura e incluye lo que falta", () => {
  const view = qualityView({ score: 80, tier: "limited", required_missing: ["lineup_official"] });
  assert.match(qualitySummary(view), /Calidad de datos Limitada · 80\/100 · falta XI oficial/);
  assert.equal(qualitySummary(qualityView({ tier: "high" })), "Calidad de datos Alta");
  assert.equal(qualitySummary(null), "");
});

test("cada tier declara etiqueta y una clase mq-", () => {
  for (const [key, meta] of Object.entries(QUALITY_TIERS)) {
    assert.ok(meta.label, `${key} sin label`);
    assert.match(meta.cls, /^mq-/, `${key} sin clase mq-`);
  }
});
