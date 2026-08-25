function pct(multiplier) {
  const value = (Number(multiplier) - 1) * 100;
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function impactClass(multiplier) {
  const value = Number(multiplier);
  if (value > 1.001) return "positive";
  if (value < 0.999) return "negative";
  return "neutral";
}

function ImpactTile({ label, value }) {
  return (
    <div className={`fe-impact-tile ${impactClass(value)}`}>
      <span>{label}</span>
      <b>{pct(value)}</b>
    </div>
  );
}

export default function WeatherAdjustmentPanel({ adjustment }) {
  if (!adjustment) return null;
  if (!adjustment.applied) {
    return (
      <div className="card" data-testid="weather-adjustment-panel">
        <div className="row-between">
          <div className="lbl">Ajuste cuantificado por clima</div>
          <span className="pill">NEUTRO</span>
        </div>
        <div className="note">Sin ajuste: {adjustment.reason || "condiciones dentro de umbrales neutros"}.</div>
      </div>
    );
  }
  const mult = adjustment.multipliers || {};
  const xg = adjustment.xg || {};
  return (
    <div className="card" data-testid="weather-adjustment-panel">
      <div className="row-between">
        <div>
          <div className="lbl">Ajuste cuantificado por clima</div>
          <div className="mut">Impacto esperado respecto a condiciones neutrales</div>
        </div>
        <span className="pill">PREPARTIDO</span>
      </div>

      <div className="fe-impact-grid">
        <ImpactTile label="Goles/xG" value={mult.goals} />
        <ImpactTile label="Remates" value={mult.shots} />
        <ImpactTile label="Faltas" value={mult.fouls} />
        <ImpactTile label="Tarjetas" value={mult.cards} />
      </div>

      {xg.before && xg.after && (
        <div className="fe-xg-shift">
          <div className="fe-xg-shift-line">
            <div className="fe-xg-side">
              <small>xG neutral</small>
              <b>{xg.before[0]}–{xg.before[1]}</b>
            </div>
            <div className="fe-xg-arrow">→</div>
            <div className="fe-xg-side">
              <small>xG con clima</small>
              <b>{xg.after[0]}–{xg.after[1]}</b>
            </div>
          </div>
          <div className="mut" style={{ marginTop: 7 }}>xG: {xg.before[0]}–{xg.before[1]} → {xg.after[0]}–{xg.after[1]}</div>
          {xg.delta && <div className="mut" style={{ marginTop: 4 }}>Δ xG local {xg.delta[0] > 0 ? "+" : ""}{xg.delta[0]} · visitante {xg.delta[1] > 0 ? "+" : ""}{xg.delta[1]}</div>}
        </div>
      )}

      <div className="mut" style={{ marginTop: 10 }}>{(adjustment.reasons || []).join(" · ")}</div>
      <p className="note source-note">Ajuste conservador sobre xG, remates, faltas/tarjetas y mercados de goles. El 1X2 calibrado no se altera hasta superar validación histórica.</p>
    </div>
  );
}
