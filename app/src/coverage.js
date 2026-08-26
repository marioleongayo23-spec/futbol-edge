function pending(value) {
  if (value == null || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return typeof value === "string" && value.startsWith("pendiente_");
}

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
  const hasAvailability = Object.prototype.hasOwnProperty.call(lineup, "disponibilidad_local")
    || Object.prototype.hasOwnProperty.call(lineup, "disponibilidad_visitante");
  const lineupStamp = lineup.source_updated_at || lineup.generated_at || lineup.ts;
  const availabilityStamp = latestAvailabilityStamp(lineup);
  const weather = m?.weather || null;
  const oddsOk = !pending(m?.odds);
  const predictionOk = Array.isArray(m?.probs) && m.probs.length === 3;
  const marketMeta = typeof m?.odds === "object" ? (m.odds?.meta || {}) : {};
  const marketRefresh = m?.market_hot_refresh || {};
  const predictionRefresh = m?.prediction_live_refresh || {};

  const weatherRequired = minutes == null || minutes <= 8 * 60;
  const absencesRequired = minutes == null || minutes <= 8 * 60;
  const probableRequired = minutes == null || minutes <= 8 * 60;
  const officialRequired = minutes == null || minutes <= 75;
  const oddsRequired = minutes == null || minutes <= 24 * 60;
  const predictionRequired = predictionOk && (minutes == null || minutes <= 18 * 60);

  const fixtureOk = Boolean(m?.id && m?.status);
  const weatherOk = Boolean(weather);
  const absencesOk = Boolean(checks.absences_checked_at || hasAvailability);
  const probableOk = status === "probable" || status === "confirmado";
  const officialOk = status === "confirmado"
    && (lineup.local || []).length === 11
    && (lineup.visitante || []).length === 11;

  const weatherResult = checks.weather_check_result;
  const absenceResult = checks.absences_check_result;
  const lineupResult = checks.lineup_check_result;

  const rows = [
    row("fixture", "Partido", fixtureOk ? "ok" : "missing", true, {
      checkedAt: checks.fixture_checked_at || m?.updatedAt,
      source: m?.source,
      detail: checks.fixture_check_result || (fixtureOk ? "calendario cargado" : "sin partido verificable"),
    }),
    row("weather", "Clima", weatherOk ? "ok" : !weatherRequired ? "scheduled" : weatherResult === "unavailable" ? "unavailable" : "missing", weatherRequired, {
      checkedAt: checks.weather_checked_at || weather?.source_updated_at,
      source: weather?.source || (weatherOk ? "Open-Meteo" : null),
      detail: weatherResult || (weatherOk ? `previsión para ${weather?.forecast_for || "kickoff"}` : !weatherRequired ? "programado T−8h" : "sin previsión"),
    }),
    row("absences", "Bajas", absencesOk ? "ok" : !absencesRequired ? "scheduled" : absenceResult === "unavailable" ? "unavailable" : "missing", absencesRequired, {
      checkedAt: checks.absences_checked_at || availabilityStamp,
      source: absencesOk ? "API-Football" : null,
      detail: absenceResult || (absencesOk ? "comprobado; 0 o más incidencias" : !absencesRequired ? "programado T−8h/T−4h/T−1h" : "sin comprobación"),
    }),
    row("lineup_probable", "XI probable", probableOk ? "ok" : !probableRequired ? "scheduled" : status === "estimado" ? "estimated" : "missing", probableRequired, {
      checkedAt: lineup.prefinal_attempt_at || lineup.prefinal_refresh_at || lineupStamp,
      source: lineup.provider || lineup.fuente,
      detail: probableOk ? "respaldado por fuente" : !probableRequired ? "refrescos T−8h/T−3h/T−90" : status === "estimado" ? "solo estimación" : "sin fuente fiable",
    }),
    row("lineup_official", "XI oficial", officialOk ? "ok" : !officialRequired ? "scheduled" : ["partial", "published"].includes(lineupResult) ? "partial" : lineupResult === "not_published" ? "waiting" : "missing", officialRequired, {
      checkedAt: checks.lineup_checked_at || lineup.official_poll_at,
      source: officialOk || checks.lineup_checked_at ? "API-Football" : null,
      detail: officialOk ? "11+11 confirmado" : !officialRequired ? "polling intensivo desde T−75" : ["partial", "published"].includes(lineupResult) ? "respuesta parcial" : lineupResult === "not_published" ? "aún no publicado" : "sin comprobación oficial",
    }),
    row("odds", "Cuotas", oddsOk ? "ok" : !oddsRequired ? "scheduled" : "missing", oddsRequired, {
      checkedAt: marketRefresh.checked_at || marketMeta.checked_at || marketMeta.source_updated_at,
      source: marketMeta.provider || (oddsOk ? "mercado real" : null),
      detail: oddsOk ? `cuotas reales${marketMeta.ttl_minutes ? ` · TTL ${marketMeta.ttl_minutes} min` : ""}` : !oddsRequired ? "fuera de ventana" : "faltan cuotas reales",
    }),
    row("prediction", "Predicción", predictionOk ? "ok" : predictionRequired ? "missing" : "scheduled", predictionRequired, {
      checkedAt: predictionRefresh.checked_at || m?.prediction_snapshot?.generated_at || m?.updatedAt,
      source: predictionRefresh.checked_at ? "Fútbol Edge · recálculo intradía" : m?.model_meta?.provider || m?.engine,
      detail: predictionRefresh.checked_at
        ? `reacciona cada ${predictionRefresh.cadence_target_minutes || 5} min a clima/XI/bajas/mercado`
        : predictionOk ? "predicción disponible; esperando próximo ciclo intradía" : "sin predicción calculable",
    }),
  ];

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
  })[state] || state;
}
