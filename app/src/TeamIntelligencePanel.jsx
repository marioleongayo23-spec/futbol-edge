import { useMemo } from "react";
import { crestFor, fmtKick } from "./feed";
import { TEAM_STYLE_DIMENSIONS, teamIntelligence, teamStyleTraits } from "./teamIntelligenceData";
import "./team-intelligence.css";

const pct = (value) => Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : "—";
const num = (value, digits = 1) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits).replace(/\.0$/, "") : "—";

function Radar({ home, away }) {
  const rows = TEAM_STYLE_DIMENSIONS;
  const size = 300, center = 150, radius = 92;
  const point = (index, score = 100) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / rows.length;
    const r = radius * Math.max(0, Math.min(100, Number(score) || 0)) / 100;
    return [center + Math.cos(angle) * r, center + Math.sin(angle) * r];
  };
  const polygon = (snapshot) => {
    const vector = snapshot?.side?.style_vector || {};
    return rows.map(([key], index) => point(index, vector[key]?.score).join(",")).join(" ");
  };
  const hasHome = Boolean(home?.side?.style_vector);
  const hasAway = Boolean(away?.side?.style_vector);
  if (!hasHome && !hasAway) return <div className="ti-empty">Sin muestra táctica suficiente para construir el radar.</div>;
  return <svg className="ti-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Radar táctico del equipo por condición local y visitante">
    {[25, 50, 75, 100].map((score) => <polygon key={score} className="ti-radar-grid" points={rows.map((_, index) => point(index, score).join(",")).join(" ")} />)}
    {rows.map(([, label], index) => {
      const [x, y] = point(index, 122);
      return <text key={label} className="ti-radar-label" x={x} y={y} textAnchor="middle" dominantBaseline="middle">{label.replace("Intensidad de ", "").replace("Presión territorial", "Territorio").replace("Eficacia de remate", "Eficacia").replace("Exposición defensiva", "Exposición").replace("Volumen ofensivo", "Ataque")}</text>;
    })}
    {hasHome && <polygon className="ti-radar-home" points={polygon(home)} />}
    {hasAway && <polygon className="ti-radar-away" points={polygon(away)} />}
  </svg>;
}

function TraitColumn({ title, snapshot, kind }) {
  const traits = teamStyleTraits(snapshot);
  if (!traits.length) return <div className="ti-traits"><div className="ti-subtitle">{title}</div><div className="ti-empty compact">Sin muestra.</div></div>;
  return <div className="ti-traits">
    <div className="ti-subtitle">{title}<span>{snapshot?.side?.samples ? `${snapshot.side.samples} partidos` : ""}</span></div>
    {traits.map((trait) => <div className="ti-trait" key={trait.key}>
      <div className="ti-trait-head"><span>{trait.label}</span><b>P{trait.score}</b></div>
      <div className="ti-track"><i className={kind} style={{ width: `${trait.score}%` }} /></div>
      <small>{trait.observed ?? "—"} {trait.unit}</small>
    </div>)}
  </div>;
}

function KeyPlayer({ player, onPlayer }) {
  const profile = player.profile || {};
  return <button type="button" className="ti-player" onClick={() => onPlayer?.(player)} aria-label={`Ver perfil de ${player.player}`}>
    <div className="ti-player-photo">
      {profile.photo ? <img src={profile.photo} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} /> : <span>{String(player.player || "?").slice(0, 2).toUpperCase()}</span>}
    </div>
    <div className="ti-player-copy"><b>{player.player}</b><span>{player.position || player.api_position || "posición sin publicar"}</span></div>
    <div className="ti-player-kpis"><span><b>{player.goals ?? 0}</b> G</span><span><b>{player.assists ?? 0}</b> A</span>{player.rating != null && <span><b>{num(player.rating)}</b> RAT</span>}</div>
  </button>;
}

function NextMatch({ data, team }) {
  const next = data?.next;
  if (!next) return <div className="ti-empty">No hay un próximo partido disponible en el feed.</div>;
  const m = next.match;
  const rivalCrest = next.isHome ? m.awayCrest : m.homeCrest;
  const rivalColors = next.isHome ? m.awayColors : m.homeColors;
  const ownXg = Array.isArray(m.xg) ? m.xg[next.isHome ? 0 : 1] : null;
  const ownProb = Array.isArray(m.probs) ? m.probs[next.isHome ? 0 : 2] : null;
  return <div className="ti-next">
    <div className="ti-next-head">
      <img className="crest" alt="" src={crestFor(next.opponent, rivalColors, rivalCrest)} onError={(e) => (e.currentTarget.src = crestFor(next.opponent, rivalColors, null))} />
      <div><span>{m.league} · {fmtKick(m.kickoff)}</span><b>{team} {next.isHome ? "vs" : "@"} {next.opponent}</b><small>{m.venue || "estadio por confirmar"}</small></div>
    </div>
    <div className="ti-next-kpis">
      {ownProb != null && <span><small>Prob. victoria</small><b>{pct(ownProb)}</b></span>}
      {ownXg != null && <span><small>xG modelo</small><b>{num(ownXg, 2)}</b></span>}
      {m.alineacion?.status && <span><small>Once</small><b>{m.alineacion.status}</b></span>}
    </div>
    {(next.clashes || []).length > 0 && <div className="ti-clashes">{next.clashes.slice(0, 3).map((clash) => <span key={clash.edge || clash.label}>⚔ {clash.label} · <b>{clash.strength}/100</b></span>)}</div>}
  </div>;
}

export default function TeamIntelligencePanel({ team, matches, players, onPlayer }) {
  const data = useMemo(() => teamIntelligence(matches, players, team), [matches, players, team]);
  const strongest = teamStyleTraits(data.style.latest).slice().sort((a, b) => b.score - a.score).slice(0, 2);
  const continuity = data.continuity;
  return <section className="team-intelligence" data-testid="team-intelligence">
    <div className="ti-grid-main">
      <div className="card ti-radar-card">
        <div className="row-between"><div className="lbl">Identidad táctica</div><span className="pill">percentiles observados</span></div>
        <Radar home={data.style.home} away={data.style.away} />
        <div className="ti-legend"><span><i className="home" /> Casa</span><span><i className="away" /> Fuera</span></div>
        {strongest.length > 0 && <div className="ti-extremes">{strongest.map((trait) => <span key={trait.key}>{trait.label} <b>P{trait.score}</b></span>)}</div>}
        <p className="note source-note">Perfil descriptivo basado en splits reales casa/fuera. Exposición defensiva alta significa más remates concedidos; no se interpreta como una fortaleza.</p>
      </div>
      <div className="card ti-style-card">
        <div className="lbl">Casa vs fuera</div>
        <div className="ti-style-columns"><TraitColumn title="Como local" snapshot={data.style.home} kind="home" /><TraitColumn title="Como visitante" snapshot={data.style.away} kind="away" /></div>
      </div>
    </div>

    <div className="ti-grid-support">
      <div className="card ti-context-card">
        <div className="lbl">Contexto del XI</div>
        <div className="ti-context-kpis">
          <span><small>Continuidad XI</small><b>{continuity.pct != null ? `${continuity.pct}%` : "—"}</b><em>{continuity.shared != null ? `${continuity.shared} titulares repetidos` : "sin dos onces comparables"}</em></span>
          <span><small>Bajas próximas</small><b>{data.absences.length}</b><em>{data.absences.length ? data.absences.slice(0, 2).map((row) => row.jugador || row.detalle || row.detail).filter(Boolean).join(" · ") : "ninguna publicada"}</em></span>
          <span><small>Forma 5</small><b>{data.base.form.length ? data.base.form.join("·") : "—"}</b><em>{data.base.overall.pj} partidos finalizados en muestra</em></span>
        </div>
      </div>
      <div className="card ti-next-card"><div className="lbl">Próximo matchup</div><NextMatch data={data} team={team} /></div>
    </div>

    {data.keyPlayers.length > 0 && <div className="card ti-key-card">
      <div className="row-between"><div className="lbl">Jugadores referencia</div><span className="pill">producción real</span></div>
      <div className="ti-key-grid">{data.keyPlayers.map((player) => <KeyPlayer key={`${player.team}-${player.player}`} player={player} onPlayer={onPlayer} />)}</div>
    </div>}
  </section>;
}
