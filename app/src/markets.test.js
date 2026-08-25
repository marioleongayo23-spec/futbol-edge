import assert from "node:assert/strict";
import test from "node:test";

import { marketMovementRows, marketMovementSourceLabel } from "./markets.js";

test("normaliza apertura, última cuota y dirección del mercado", () => {
  const rows = marketMovementRows({
    meta: {
      opening_1x2: { 1: 2.5, X: 3.2, 2: 2.9 },
      latest_1x2: { 1: 2.25, X: 3.2, 2: 3.1 },
      movement_pct: { 1: -10, X: 0, 2: 6.9 },
      movement_source: "market_average",
    },
  });
  assert.deepEqual(rows.map((row) => row.direction), ["shortening", "flat", "drifting"]);
  assert.equal(rows[0].movementPct, -10);
  assert.equal(rows[2].latest, 3.1);
  assert.equal(marketMovementSourceLabel({ meta: { movement_source: "market_average" } }), "media de mercado");
});

test("mantiene compatibilidad con closing_1x2 histórico y etiqueta Bet365 fallback", () => {
  const rows = marketMovementRows({
    meta: {
      opening_1x2: { 1: 2.3, X: 3.3, 2: 3.0 },
      closing_1x2: { 1: 2.15, X: 3.4, 2: 3.25 },
      movement_source: "Bet365",
    },
  });
  assert.equal(rows[0].latest, 2.15);
  assert.equal(rows[0].movementPct, -6.5);
  assert.equal(marketMovementSourceLabel({ meta: { movement_source: "Bet365" } }), "Bet365 (fallback)");
});

test("omite el panel cuando la fuente no publica ambos cortes", () => {
  assert.deepEqual(marketMovementRows({ "1x2": { odds: { 1: 2 } } }), []);
});
