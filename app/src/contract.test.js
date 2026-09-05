import assert from "node:assert/strict";
import test from "node:test";

import { bestValue, modelAccuracy, topValueBets } from "./insights.js";
import { matrix, oneXtwo, over } from "./poisson.js";

test("la UI no recomienda value cuando el backend se abstiene", () => {
  const match = {
    finished: false,
    recommendation: { decision: "no_pick" },
    value: [{ selection: "1", edge: 0.20, odds: 2.1 }],
  };
  assert.equal(bestValue(match), null);
  assert.deepEqual(topValueBets([match]), []);
});

test("el acierto solo utiliza el snapshot publicado", () => {
  const matches = [{
    finished: true,
    result: [0, 2],
    probs: [90, 5, 5],
    kickoff: "2026-09-05T20:00:00Z",
    prediction_snapshot: { probs: [20, 20, 60], generated_at: "2026-09-05T19:00:00Z" },
  }];
  assert.deepEqual(modelAccuracy(matches), { hits: 1, total: 1, pct: 100 });
  const invalid = [
    {...matches[0], prediction_snapshot: {probs: [20, 20, 60]}},
    {...matches[0], prediction_snapshot: {probs: [20, 20, 60], generated_at: "2026-09-05T22:00:00Z"}},
  ];
  assert.deepEqual(modelAccuracy(invalid), {hits: 0, total: 0, pct: null});
});

test("los mercados cliente forman una distribución coherente", () => {
  const scores = matrix(1.5, 1.0);
  const signs = oneXtwo(scores);
  assert.ok(Math.abs(signs[1] + signs.X + signs[2] - 1) < 1e-9);
  assert.ok(over(scores, 1.5) > over(scores, 3.5));
});
