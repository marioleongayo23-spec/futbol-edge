import test from "node:test";
import assert from "node:assert/strict";
import { auditablePrediction, leadTimeLabel, predictionTimelinePoints, strongestRealEdge } from "./predictionTimelineData.js";

const kickoff = "2026-08-24T21:00:00+02:00";

function snapshot(window, generatedAt, probs, extra = {}) {
  return { window, generated_at: generatedAt, probs, model_version: "edge-2.0", ...extra };
}

test("timeline solo muestra snapshots reales prepartido y elimina duplicados", () => {
  const initial = snapshot("initial", "2026-08-23T15:00:00+02:00", [48, 31, 21]);
  const t24 = snapshot("T-24h", "2026-08-23T21:00:00+02:00", [49, 31, 20]);
  const post = snapshot("fake", "2026-08-24T22:00:00+02:00", [99, 1, 0]);
  const points = predictionTimelinePoints({
    kickoff,
    prediction_history: [initial, t24, post],
    prediction_snapshot: t24,
  });
  assert.deepEqual(points.map((row) => row.label), ["Primera captura", "T−24h"]);
  assert.deepEqual(points.map((row) => row.probs[0]), [48, 49]);
});

test("leadTimeLabel deriva la distancia real al saque inicial", () => {
  assert.equal(leadTimeLabel("2026-08-24T15:00:00+02:00", kickoff), "T−6h 00m");
  assert.equal(leadTimeLabel("2026-08-23T21:00:00+02:00", kickoff), "T−1d 0h");
});

test("mercado es delta real publicado menos motor; once y clima no inventan 1X2", () => {
  const current = snapshot("official_lineup", "2026-08-24T19:45:00+02:00", [54, 27, 19], {
    model_probs: [51, 29, 20],
    market_calibration: { model_weight: 0.7, market_weight: 0.3, temperature: 1.05 },
    lineup_impact: { evidence: "alta", confidence_penalty_pp: 4, probability_adjustment: "not_applied" },
    weather_adjustment: { applied: true, xg: { delta: [-0.08, -0.04] } },
    model_meta: { components: { dixon_coles: { "1": 0.50, X: 0.30, "2": 0.20 }, elo: { "1": 0.56, X: 0.26, "2": 0.18 } } },
  });
  const result = auditablePrediction({ kickoff, prediction_history: [current], prediction_snapshot: current });
  assert.equal(result.favoriteSign, "1");
  assert.equal(result.marketDelta, 3);
  const market = result.rows.find((row) => row.key === "market_calibration");
  const lineup = result.rows.find((row) => row.key === "lineup");
  const weather = result.rows.find((row) => row.key === "weather");
  const disagreement = result.rows.find((row) => row.key === "dc_elo");
  assert.equal(market.display, "+3.0 pp");
  assert.equal(lineup.display, "0.0 pp 1X2");
  assert.match(lineup.detail, /no aplicado al 1X2/);
  assert.equal(weather.display, "0.0 pp 1X2");
  assert.match(weather.detail, /Δ xG total -0.12/);
  assert.equal(disagreement.display, "6.0 pp");
  assert.equal(disagreement.kind, "diagnostic");
});

test("cambio de último snapshot se calcula sobre el favorito publicado", () => {
  const a = snapshot("T-6h", "2026-08-24T15:00:00+02:00", [50, 30, 20]);
  const b = snapshot("official_lineup", "2026-08-24T19:45:00+02:00", [53, 28, 19], { model_probs: [52, 29, 19] });
  const result = auditablePrediction({ kickoff, prediction_history: [a, b], prediction_snapshot: b });
  assert.equal(result.previousDelta, 3);
  assert.equal(result.previousLabel, "T−6h");
  assert.equal(result.latestLabel, "Once oficial");
});

test("strongestRealEdge solo utiliza value 1X2 con cuota y edge numéricos", () => {
  const best = strongestRealEdge({ value: [
    { market: "ou25", edge: 0.20, odds: 1.9 },
    { market: "1x2", selection: "2", edge: 0.04, odds: 3.2 },
    { market: "1x2", selection: "1", edge: 0.07, odds: 2.1 },
  ] });
  assert.equal(best.selection, "1");
  assert.equal(best.edge, 0.07);
});
