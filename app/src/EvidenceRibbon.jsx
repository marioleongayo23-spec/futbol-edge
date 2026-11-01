import { dayEvidence, feedFreshness } from "./evidenceStatus.js";
import "./evidence-ribbon.css";

function madridTimestamp(value) {
  if (!value) return "Fecha desconocida";
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

export default function EvidenceRibbon({ feed, matches }) {
  const state = feedFreshness(feed?.generated_at, Boolean(feed?._fromFallback));
  const day = dayEvidence(matches);
  const coverage = day.total ? Math.round(100 * day.predicted / day.total) : 0;
  return (
    <section className="evidence-ribbon" aria-label="Estado de los datos y predicciones">
      <div className="evidence-intro">
        <div className="evidence-eyebrow">OBSERVATORIO DE DATOS</div>
        <h2>La evidencia, a la vista</h2>
        <p>Disponibilidad de información para la fecha seleccionada. Una probabilidad no garantiza un resultado.</p>
      </div>
      <div className="evidence-facts">
        <div className="evidence-fact">
          <span className="evidence-fact-label">Estado del feed</span>
          <strong className={`evidence-status evidence-${state.tone}`}>
            <i aria-hidden="true" />{state.label}
          </strong>
          <small>{state.stamp ? madridTimestamp(state.stamp) + " · Madrid" : "No se puede verificar la fecha"}</small>
        </div>
        <div className="evidence-fact">
          <span className="evidence-fact-label">Predicciones del día</span>
          <strong>{day.predicted} <span className="evidence-denom">/ {day.total}</span></strong>
          <div className="evidence-meter" role="progressbar" aria-label="Partidos con predicción válida" aria-valuemin={0} aria-valuemax={100} aria-valuenow={coverage}><span style={{ width: `${coverage}%` }} /></div>
          <small>{day.total ? `${coverage}% con distribución 1X2 válida` : "No hay partidos seleccionados"}</small>
        </div>
        <div className="evidence-fact">
          <span className="evidence-fact-label">Cuotas con sello reciente</span>
          <strong>{day.verifiedPriced} <span className="evidence-denom">/ {day.priced}</span></strong>
          <small>{day.priced - day.verifiedPriced} con fecha sin verificar o ya antiguas. El precio puede cambiar antes de apostar.</small>
        </div>
      </div>
    </section>
  );
}
