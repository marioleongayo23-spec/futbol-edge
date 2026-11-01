import test from "node:test";
import assert from "node:assert/strict";
import { madridDateKey, madridTime, selectedDayIndex } from "./calendarTime.js";

test("Madrid calendar date is independent of browser timezone", () => {
  assert.equal(madridDateKey(new Date("2026-11-01T23:30:00Z")), "2026-11-02");
  assert.equal(madridDateKey(new Date("2026-06-01T22:30:00Z")), "2026-06-02");
});

test("kickoff times respect the March DST transition in Madrid", () => {
  assert.equal(madridTime("2026-03-29T00:30:00Z"), "01:30");
  assert.equal(madridTime("2026-03-29T01:30:00Z"), "03:30");
  assert.equal(madridTime("not-a-date"), "");
});

test("calendar selection survives added or removed dates", () => {
  const original = ["2026-11-01", "2026-11-02", "2026-11-03"];
  assert.equal(selectedDayIndex(original, "2026-11-02", 0), 1);
  assert.equal(selectedDayIndex(["2026-10-31", ...original], "2026-11-02", 0), 2);
  assert.equal(selectedDayIndex(original.filter(d => d !== "2026-11-02"), "2026-11-02", 1), 1);
  assert.equal(selectedDayIndex([], "2026-11-02", 3), 0);
});
