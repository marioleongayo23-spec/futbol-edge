import assert from "node:assert/strict";
import test from "node:test";
import { bestValue } from "./insights.js";

const now = Date.parse("2026-11-01T10:00:00Z");
const match = {
  kickoff: "2026-11-01T19:00:00Z",
  value: [
    { selection: "1", edge: 0.4, odds: Number.POSITIVE_INFINITY },
    { selection: "X", edge: 0.08, odds: 3.2 },
    { selection: "2", edge: 0.05, odds: 4.3 },
  ],
};

test("el value visible requiere cuota finita y escoge el mejor dato válido", () => {
  assert.equal(bestValue(match, 0.03, now)?.selection, "X");
});
test("ningún value prepartido aparece después del inicio", () => {
  assert.equal(bestValue(match, 0.03, Date.parse("2026-11-01T19:00:00Z")), null);
});
test("el no_pick del modelo manda sobre un edge aparente", () => {
  assert.equal(bestValue({ ...match, recommendation: { decision: "no_pick" } }, 0.03, now), null);
});
test("rechaza probabilidades y cuotas imposibles", () => {
  assert.equal(bestValue({ ...match, value: [{ selection: "1", edge: NaN, odds: 2.1 }] }, 0.03, now), null);
  assert.equal(bestValue({ ...match, value: [{ selection: "1", edge: 0.2, odds: 1.0 }] }, 0.03, now), null);
});
