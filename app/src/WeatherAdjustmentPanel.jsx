function pct(multiplier) {
  const value = (Number(multiplier) - 1) * 100;
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export default function WeatherAdjustmentPanel({ adjustment }) {
  if (!adjustment) return null;
  if (!adjustment.applied) {
    return (
      <div className="card" data-testid="weather-adjustment-panel">
        <div className="lbl">Ajuste cuantificado por clima</div>
        <div className="note">Sin ajuste: {adjustment.reason || "condiciones dentro de umbrales neutros"}.</div>
      </div>
    );
  }
  const mult = adjustment.multipliers || {};
  const xg = adjustment.xg || {};
  return (
    <div className="card" data-testid="weather-adjustment-panel">
      <div className="lbl">Ajuste cuantificado por clima</div>
      <div className="chips">
        <span className="chip"><span>Goles/xG</span> <b>{pct(mult.goals)}</b></span>
        <span className="chip"><span>Remates</span> <b>{pct(mult.shots)}</b></span>
        <span className="chip"><span>Faltas</span> <b>{pct(mult.fouls)}</b></span>
        <span className="chip"><span>Tarjetas</span> <b>{pct(mult.cards)}</b></span>
      </div>
      {xg.before && xg.after && (
        <div className="note" style={{ marginTop: 8 }}>
          xG: <b>{xg.before[0]}–{xg.before[1]}</b> → <b>{xg.after[0]}–{xg.after[1]}</b>
          {xg.delta ? ` · Δ ${xg.delta[0] > 0 ? "+" : ""}${xg.delta[0]} / ${xg.delta[1] > 0 ? "+" : ""}${xg.delta[1]}` : ""}
        </div>
      )}
      <div className="mut" style={{ marginTop: 6 }}>{(adjustment.reasons || []).join(" · ")}</div>
      <p className="note source-note">Ajuste conservador sobre xG, remates, faltas/tarjetas y mercados de goles. El 1X2 calibrado no se altera hasta superar validación histórica.</p>
    </div>
  );
}
