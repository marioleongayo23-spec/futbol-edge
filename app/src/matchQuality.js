// Vista de la calidad de datos por partido para la UI.
//
// El backend (football/) publica `match_quality` en cada partido dentro de la
// ventana operativa: un score 0–100, un tier, las fuentes requeridas que faltan
// y la cobertura por fuente. Aquí solo lo normalizamos para pintarlo; nunca
// recalculamos ni inventamos calidad. Si el partido está fuera de ventana (o el
// feed es antiguo y no trae el campo), la UI simplemente no muestra el badge.

export const QUALITY_TIERS = {
  high: { label: "Alta", cls: "mq-high", rank: 4 },
  medium: { label: "Media", cls: "mq-medium", rank: 3 },
  limited: { label: "Limitada", cls: "mq-limited", rank: 2 },
  insufficient: { label: "Insuficiente", cls: "mq-insufficient", rank: 1 },
  blocked: { label: "Bloqueada", cls: "mq-blocked", rank: 0 },
};

// Etiquetas legibles para cada fuente de cobertura del score.
export const SOURCE_LABELS = {
  fixture: "Partido",
  weather: "Clima",
  absences: "Bajas",
  lineup_probable: "XI probable",
  lineup_official: "XI oficial",
  odds: "Cuotas",
  players: "Jugadores",
};

function clampPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

// Normaliza `match_quality` del feed a lo que necesita la UI. Devuelve null si
// no hay señal utilizable, para que quien llame decida no renderizar nada.
export function qualityView(mq) {
  if (!mq || typeof mq !== "object") return null;
  const tierMeta = QUALITY_TIERS[mq.tier];
  const hasScore = typeof mq.score === "number" && Number.isFinite(mq.score);
  if (!tierMeta && !hasScore) return null;
  const meta = tierMeta || QUALITY_TIERS.limited;
  const missing = Array.isArray(mq.required_missing)
    ? mq.required_missing.map((key) => SOURCE_LABELS[key] || key)
    : [];
  const components = mq.components && typeof mq.components === "object"
    ? Object.entries(mq.components).map(([key, value]) => ({
        key,
        label: SOURCE_LABELS[key] || key,
        pct: clampPct(value),
      }))
    : [];
  return {
    tier: tierMeta ? mq.tier : "limited",
    label: meta.label,
    cls: meta.cls,
    score: hasScore ? Math.round(mq.score) : null,
    missing,
    components,
  };
}

// Texto de tooltip / aria para el badge. Deja claro que es cobertura de datos,
// no la confianza del pronóstico (que la app muestra aparte).
export function qualitySummary(view) {
  if (!view) return "";
  const head = view.score != null
    ? `Calidad de datos ${view.label} · ${view.score}/100`
    : `Calidad de datos ${view.label}`;
  return view.missing.length ? `${head} · falta ${view.missing.join(", ")}` : head;
}
