import { portfolioClv } from "./clv";

function signed(value, suffix = "%") {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value}${suffix}`;
}

export default function ClvPanel({ bets, matches }) {
  const summary = portfolioClv(bets, matches);
  if (!summary.n) {
    return (
      <div className="card">
        <div className="lbl">CLV histórico</div>
        <div className="note">Se activará cuando haya apuestas 1X2 vinculadas a partidos terminados con cuota de cierre histórica real.</div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="row-between">
        <div className="lbl">CLV histórico</div>
        <span className="pill">n={summary.n}</span>
      </div>
      <div className="chips">
        <span className="chip">CLV medio <b className={summary.averagePct >= 0 ? "value-yes" : "value-no"}>{signed(summary.averagePct)}</b></span>
        <span className="chip">CLV ponderado stake <b className={summary.stakeWeightedPct >= 0 ? "value-yes" : "value-no"}>{signed(summary.stakeWeightedPct)}</b></span>
        <span className="chip">Cierres batidos <b>{summary.positiveRatePct}%</b></span>
        <span className="chip">Ventaja justa cierre <b className={summary.averageFairEdgePp >= 0 ? "value-yes" : "value-no"}>{signed(summary.averageFairEdgePp, " pp")}</b></span>
      </div>
      <div className="tbl-wrap" style={{ marginTop: 10 }}>
        <table className="tbl-mk">
          <thead><tr><th className="tl">Apuesta</th><th>Tomada</th><th>Cierre</th><th>CLV</th><th>Fair edge</th></tr></thead>
          <tbody>
            {summary.rows.slice(0, 12).map((row) => (
              <tr key={row.bet.id}>
                <td className="tl"><b>{row.bet.match}</b><div className="mk-sub">{row.bet.sel} · {row.source}</div></td>
                <td>{row.takenOdds.toFixed(2)}</td>
                <td>{row.closingOdds.toFixed(2)}</td>
                <td className={row.priceClvPct >= 0 ? "value-yes" : "value-no"}>{signed(row.priceClvPct)}</td>
                <td className={row.fairEdgePp >= 0 ? "value-yes" : "value-no"}>{signed(row.fairEdgePp, " pp")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note source-note">CLV precio = cuota tomada ÷ cuota de cierre − 1. La ventaja justa compara la probabilidad sin vig del cierre con el break-even de la cuota tomada. CLV positivo indica que se batió al mercado al cierre; no garantiza beneficio en una apuesta individual.</p>
    </div>
  );
}
