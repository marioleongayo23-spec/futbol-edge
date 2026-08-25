function fmt(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function statCell(row, key) {
  const stat = (row.stats || []).find((item) => item.key === key);
  if (!stat) return <span className="dim">—</span>;
  const delta = Number(stat.delta?.total || 0);
  const sign = delta > 0 ? "+" : "";
  return <span title={`${stat.label}: predicho ${fmt(stat.predicted?.home)}-${fmt(stat.predicted?.away)} · real ${fmt(stat.actual?.home)}-${fmt(stat.actual?.away)}`}>
    <b>{fmt(stat.predicted?.total)}→{fmt(stat.actual?.total)}</b>
    <small className="dim" style={{ display: "block" }}>Δ {sign}{fmt(delta)}</small>
  </span>;
}

export default function AccuracyMatchDetails({ rows }) {
  if (!(rows || []).length) return null;
  return <div style={{ marginTop: 16 }}>
    <div className="row-between" style={{ marginBottom: 8 }}>
      <div className="lbl">Partidos finalizados · detalle predicho vs real</div>
      <span className="pill">{rows.length} evaluados</span>
    </div>
    <div className="mut" style={{ marginBottom: 10 }}>
      El 1X2 se marca como acierto/fallo exacto. En estadísticas se muestra el valor esperado prepartido, el dato final y su desviación; no se fuerza un “acierto” binario sobre una variable continua.
    </div>
    <div className="tbl-wrap">
      <table className="tbl-mk accuracy-detail-table">
        <thead><tr>
          <th className="tl">Partido</th><th>1X2</th><th>Goles</th><th>Remates</th><th>A puerta</th><th>Córners</th><th>Faltas</th><th>Amarillas</th><th>Rojas</th>
        </tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.id || `${row.date}-${row.home}-${row.away}`}>
            <td className="tl">
              <b>{row.home}–{row.away}</b>
              <small className="dim" style={{ display: "block" }}>{row.date || ""}{row.stats_source ? ` · ${row.stats_source}` : ""}</small>
            </td>
            <td>
              <span className={"pill " + (row.hit_1x2 ? "y" : "n")}>{row.predicted_sign || "—"}→{row.actual_sign || "—"} {row.hit_1x2 == null ? "" : row.hit_1x2 ? "✓" : "✕"}</span>
            </td>
            <td>{statCell(row, "goals")}</td>
            <td>{statCell(row, "shots")}</td>
            <td>{statCell(row, "sot")}</td>
            <td>{statCell(row, "corners")}</td>
            <td>{statCell(row, "fouls")}</td>
            <td>{statCell(row, "yellows")}</td>
            <td>{statCell(row, "reds")}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </div>;
}
