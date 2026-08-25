import "./quality.css";

const SOURCE_ROWS = [
  ["published", "Probabilidad publicada"],
  ["model_only", "Modelo puro"],
  ["market", "Mercado sin margen"],
];

function sampleMeta(n) {
  if (!n) return { label: "sin muestra", className: "value-no" };
  if (n < 10) return { label: "muestra insuficiente", className: "value-no" };
  if (n < 30) return { label: "muestra preliminar", className: "" };
  return { label: "muestra en seguimiento", className: "value-yes" };
}

function fmtMetric(value) {
  return value == null ? "—" : Number(value).toFixed(4);
}

function Delta({ value }) {
  if (value == null) return <span>—</span>;
  const number = Number(value);
  const className = number < 0 ? "value-yes" : number > 0 ? "value-no" : "dim";
  return <span className={className}>{number > 0 ? "+" : ""}{number.toFixed(4)}</span>;
}

function QualityVisual({ rows }) {
  const metrics = [
    ["log_loss", "LogLoss"],
    ["brier", "Brier"],
    ["rps", "RPS"],
  ];
  return (
    <div className="quality-visual" aria-label="Comparativa visual de calidad probabilística">
      {metrics.map(([key, label]) => {
        const available = rows.filter((row) => row.data?.[key] != null);
        const max = Math.max(...available.map((row) => Number(row.data[key])), 0.0001);
        const best = Math.min(...available.map((row) => Number(row.data[key])), Infinity);
        return (
          <div className="quality-metric" key={key}>
            <div className="quality-metric-head"><b>{label}</b><span>menor = mejor</span></div>
            {available.map(({ key: sourceKey, label: sourceLabel, data }) => {
              const value = Number(data[key]);
              const width = Math.max(7, Math.min(100, (value / max) * 100));
              const isBest = Math.abs(value - best) < 1e-9;
              return (
                <div className={`quality-bar-row ${isBest ? "best" : ""}`} key={sourceKey}>
                  <span>{sourceLabel}</span>
                  <div className="quality-track"><i style={{ width: `${width}%` }} /></div>
                  <b>{value.toFixed(4)}</b>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function Comparison({ title, comparison }) {
  if (!comparison) return null;
  const sample = sampleMeta(comparison.n);
  return (
    <div className="card" style={{ margin: 0, flex: "1 1 300px" }}>
      <div className="row-between">
        <div className="lbl">{title}</div>
        <span className={"pill " + sample.className}>{sample.label} · n={comparison.n}</span>
      </div>
      <div className="mut" style={{ marginBottom: 8 }}>Delta publicada − referencia. Negativo = mejora de la probabilidad publicada.</div>
      <div className="chips">
        <span className="chip">LogLoss <b><Delta value={comparison.log_loss_delta} /></b></span>
        <span className="chip">Brier <b><Delta value={comparison.brier_delta} /></b></span>
        <span className="chip">RPS <b><Delta value={comparison.rps_delta} /></b></span>
      </div>
      <div className={"note " + (comparison.improved_both ? "value-yes" : "value-no")} style={{ marginTop: 8 }}>
        {comparison.improved_both
          ? "La publicada mejora simultáneamente LogLoss y RPS en esta muestra pareada."
          : "La publicada todavía no mejora simultáneamente LogLoss y RPS frente a esta referencia."}
      </div>
    </div>
  );
}

export default function ProbabilityQualityPanel({ quality }) {
  if (!quality) return null;
  const rows = SOURCE_ROWS
    .map(([key, label]) => ({ key, label, data: quality[key] }))
    .filter((row) => row.data);
  if (!rows.length) return null;

  const pairedN = Math.max(
    quality.published_vs_model?.n || 0,
    quality.published_vs_market?.n || 0,
  );
  const overallSample = sampleMeta(pairedN || quality.published?.n || 0);

  return (
    <div className="card" data-testid="probability-quality-panel">
      <div className="row-between">
        <div>
          <div className="lbl">Calidad de probabilidad publicada</div>
          <div className="mut">Modelo puro vs probabilidad realmente publicada vs mercado, medidos solo con snapshots prepartido.</div>
        </div>
        <span className={"pill " + overallSample.className}>{overallSample.label}</span>
      </div>

      <QualityVisual rows={rows} />

      <div className="tbl-wrap" style={{ marginTop: 10 }}>
        <table className="tbl-mk">
          <thead><tr><th className="tl">Fuente</th><th>N</th><th>LogLoss</th><th>Brier</th><th>RPS</th><th>Acierto</th></tr></thead>
          <tbody>
            {rows.map(({ key, label, data }) => {
              const sample = sampleMeta(data.n);
              return (
                <tr key={key}>
                  <td className="tl"><b>{label}</b><div className={"mk-sub " + sample.className}>{sample.label}</div></td>
                  <td>{data.n}</td>
                  <td>{fmtMetric(data.log_loss)}</td>
                  <td>{fmtMetric(data.brier)}</td>
                  <td>{fmtMetric(data.rps)}</td>
                  <td>{data.accuracy == null ? "—" : `${Number(data.accuracy).toFixed(1)}%`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="row" style={{ gap: 10, alignItems: "stretch", flexWrap: "wrap", marginTop: 10 }}>
        <Comparison title="Publicada vs modelo puro" comparison={quality.published_vs_model} />
        <Comparison title="Publicada vs mercado" comparison={quality.published_vs_market} />
      </div>

      <div className="mut" style={{ marginTop: 10 }}>
        Las comparaciones se calculan sobre exactamente los mismos partidos. Con menos de 30 observaciones deben leerse como señal preliminar, no como evidencia concluyente. Menor LogLoss, Brier y RPS es mejor.
      </div>
    </div>
  );
}
