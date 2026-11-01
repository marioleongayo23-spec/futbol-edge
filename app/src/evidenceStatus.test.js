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
  assert.deepEqual(dayEvidence(rows), { total: 3, predicted: 2, priced: 1 });
  assert.deepEqual(dayEvidence([]), { total: 0, predicted: 0, priced: 0 });
});
