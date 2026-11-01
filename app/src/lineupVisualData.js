/** Pure XI validation: reject duplicate names and unknown positional mappings.
 * Never infer an official XI or draw a player in an invented pitch slot.
 */
const strip = value => String(value || "").normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "").toLowerCase()
  .replace(/[^a-z0-9]+/g, " ").trim();

const ALIASES = {
  POR: ["POR", "GK", "G", "GOALKEEPER", "PORTERO"],
  LI: ["LI", "LB", "LEFT BACK", "LATERAL IZQUIERDO"],
  LD: ["LD", "RB", "RIGHT BACK", "LATERAL DERECHO"],
  DFC: ["DFC", "CB", "CENTRE BACK", "CENTER BACK", "CENTRAL", "DEFENSA CENTRAL"],
  CAI: ["CAI", "LWB", "LEFT WING BACK"],
  CAD: ["CAD", "RWB", "RIGHT WING BACK"],
  MCD: ["MCD", "CDM", "DM", "DEFENSIVE MIDFIELDER"],
  MC: ["MC", "CM", "MIDFIELDER", "CENTRAL MIDFIELDER"],
  MP: ["MP", "CAM", "AM", "ATTACKING MIDFIELDER"],
  MI: ["MI", "LM", "LEFT MIDFIELDER"],
  MD: ["MD", "RM", "RIGHT MIDFIELDER"],
  EI: ["EI", "LW", "LEFT WINGER"],
  ED: ["ED", "RW", "RIGHT WINGER"],
  DC: ["DC", "ST", "CF", "STRIKER", "CENTRE FORWARD", "CENTER FORWARD"],
};
const LOOKUP = new Map(Object.entries(ALIASES)
  .flatMap(([code, labels]) => labels.map(label => [strip(label), code])));
const DEPTH = {POR:0,LI:1,LD:1,DFC:1,CAI:1,CAD:1,MCD:2,MC:2,MP:2,MI:2,MD:2,EI:3,ED:3,DC:3};
const LATERAL = {LI:0,CAI:0,MI:0,EI:0,DFC:2,MCD:2,MC:2,MP:2,DC:2,POR:2,LD:4,CAD:4,MD:4,ED:4};
export const normalizePlayerName = strip;

export function positionCode(raw) {
  return LOOKUP.get(strip(raw)) || null;
}

export function analyseLineup(names, positions) {
  const raw = Array.isArray(names) ? names : [];
  const hasPositions = Array.isArray(positions) && positions.length === raw.length;
  const used = new Set();
  const roster = [];
  let duplicates = 0;
  for (let i = 0; i < raw.length; i++) {
    const name = typeof raw[i] === "string" ? raw[i].trim()
      : String(raw[i]?.name || raw[i]?.player || "").trim();
    const key = strip(name);
    if (!key) continue;
    if (used.has(key)) { duplicates++; continue; }
    used.add(key);
    roster.push({ name, position: hasPositions ? positionCode(positions[i]) : null, index:i });
  }
  const full = raw.length === 11 && roster.length === 11 && !duplicates;
  const mapped = full && roster.every(p => p.position);
  const gk = roster.filter(p => p.position === "POR").length;
  const canPlot = mapped && gk === 1;
  const rows = canPlot ? [0,1,2,3].map(depth => roster
    .filter(p => DEPTH[p.position] === depth)
    .sort((a,b) => (LATERAL[a.position] ?? 2) - (LATERAL[b.position] ?? 2) || a.index - b.index)
  ).filter(row => row.length) : [];
  return {
    roster, count:roster.length, full, canPlot,
    duplicates, invalidPositions: full && !canPlot,
    rows, status: full ? (canPlot ? "plottable" : "list_only") : "incomplete",
  };
}

export function confirmedLineup(a) {
  if (!a || String(a.status || "").toLowerCase() !== "confirmado") return false;
  return analyseLineup(a.local, a.posiciones_local).full &&
    analyseLineup(a.visitante, a.posiciones_visitante).full;
}

/** Resolve a single rich player by full name and specific team, never by surname alone. */
export function lineupPlayerRecord(players, name, team) {
  if (!name || !team || !players) return null;
  const teamKey = strip(team).split(" ").filter(x => !["fc","cf","sad","s a d"].includes(x)).join(" ");
  const nameKey = strip(name);
  const pool = Object.values(players).flatMap(group => Array.isArray(group?.players) ? group.players : []);
  const hits = pool.filter(p => {
    const candidateTeam = strip(p.team || p.equipo).split(" ").filter(x => !["fc","cf","sad"].includes(x)).join(" ");
    return strip(p.player || p.jugador || p.name) === nameKey && candidateTeam === teamKey;
  });
  return hits.length === 1 ? hits[0] : null;
}
