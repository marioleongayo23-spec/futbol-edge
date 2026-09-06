import { crestFor } from './feed';

function ProbabilityRing({ probs, favorite }) {
  const radius = 62, circumference = 2 * Math.PI * radius;
  const colors = ['var(--green)', 'var(--ring-draw)', 'var(--blue)'];
  return <svg className="probability-ring" viewBox="0 0 160 160" role="img"
    aria-label={`Probabilidades: local ${probs[0]}%, empate ${probs[1]}%, visitante ${probs[2]}%`}>
    <circle cx="80" cy="80" r="72" fill="none" stroke="var(--line)" strokeDasharray="1 7" />
    <circle cx="80" cy="80" r={radius} fill="none" stroke="var(--line)" strokeWidth="8" />
    {probs.map((p, i) => {
      const start = probs.slice(0, i).reduce((sum, value) => sum + value, 0) / 100 * circumference;
      return <circle key={i} cx="80" cy="80" r={radius} fill="none" stroke={colors[i]} strokeWidth="8"
        strokeDasharray={`${Math.max(0, p / 100 * circumference - 3)} ${circumference}`}
        strokeDashoffset={-start} transform="rotate(-90 80 80)" />;
    })}
    <text x="80" y="78" textAnchor="middle" className="ring-value">{probs[favorite]}<tspan className="ring-percent">%</tspan></text>
    <text x="80" y="98" textAnchor="middle" className="ring-label">{['LOCAL', 'EMPATE', 'VISITANTE'][favorite]}</text>
  </svg>;
}

export default function MissionOverview({ pick, dayMatches, predicted, strong, goalsDay, acc, interval, onOpen }) {
  const match = pick?.m;
  const favorite = match ? match.probs.indexOf(Math.max(...match.probs)) : -1;
  return <div className="mission-overview">
    <section className="spotlight" aria-label="Partido destacado">
      <div className="spotlight-heading"><span className="eyebrow">Análisis destacado</span><span className="instrument-label">1 / X / 2</span></div>
      {match ? <>
        <div className="spotlight-body">
          <div className="spotlight-match">
            <span className="spotlight-meta">{match.league} · {new Date(match.kickoff).toLocaleTimeString('es-ES', {hour:'2-digit',minute:'2-digit',timeZone:'Europe/Madrid'})} Madrid</span>
            <h2>{[match.home, match.away].map((team, i) => <span key={i}>
              <img className="crest" alt="" src={crestFor(team, i ? match.awayColors : match.homeColors, i ? match.awayCrest : match.homeCrest)}
                onError={e => {e.currentTarget.src = crestFor(team, null, null);}} />{team}
            </span>)}</h2>
          </div>
          <ProbabilityRing probs={match.probs} favorite={favorite} />
        </div>
        <div className="spotlight-bottom"><div className="probability-key">{['Local', 'Empate', 'Visitante'].map((label, i) => <span key={label}><i className={`key-${i}`} />{label} <b>{match.probs[i]}%</b></span>)}</div>
          <button className="analysis-button" type="button" onClick={() => onOpen(match)}>Abrir análisis <span aria-hidden="true">↗</span></button>
        </div>
        <p className="spotlight-note">Mayor probabilidad favorita del día. No equivale a una apuesta recomendada.</p>
      </> : <div className="spotlight-empty"><h2>La próxima lectura<br />está por llegar.</h2><p>Sin predicciones disponibles para este día. Puedes consultar los resultados o elegir otra fecha.</p></div>}
    </section>
    <div className="mission-metrics">
      <div className="stat"><span className="stat-k">Partidos</span><b className="stat-v">{dayMatches.length.toString().padStart(2, '0')}</b><span className="stat-s">{predicted.length} con predicción disponible</span></div>
      <div className="stat"><span className="stat-k">Goles esperados</span><b className="stat-v">{predicted.length ? goalsDay.toFixed(2) : '—'}</b><span className="stat-s">Media del modelo por partido</span></div>
      <div className="stat"><span className="stat-k">Favoritos ≥ 55%</span><b className="stat-v">{strong.toString().padStart(2, '0')}</b><span className="stat-s">Probabilidad, no tasa de acierto</span></div>
      <div className="stat"><span className="stat-k">Acierto modelo</span><b className="stat-v">{acc.pct == null ? '—' : `${acc.pct}%`}</b><span className="stat-s">{acc.total ? `${acc.hits}/${acc.total} · intervalo 95%: ${interval.map(v => Math.round(v * 100)).join('–')}%` : 'Aún sin muestra evaluable'}</span></div>
    </div>
  </div>;
}
