import { validProbabilities } from "./probabilityContract.js";

function minutesToKickoff(m, now) {
  const kickoff = new Date(m?.kickoff || "").getTime();
  if (!Number.isFinite(kickoff)) return null;
  return (kickoff - now) / 60000;
}

function latestAvailabilityStamp(lineup) {
  const stamps = [
    ...(lineup?.disponibilidad_local || []),
    ...(lineup?.disponibilidad_visitante || []),
  ]
    .map((row) => new Date(row?.source_updated_at || "").getTime())
    .filter(Number.isFinite);
  return stamps.length ? new Date(Math.max(...stamps)).toISOString() : null;
}

function row(key, label, state, required, extra = {}) {
  return { key, label, state, required: Boolean(required), ...extra };
}

export function coverageRows(m, now = Date.now()) {
  const minutes = minutesToKickoff(m, now);
  const lineup = m?.alineacion || {};
  const checks = m?.operational_checks || {};
  const status = String(lineup.status || "sin confirmar").toLowerCase();
  const lineupStamp = lineup.source_updated_at || lineup.generated_at || lineup.ts;
  const availabilityStamp = latestAvailabilityStamp(lineup);
  const weather = m?.weather || null;
  const prices = m?.odds?.["1x2"]?.odds || m?.odds?.["1x2"] || {};
  const oddsOk = ["1", "X", "2"].every(key => typeof prices[key] === "number" && Number.isFinite(prices[key]) && prices[key] > 1);
  const predictionOk = validProbabilities(m?.probs);
  const marketMeta = typeof m?.odds === "object" ? (m.odds?.meta || {}) : {};
  const predictionRefresh = m?.prediction_live_refresh || {};

  const weatherRequired = minutes == null || minutes <= 8 * 60;
  const absencesRequired = minutes == null || minutes <= 6 * 60;
  const probableRequired = minutes == null || minutes <= 3 * 60;
  const officialRequired = minutes == null || minutes <= 45;
  const oddsRequired = minutes == null || minutes <= 24 * 60;
  const predictionRequired = predictionOk && (minutes == null || minutes <= 18 * 60);

  const fixtureOk = Boolean(m?.id && m?.status)
    && !["not_found", "fixture_not_found", "error", "failed", "unavailable"].includes(checks.fixture_check_result);
  const weatherOk = Boolean(weather);
  const absencesOk = Boolean(checks.absences_checked_at)
    && checks.absences_check_result === "ok";
  const probableOk = ["probable", "confirmado"].includes(status)
    && (lineup.local || []).length === 11 && (lineup.visitante || []).length === 11
    && !["model_only", "statistical_fallback", "roster_grounded", "media_partial"].includes(lineup.source_quality);
  const officialOk = status === "confirmado"
    && (lineup.local || []).length === 11
    && (lineup.visitante || []).length === 11;

  const weatherResult = checks.weather_check_result;
  const absenceResult = checks.absences_check_result;
  const lineupResult = checks.lineup_check_result;

  const rows = [
    row("fixture", "Partido", fixtureOk ? "ok" : "missing", true, {
      checkedAt: checks.fixture_checked_at || (fixtureOk ? m?.updatedAt : null),
      source: m?.source,
      detail: checks.fixture_check_result || (fixtureOk ? "calendario cargado" : "sin partido verificable"),
    }),
    row("weather", "Clima", weatherOk ? "ok" : !weatherRequired ? "scheduled" : weatherResult === "unavailable" ? "unavailable" : "missing", weatherRequired, {
      checkedAt: weather?.source_updated_at || checks.weather_checked_at,
      source: weather?.source || (weatherOk ? "Open-Meteo" : null),
      detail: weatherResult || (weatherOk ? `previsión para ${weather?.forecast_for || "kickoff"}` : !weatherRequired ? "programado T−8h" : "sin previsión"),
    }),
    row("absences", "Bajas", absencesOk ? "ok" : !absencesRequired ? "scheduled" : absenceResult === "unavailable" ? "unavailable" : "missing", absencesRequired, {
      checkedAt: checks.absences_checked_at || availabilityStamp,
      source: absencesOk ? "API-Football" : null,
      detail: absenceResult || (absencesOk ? "comprobado; 0 o más incidencias" : !absencesRequired ? "ventana T−6h" : "sin comprobación"),
    }),
    row("lineup_probable", "XI probable", probableOk ? "ok" : !probableRequired ? "scheduled" : status === "estimado" ? "estimated" : "missing", probableRequired, {
      checkedAt: lineupStamp,
      source: lineup.provider || lineup.fuente,
      detail: probableOk ? "respaldado por fuente" : !probableRequired ? "ventana T−3h" : status === "estimado" ? "solo estimación" : "sin fuente fiable",
    }),
    row("lineup_official", "XI oficial", officialOk ? "ok" : !officialRequired ? "scheduled" : ["partial", "published"].includes(lineupResult) ? "partial" : lineupResult === "not_published" ? "waiting" : "missing", officialRequired, {
      checkedAt: checks.lineup_checked_at || lineup.official_poll_at,
      source: officialOk || checks.lineup_checked_at ? "API-Football" : null,
      detail: officialOk ? "11+11 confirmado" : !officialRequired ? "requerido desde T−45" : ["partial", "published"].includes(lineupResult) ? "respuesta parcial" : lineupResult === "not_published" ? "aún no publicado" : "sin comprobación oficial",
    }),
    row("odds", "Cuotas", oddsOk ? "ok" : !oddsRequired ? "scheduled" : "missing", oddsRequired, {
      checkedAt: marketMeta.source_updated_at || marketMeta.checked_at,
      source: marketMeta.provider || (oddsOk ? "mercado real" : null),
      detail: oddsOk ? `cuotas reales${marketMeta.ttl_minutes ? ` · TTL ${marketMeta.ttl_minutes} min` : ""}` : !oddsRequired ? "fuera de ventana" : "faltan cuotas reales",
    }),
    row("prediction", "Predicción", predictionOk ? "ok" : predictionRequired ? "missing" : "scheduled", predictionRequired, {
      checkedAt: predictionRefresh.checked_at || m?.prediction_snapshot?.generated_at || m?.updatedAt,
      source: predictionRefresh.checked_at ? "Fútbol Edge · recálculo intradía" : m?.model_meta?.provider || m?.engine,
      detail: predictionRefresh.checked_at
        ? "revisión intradía; la influencia depende del modelo y de los datos disponibles"
        : predictionOk ? "predicción disponible; esperando próximo ciclo intradía" : "sin predicción calculable",
    }),
  ];

  // Versioned backend evidence is authoritative. Legacy feeds are evaluated
  // conservatively above; new feed timestamps must never refresh old evidence.
  const ttlHours = { weather: 12, absences: 12, lineup_probable: 24, odds: 6 };
  for (const item of rows) {
    const published = m?.coverage?.schema_version === 2 ? m.coverage.items?.[item.key] : null;
    if (published) Object.assign(item, { state: published.state, required: published.required,
      source: published.source, checkedAt: published.checked_at, detail: published.detail });
    const stamp = Date.parse(item.checkedAt || "");
    const age = (now - stamp) / 3600000;
    if (item.state === "ok" && ttlHours[item.key] && Number.isFinite(stamp)
        && (age > ttlHours[item.key] || age < -0.25)) {
      item.state = "stale";
      item.detail = "fecha de fuente fuera de la ventana de frescura";
    }
  }
  return {
    rows,
    complete: rows.every((item) => !item.required || item.state === "ok"),
    missingRequired: rows.filter((item) => item.required && item.state !== "ok").map((item) => item.key),
  };
}

export function coverageSymbol(state) {
  if (state === "ok") return "✓";
  if (["scheduled", "waiting", "partial"].includes(state)) return "◷";
  return "✕";
}

export function coverageStateLabel(state) {
  return ({
    ok: "ok",
    scheduled: "programado",
    waiting: "esperando",
    partial: "parcial",
    estimated: "solo estimado",
    unavailable: "fuente no disponible",
    missing: "falta",
    stale: "desactualizada",
  })[state] || state;
}
