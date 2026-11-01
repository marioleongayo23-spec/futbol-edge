/**
 * FÚTBOL EDGE / OPEN-DATA BRIDGE
 * Bind this script to a PRIVATE Google Sheet. Runs 100% on public-domain
 * OpenFootball football.json; never retrieves paywalled, logged-in or
 * commercial bookmaker data. Stores only FINISHED scores, not predictions.
 *
 * Sheet -> Extensions -> Apps Script, paste Code.gs, run setupEdgeBridge once,
 * then run pullOpenFootball once and optionally installDailyTrigger.
 *
 * Source: https://github.com/openfootball/football.json (Public Domain / CC0).
 */
const EDGE_BRIDGE = Object.freeze({
  sheetName: "Observaciones",
  seasonsBack: 1,
  sourceBase: "https://raw.githubusercontent.com/openfootball/football.json/master",
  columns: [
    "record_id", "match_uid", "league", "season", "kickoff", "kickoff_precision",
    "home", "away", "feature", "value_json", "source", "source_url",
    "license", "available_at", "phase", "quality",
  ],
  divisions: [
    { suffix: "es.1.json", league: "laliga", code: "es1" },
    { suffix: "es.2.json", league: "segunda", code: "es2" },
  ],
});

function setupEdgeBridge() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error("Ejecuta este script asociado a una hoja de cálculo.");
  let sheet = ss.getSheetByName(EDGE_BRIDGE.sheetName);
  if (!sheet) sheet = ss.insertSheet(EDGE_BRIDGE.sheetName);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, EDGE_BRIDGE.columns.length)
      .setValues([EDGE_BRIDGE.columns]).setFontWeight("bold");
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, sheet.getMaxRows(), EDGE_BRIDGE.columns.length)
      .setNumberFormat("@");
  } else {
    const cols = sheet.getRange(1, 1, 1, EDGE_BRIDGE.columns.length).getDisplayValues()[0];
    if (JSON.stringify(cols) !== JSON.stringify(EDGE_BRIDGE.columns)) {
      throw new Error("Cabeceras inesperadas; usa otra hoja para no sobrescribir datos.");
    }
  }
  return sheet;
}

function _edgeSlug(text) {
  return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function _edgeHash(text) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8);
  return bytes.map(v => ("0" + (v & 255).toString(16)).slice(-2)).join("");
}

function _edgeSeason() {
  const now = new Date();
  const year = Number(Utilities.formatDate(now, "Europe/Madrid", "yyyy"));
  const month = Number(Utilities.formatDate(now, "Europe/Madrid", "MM"));
  return month >= 7 ? year : year - 1;
}

function _edgeSeasonSlug(year) {
  return year + "-" + String((year + 1) % 100).padStart(2, "0");
}

function _edgeFetchOpenFootball(url) {
  // No credentials, cookies, fake browser fingerprints or scraping of HTML.
  const response = UrlFetchApp.fetch(url, {
    method: "get", followRedirects: true, muteHttpExceptions: true,
    headers: { Accept: "application/json" },
  });
  if (response.getResponseCode() === 404) return null;
  if (response.getResponseCode() !== 200) {
    throw new Error("Fuente no disponible (" + response.getResponseCode() + ") " + url);
  }
  const parsed = JSON.parse(response.getContentText("UTF-8"));
  if (!parsed || !Array.isArray(parsed.matches)) {
    throw new Error("Esquema inesperado en " + url);
  }
  return parsed.matches;
}

/** Ingest a strictly date-only historical result, never an exact kickoff. */
function _edgeRecord(match, div, year, url, fetchedAt) {
  if (!match || typeof match !== "object") return null;
  const date = String(match.date || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const home = String(match.team1 || "").trim();
  const away = String(match.team2 || "").trim();
  if (!home || !away || home === away) return null;
  const score = match.score && typeof match.score === "object" &&
    !Array.isArray(match.score) ? match.score.ft : match.score;
  if (!Array.isArray(score) || score.length !== 2 ||
      !score.every(n => Number.isInteger(n) && n >= 0 && n <= 30)) return null;

  const identity = "openfootball:" + div.code + ":" + year + ":" +
    _edgeSlug(home) + ":" + _edgeSlug(away);
  const payload = JSON.stringify(score);
  const revision = date + "|" + identity + "|" + payload;
  // This timestamp is for indexing historical date-only results; it is NOT
  // an observed match start time and must never be fed into pre-match training.
  const dateIndex = date + "T00:00:00Z";
  return [
    "of-" + _edgeHash(revision).slice(0, 20), identity,
    div.league, String(year), dateIndex, "date_only",
    home, away, "result.score", payload, "openfootball", url,
    "CC0-1.0", fetchedAt, "postmatch", "observed_date_only",
  ];
}

function pullOpenFootball() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) throw new Error("Ya hay una recopilación en curso.");
  try {
    const sheet = setupEdgeBridge();
    const lastRow = sheet.getLastRow();
    const seen = new Set(lastRow > 1
      ? sheet.getRange(2, 1, lastRow - 1, 1).getDisplayValues().map(r => r[0])
      : []);
    const season = _edgeSeason();
    const rows = [];
    let fetched = 0, skipped = 0;
    const fetchedAt = new Date().toISOString();
    for (let year = season - EDGE_BRIDGE.seasonsBack; year <= season; year++) {
      for (const div of EDGE_BRIDGE.divisions) {
        const url = EDGE_BRIDGE.sourceBase + "/" + _edgeSeasonSlug(year) + "/" + div.suffix;
        const matches = _edgeFetchOpenFootball(url);
        if (matches === null) continue;
        fetched++;
        for (const match of matches) {
          const row = _edgeRecord(match, div, year, url, fetchedAt);
          if (!row || seen.has(row[0])) { skipped++; continue; }
          seen.add(row[0]);
          rows.push(row);
        }
      }
    }
    if (rows.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, EDGE_BRIDGE.columns.length)
        .setValues(rows);
    }
    const result = { fetched_sources: fetched, new_observations: rows.length, skipped };
    console.log(JSON.stringify(result));
    return result;
  } finally {
    lock.releaseLock();
  }
}

function installDailyTrigger() {
  // Explicit opt-in. Schedules may be delayed; not for live odds.
  ScriptApp.getProjectTriggers().filter(t =>
    t.getHandlerFunction() === "pullOpenFootball").forEach(ScriptApp.deleteTrigger);
  ScriptApp.newTrigger("pullOpenFootball").timeBased()
    .everyDays(1).atHour(7).nearMinute(17).inTimezone("Europe/Madrid").create();
}
