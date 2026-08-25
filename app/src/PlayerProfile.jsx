import { useMemo } from "react";
import { crestFor, fmtKick } from "./feed";
import { nextFixture, playerMetricRows, positionGroup, profileCompleteness, resolvePlayer } from "./playerProfileData";
import "./player-profile.css";

const fmt = (value, digits = 2) => {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits).replace(/\.00$/, "") : "—";
};

const posLabel = {
  goalkeeper: "Portero",
  defender: "Defensa",
  midfielder: "Centrocampista",
  attacker: "Atacante",
  other: "Jugador",
};

function Initials({ name }) {
  const chars = String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join("");
  return <div className="pp-avatar-fallback" aria-hidden="true">{chars || "?"}</div>;
}

function Radar({ metrics }) {
  const rows = metrics.filter((m) => m.percentile != null).slice(0, 6);
  if (rows.length < 3) return <div className="pp-empty">Sin muestra posicional suficiente para construir un radar fiable.</div>;
  const size = 280, c = 140, r = 92;
  const point = (i, pct = 100) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / rows.length;
    const rr = r * pct / 100;
    return [c + Math.cos(a) * rr, c + Math.sin(a) * rr];
  };
  const polygon = rows.map((m, i) => point(i, m.percentile).join(",")).join(" ");
  return (
    <svg className="pp-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Radar de percentiles por posición">
      {[25, 50, 75, 100].map((pct) => <polygon key={pct} className="pp-radar-grid" points={rows.map((_, i) => point(i, pct).join(",")).join(" ")} />)}
      {rows.map((_, i) => { const [x, y] = point(i); return <line key={i} className="pp-radar-axis" x1={c} y1={c} x2={x} y2={y} />; })}
      <polygon className="pp-radar-shape" points={polygon} />
      {rows.map((m, i) => {
        const [x, y] = point(i, 121);
        return <text key={m.key} className="pp-radar-label" x={x} y={y} textAnchor="middle" dominantBaseline="middle">{m.short}</text>;
      })}
    </svg>
  );
}

function MetricBars({ metrics }) {
  if (!metrics.length) return <div className="pp-empty">Todavía no hay métricas por 90 verificadas para este jugador.</div>;
  return <div className="pp-metrics">{metrics.map((m) => (
    <div className="pp-metric" key={m.key}>
      <div className="pp-metric-head"><span>{m.label}</span><b>{fmt(m.value)}</b></div>
      <div className="pp-track"><i style={{ width: `${m.percentile ?? 0}%` }} /></div>
      <div className="pp-metric-foot"><span>{m.percentile != null ? `P${m.percentile} de su posición` : "sin percentil"}</span><span>{m.sample >= 5 ? `n=${m.sample}` : "muestra insuficiente"}</span></div>
    </div>
  ))}</div>;
}

function PropTile({ label, value }) {
  if (value == null || !Number.isFinite(Number(value))) return null;
  return <div className="pp-prop"><span>{label}</span><b>{fmt(value)}</b></div>;
}

export default function PlayerProfile({ candidate, players, matches, onBack, onTeam }) {
  const player = useMemo(() => resolvePlayer(players, candidate), [players, candidate]);
  const metrics = useMemo(() => playerMetricRows(players, player), [players, player]);
  const next = useMemo(() => nextFixture(matches, player), [matches, player]);
  if (!player) return <div className="card"><button type="button" className="back" onClick={onBack}>← Volver</button><div className="pp-empty">No se ha podido resolver este jugador en el feed.</div></div>;

  const profile = player.profile || {};
  const season = player.season || {};
  const expected = player.expected_match || {};
  const group = positionGroup(player.position || player.api_position);
  const completeness = profileCompleteness(player);
  const teamMatch = next ? (next.home === player.team ? { rival: next.away, crest: next.awayCrest, colors: next.awayColors } : { rival: next.home, crest: next.homeCrest, colors: next.homeColors }) : null;

  return (
    <div className="player-profile" data-testid="player-profile">
      <button type="button" className="back" onClick={onBack}>← Volver</button>
      <section className="pp-hero card">
        <div className="pp-photo-wrap">
          {profile.photo ? <img className="pp-photo" src={profile.photo} alt={`Foto de ${player.player}`} onError={(e) => { e.currentTarget.style.display = "none"; e.currentTarget.nextElementSibling?.classList.add("show"); }} /> : null}
          <Initials name={player.player} />
        </div>
        <div className="pp-identity">
          <div className="pp-eyebrow">PLAYER INTELLIGENCE · {posLabel[group]}</div>
          <h1>{player.player}</h1>
          <button type="button" className="pp-team-link" onClick={() => onTeam?.(player.team)}>{player.team || "Equipo por confirmar"}</button>
          <div className="pp-tags">
            {(player.position || player.api_position) && <span>{player.position || player.api_position}</span>}
            {profile.age && <span>{profile.age} años</span>}
            {profile.nationality && <span>{profile.nationality}</span>}
            {profile.height && <span>{profile.height}</span>}
            {profile.weight && <span>{profile.weight}</span>}
          </div>
        </div>
        <div className="pp-quality">
          <span>Completitud</span><b>{completeness}%</b>
          <div className="pp-quality-track"><i style={{ width: `${completeness}%` }} /></div>
          <small>solo datos verificados del feed</small>
        </div>
      </section>

      <section className="pp-kpis">
        <div className="pp-kpi card"><span>Rating</span><b>{fmt(player.rating)}</b><small>API-Football</small></div>
        <div className="pp-kpi card"><span>Minutos</span><b>{season.minutes ?? player.sample_minutes ?? player.min ?? "—"}</b><small>muestra temporada</small></div>
        <div className="pp-kpi card"><span>Titularidad</span><b>{season.starter_rate != null ? `${Math.round(season.starter_rate * 100)}%` : player.starter_probability != null ? `${Math.round(player.starter_probability * 100)}%` : "—"}</b><small>{season.starts != null && season.appearances != null ? `${season.starts}/${season.appearances} apariciones` : "sin muestra completa"}</small></div>
        <div className="pp-kpi card"><span>Min. esperados</span><b>{player.expected_minutes ?? season.expected_start_minutes ?? "—"}</b><small>si parte de inicio</small></div>
      </section>

      <section className="pp-grid-two">
        <div className="card pp-panel"><div className="lbl">Percentiles por posición</div><Radar metrics={metrics} /><div className="pp-note">Comparación únicamente contra jugadores del mismo grupo posicional y con ≥270 minutos cuando existe una muestra de al menos 5.</div></div>
        <div className="card pp-panel"><div className="lbl">Producción por 90</div><MetricBars metrics={metrics} /></div>
      </section>

      {(season.per90_extended || player.pass_accuracy_pct != null) && <section className="card pp-panel">
        <div className="lbl">Perfil de rol</div>
        <div className="pp-role-grid">
          <PropTile label="Precisión pase %" value={player.pass_accuracy_pct} />
          <PropTile label="Pases /90" value={season.per90_extended?.passes} />
          <PropTile label="Pases clave /90" value={season.per90_extended?.key_passes} />
          <PropTile label="Entradas /90" value={season.per90_extended?.tackles} />
          <PropTile label="Intercepciones /90" value={season.per90_extended?.interceptions} />
          <PropTile label="Duelos /90" value={season.per90_extended?.duels} />
          <PropTile label="Duelos ganados /90" value={season.per90_extended?.duels_won} />
          <PropTile label="Regates buenos /90" value={season.per90_extended?.dribbles_success} />
          <PropTile label="Paradas /90" value={season.per90_extended?.saves} />
        </div>
      </section>}

      <section className="pp-grid-two">
        <div className="card pp-panel">
          <div className="lbl">Próximo partido</div>
          {next && teamMatch ? <div className="pp-next">
            <img className="crest" alt="" src={crestFor(teamMatch.rival, teamMatch.colors, teamMatch.crest)} onError={(e) => (e.currentTarget.src = crestFor(teamMatch.rival, teamMatch.colors, null))} />
            <div><span className="mut">{next.league} · {fmtKick(next.kickoff)}</span><b>vs {teamMatch.rival}</b><small>{next.venue || "Estadio por confirmar"}</small></div>
          </div> : <div className="pp-empty">No hay un próximo partido disponible en el feed.</div>}
        </div>
        <div className="card pp-panel">
          <div className="lbl">Expectativa individual · próximo XI</div>
          {Object.keys(expected).length ? <div className="pp-role-grid">
            <PropTile label="Goles" value={expected.g} /><PropTile label="Asistencias" value={expected.a} /><PropTile label="Remates" value={expected.r} /><PropTile label="A puerta" value={expected.rp} /><PropTile label="Faltas cometidas" value={expected.fc} /><PropTile label="Faltas recibidas" value={expected.fr} /><PropTile label="Tarjetas" value={expected.t} />
          </div> : <div className="pp-empty">Las props solo aparecen cuando existe evidencia prepartido verificable; no se rellenan con valores inventados.</div>}
        </div>
      </section>

      <div className="pp-source">Fuente principal: {player.rich_source || player.source || "feed consolidado"}. Los percentiles son descriptivos y todavía no alteran el 1X2 hasta superar validación walk-forward.</div>
    </div>
  );
}
