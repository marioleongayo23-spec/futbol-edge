import assert from "node:assert/strict";
import test from "node:test";

import { actionableValueRows, marketLabel, selectionLabel } from "./extendedValue.js";

test("rankea solo value con cuota real y edge superior al umbral", () => {
  const rows = actionableValueRows([
    { market: "btts", selection: "Yes", odds: 2.1, modelProb: 0.55, edge: 0.155 },
    { market: "alternate_totals_corners", selection: "Over", line: 9.5, odds: 1.9, edge: 0.019 },
    { market: "player_shots", player: "Jugador", selection: "Over", line: 2.5, odds: 2.3, edge: 0.08 },
    { market: "spreads", selection: "Local", odds: 0, edge: 0.5 },
  ]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].market, "btts");
  assert.equal(rows[1].market, "player_shots");
});

test("etiqueta mercados y props sin perder línea", () => {
  assert.equal(marketLabel("alternate_totals_cards"), "Tarjetas");
  assert.equal(selectionLabel({ player: "Antoine Griezmann", selection: "Over", line: 1.5 }), "Antoine Griezmann · Over · 1.5");
});
