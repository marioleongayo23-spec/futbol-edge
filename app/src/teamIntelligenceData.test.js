import test from "node:test";
import assert from "node:assert/strict";
import { teamIntelligence, teamStyleSnapshots, teamStyleTraits, xiContinuity } from "./teamIntelligenceData.js";

const vector = (offset = 0) => ({
  attack_volume: { label: "Volumen ofensivo", score: 70 + offset, observed: 13, unit: "remates" },
  territorial_pressure: { label: "Presión territorial", score: 60 + offset, observed: 5, unit: "córners" },
  defensive_exposure: { label: "Exposición defensiva", score: 40 + offset, observed: 10, unit: "remates concedidos" },
  finishing_efficiency: { label: "Eficacia de remate", score: 75 + offset, observed: 0.35, unit: "AP/remate" },
  contact_intensity: { label: "Intensidad de contacto", score: 55 + offset, observed: 14, unit: "faltas" },
});

const matches = [
  {
    id: "old", home: "Club Test", away: "Rival A", league: "LaLiga", kickoff: "2026-08-01T18:00:00Z", finished: true, result: [2, 1],
    tactical_matchup: { home: { style_vector: vector(0), samples: 8 }, away: { style_vector: vector(-5), samples: 8 }, style_clashes: [] },
    alineacion: { local: ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11"], visitante: [] },
  },
  {
    id: "recent", home: "Rival B", away: "Club Test", league: "LaLiga", kickoff: "2026-08-10T18:00:00Z", finished: true, result: [0, 0],
    tactical_matchup: { home: { style_vector: vector(-3), samples: 9 }, away: { style_vector: vector(5), samples: 9 }, style_clashes: [] },
    alineacion: { local: [], visitante: ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P12", "P13"] },
  },
  {
    id: "next", home: "Club Test", away: "Rival C", league: "LaLiga", kickoff: "2026-08-30T18:00:00Z", finished: false, probs: [.55, .25, .20], xg: [1.8, .9],
    tactical_matchup: { home: { style_vector: vector(2), samples: 10 }, away: { style_vector: vector(-2), samples: 10 }, style_clashes: [{ edge: "attack", label: "Volumen vs exposición", strength: 78 }] },
    alineacion: { local: ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P14"], visitante: [], bajas_local: [{ jugador: "Lesionado Uno" }], status: "probable" },
  },
];

const players = { laliga: { players: [
  { player: "P1", team: "Club Test", goals: 8, assists: 2, min: 900 },
  { player: "P2", team: "Club Test", goals: 5, assists: 4, min: 850 },
  { player: "P3", team: "Club Test", goals: 2, assists: 6, min: 800 },
  { player: "P4", team: "Club Test", goals: 1, assists: 1, min: 700 },
] } };

test("teamStyleSnapshots separa el último perfil casa y fuera", () => {
  const out = teamStyleSnapshots(matches, "Club Test");
  assert.equal(out.home.match.id, "next");
  assert.equal(out.away.match.id, "recent");
  assert.equal(out.latest.match.id, "next");
});

test("teamStyleTraits conserva exposición como rasgo adverso descriptivo", () => {
  const traits = teamStyleTraits(teamStyleSnapshots(matches, "Club Test").home);
  const exposure = traits.find((row) => row.key === "defensive_exposure");
  assert.equal(exposure.adverse, true);
  assert.equal(exposure.score, 42);
});

test("xiContinuity calcula titulares repetidos entre los dos onces más recientes", () => {
  const out = xiContinuity(matches, "Club Test");
  assert.equal(out.shared, 9);
  assert.equal(out.pct, 82);
});

test("teamIntelligence resuelve próximo rival, bajas y jugadores referencia", () => {
  const out = teamIntelligence(matches, players, "Club Test", Date.parse("2026-08-25T12:00:00Z"));
  assert.equal(out.next.opponent, "Rival C");
  assert.equal(out.next.isHome, true);
  assert.equal(out.absences[0].jugador, "Lesionado Uno");
  assert.equal(out.keyPlayers[0].player, "P1");
  assert.deepEqual(out.base.form, ["W", "D"]);
});
