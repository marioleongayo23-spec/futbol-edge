import { actionableValueRows, excludedQuoteCounts, marketLabel, selectionLabel } from "./extendedValue";

function observedTime(iso) {
  const date = new Date(iso);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).format(date) : "Sin fecha";
}

export default function GlobalValuePanel({ rows }) {
  const now = Date.now();
  const ranked = actionableValueRows(rows, 0.02, now).slice(0, 20);
  const excluded = excludedQuoteCounts(rows, now);
  const excludedText = [
    excluded.unverified ? `${excluded.unverified} sin hora de origen` : null,
    excluded.stale ? `${excluded.stale} desactualizadas` : null,
  ].filter(Boolean).join(" · ");

  return (
    <section className="card" data-testid="global-value-panel" aria-label="Oportunidades con cuotas verificadas">
      <div className="row-between">
        <div className="lbl">Ranking value · cuotas verificadas</div>
        <span className="pill">{ranked.length} señales</span>
      </div>
      <p className="note" style={{ marginBottom: 12 }}>
        Solo cuotas con actualización del proveedor comprobable, de menos de tres horas y previas al saque inicial.
        Las ventajas son teóricas, no un beneficio garantizado.
      </p>
      {excludedText && (
        <p className="note" role="note" data-testid="unverified-value-count" style={{ marginBottom: 12 }}>
          No se promocionan: {excludedText}. Se mantienen en el histórico para auditoría, no como recomendaciones actuales.
        </p>
      )}
      {!ranked.length ? (
        <div className="state">Sin oportunidades con cuota vigente y origen verificable. No se sustituyen por precios sin fecha.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl-mk">
            <thead><tr>
              <th className="tl">Partido</th>
              <th className="tl">Mercado</th>
              <th className="tl">Selección</th>
              <th>Cuota</th>
              <th>Prob.</th>
              <th>EV</th>
              <th className="tl">Origen</th>
              <th className="tl">Verificada</th>
            </tr></thead>
            <tbody>
              {ranked.map((row, index) => (
                <tr key={`${row.match_id}-${row.market}-${row.selection}-${row.line}-${row.player}-${index}`}>
                  <td className="tl"><b>{row.home}–{row.away}</b></td>
                  <td className="tl">{marketLabel(row.market)}</td>
                  <td className="tl">{selectionLabel(row)}</td>
                  <td>{row.odds.toFixed(2)}</td>
                  <td>{Number.isFinite(row.modelProb) ? `${Math.round(row.modelProb * 100)}%` : "—"}</td>
                  <td className="value-yes">+{(row.edge * 100).toFixed(1)}%</td>
                  <td className="tl">{row.bookmaker || row.market_source || "Proveedor sin identificar"}</td>
                  <td className="tl">{observedTime(row.source_updated_at)} <span className="dim">Madrid</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="note source-note">
        La disponibilidad de una cotización no confirma que siga siendo ejecutable en la casa de apuestas.
        Comprobar precio y condiciones antes de cualquier decisión.
      </p>
    </section>
  );
}
