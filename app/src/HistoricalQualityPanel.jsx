function metric(value, digits = 4) {
  return value == null ? "—" : Number(value).toFixed(digits);
}

export default function HistoricalQualityPanel({ seeds }) {
  const entries = Object.entries(seeds || {});
  if (!entries.length) return null;
  return (
    <div className="card" data-testid="historical-quality-panel">
      <div className="lbl">Calibración histórica para arrancar la temporada</div>
      <div className="mut" style={{ marginBottom: 10 }}>
        Señal separada de la temporada en curso: walk-forward del año anterior con cierres reales. Se usa como semilla hasta que la muestra actual supera el mínimo.
      </div>
      {entries.map(([league, seed]) => {
        const q = seed.probability_quality || {};
        const cal = seed.market_calibration || {};
        const rows = [
          ["Modelo puro", q.model_only],
          ["Mercado sin margen", q.market],
          ["Publicada sembrada", q.published_seed],
        ];
        return (
          <div key={league} style={{ marginTop: 10 }}>
            <div className="row-between">
              <b>{league === "laliga" ? "LaLiga" : league === "segunda" ? "LaLiga Hypermotion" : league}</b>
              <span className="pill">{seed.evaluation_season}/{String(seed.evaluation_season + 1).slice(-2)} · histórico</span>
            </div>
            <div className="chips" style={{ margin: "6px 0" }}>
              <span className="chip">Muestra <b>{cal.n ?? "—"}</b></span>
              <span className="chip">Peso modelo <b>{cal.production ? Math.round(cal.production.model_weight * 100) + "%" : "—"}</b></span>
              <span className="chip">Gate <b className={cal.accepted ? "value-yes" : "value-no"}>{cal.accepted ? "aceptado" : "bloqueado"}</b></span>
            </div>
            <div className="tbl-wrap">
              <table className="tbl-mk"><thead><tr><th className="tl">Capa</th><th>N</th><th>LogLoss</th><th>Brier</th><th>RPS</th><th>Acierto</th></tr></thead>
                <tbody>{rows.map(([label, row]) => row && <tr key={label}><td className="tl">{label}</td><td>{row.n}</td><td>{metric(row.log_loss)}</td><td>{metric(row.brier)}</td><td>{metric(row.rps)}</td><td>{row.accuracy}%</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        );
      })}
      <p className="note source-note">Fuente: Dixon-Coles walk-forward + cierres históricos football-data.co.uk. Coste API: 0. La temporada actual sigue mostrándose en el panel de probabilidad publicada.</p>
    </div>
  );
}
