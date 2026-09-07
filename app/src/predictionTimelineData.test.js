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
  const current = snapshot("final_T-60_official", "2026-08-24T20:00:00+02:00", [54, 27, 19], {
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
  const b = snapshot("final_T-60_official", "2026-08-24T20:00:00+02:00", [53, 28, 19], { model_probs: [52, 29, 19] });
  const result = auditablePrediction({ kickoff, prediction_history: [a, b], prediction_snapshot: b });
  assert.equal(result.previousDelta, 3);
  assert.equal(result.previousLabel, "T−6h");
  assert.equal(result.latestLabel, "FINAL · XI T−60");
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


test("timeline distingue pre-final y final oficial", () => {
  const pre = snapshot("pre_final_T-3h", "2026-08-24T18:00:00+02:00", [51, 29, 20], {
    alineacion: { phase: "pre_final", status: "probable", source_quality: "media_grounded", media_sources: [{ source: "AS" }] },
  });
  const final = snapshot("final_T-30_official", "2026-08-24T20:30:00+02:00", [53, 28, 19], {
    alineacion: { phase: "final", status: "confirmado", official_poll_window: "T-30" },
  });
  const points = predictionTimelinePoints({ kickoff, prediction_history: [pre, final], prediction_snapshot: final });
  assert.equal(points[0].label, "PRE-FINAL · T−3h");
  assert.equal(points[0].sourceQuality, "media_grounded");
  assert.equal(points[1].label, "FINAL · XI T−30");
  assert.equal(points[1].officialPollWindow, "T-30");
});

test("timeline añade ACTUAL cuando el refresco live es posterior al snapshot histórico", () => {
  const initial = snapshot("initial", "2026-08-24T10:00:00+02:00", [48, 31, 21]);
  const match = {
    kickoff,
    probs: [52, 29, 19],
    model_probs: [50, 30, 20],
    prediction_history: [initial],
    prediction_snapshot: initial,
    prediction_live_refresh: { checked_at: "2026-08-24T18:30:00+02:00" },
  };
  const points = predictionTimelinePoints(match);
  assert.deepEqual(points.map((row) => row.label), ["Primera captura", "ACTUAL"]);
  assert.equal(points.at(-1).currentState, true);
  assert.deepEqual(points.at(-1).probs, [52, 29, 19]);

  const result = auditablePrediction(match);
  assert.equal(result.latestLabel, "ACTUAL");
  assert.equal(result.previousLabel, "Primera captura");
  assert.equal(result.favoriteSign, "1");
  assert.equal(result.previousDelta, 4);
});

test("ACTUAL no se inventa si el refresco no es posterior al histórico", () => {
  const current = snapshot("T-6h", "2026-08-24T15:00:00+02:00", [50, 30, 20]);
  const points = predictionTimelinePoints({
    kickoff,
    probs: [51, 29, 20],
    prediction_history: [current],
    prediction_snapshot: current,
    prediction_live_refresh: { checked_at: "2026-08-24T14:59:00+02:00" },
  });
  assert.deepEqual(points.map((row) => row.label), ["T−6h"]);
});

test("ACTUAL nunca se añade después del kickoff ni a partidos terminados", () => {
  const initial = snapshot("initial", "2026-08-24T10:00:00+02:00", [48, 31, 21]);
  for (const extra of [
    { prediction_live_refresh: { checked_at: "2026-08-24T21:05:00+02:00" } },
    { prediction_live_refresh: { checked_at: "2026-08-24T18:30:00+02:00" }, finished: true },
  ]) {
    const points = predictionTimelinePoints({
      kickoff,
      probs: [52, 29, 19],
      prediction_history: [initial],
      prediction_snapshot: initial,
      ...extra,
    });
    assert.deepEqual(points.map((row) => row.label), ["Primera captura"]);
  }
});
