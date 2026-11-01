import assert from "node:assert/strict";
import test from "node:test";

import { actionableValueRows, excludedQuoteCounts, marketLabel, quoteEvidence, selectionLabel } from "./extendedValue.js";

const NOW = Date.parse("2026-11-01T13:00:00Z");
const BASE = {
  market: "btts", selection: "Yes", odds: 2.1, modelProb: 0.55, edge: 0.155,
  kickoff: "2026-11-01T18:00:00Z", source_updated_at: "2026-11-01T12:54:00Z",
};

test("ranking only promotes valid and time-verifiable pre-match prices", () => {
  const rows = actionableValueRows([
    BASE,
    { ...BASE, market: "player_shots", odds: 2.3, edge: 0.08 },
    { ...BASE, market: "alternate_totals_corners", edge: 0.019 },
    { ...BASE, odds: Infinity, edge: 0.20 },
    { ...BASE, odds: 1.1, edge: NaN },
    { ...BASE, source_updated_at: null, edge: 0.30 },
    { ...BASE, source_updated_at: "2026-11-01T06:00:00Z", edge: 0.35 },
    { ...BASE, kickoff: "2026-11-01T11:59:00Z", edge: 0.4 },
    { ...BASE, modelProb: Infinity, edge: 0.4 },
  ], 0.02, NOW);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].market, "btts");
  assert.equal(rows[1].market, "player_shots");
});

test("unknown and stale provider updates remain visible as excluded counts", () => {
  assert.equal(quoteEvidence(BASE, NOW), "verified_recent");
  assert.equal(quoteEvidence({ ...BASE, source_updated_at: null }, NOW), "unverified");
  assert.equal(quoteEvidence({ ...BASE, source_updated_at: "2026-10-31T12:00:00Z" }, NOW), "stale");
  assert.deepEqual(excludedQuoteCounts([BASE,
    { ...BASE, source_updated_at: null },
    { ...BASE, source_updated_at: "2026-10-31T12:00:00Z" },
  ], NOW), { unverified: 1, stale: 1 });
});

test("label markets and props without losing selection line", () => {
  assert.equal(marketLabel("alternate_totals_cards"), "Tarjetas");
  assert.equal(selectionLabel({ player: "Antoine Griezmann", selection: "Over", line: 1.5 }),
    "Antoine Griezmann · Over · 1.5");
});
