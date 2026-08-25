import assert from "node:assert/strict";
import test from "node:test";

import { betClv, findBetMatch, portfolioClv } from "./clv.js";

const matches = [{
  id: "m1",
  home: "Atlético Madrid",
  away: "Sevilla",
  finished: true,
  closing_odds: {
    source: "football-data.co.uk",
    market_source: "market_average",
    is_real: true,
    capture_kind: "historical_provider_close",
    "1x2": { "1": 2.2, X: 3.4, "2": 3.5 },
  },
}];

test("resuelve apuestas nuevas por matchId y antiguas por texto normalizado", () => {
  assert.equal(findBetMatch({ matchId: "m1", match: "otro" }, matches)?.id, "m1");
  assert.equal(findBetMatch({ match: "Atletico Madrid - Sevilla" }, matches)?.id, "m1");
});

test("CLV positivo cuando la cuota tomada supera al cierre real", () => {
  const row = betClv({ matchId: "m1", sel: "1", odds: 2.5, stake: 20 }, matches);
  assert.equal(row.closingOdds, 2.2);
  assert.equal(row.priceClvPct, 13.64);
  assert.equal(row.source, "media de mercado");
  assert.ok(row.fairEdgePp > 0);
});

test("no calcula CLV con cuota no certificada como real", () => {
  const fake = [{ ...matches[0], closing_odds: { "1x2": { "1": 2.2, X: 3.4, "2": 3.5 }, market_source: "sample" } }];
  assert.equal(betClv({ matchId: "m1", sel: "1", odds: 2.5 }, fake), null);
});

test("no calcula CLV para props ni partidos no terminados", () => {
  assert.equal(betClv({ matchId: "m1", sel: "Over", odds: 2.0 }, matches), null);
  assert.equal(betClv({ matchId: "m2", sel: "1", odds: 2.0 }, [{ ...matches[0], id: "m2", finished: false }]), null);
});

test("agrega CLV simple, ponderado por stake y porcentaje positivo", () => {
  const summary = portfolioClv([
    { matchId: "m1", sel: "1", odds: 2.5, stake: 30 },
    { matchId: "m1", sel: "X", odds: 3.2, stake: 10 },
  ], matches);
  assert.equal(summary.n, 2);
  assert.ok(summary.averagePct > 0);
  assert.ok(summary.stakeWeightedPct > summary.averagePct);
  assert.equal(summary.positiveRatePct, 50);
});
