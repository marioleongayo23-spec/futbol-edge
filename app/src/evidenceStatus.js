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

export function verifiedOneXTwo(match, now = Date.now()) {
  const kickoff = Date.parse(match?.kickoff || "");
  const odds = match?.odds?.["1x2"]?.odds;
  const meta = match?.odds?.meta;
  if (match?.finished || !Number.isFinite(kickoff) || kickoff <= now ||
      !odds || !["1", "X", "2"].every(k =>
        typeof odds[k] === "number" && Number.isFinite(odds[k]) && odds[k] > 1)) {
    return null;
  }
  // Legacy data can have a generated_at field masquerading as source time.
  if (meta?.provider !== "The Odds API" ||
      meta?.movement_source !== "the_odds_api_live" ||
      quoteEvidence({ source_updated_at: meta?.source_updated_at }, now) !== "verified_recent") {
    return null;
  }
  return odds;
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
    if (verifiedOneXTwo(m, now)) verifiedPriced++;
  }
  return { total: rows.length, predicted, priced, verifiedPriced };
}
