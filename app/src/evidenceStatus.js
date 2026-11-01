import { validProbabilities } from "./probabilityContract.js";

export function feedFreshness(generatedAt, fromFallback = false, now = Date.now()) {
  const stamp = Date.parse(generatedAt || "");
  if (!Number.isFinite(stamp)) return { tone: "unknown", label: "Sin fecha de actualización", stamp: null };
  const hours = (now - stamp) / 3600000;
  if (fromFallback) return { tone: "fallback", label: "Copia de respaldo", stamp };
  if (hours < -0.25 || hours > 24) return { tone: "stale", label: "Revisar actualización", stamp };
  if (hours > 6) return { tone: "delayed", label: "Actualización retrasada", stamp };
  return { tone: "fresh", label: "Feed actualizado", stamp };
}

export function dayEvidence(matches) {
  const rows = Array.isArray(matches) ? matches : [];
  const predicted = rows.filter(m => validProbabilities(m?.probs)).length;
  const priced = rows.filter(m => {
    const odds = m?.odds?.["1x2"]?.odds;
    return odds && ["1", "X", "2"].every(k =>
      typeof odds[k] === "number" && Number.isFinite(odds[k]) && odds[k] > 1);
  }).length;
  return { total: rows.length, predicted, priced };
}
