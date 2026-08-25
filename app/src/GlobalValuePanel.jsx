import { actionableValueRows, marketLabel, selectionLabel } from "./extendedValue";

export default function GlobalValuePanel({ rows, onOpen }) {
  const ranked = actionableValueRows(rows).slice(0, 20);
  if (!ranked.length) {
    return (
      <div className="card" data-testid="global-value-panel">
        <div className="lbl">Ranking value global</div>
        <div className="note">Sin value accionable con cuota real y edge superior al 2%.</div>
      </div>
    );
  }
  return (
    <div className="card" data-testid="global-value-panel">
      <div className="row-between">
        <div className="lbl">Ranking value global</div>
        <span className="pill">{ranked.length} señales</span>
      </div>
      <div className="mut" style={{ marginBottom: 8 }}>
        Solo cuotas reales. Edge = probabilidad del modelo × cuota − 1; en hándicap con push se usa retorno esperado equivalente.
      </div>
      <div className="tbl-wrap">
        <table className="tbl-mk">
          <thead><tr><th className="tl">Partido</th><th className="tl">Mercado</th><th className="tl">Selección</th><th>Cuota</th><th>Prob.</th><th>Edge</th><th className="tl">Casa</th></tr></thead>
          <tbody>
            {ranked.map((row, index) => (
              <tr key={`${row.match_id}-${row.market}-${row.selection}-${row.line}-${row.player}-${index}`}>
                <td className="tl">
                  <button type="button" className="mini" onClick={() => onOpen?.(row.match_id)}>{row.home}–{row.away}</button>
                </td>
                <td className="tl">{marketLabel(row.market)}</td>
                <td className="tl">{selectionLabel(row)}</td>
                <td>{Number(row.odds).toFixed(2)}</td>
                <td>{Math.round(Number(row.modelProb) * 100)}%</td>
                <td className="value-yes">+{(Number(row.edge) * 100).toFixed(1)}%</td>
                <td className="tl">{row.bookmaker || row.market_source || "mercado"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note source-note">BTTS, córners, tarjetas, hándicap y props solo aparecen cuando la fuente devuelve una cuota real compatible con nuestra línea.</p>
    </div>
  );
}
