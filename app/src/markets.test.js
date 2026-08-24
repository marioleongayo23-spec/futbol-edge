import assert from "node:assert/strict";
import test from "node:test";

import { marketMovementRows } from "./markets.js";

test("normaliza apertura, última cuota y dirección del mercado", () => {
  const rows = marketMovementRows({
    meta: {
      opening_1x2: { 1: 2.5, X: 3.2, 2: 2.9 },
      closing_1x2: { 1: 2.25, X: 3.2, 2: 3.1 },
      movement_pct: { 1: -10, X: 0, 2: 6.9 },
    },
  });
  assert.deepEqual(rows.map((row) => row.direction), ["shortening", "flat", "drifting"]);
  assert.equal(rows[0].movementPct, -10);
  assert.equal(rows[2].latest, 3.1);
});

test("omite el panel cuando la fuente no publica ambos cortes", () => {
  assert.deepEqual(marketMovementRows({ "1x2": { odds: { 1: 2 } } }), []);
});
