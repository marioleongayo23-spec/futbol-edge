const SIGNS = ["1", "X", "2"];

const WINDOW_LABELS = {
  initial: "Primera captura",
  "T-24h": "T−24h",
  "T-12h": "T−12h",
  "T-6h": "T−6h",
  official_lineup: "Once oficial",
  "00:15": "00:15",
  "10:15": "10:15",
};

function validProbs(value) {
  return Array.isArray(value) && value.length === 3 && value.every((item) => Number.isFinite(Number(item)));
}

function parseTime(value) {
  const time = new Date(value || "").getTime();
  return Number.isFinite(time) ? time : null;
}

export function windowLabel(window) {
  return WINDOW_LABELS[window] || window || "Snapshot";
}

export function leadTimeLabel(generatedAt, kickoff) {
  const from = parseTime(generatedAt);
  const to = parseTime(kickoff);
  if (from == null || to == null || from >= to) return null;
  const minutes = Math.round((to - from) / 60000);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    const remHours = hours % 24;
    return `T−${days}d ${remHours}h`;
  }
  return `T−${hours}h ${String(rest).padStart(2, "0")}m`;
}

export function predictionTimelinePoints(match) {
  const kickoff = parseTime(match?.kickoff);
  const source = [
    ...(Array.isArray(match?.prediction_history) ? match.prediction_history : []),
    ...(match?.prediction_snapshot ? [match.prediction_snapshot] : []),
  ];
  const seen = new Set();
  return source
    .filter((item) => item && validProbs(item.probs) && parseTime(item.generated_at) != null)
    .filter((item) => kickoff == null || parseTime(item.generated_at) < kickoff)
    .sort((a, b) => parseTime(a.generated_at) - parseTime(b.generated_at))
    .filter((item) => {
      const key = `${item.generated_at}|${item.window || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((item, index) => ({
      index,
      generatedAt: item.generated_at,
      window: item.window || "snapshot",
      label: windowLabel(item.window),
      lead: leadTimeLabel(item.generated_at, match?.kickoff),
      probs: item.probs.map(Number),
      xg: Array.isArray(item.xg) ? item.xg.map(Number) : null,
      lineupStatus: item.alineacion?.status || null,
      modelVersion: item.model_version || item.model_meta?.version || null,
      snapshot: item,
    }));
}

function currentSnapshot(match) {
  return match?.prediction_snapshot || predictionTimelinePoints(match).at(-1)?.snapshot || match || {};
}

function favoriteIndex(probs) {
  if (!validProbs(probs)) return null;
  return probs.map(Number).reduce((best, value, index, arr) => value > arr[best] ? index : best, 0);
}

function pp(value) {
  const rounded = Math.round(Number(value) * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)} pp`;
}

export function auditablePrediction(match) {
  const snapshot = currentSnapshot(match);
  const published = validProbs(snapshot.probs) ? snapshot.probs.map(Number)
    : validProbs(match?.probs) ? match.probs.map(Number) : null;
  const rawModel = validProbs(snapshot.model_probs) ? snapshot.model_probs.map(Number)
    : validProbs(match?.model_probs) ? match.model_probs.map(Number) : null;
  const favIndex = favoriteIndex(published);
  const sign = favIndex == null ? null : SIGNS[favIndex];
  const timeline = predictionTimelinePoints(match);
  const previous = timeline.length > 1 ? timeline[timeline.length - 2] : null;
  const latest = timeline.at(-1) || null;

  const rows = [];
  if (favIndex != null && rawModel && published) {
    const delta = published[favIndex] - rawModel[favIndex];
    const calibration = snapshot.market_calibration || match?.market_calibration || {};
    rows.push({
      key: "market_calibration",
      kind: "applied",
      label: "Mercado + calibración",
      delta,
      display: pp(delta),
      detail: calibration.model_weight != null
        ? `modelo ${Math.round(Number(calibration.model_weight) * 100)}% · mercado ${Math.round(Number(calibration.market_weight || 0) * 100)}%${calibration.temperature != null ? ` · temperatura ${Number(calibration.temperature).toFixed(2)}` : ""}`
        : "diferencia entre probabilidad pura del motor y probabilidad publicada",
    });
  }

  const lineup = snapshot.lineup_impact || match?.lineup_impact;
  if (lineup) {
    rows.push({
      key: "lineup",
      kind: "context",
      label: "Once y bajas",
      delta: 0,
      display: "0.0 pp 1X2",
      detail: `no aplicado al 1X2 · penalización de confianza ${Number(lineup.confidence_penalty_pp || 0).toFixed(1)} pp · evidencia ${lineup.evidence || "—"}`,
    });
  }

  const weather = snapshot.weather_adjustment || match?.weather_adjustment;
  if (weather) {
    const xgDelta = Array.isArray(weather.xg?.delta)
      ? weather.xg.delta.map(Number).filter(Number.isFinite).reduce((sum, value) => sum + value, 0)
      : null;
    rows.push({
      key: "weather",
      kind: "context",
      label: "Clima",
      delta: 0,
      display: "0.0 pp 1X2",
      detail: weather.applied
        ? `no aplicado al 1X2${xgDelta != null ? ` · Δ xG total ${xgDelta > 0 ? "+" : ""}${xgDelta.toFixed(2)}` : ""}`
        : `sin ajuste · ${weather.reason || "condiciones neutrales"}`,
    });
  }

  const components = snapshot.model_meta?.components || match?.model_meta?.components || {};
  const dc = components.dixon_coles;
  const elo = components.elo;
  if (sign && dc?.[sign] != null && elo?.[sign] != null) {
    const disagreement = Math.abs(Number(dc[sign]) - Number(elo[sign])) * 100;
    rows.push({
      key: "dc_elo",
      kind: "diagnostic",
      label: "Desacuerdo Dixon-Coles ↔ Elo",
      delta: disagreement,
      display: `${disagreement.toFixed(1)} pp`,
      detail: "diagnóstico interno; no es una contribución aditiva al resultado final",
    });
  }

  return {
    published,
    rawModel,
    favoriteIndex: favIndex,
    favoriteSign: sign,
    marketDelta: favIndex != null && rawModel && published ? published[favIndex] - rawModel[favIndex] : null,
    previousDelta: previous && latest && favIndex != null ? latest.probs[favIndex] - previous.probs[favIndex] : null,
    previousLabel: previous?.label || null,
    latestLabel: latest?.label || null,
    rows,
  };
}

export function strongestRealEdge(match) {
  const rows = Array.isArray(match?.value) ? match.value : [];
  const eligible = rows
    .filter((row) => row?.market === "1x2" && Number.isFinite(Number(row.edge)) && Number.isFinite(Number(row.odds)))
    .sort((a, b) => Number(b.edge) - Number(a.edge));
  return eligible[0] || null;
}
