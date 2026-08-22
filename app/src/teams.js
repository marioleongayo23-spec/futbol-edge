// Perfil de un equipo a partir del feed: récord local/visitante, forma reciente,
// tendencias de estadísticas reales (a favor / en contra) y sus partidos.
// Todo se calcula en el cliente desde los partidos que ya trae el feed.

const STAT_KEYS = ["shots", "sot", "corners", "fouls", "yellows"];

export function teamNames(matches) {
  const s = new Set();
  for (const m of matches) { if (m.home) s.add(m.home); if (m.away) s.add(m.away); }
  return [...s].sort((a, b) => a.localeCompare(b));
}

function blank() {
  return { pj: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0, pts: 0 };
}
function addResult(rec, gf, ga) {
  rec.pj++; rec.gf += gf; rec.ga += ga;
  if (gf > ga) { rec.w++; rec.pts += 3; }
  else if (gf < ga) { rec.l++; }
  else { rec.d++; rec.pts += 1; }
}

export function teamProfile(matches, team) {
  const fixtures = matches
    .filter((m) => m.home === team || m.away === team)
    .sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || ""));

  const overall = blank(), home = blank(), away = blank();
  const acc = {}; // stat -> {for, against, n}
  for (const k of STAT_KEYS) acc[k] = { for: 0, against: 0, n: 0 };
  const form = []; // resultados jugados, cronológico

  for (const m of fixtures) {
    const isHome = m.home === team;
    if (m.finished && Array.isArray(m.result)) {
      const gf = isHome ? m.result[0] : m.result[1];
      const ga = isHome ? m.result[1] : m.result[0];
      addResult(overall, gf, ga);
      addResult(isHome ? home : away, gf, ga);
      form.push(gf > ga ? "W" : gf < ga ? "L" : "D");
      const sr = m.statsReal;
      if (sr) {
        for (const k of STAT_KEYS) {
          if (!sr[k]) continue;
          acc[k].for += isHome ? sr[k].home : sr[k].away;
          acc[k].against += isHome ? sr[k].away : sr[k].home;
          acc[k].n++;
        }
      }
    }
  }

  const tendencies = {};
  for (const k of STAT_KEYS) {
    if (acc[k].n) tendencies[k] = {
      for: Math.round((acc[k].for / acc[k].n) * 10) / 10,
      against: Math.round((acc[k].against / acc[k].n) * 10) / 10,
    };
  }

  return {
    name: team,
    fixtures,
    overall, home, away,
    form: form.slice(-5),
    tendencies,
    league: fixtures[0]?.league || "",
    crest: fixtures.find((m) => m.home === team)?.homeCrest
      || fixtures.find((m) => m.away === team)?.awayCrest || null,
    colors: fixtures.find((m) => m.home === team)?.homeColors
      || fixtures.find((m) => m.away === team)?.awayColors || null,
  };
}

// Goleadores/asistentes de este equipo desde data.players (football-data.org).
export function teamScorers(players, team) {
  if (!players) return [];
  const out = [];
  const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const t = norm(team);
  for (const lg of Object.values(players)) {
    const r = lg?.rankings || {};
    for (const [cat, block] of Object.entries(r)) {
      for (const p of block.players || []) {
        const pt = norm(p.team);
        if (pt && (t.includes(pt) || pt.includes(t) || t.split(" ").some((w) => w.length > 3 && pt.includes(w)))) {
          out.push({ ...p, cat: block.label || cat });
        }
      }
    }
  }
  return out;
}
