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
    odds: { "1x2": { "1": 2, "X": 3, "2": 4 } },
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

test("vacíos y cuotas incompletas no acreditan cobertura", () => {
  const result = coverageRows({ id: "m", status: "SCHEDULED", kickoff: "2026-08-26T19:30:00+02:00",
    alineacion: {status: "probable", disponibilidad_local: [], disponibilidad_visitante: []},
    odds: {"1x2": {"1": 2}}, operational_checks: {} }, NOW);
  for (const key of ["absences", "lineup_probable", "odds"]) {
    assert.equal(result.rows.find(row => row.key === key).state, "missing");
  }
});

test("la fecha del feed no rejuvenece observaciones y respeta cobertura del servidor", () => {
  const result = coverageRows({ id: "m", status: "SCHEDULED", kickoff: "2026-08-26T19:30:00+02:00",
    updatedAt: new Date(NOW).toISOString(), coverage: {schema_version: 2, items: {
      odds: {state: "ok", required: true, source: "Provider", checked_at: "2026-08-25T18:00:00Z"},
      absences: {state: "unavailable", required: true, detail: "error del proveedor"},
    }}}, NOW);
  assert.equal(result.rows.find(row => row.key === "odds").state, "stale");
  assert.equal(result.rows.find(row => row.key === "odds").source, "Provider");
  assert.equal(result.rows.find(row => row.key === "absences").state, "unavailable");
  assert.equal(result.complete, false);
});
