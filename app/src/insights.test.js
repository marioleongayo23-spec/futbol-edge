import test from "node:test";
import assert from "node:assert/strict";
import { bestValue, topValueBets } from "./insights.js";

const choices = [
  { selection: "1", edge: 0.045 },
  { selection: "X", edge: 0.09 },
  { selection: "2", edge: Infinity },
  { selection: "2", edge: NaN },
];

test("best value chooses maximum valid edge even when feed is unsorted", () => {
  assert.equal(bestValue({ finished: false, value: choices })?.selection, "X");
});

test("finished matches and no-pick decisions cannot be promoted", () => {
  assert.equal(bestValue({ finished: true, value: choices }), null);
  assert.equal(bestValue({ recommendation: { decision: "no_pick" }, value: choices }), null);
});

test("non-finite and below-threshold edges never become signals", () => {
  assert.equal(bestValue({ value: [{ edge: Infinity }, { edge: NaN }, { edge: 0.02 }] }), null);
  assert.equal(bestValue({ value: [{ edge: 0.07 }] }, 0.08), null);
});

test("top value bets only shows open fixtures with valid edges", () => {
  const a = { id: "a", finished: true, value: [{ selection: "1", edge: 0.5 }] };
  const b = { id: "b", finished: false, value: [{ selection: "2", edge: 0.06 }] };
  assert.deepEqual(topValueBets([a, b], 3).map(row => row.m.id), ["b"]);
});
