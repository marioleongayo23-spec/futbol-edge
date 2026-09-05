import "./prediction-build.css";

// Cadena cuantificada de la predicción, leyendo lo que el modelo ya expone:
// model_meta.components (Dixon-Coles y Elo) + ensemble + market_calibration.
// No inventa nada: muestra cómo se combinan los dos motores y cómo el mercado
// recalibra el resultado, con las probabilidades reales de cada etapa.

function round(x) {
  return Math.round(x || 0);
}

function toArr(o) {
  if (!o) return null;
  return [o["1"], o["X"], o["2"]].map((v) => round((v || 0) * 100));
}

function MiniBar({ probs, home, away }) {
  const [p1, px, p2] = probs;
  return (
    <div className="pb-bar">
      <div className="seg s1" style={{ flex: Math.max(p1, 0.6) }} title={`${home}: ${p1}%`}>{p1 >= 14 ? p1 + "%" : ""}</div>
      <div className="seg sx" style={{ flex: Math.max(px, 0.6) }} title={`Empate: ${px}%`}>{px >= 14 ? px + "%" : ""}</div>
      <div className="seg s2" style={{ flex: Math.max(p2, 0.6) }} title={`${away}: ${p2}%`}>{p2 >= 14 ? p2 + "%" : ""}</div>
    </div>
  );
}

export default function PredictionBuild({ m }) {
  const meta = m?.model_meta;
  if (!meta || !meta.components || !Array.isArray(m.probs) || m.probs.length !== 3) return null;

  const ens = meta.ensemble || {};
  const dc = toArr(meta.components.dixon_coles);
  const elo = toArr(meta.components.elo);
  const model = Array.isArray(m.model_probs) ? m.model_probs.map(round) : null;
  const final = m.probs.map(round);
  const mc = m.market_calibration;
  const home = m.home, away = m.away;

  const stages = [];
  if (dc) stages.push({ k: "dc", label: "Dixon-Coles", sub: `ataque · defensa · ventaja de campo${ens.accepted && ens.dc_weight != null ? ` — peso ${round(ens.dc_weight * 100)}%` : ""}`, probs: dc });
  if (elo) stages.push({ k: "elo", label: ens.accepted || meta.residual?.accepted ? "Elo" : "Elo · referencia, sin peso activo", sub: `fuerza relativa acumulada${ens.accepted && ens.elo_weight != null ? ` — peso ${round(ens.elo_weight * 100)}%` : ""}`, probs: elo });
  if (model && (dc || elo)) stages.push({ k: "model", label: meta.residual?.accepted ? "Modelo residual validado" : ens.accepted ? "Modelo combinado" : "Modelo Dixon-Coles", sub: meta.residual?.accepted ? "corrección residual aceptada por validación" : ens.accepted ? "mezcla geométrica y temperatura validadas" : "Elo se muestra como referencia; no interviene en el 1X2", probs: model, strong: true });

  const base = model || final;
  if (mc && base) {
    const shift = final.map((v, i) => v - base[i]);
    stages.push({
      k: "market",
      label: "Calibrado con el mercado",
      sub: `modelo ${round((mc.model_weight || 0) * 100)}% · mercado ${round((mc.market_weight || 0) * 100)}%`,
      probs: final,
      shift: shift.some((d) => Math.abs(d) >= 1) ? shift : null,
    });
  }

  // Marca la última etapa como final (o añade una si nada la representa aún).
  if (stages.length) {
    const last = stages[stages.length - 1];
    if (last.probs.every((v, i) => v === final[i])) last.final = true;
    else stages.push({ k: "final", label: "Predicción final", probs: final, final: true });
  }
  if (stages.length < 2) return null;

  // Ajustes de contexto que sí movieron algo (informativo).
  const adj = [];
  if (m.weather_adjustment?.applied) adj.push("clima aplicado al escenario de simulación");
  const li = m.lineup_impact || {};
  if (li.probability_adjustment) adj.push("once y bajas confirmadas");
  else if (li.confidence_penalty_pp) adj.push(`bajas: −${li.confidence_penalty_pp} pp de confianza`);

  return (
    <div className="card">
      <div className="lbl">Cómo se forma la predicción <span className="dim">· 1X2</span></div>
      <div className="pb-legend">
        <span><i className="pb-dot s1" />{home}</span>
        <span><i className="pb-dot sx" />Empate</span>
        <span><i className="pb-dot s2" />{away}</span>
      </div>
      {stages.map((s, i) => (
        <div className={"pb-stage" + (s.strong ? " strong" : "") + (s.final ? " final" : "")} key={s.k}>
          <div className="pb-head"><b>{s.label}</b>{s.sub && <span className="dim">{s.sub}</span>}</div>
          <MiniBar probs={s.probs} home={home} away={away} />
          {s.shift && (
            <div className="pb-shift">
              {s.shift.map((d, j) => d ? <span key={j} className={d > 0 ? "up" : "down"}>{["1", "X", "2"][j]} {d > 0 ? "+" : ""}{d}pp</span> : null)}
            </div>
          )}
          {i < stages.length - 1 && <div className="pb-arrow">↓</div>}
        </div>
      ))}
      {adj.length > 0 && <p className="note" style={{ marginTop: 6 }}>Contexto adicional: {adj.join(" · ")}.</p>}
      <p className="note dim" style={{ marginTop: 6 }}>Las etapas indican qué modelo está activo. Solo se combinan motores si superan la validación. La mezcla con cuotas se identifica por separado. Clima, once y bajas aportan contexto y solidez; no implican por sí solos un cambio del 1X2.</p>
    </div>
  );
}
