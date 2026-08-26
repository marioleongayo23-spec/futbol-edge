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

function fmtWeatherTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function WeatherForecastSummary({ adjustment }) {
  const source = adjustment.weather_source || "Open-Meteo";
  const forecast = fmtWeatherTime(adjustment.weather_forecast_for);
  const refreshed = fmtWeatherTime(adjustment.weather_source_updated_at);
  const temp = adjustment.weather_temperature_c;
  const apparent = adjustment.weather_apparent_temperature_c;
  const rainProb = adjustment.weather_precipitation_probability_pct;
  const rainMm = adjustment.weather_precipitation_mm;
  const wind = adjustment.weather_wind_kmh;
  const humidity = adjustment.weather_humidity_pct;
  const hasSnapshot = [temp, apparent, rainProb, rainMm, wind, humidity].some((value) => value != null);

  return (
    <div style={{ marginTop: 10, marginBottom: 10 }} data-testid="kickoff-weather-forecast">
      <div className="row-between">
        <div>
          <div className="lbl">Previsión para la hora del partido</div>
          <div className="mut">No es el tiempo actual: es la previsión usada para el saque inicial.</div>
        </div>
        {forecast && <span className="pill y">{forecast}</span>}
      </div>
      {hasSnapshot && (
        <div className="chips" style={{ marginTop: 8 }}>
          {temp != null && <span className="chip">🌡 <b>{temp} °C</b>{apparent != null ? ` · sensación ${apparent} °C` : ""}</span>}
          {(rainProb != null || rainMm != null) && <span className="chip">🌧 <b>{rainProb ?? "—"}%</b>{rainMm != null ? ` · ${rainMm} mm` : ""}</span>}
          {wind != null && <span className="chip">💨 <b>{wind} km/h</b></span>}
          {humidity != null && <span className="chip">Humedad <b>{humidity}%</b></span>}
        </div>
      )}
      <div className="mut" style={{ marginTop: 6 }}>
        {source}{refreshed ? ` · última consulta ${refreshed}` : ""} · zona Europe/Madrid
      </div>
    </div>
  );
}

function WeatherSource({ adjustment }) {
  const source = adjustment.weather_source || "Open-Meteo";
  const forecast = fmtWeatherTime(adjustment.weather_forecast_for);
  const refreshed = fmtWeatherTime(adjustment.weather_source_updated_at);
  const sameStamp = adjustment.weather_forecast_for && adjustment.weather_source_updated_at
    && adjustment.weather_forecast_for === adjustment.weather_source_updated_at;
  return (
    <p className="note source-note">
      {source}{forecast ? ` · previsión para ${forecast}` : ""}{refreshed && !sameStamp ? ` · refrescada ${refreshed}` : ""}.
      {" "}La hora corresponde a la zona Europe/Madrid utilizada para el saque inicial.
    </p>
  );
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
        <WeatherForecastSummary adjustment={adjustment} />
        <div className="note">Sin ajuste: {adjustment.reason || "condiciones dentro de umbrales neutros"}.</div>
        <WeatherSource adjustment={adjustment} />
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

      <WeatherForecastSummary adjustment={adjustment} />

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
      <WeatherSource adjustment={adjustment} />
      <p className="note source-note">Ajuste conservador sobre xG, remates, faltas/tarjetas y mercados de goles. El 1X2 calibrado no se altera hasta superar validación histórica.</p>
    </div>
  );
}
