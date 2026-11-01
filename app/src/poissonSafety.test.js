import test from "node:test";
import assert from "node:assert/strict";
import { validDecimalOdds, kelly, fairProbs } from "./poisson.js";

test("only finite decimal odds above one qualify as market odds", () => {
  assert.equal(validDecimalOdds(2.15), true);
  for (const v of [0, 1, Infinity, NaN, -3, "2.5"]) assert.equal(validDecimalOdds(v), false);
});

test("Kelly never produces non-finite or negative stakes from invalid inputs", () => {
  for (const [p, odds] of [[0.5, Infinity], [0.5, NaN], [-0.2, 3], [1.2, 3], [0.4, 1]])
    assert.equal(kelly(p, odds), 0);
  assert.ok(Math.abs(kelly(0.6, 2) - 0.2) < 1e-12);
  assert.equal(kelly(1, 2), 1);
});

test("three valid odds normalize to a probability distribution", () => {
  const ps = fairProbs([2, 3.5, 4]);
  assert.ok(Math.abs(ps.reduce((a, b) => a + b, 0) - 1) < 1e-12);
  assert.deepEqual(fairProbs([NaN, Infinity]), [0, 0]);
});
