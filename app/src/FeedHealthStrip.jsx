/** Compact and accessible feed alerts. Never suppress severe source warnings. */
export function feedHealthState(data, stale, ageHours) {
  const alerts = Array.isArray(data?.alerts) ? data.alerts : [];
  const critical = [...new Set(alerts.filter(a => a?.severity === "critical" && a?.message).map(a => a.message))];
  const warnings = [...new Set(alerts.filter(a => a?.severity === "warning" && a?.message).map(a => a.message))];
  const issues = [
    ...(stale ? [{ title: "Feed por actualizar", detail: `El feed puede estar desactualizado (hace ${Number.isFinite(ageHours) ? Math.round(ageHours) : "?"} h). Se revisa a las 00:15 y 10:15, con control adicional cuando hay onces oficiales.` }] : []),
    ...critical.map(detail => ({ title: "Fuente crítica con incidencias", detail })),
    ...(data?._fromFallback ? [{ title: "Mostrando copia de respaldo", detail: "No se pudo actualizar el feed remoto. Los datos locales pueden estar desactualizados." }] : []),
    ...warnings.map(detail => ({ title: "Fuente con incidencias", detail })),
  ];
  return {
    issues, severity: critical.length || stale ? "warning" : "info",
    criticalCount: critical.length + (stale ? 1 : 0),
  };
}

export default function FeedHealthStrip({ data, stale = false, ageHours = null }) {
  const { issues, severity, criticalCount } = feedHealthState(data, stale, ageHours);
  if (!issues.length) return null;
  const titles = [...new Set(issues.map(item => item.title))];
  return (
    <section className={`feed-health-strip feed-health-${severity}`} aria-label="Avisos sobre el estado de los datos">
      <div className="feed-health-topline">
        <span className="feed-health-indicator" aria-hidden="true" />
        <strong>{criticalCount ? "Atención: datos con incidencias" : "Avisos de actualización"}</strong>
        <span className="feed-health-number">{issues.length} {issues.length === 1 ? "aviso" : "avisos"}</span>
      </div>
      <p>{titles.join(" · ")}. Verifica la vigencia antes de interpretar las cuotas o pronósticos.</p>
      <details className="feed-health-details">
        <summary>Consultar los detalles de las fuentes</summary>
        <ul>
          {issues.map((issue, index) => <li key={index}><b>{issue.title}:</b> {issue.detail}</li>)}
        </ul>
      </details>
    </section>
  );
}
