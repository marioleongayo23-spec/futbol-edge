import test from "node:test";
import assert from "node:assert/strict";
import { feedFreshness, dayEvidence } from "./evidenceStatus.js";

const NOW = Date.parse("2026-11-01T13:00:00Z");
test("feed freshness distinguishes remote, fallback and stale", () => {
  assert.equal(feedFreshness("2026-11-01T11:00:00Z", false, NOW).tone, "fresh");
  assert.equal(feedFreshness("2026-11-01T11:00:00Z", true, NOW).tone, "fallback");
  assert.equal(feedFreshness("2026-10-31T10:00:00Z", false, NOW).tone, "stale");
  assert.equal(feedFreshness("", false, NOW).tone, "unknown");
  assert.equal(feedFreshness("2026-11-02T11:00:00Z", false, NOW).tone, "stale");
});
test("coverage does not count invalid predictions or partial/imaginary odds", () => {
  const rows = [
    { probs: [55, 25, 20], odds: { "1x2": { odds: { "1": 2.1, X: 3.2, "2": 4.2 } } } },
    { probs: [50, 30, 20], odds: { "1x2": { odds: { "1": 2.1, X: Infinity, "2": 4.2 } } } },
    { probs: [99, 99, 99] },
  ];
  assert.deepEqual(dayEvidence(rows, NOW), { total: 3, predicted: 2, priced: 1, verifiedPriced: 0 });
  assert.deepEqual(dayEvidence([], NOW), { total: 0, predicted: 0, priced: 0, verifiedPriced: 0 });
});

test("a source-timestamped 1X2 price counts only when both recent and pre-kickoff", () => {
  const match = {
    kickoff: "2026-11-01T18:00:00Z", probs: [55, 25, 20],
    odds: {
      "1x2": { odds: { "1": 2.1, X: 3.2, "2": 4.2 } },
      meta: {
        provider: "The Odds API", movement_source: "the_odds_api_live",
        source_updated_at: "2026-11-01T12:55:00Z",
      },
    },
  };
  assert.deepEqual(dayEvidence([match], NOW), { total: 1, predicted: 1, priced: 1, verifiedPriced: 1 });
  assert.equal(dayEvidence([{ ...match, kickoff: "2026-11-01T12:00:00Z" }], NOW).verifiedPriced, 0);
  assert.equal(dayEvidence([{
    ...match, odds: { ...match.odds, meta: {
      ...match.odds.meta, provider: "football-data.co.uk",
    } },
  }], NOW).verifiedPriced, 0);
  assert.equal(dayEvidence([{
    ...match, odds: { ...match.odds, meta: { source_updated_at: "2026-10-31T12:00:00Z" } },
  }], NOW).verifiedPriced, 0);
});
