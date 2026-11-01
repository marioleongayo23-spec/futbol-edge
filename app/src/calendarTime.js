// Calendar and kickoff time contracts: always use the league's Madrid timezone,
// independent of the browser timezone (including DST transitions).
const ZONE = "Europe/Madrid";

export function madridDateKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const part = (name) => parts.find((item) => item.type === name)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function madridTime(iso) {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return "";
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: ZONE, hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

export function selectedDayIndex(days, selectedDay, fallbackIndex = 0) {
  const i = days.indexOf(selectedDay);
  return i === -1
    ? Math.max(0, Math.min(days.length - 1, fallbackIndex))
    : i;
}
