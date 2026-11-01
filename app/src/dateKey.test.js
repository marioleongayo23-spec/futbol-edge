import assert from "node:assert/strict";
import test from "node:test";
import { madridDayKey } from "./dateKey.js";

test("día deportivo basado en Madrid, independientemente de la zona del navegador", () => {
  assert.equal(madridDayKey(new Date("2026-10-31T23:30:00Z")), "2026-11-01");
  assert.equal(madridDayKey(new Date("2026-06-01T22:30:00Z")), "2026-06-02");
  assert.equal(madridDayKey(new Date("2026-10-25T00:30:00Z")), "2026-10-25");
});
