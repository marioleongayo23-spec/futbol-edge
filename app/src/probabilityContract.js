// Shared display contract. Missing evidence is never converted into certainty.
export function validProbabilities(values) {
  return Array.isArray(values) && values.length === 3
    && values.every(v => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 100)
    && Math.abs(values.reduce((a, b) => a + b, 0) - 100) <= 1.1;
}

export function displayPercentages(values) {
  if (!validProbabilities(values)) return null;
  const total = values.reduce((a, b) => a + b, 0);
  const scaled = values.map(v => v * 100 / total);
  const result = scaled.map(Math.floor);
  const order = scaled.map((v, i) => ({ i, rest: v - result[i] })).sort((a, b) => b.rest - a.rest);
  for (let i = 0, left = 100 - result.reduce((a, b) => a + b, 0); i < left; i++) result[order[i].i]++;
  return result;
}
