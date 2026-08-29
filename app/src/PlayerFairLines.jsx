import { useMemo, useState } from "react";

const METRICS = [
  ["r", "Remates"],
  ["rp", "Remates a puerta"],
  ["fc", "Faltas cometidas"],
  ["fr", "Faltas recibidas"],
  ["t", "Tarjeta amarilla"],
];

function allPlayers(match) {
  const lineup = match?.alineacion || {};
  return [
    ...(lineup.clave_local || []).map((row) => ({ ...row, team: match.home })),
    ...(lineup.clave_visitante || []).map((row) => ({ ...row, team: match.away })),
  ].filter((row) => row?.fair_lines && Object.keys(row.fair_lines).length);
}

function pct(value) {
  return value == null ? "—" : `${Math.round(Number(value) * 100)}%`;
}

function odds(value) {
  return value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(2);
}

export default function PlayerFairLines({ match }) {
  const players = useMemo(() => allPlayers(match), [match]);
  const [playerKey, setPlayerKey] = useState("");
  const [metric, setMetric] = useState("r");
  if (!players.length) return null;

  const selected = players.find((row) => `${row.team}|${row.jugador}` === playerKey) || players[0];
  const available = METRICS.filter(([key]) => (selected.fair_lines?.[key] || []).length);
  const selectedMetric = available.some(([key]) => key === metric) ? metric : available[0]?.[0];
  const lines = selected.fair_lines?.[selectedMetric] || [];
  const metricLabel = METRICS.find(([key]) => key === selectedMetric)?.[1] || selectedMetric;

  return (
    <div className="card section-anchor" id="match-player-fair-lines">
      <div className="row-between">
        <div className="lbl">Líneas justas de jugador</div>
        <span className="pill">sin cuota de bookmaker</span>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <select aria-label="Jugador para líneas justas" value={`${selected.team}|${selected.jugador}`} onChange={(event) => setPlayerKey(event.target.value)}>
          {players.map((row) => <option key={`${row.team}|${row.jugador}`} value={`${row.team}|${row.jugador}`}>{row.jugador} · {row.team}</option>)}
        </select>
        <select aria-label="Métrica de jugador para líneas justas" value={selectedMetric} onChange={(event) => setMetric(event.target.value)}>
          {available.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
      </div>
      <div className="chips" style={{ marginTop: 8 }}>
        <span className="chip">Esperado <b>{selected[selectedMetric] ?? "—"}</b></span>
        <span className="chip">Min previstos <b>{selected.min ?? "—"}</b></span>
        {selected.sample_minutes && <span className="chip">Muestra <b>{selected.sample_minutes} min</b></span>}
      </div>
      <div className="tbl-wrap" style={{ marginTop: 10 }}>
        <table className="tbl-mk">
          <thead><tr><th scope="col" className="tl">{metricLabel}</th><th scope="col">Over</th><th scope="col">Cuota justa O</th><th scope="col">Under</th><th scope="col">Cuota justa U</th></tr></thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.line}>
                <td className="tl"><b>{line.line}</b></td>
                <td>{pct(line.over)}</td>
                <td>{odds(line.fair_over_odds)}</td>
                <td>{pct(line.under)}</td>
                <td>{odds(line.fair_under_odds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note source-note">Baseline Poisson sobre la expectativa de partido derivada de tasas reales API-Football y minutos previstos. Es una probabilidad/cuota justa teórica, no una recomendación ni una cuota disponible. Solo puede existir value cuando se compare con una cuota real de una casa.</p>
    </div>
  );
}
