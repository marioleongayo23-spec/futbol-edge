import { qualityView, qualitySummary } from "./matchQuality";
import "./match-quality.css";

// Badge compacto de calidad de datos. `compact` muestra solo el score (para las
// filas y tablas densas); si no, incluye la etiqueta del tier. Es informativo
// (un <span>), nunca un botón, para no capturar el clic de la fila que lo aloja.
export function QualityBadge({ mq, compact = false }) {
  const view = qualityView(mq);
  if (!view) return null;
  const summary = qualitySummary(view);
  return (
    <span className={`mq-badge ${view.cls}`} title={summary} aria-label={summary}>
      <span className="mq-dot" aria-hidden="true" />
      {compact
        ? (view.score != null ? view.score : view.label)
        : `Datos ${view.score != null ? `${view.score} · ` : ""}${view.label}`}
    </span>
  );
}

// Panel de desglose para el detalle del partido: score, fuentes requeridas que
// aún faltan y cobertura por fuente. Deja explícito que mide la cobertura de
// datos, no la confianza del pronóstico (que el partido muestra por separado).
export function MatchQualityCard({ mq }) {
  const view = qualityView(mq);
  if (!view) return null;
  return (
    <div className="card mq-card">
      <div className="mq-head">
        <div className="lbl" style={{ margin: 0 }}>🧪 Calidad de datos</div>
        <QualityBadge mq={mq} />
      </div>
      {view.score != null && (
        <div className="mq-score">
          <b>{view.score}</b>
          <span>/100 · cobertura de las fuentes, no la confianza del pronóstico</span>
        </div>
      )}
      {view.missing.length > 0 && (
        <div className="mq-missing">Aún falta: {view.missing.join(", ")}</div>
      )}
      {view.components.length > 0 && (
        <div className="mq-grid">
          {view.components.map((c) => (
            <div className={`mq-row ${c.pct >= 100 ? "full" : c.pct <= 0 ? "none" : ""}`} key={c.key}>
              <span>{c.label}</span>
              <span className="mq-track"><i style={{ width: `${c.pct}%` }} /></span>
              <b>{c.pct}%</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
