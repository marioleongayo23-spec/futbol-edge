import assert from "node:assert/strict";
import test from "node:test";
import { portfolioStats, validBet } from "./portfolioMath.js";

test("no acepta cuotas o stakes no finitos", () => {
  assert.equal(validBet(Infinity, 10), false);
  assert.equal(validBet(2.5, NaN), false);
  assert.equal(validBet(1, 10), false);
  assert.equal(validBet(2, 0), false);
  assert.equal(validBet(2.2, 10), true);
});
test("el ROI excluye apuestas nulas y abiertas", () => {
  const stats = portfolioStats([
    { result: "won", odds: 2, stake: 10 },
    { result: "lost", odds: 3, stake: 5 },
    { result: "void", odds: 4, stake: 100 },
    { result: "open", odds: 7, stake: 100 },
  ]);
  assert.equal(stats.staked, 15);
  assert.equal(stats.profit, 5);
  assert.equal(stats.roi, 5 / 15 * 100);
  assert.equal(stats.settled, 2);
  assert.equal(stats.hit, 50);
});
test("sin apuestas liquidadas no muestra un ROI inventado", () => {
  assert.equal(portfolioStats([{ result: "void", stake: 25 }]).roi, null);
});
