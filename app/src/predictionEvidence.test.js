import test from "node:test";
import assert from "node:assert/strict";
import { displayPercentages, validProbabilities, publishedMatrix, wilsonInterval, evidenceRows, picksForDay } from "./predictionEvidence.js";

test("display percentages total 100 without mutating raw forecast", () => {
  const raw = [33.3, 33.3, 33.3];
  assert.deepEqual(displayPercentages(raw), [34, 33, 33]);
  assert.deepEqual(raw, [33.3, 33.3, 33.3]);
  for (const bad of [[NaN, 50, 50], [-1, 50, 51], [10, 10, 10], [null, 50, 50]]) assert.equal(validProbabilities(bad), false);
});

test("uses server matrix without reconstructing an independent Poisson", () => {
  const match = {xg: [1, 1], score_matrix: {matrix: [[.4, .2], [.1, .3]]}};
  assert.deepEqual(publishedMatrix(match), [[.4, .2], [.1, .3]]);
  assert.equal(publishedMatrix({xg: [1, 1]}), null);
  assert.equal(publishedMatrix({score_matrix: {matrix: [[-1, 2], [0, 0]]}}), null);
});

test("accuracy interval shows uncertainty for the actual 10/22 sample", () => {
  const [low, high] = wilsonInterval(10, 22);
  assert.ok(low > .26 && low < .28);
  assert.ok(high > .65 && high < .66);
  assert.equal(wilsonInterval(0, 0), null);
});

test("unknown sources never become verified or freshly checked", () => {
  const rows = evidenceRows({updatedAt: new Date().toISOString()});
  assert.ok(rows.every(r => r.state !== "Disponible" && r.checkedAt === null));
});

test("daily selections exclude other dates, started games and abstentions", () => {
  const now = Date.parse('2026-09-05T10:00:00Z');
  const base = {date: '2026-09-05', kickoff: '2026-09-05T20:00:00Z', probs: [50, 25, 25]};
  const matches = [{...base, id: 'yes'}, {...base, id: 'tomorrow', date: '2026-09-06'},
    {...base, id: 'blocked', recommendation: {decision: 'no_pick'}},
    {...base, id: 'started', kickoff: '2026-09-05T09:00:00Z'}];
  assert.deepEqual(picksForDay(matches.map(m => ({match_id: m.id})), matches, base.date, now), [{match_id: 'yes'}]);
});
