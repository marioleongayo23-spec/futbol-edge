import { validProbabilities } from "./probabilityContract.js";
import { quoteEvidence } from "./extendedValue.js";

export function feedFreshness(generatedAt, fromFallback = false, now = Date.now()) {
  const stamp = Date.parse(generatedAt || "");
  if (!Number.isFinite(stamp)) return { tone: "unknown", label: "Sin fecha de actualización", stamp: null };
  const hours = (now - stamp) / 3600000;
  if (fromFallback) return { tone: "fallback", label: "Copia de respaldo", stamp };
  if (hours < -0.25 || hours > 24) return { tone: "stale", label: "Revisar actualización", stamp };
  if (hours > 6) return { tone: "delayed", label: "Actualización retrasada", stamp };
  return { tone: "fresh", label: "Feed actualizado", stamp };
}

export function dayEvidence(matches, now = Date.now()) {
  const rows = Array.isArray(matches) ? matches : [];
  const predicted = rows.filter(m => validProbabilities(m?.probs)).length;
  let priced = 0, verifiedPriced = 0;
  for (const m of rows) {
    const odds = m?.odds?.["1x2"]?.odds;
    if (!odds || !["1", "X", "2"].every(k =>
      typeof odds[k] === "number" && Number.isFinite(odds[k]) && odds[k] > 1)) continue;
    priced++;
    // A complete set of prices is not proof that those prices are current.
    const kickoff = Date.parse(m?.kickoff || "");
    const meta = m?.odds?.meta;
    // Legacy feeds can carry a synthesized timestamp. Only the provider's
    // timestamped live-price pathway is sufficient evidence of freshness.
    if (kickoff > now && meta?.provider === "The Odds API" &&
        meta?.movement_source === "the_odds_api_live" &&
        quoteEvidence({ source_updated_at: meta?.source_updated_at }, now) === "verified_recent") {
      verifiedPriced++;
    }
  }
  return { total: rows.length, predicted, priced, verifiedPriced };
}
