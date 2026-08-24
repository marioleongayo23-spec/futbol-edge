import test from "node:test";
import assert from "node:assert/strict";

import { formatOfficialStat, normalizeClubName, officialStatsRows, officialTeamStats } from "./officialStats.js";

test("normaliza nombres y resuelve local/visitante aunque el proveedor use variantes", () => {
  const context = {
    live_or_post_stats: {
      "Atletico Madrid": { shots: 16, possession: 58 },
      "Valencia CF": { shots: 9, possession: 42 },
    },
  };
  const teams = officialTeamStats(context, "Atlético de Madrid", "Valencia");
  assert.deepEqual(teams.home, { shots: 16, possession: 58 });
  assert.deepEqual(teams.away, { shots: 9, possession: 42 });
  assert.equal(normalizeClubName("Valencia CF"), "valencia");
});

test("genera solo filas oficiales presentes y formatea porcentajes", () => {
  const context = {
    live_or_post_stats: {
      "A FC": { shots: 12, sot: 5, corners: 7, possession: 61.5 },
      "B Club": { shots: 8, sot: 2, corners: 3, possession: 38.5 },
    },
  };
  const rows = officialStatsRows(context, "A", "B");
  assert.deepEqual(rows.map((row) => row.key), ["shots", "sot", "corners", "possession"]);
  assert.equal(formatOfficialStat(rows.at(-1).home, rows.at(-1).suffix), "61.5%");
  assert.equal(formatOfficialStat(rows[0].away, rows[0].suffix), "8");
});

test("sin dos equipos con estadísticas no inventa una tabla", () => {
  assert.deepEqual(officialStatsRows({}, "A", "B"), []);
  assert.deepEqual(officialStatsRows({ live_or_post_stats: { A: { shots: 3 } } }, "A", "B"), []);
});
