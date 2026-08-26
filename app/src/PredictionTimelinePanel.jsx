import { confidence } from "./insights";
import { auditablePrediction, predictionTimelinePoints, strongestRealEdge } from "./predictionTimelineData";
import "./match-timeline.css";

const SERIES = [
  { key: 0, sign: "1", cls: "home" },
  { key: 1, sign: "X", cls: "draw" },
  { key: 2, sign: "2", cls: "away" },
];

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleString("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
}

function fmtOperationalTime(iso) {
  if (!iso) return null;
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return null;
  return time.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function latestAvailabilityStamp(lineup) {
  const stamps = [
    ...(lineup?.disponibilidad_local || []),
    ...(lineup?.disponibilidad_visitante || []),
  ]
    .map((row) => new Date(row?.source_updated_at || "").getTime())
    .filter(Number.isFinite);
  return stamps.length ? new Date(Math.max(...stamps)).toISOString() : null;
}

function OperationalFreshness({ m }) {
  const lineup = m?.alineacion || {};
  const absenceStamp = latestAvailabilityStamp(lineup);
  const hasAvailability = Object.prototype.hasOwnProperty.call(lineup, "disponibilidad_local")
    || Object.prototype.hasOwnProperty.call(lineup, "disponibilidad_visitante");
  const weatherStamp = m?.weather?.source_updated_at;
  const weatherFor = m?.weather?.forecast_for;
  const lineupStamp = lineup.source_updated_at || lineup.generated_at || lineup.ts;
  const rows = [
    {
      label: "Partido",
      ok: Boolean(m?.updatedAt),
      text: m?.updatedAt ? fmtOperationalTime(m.updatedAt) : "sin refresco intradía",
    },
    {
      label: "Clima",
      ok: Boolean(m?.weather),
      text: weatherStamp
        ? `act. ${fmtOperationalTime(weatherStamp)}`
        : weatherFor ? `previsión ${fmtOperationalTime(weatherFor)}` : "sin dato",
    },
    {
      label: "Bajas",
      ok: hasAvailability,
      text: absenceStamp
        ? `act. ${fmtOperationalTime(absenceStamp)}`
        : hasAvailability ? "sin bajas reportadas" : "sin comprobación",
    },
    {
      label: "XI",
      ok: lineup.status === "confirmado" || lineup.status === "probable",
      text: lineupStamp
        ? `${lineup.status || "sin confirmar"} · ${fmtOperationalTime(lineupStamp)}`
        : lineup.status || "sin confirmar",
    },
  ];
  return (
    <div className="chips" style={{ marginTop: 10 }} aria-label="Estado operativo de datos del partido">
      {rows.map((row) => (
        <span className="chip" key={row.label}>
          <b>{row.label}</b> {row.ok ? "✓" : "◷"} {row.text}
        </span>
      ))}
    </div>
  );
}

function ProbabilityTimeline({ points, home, away }) {
  if (!points.length) return null;
  const width = 720;
  const height = 230;
  const left = 46;
  const right = 22;
  const top = 22;
  const bottom = 48;
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const x = (index) => points.length === 1 ? left + innerW / 2 : left + (index / (points.length - 1)) * innerW;
  const y = (value) => top + (1 - Number(value) / 100) * innerH;
  const path = (series) => points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.probs[series]).toFixed(1)}`).join(" ");
  const label = (series) => series === 0 ? `1 · ${home}` : series === 1 ? "X · Empate" : `2 · ${away}`;

  return (
    <div className="prediction-chart-wrap">
      <svg className="prediction-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Evolución real de probabilidades 1 X 2">
        {[20, 40, 60, 80].map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="pt-grid" />
            <text x={left - 8} y={y(tick) + 4} textAnchor="end" className="pt-axis">{tick}%</text>
          </g>
        ))}
        {points.map((point, index) => (
          <line key={point.generatedAt} x1={x(index)} x2={x(index)} y1={top} y2={height - bottom} className="pt-vgrid" />
        ))}
        {SERIES.map((series) => (
          <g key={series.sign} className={`pt-series ${series.cls}`}>
            {points.length > 1 && <path d={path(series.key)} className="pt-line" />}
            {points.map((point, index) => (
              <g key={`${series.sign}-${point.generatedAt}`}>
                <circle cx={x(index)} cy={y(point.probs[series.key])} r="5" className="pt-dot">
                  <title>{`${label(series.key)} · ${point.probs[series.key].toFixed(1)}% · ${point.label} · ${fmtTime(point.generatedAt)}`}</title>
                </circle>
                {index === points.length - 1 && <text x={x(index) + 9} y={y(point.probs[series.key]) + 4} className="pt-last">{point.probs[series.key].toFixed(0)}%</text>}
              </g>
            ))}
          </g>
        ))}
        {points.map((point, index) => (
          <g key={`label-${point.generatedAt}`}>
            <text x={x(index)} y={height - 25} textAnchor="middle" className="pt-window">{point.label}</text>
            <text x={x(index)} y={height - 10} textAnchor="middle" className="pt-lead">{point.lead || ""}</text>
          </g>
        ))}
      </svg>
      <div className="pt-legend" aria-hidden="true">
        <span className="home"><i />1 · {home}</span><span className="draw"><i />X</span><span className="away"><i />2 · {away}</span>
      </div>
    </div>
  );
}

function HeroKpis({ m, audit, points }) {
  const conf = confidence(m);
  const edge = strongestRealEdge(m);
  const last = points.at(-1);
  const probs = audit.published || m.probs;
  const maxP = Array.isArray(probs) ? Math.max(...probs.map(Number)) : null;
  return (
    <div className="match-intel-kpis">
      <div><small>Prob. máxima</small><b>{maxP != null ? `${maxP.toFixed(0)}%` : "—"}</b><span>{audit.favoriteSign ? `signo ${audit.favoriteSign}` : "sin predicción"}</span></div>
      <div><small>xG</small><b>{Array.isArray(m.xg) ? `${Number(m.xg[0]).toFixed(2)}–${Number(m.xg[1]).toFixed(2)}` : "—"}</b><span>{m.markets?.marcador ? `marcador ${m.markets.marcador}` : "modelo de goles"}</span></div>
      <div><small>Confianza</small><b>{conf?.score != null ? `${conf.score}/100` : "—"}</b><span>{conf?.label || "sin muestra"}</span></div>
      <div><small>Mejor edge 1X2</small><b>{edge ? `${Number(edge.edge) >= 0 ? "+" : ""}${(Number(edge.edge) * 100).toFixed(1)}%` : "—"}</b><span>{edge ? `${edge.selection} @ ${Number(edge.odds).toFixed(2)}` : "sin cuota/value real"}</span></div>
      <div><small>Última captura</small><b>{last ? last.label : "—"}</b><span>{last ? fmtTime(last.generatedAt) : "sin snapshot"}</span></div>
    </div>
  );
}

function minutesToKickoff(m) {
  const kickoff = new Date(m?.kickoff || "").getTime();
  if (!Number.isFinite(kickoff)) return null;
  return Math.round((kickoff - Date.now()) / 60000);
}

function missingVersionState(kind, m) {
  const minutes = minutesToKickoff(m);
  const lineup = m?.alineacion || {};
  if (kind === "initial") {
    return minutes != null && minutes <= 0
      ? { label: "sin captura inicial", status: "no quedó snapshot INICIAL antes del saque" }
      : { label: "primera captura", status: "esperando primera captura válida" };
  }
  if (kind === "prefinal") {
    if (lineup.prefinal_attempt_at && minutes != null && minutes > 0) {
      return { label: "T−3h procesada", status: "sin once probable suficientemente fiable" };
    }
    if (minutes == null) return { label: "objetivo T−3h", status: "sin hora de referencia" };
    if (minutes > 200) return { label: "objetivo T−3h", status: "programada para la ventana T−3h" };
    if (minutes > 150) return { label: "ventana T−3h", status: "actualizando fuentes y once probable" };
    if (minutes > 0) return { label: "sin PRE-FINAL", status: "ventana T−3h superada sin fuente fiable" };
    return { label: "sin PRE-FINAL", status: "no hubo PRE-FINAL fiable antes del saque" };
  }
  if (lineup.status === "confirmado") {
    return minutes != null && minutes > 0
      ? { label: "XI confirmado", status: "archivando la versión FINAL prepartido" }
      : { label: "sin FINAL prepartido", status: "el XI oficial no quedó capturado antes del saque" };
  }
  if (minutes == null) return { label: "XI oficial T−60 / T−30", status: "sin hora de referencia" };
  if (minutes > 75) return { label: "XI oficial T−60 / T−30", status: "esperando ventana de publicación oficial" };
  if (minutes > 0) return { label: "esperando XI oficial", status: "API preparada para T−60 / T−30" };
  return { label: "sin FINAL prepartido", status: "no se capturó XI oficial antes del saque" };
}

function VersionStrip({ points, m }) {
  const initial = points.find((point) => point.window === "initial");
  const prefinal = points.find((point) => point.window === "pre_final_T-3h");
  const final = points.find((point) => point.window === "final_T-60_official" || point.window === "final_T-30_official");
  const cell = (kind, title, point) => {
    const missing = point ? null : missingVersionState(kind, m);
    return (
      <div className={`betting-version ${kind} ${point ? "ready" : "pending"}`}>
        <small>{title}</small>
        <b>{point ? point.label : missing.label}</b>
        <span>{point ? `${point.probs[0].toFixed(0)} / ${point.probs[1].toFixed(0)} / ${point.probs[2].toFixed(0)} · ${point.lead || ""}` : missing.status}</span>
        {point?.sourceQuality === "media_grounded" && <em>medios + modelo</em>}
        {point?.officialPollWindow && <em>API-Football · {point.officialPollWindow}</em>}
      </div>
    );
  };
  return (
    <div className="betting-version-strip" aria-label="Versiones de predicción para apostar">
      {cell("initial", "INICIAL", initial)}
      {cell("prefinal", "PRE-FINAL", prefinal)}
      {cell("final", "FINAL", final)}
    </div>
  );
}

function PublishedBridge({ audit }) {
  if (!audit.rawModel || !audit.published || audit.favoriteIndex == null) return null;
  const i = audit.favoriteIndex;
  const raw = audit.rawModel[i];
  const final = audit.published[i];
  const delta = final - raw;
  return (
    <div className="prediction-bridge" aria-label="Puente de probabilidad publicada">
      <div className="bridge-node"><small>Motor puro · {audit.favoriteSign}</small><b>{raw.toFixed(1)}%</b></div>
      <div className={`bridge-delta ${delta > 0 ? "up" : delta < 0 ? "down" : "flat"}`}><span>mercado + calibración</span><b>{delta > 0 ? "+" : ""}{delta.toFixed(1)} pp</b></div>
      <div className="bridge-arrow">→</div>
      <div className="bridge-node published"><small>Publicada</small><b>{final.toFixed(1)}%</b></div>
    </div>
  );
}

function DriverRows({ audit }) {
  if (!audit.rows.length) return null;
  return (
    <div className="audit-drivers">
      {audit.rows.map((row) => (
        <div className={`audit-driver ${row.kind}`} key={row.key}>
          <div><b>{row.label}</b><small>{row.detail}</small></div>
          <span>{row.display}</span>
        </div>
      ))}
    </div>
  );
}

export default function PredictionTimelinePanel({ m }) {
  const points = predictionTimelinePoints(m);
  if (!Array.isArray(m?.probs) && !points.length) return null;
  const audit = auditablePrediction(m);
  return (
    <section className="card prediction-intelligence" data-testid="prediction-timeline-panel" aria-label="Inteligencia de predicción">
      <div className="row-between prediction-intel-head">
        <div>
          <div className="lbl">Prediction Intelligence</div>
          <div className="mut">Inicial → PRE-FINAL T−3h → FINAL con XI oficial T−60/T−30 · solo información realmente disponible antes del partido</div>
        </div>
        <span className="pill">NO LEAKAGE</span>
      </div>

      <OperationalFreshness m={m} />
      <HeroKpis m={m} audit={audit} points={points} />
      <VersionStrip points={points} m={m} />

      {points.length > 0 ? (
        <>
          <div className="prediction-section-title"><span>Evolución 1X2</span><small>{points.length} capturas reales</small></div>
          <ProbabilityTimeline points={points} home={m.home} away={m.away} />
          {audit.previousDelta != null && (
            <div className="timeline-change">Última revisión: <b>{audit.previousLabel}</b> → <b>{audit.latestLabel}</b> · favorito {audit.favoriteSign} <strong>{audit.previousDelta > 0 ? "+" : ""}{audit.previousDelta.toFixed(1)} pp</strong></div>
          )}
        </>
      ) : <div className="timeline-empty">Aún no hay historial de snapshots. El gráfico aparecerá con la primera captura prepartido.</div>}

      <div className="prediction-section-title"><span>De dónde sale la probabilidad publicada</span><small>sin atribuciones ficticias</small></div>
      <PublishedBridge audit={audit} />
      <DriverRows audit={audit} />
      <p className="note source-note prediction-audit-note">Mercado/calibración muestra un delta real entre el motor y la probabilidad publicada. Once, bajas y clima figuran como 0 pp en 1X2 mientras no superen su validación histórica; pueden afectar confianza, xG u otros mercados sin presentarse como causa del 1X2.</p>
    </section>
  );
}
