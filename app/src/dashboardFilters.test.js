import test from "node:test";
import assert from "node:assert/strict";
import { competitionFilters, visibleMatchday } from "./dashboardFilters.js";

const matches = [
  { id: "1", league: "LaLiga" },
  { id: "2", league: "Champions League" },
  { id: "3", league: "LaLiga" },
  { id: "4", league: "LaLiga Hypermotion" },
];

test("dashboard competition filters show real counts with an all option", () => {
  const filters = competitionFilters(matches);
  assert.deepEqual(filters.find(f => f.key === "all"), { key: "all", label: "Todos", count: 4 });
  assert.deepEqual(filters.find(f => f.key === "LaLiga Hypermotion"), { key: "LaLiga Hypermotion", label: "Segunda", count: 1 });
  assert.equal(filters.filter(f => f.key !== "all").reduce((n,f) => n+f.count,0), 4);
});
test("filtering never changes the original match order or list", () => {
  assert.deepEqual(visibleMatchday(matches, "LaLiga").map(x=>x.id), ["1","3"]);
  assert.deepEqual(visibleMatchday(matches, "all"), matches);
  assert.deepEqual(visibleMatchday(matches, "absent"), []);
  assert.deepEqual(visibleMatchday(null, "all"), []);
});
