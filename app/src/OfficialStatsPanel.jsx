import { formatOfficialStat, officialStatsRows } from "./officialStats";

export default function OfficialStatsPanel({ match }) {
  const rows = officialStatsRows(match?.official_context, match?.home, match?.away);
  if (!rows.length) return null;
  const stateLabel = match?.finished ? "POSTPARTIDO" : "EN VIVO";
  return (
    <div className="card section-anchor" id="match-official-stats" data-source="api-football-live-stats">
      <div className="row-between">
        <div className="lbl">Estadísticas oficiales API-Football</div>
        <span className="pill">{stateLabel}</span>
      </div>
      <div className="tbl-wrap">
        <table className="tbl-mk">
          <thead>
            <tr><th className="tl">Métrica</th><th>{match.home}</th><th>{match.away}</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="tl">{row.label}</td>
                <td>{formatOfficialStat(row.home, row.suffix)}</td>
                <td>{formatOfficialStat(row.away, row.suffix)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note source-note">
        Dato oficial live/postpartido de API-Football. Se muestra para seguimiento y evaluación; no alimenta retrospectivamente la predicción prepartido.
      </p>
    </div>
  );
}
