import { evidenceRows, validProbabilities } from "./predictionEvidence";

export default function PredictionEvidence({ m }) {
  const rows = evidenceRows(m);
  const ready = rows.filter(r => r.state === "Disponible").length;
  const probs = validProbabilities(m.probs) ? m.probs : null;
  const best = probs ? probs.indexOf(Math.max(...probs)) : -1;
  const tied = probs && probs.filter(p => p === Math.max(...probs)).length > 1;
  return <section className="evidence-panel" aria-label="Lectura de la predicción">
    <div className="evidence-summary">
      <div><span className="eyebrow">Lectura del partido</span><h2>{best < 0 ? "Predicción pendiente" : tied ? "Sin un favorito único" : best === 1 ? "El empate es el escenario más probable" : `Ventaja para ${best === 0 ? m.home : m.away}`}</h2>
        <p>{probs ? tied ? "Dos o más resultados comparten la probabilidad máxima mostrada." : `El resultado favorito tiene un ${Math.max(...probs)}% de probabilidad. Los otros resultados suman un ${100 - Math.max(...probs)}%.` : "Faltan probabilidades válidas para interpretar este encuentro."}</p>
      </div>
      <div className="evidence-count"><b>{ready}<small> / 6</small></b><span>fuentes disponibles</span></div>
    </div>
    <div className="evidence-footnotes">
      <span><b>1X2</b> {m.calibrated ? "Modelo combinado con cuotas de mercado" : "Probabilidad del modelo"}</span>
      <span><b>Solidez</b> Indicador de evidencia; no es una tasa de acierto</span>
    </div>
    <details className="evidence-details">
      <summary>Ver fuentes, revisión e influencia en el análisis</summary>
      <div className="evidence-grid">{rows.map(r => <article key={r.key}>
        <div className="evidence-source-title"><h3>{r.label}</h3><span className={`evidence-state ${r.state === "Disponible" ? "available" : ""}`}>{r.state}</span></div>
        <b>{r.source}</b><p>{r.detail}</p><p>{r.effect}</p>
        <small>{r.checkedAt ? `Revisión: ${new Date(r.checkedAt).toLocaleString("es-ES", { timeZone: "Europe/Madrid" })} · Madrid` : "Sin fecha de revisión acreditada"}</small>
      </article>)}</div>
    </details>
  </section>;
}
