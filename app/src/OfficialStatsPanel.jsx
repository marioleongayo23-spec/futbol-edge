import { formatOfficialStat, officialStatsRows } from "./officialStats";

function numeric(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number.parseFloat(String(value ?? "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : 0;
}

function CompareBars({ rows, home, away }) {
  return (
    <div className="fe-visual-stack" aria-label={`Comparativa visual ${home} y ${away}`}>
      {rows.map((row) => {
        const hv = Math.max(0, numeric(row.home));
        const av = Math.max(0, numeric(row.away));
        const max = Math.max(hv, av, 1);
        const hp = Math.max(hv > 0 ? 6 : 0, (hv / max) * 100);
        const ap = Math.max(av > 0 ? 6 : 0, (av / max) * 100);
        return (
          <div className="fe-compare-row" key={row.key}>
            <span className="fe-compare-value home">{formatOfficialStat(row.home, row.suffix)}</span>
            <span className="fe-dualbar-half home" aria-hidden="true"><i className="fe-dualbar-fill" style={{ width: `${hp}%` }} /></span>
            <span className="fe-compare-label">{row.label}</span>
            <span className="fe-dualbar-half away" aria-hidden="true"><i className="fe-dualbar-fill" style={{ width: `${ap}%` }} /></span>
            <span className="fe-compare-value away">{formatOfficialStat(row.away, row.suffix)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function OfficialStatsPanel({ match }) {
  const rows = officialStatsRows(match?.official_context, match?.home, match?.away);
  if (!rows.length) return null;
  const stateLabel = match?.finished ? "POSTPARTIDO" : "EN VIVO";
  return (
    <div className="card section-anchor" id="match-official-stats" data-source="api-football-live-stats">
      <div className="row-between">
        <div>
          <div className="lbl">Estadísticas oficiales API-Football</div>
          <div className="mut">{match.home} <span className="dim">vs</span> {match.away}</div>
        </div>
        <span className="pill">{stateLabel}</span>
      </div>

      <CompareBars rows={rows} home={match.home} away={match.away} />

      {/* La tabla se conserva para accesibilidad, auditoría y el contrato E2E. */}
      <div className="tbl-wrap fe-audit-table">
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
