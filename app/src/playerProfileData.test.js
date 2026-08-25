import test from "node:test";
import assert from "node:assert/strict";
import { percentile, playerMetricRows, positionGroup, profileCompleteness, resolvePlayer } from "./playerProfileData.js";

test("positionGroup normaliza etiquetas comunes", () => {
  assert.equal(positionGroup("Goalkeeper"), "goalkeeper");
  assert.equal(positionGroup("Centre Back"), "defender");
  assert.equal(positionGroup("Midfielder"), "midfielder");
  assert.equal(positionGroup("Attacker"), "attacker");
});

test("percentile exige una muestra mínima de cinco", () => {
  assert.equal(percentile(5, [1, 2, 3, 4]), null);
  assert.equal(percentile(5, [1, 2, 3, 4, 5, 6]), 75);
});

test("resolvePlayer encuentra el registro rico por nombre y equipo", () => {
  const rich = { player: "Álex Prueba", team: "Real Test", profile: { age: 25 } };
  const players = { laliga: { players: [rich] } };
  assert.equal(resolvePlayer(players, { player: "Alex Prueba", team: "Real Test" }), rich);
});

test("playerMetricRows compara solo contra el mismo grupo posicional", () => {
  const rows = Array.from({ length: 6 }, (_, i) => ({
    player: `Delantero ${i}`,
    team: `Club ${i}`,
    position: "Attacker",
    season: { minutes: 900, per90: { g: i / 10, a: .1, r: 2 + i / 10, rp: 1, fr: 1, fc: .5 }, per90_extended: { key_passes: .5, duels_won: 2, tackles: .3, interceptions: .2, dribbles_success: 1 } },
  }));
  rows.push({ player: "Central", team: "Club Z", position: "Defender", season: { minutes: 1200, per90: { g: 9 }, per90_extended: {} } });
  const players = { laliga: { players: rows } };
  const metrics = playerMetricRows(players, rows[5]);
  const goals = metrics.find((m) => m.key === "g");
  assert.equal(goals.sample, 6);
  assert.ok(goals.percentile >= 80);
});

test("profileCompleteness no premia campos inexistentes", () => {
  assert.equal(profileCompleteness({ player: "Sin datos" }), 0);
  assert.ok(profileCompleteness({ profile: { photo: "x", age: 24 }, position: "Midfielder", rating: 7, season: { minutes: 900, per90: {}, per90_extended: {} } }) >= 75);
});
