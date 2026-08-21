// Clasificación proyectada: combina los resultados reales ya jugados con los
// puntos esperados del modelo — 3·P(gana) + 1·P(empata) — sobre cada partido
// que el motor Dixon-Coles es capaz de predecir. Da una foto de "cómo puede
// acabar la liga" en lugar de solo lo jugado.

import { hasPrediction } from "./feed";

export function leaguesIn(matches) {
  return [...new Set(matches.map((m) => m.league).filter(Boolean))].sort();
}

export function projectedTable(matches, league) {
  const T = {};
  const team = (name, crest, colors) => {
    if (!T[name]) {
      T[name] = {
        name, crest, colors,
        pj: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0,
        ptsReal: 0, ptsProy: 0, xgf: 0, xga: 0, rem: 0,
      };
    }
    if (crest && !T[name].crest) T[name].crest = crest;
    return T[name];
  };

  for (const m of matches) {
    if (league && m.league !== league) continue;
    const h = team(m.home, m.homeCrest, m.homeColors);
    const a = team(m.away, m.awayCrest, m.awayColors);

    if (m.finished && Array.isArray(m.result)) {
      const [hg, ag] = m.result;
      h.pj++; a.pj++;
      h.gf += hg; h.ga += ag; a.gf += ag; a.ga += hg;
      h.xgf += hg; h.xga += ag; a.xgf += ag; a.xga += hg;
      if (hg > ag) { h.w++; a.l++; h.ptsReal += 3; h.ptsProy += 3; }
      else if (hg < ag) { a.w++; h.l++; a.ptsReal += 3; a.ptsProy += 3; }
      else { h.d++; a.d++; h.ptsReal++; a.ptsReal++; h.ptsProy++; a.ptsProy++; }
    } else if (hasPrediction(m) && Array.isArray(m.probs)) {
      const p1 = m.probs[0] / 100, pX = m.probs[1] / 100, p2 = m.probs[2] / 100;
      h.ptsProy += 3 * p1 + pX;
      a.ptsProy += 3 * p2 + pX;
      h.rem++; a.rem++;
      if (Array.isArray(m.xg)) {
        h.xgf += m.xg[0]; h.xga += m.xg[1];
        a.xgf += m.xg[1]; a.xga += m.xg[0];
      }
    }
  }

  return Object.values(T)
    .map((t) => ({
      ...t,
      ptsProy: Math.round(t.ptsProy),
      difGoles: Math.round((t.xgf - t.xga) * 10) / 10,
    }))
    .sort((x, y) => y.ptsProy - x.ptsProy || (y.xgf - y.xga) - (x.xgf - x.xga) || x.name.localeCompare(y.name));
}
