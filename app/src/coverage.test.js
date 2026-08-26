import assert from "node:assert/strict";
import test from "node:test";

import { coverageRows } from "./coverage.js";

const NOW = new Date("2026-08-26T19:00:00+02:00").getTime();

function xi(status = "probable") {
  return {
    status,
    local: Array.from({ length: 11 }, (_, i) => `L${i}`),
    visitante: Array.from({ length: 11 }, (_, i) => `V${i}`),
    provider: status === "confirmado" ? "API-Football" : "Fuente externa",
    source_updated_at: "2026-08-26T18:55:00+02:00",
  };
}

test("a T-2h muestra huecos reales y no exige XI oficial todavía", () => {
  const m = {
    id: "m1", status: "SCHEDULED", source: "football_data",
    kickoff: "2026-08-26T21:00:00+02:00", updatedAt: "2026-08-26T18:50:00+02:00",
    alineacion: xi("estimado"), odds: "pendiente_odds_api",
  };
  const coverage = coverageRows(m, NOW);
  const byKey = Object.fromEntries(coverage.rows.map((row) => [row.key, row]));
  assert.equal(byKey.weather.state, "missing");
  assert.equal(byKey.absences.state, "missing");
  assert.equal(byKey.lineup_probable.state, "estimated");
  assert.equal(byKey.lineup_official.state, "scheduled");
  assert.equal(byKey.odds.state, "missing");
  assert.equal(coverage.complete, false);
});

test("una comprobación de bajas con cero incidencias cuenta como cobertura", () => {
  const m = {
    id: "m2", status: "SCHEDULED", kickoff: "2026-08-26T21:00:00+02:00",
    alineacion: xi("probable"), weather: { temperature_c: 24 },
    odds: { "1x2": { "1": 2 } },
    operational_checks: { absences_checked_at: "2026-08-26T18:58:00+02:00" },
  };
  const coverage = coverageRows(m, NOW);
  const absences = coverage.rows.find((row) => row.key === "absences");
  assert.equal(absences.state, "ok");
});

test("XI parcial a T-30 nunca se presenta como oficial completo", () => {
  const m = {
    id: "m3", status: "SCHEDULED", kickoff: "2026-08-26T19:30:00+02:00",
    alineacion: xi("probable"), weather: { temperature_c: 24 },
    odds: { "1x2": { "1": 2 } },
    operational_checks: {
      absences_checked_at: "2026-08-26T18:58:00+02:00",
      lineup_checked_at: "2026-08-26T18:59:00+02:00",
      lineup_check_result: "partial",
    },
  };
  const coverage = coverageRows(m, NOW);
  const official = coverage.rows.find((row) => row.key === "lineup_official");
  assert.equal(official.required, true);
  assert.equal(official.state, "partial");
  assert.equal(coverage.complete, false);
});

test("XI confirmado 11+11 cierra la pieza oficial", () => {
  const m = {
    id: "m4", status: "SCHEDULED", kickoff: "2026-08-26T19:30:00+02:00",
    alineacion: xi("confirmado"), weather: { temperature_c: 24 },
    odds: { "1x2": { "1": 2 } },
    operational_checks: {
      absences_checked_at: "2026-08-26T18:58:00+02:00",
      lineup_checked_at: "2026-08-26T18:59:00+02:00",
      lineup_check_result: "published",
    },
  };
  const coverage = coverageRows(m, NOW);
  assert.equal(coverage.rows.find((row) => row.key === "lineup_official").state, "ok");
  assert.equal(coverage.complete, true);
});
