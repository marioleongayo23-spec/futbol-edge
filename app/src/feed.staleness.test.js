import test from "node:test";
import assert from "node:assert/strict";
import { isStale } from "./feed.js";

const H = 36e5;
const now = Date.parse("2026-08-25T03:00:00Z"); // madrugada, sin partidos

function feed(ageHours, kickoffs = []) {
  return {
    generated_at: new Date(now - ageHours * H).toISOString(),
    matches: kickoffs.map((iso, i) => ({ id: `m${i}`, home: "A", away: "B", league: "L", kickoff: iso })),
  };
}

test("recién actualizado no está desactualizado", () => {
  assert.equal(isStale(feed(1), now), false);
});

test("de madrugada y sin partidos cercanos NO avisa aunque tenga horas", () => {
  assert.equal(isStale(feed(9), now), false); // antes saltaba a las 2 h
});

test("feed viejo con partido inminente (±3h) SÍ avisa", () => {
  const soon = new Date(now + 1 * H).toISOString();
  assert.equal(isStale(feed(4, [soon]), now), true);
});

test("feed viejo con partido en juego SÍ avisa", () => {
  const live = new Date(now - 1 * H).toISOString();
  assert.equal(isStale(feed(4, [live]), now), true);
});

test("atascado >18h avisa siempre", () => {
  assert.equal(isStale(feed(20), now), true);
});

test("sin fecha de generación no avisa", () => {
  assert.equal(isStale({ matches: [] }, now), false);
});
