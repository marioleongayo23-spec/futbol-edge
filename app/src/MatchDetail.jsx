import { Fragment, useMemo, useState } from "react";
import { accent, crestFor, fmtKick } from "./feed";
import { ah, btts, kelly, matrix, oneXtwo, over, topScores } from "./poisson";
import { confidence, countdown, isSurprise } from "./insights";
import { marketMovementRows, marketMovementSourceLabel } from "./markets";
import OfficialStatsPanel from "./OfficialStatsPanel";
import WeatherAdjustmentPanel from "./WeatherAdjustmentPanel";
import PlayerFairLines from "./PlayerFairLines";
import { teamSquad } from "./teams";
import PredictionTimelinePanel from "./PredictionTimelinePanel";
import { hasAccess } from "./plans";

function Teams({ m, onTeam }) {
  return (
    <div className="teams">
      <button type="button" className="team team-button" onClick={() => onTeam && onTeam(m.home)} disabled={!onTeam} aria-label={`Ver perfil de ${m.home}`}>
        <img className="crest" src={crestFor(m.home, m.homeColors, m.homeCrest)}
          alt="" onError={(e) => (e.target.src = crestFor(m.home, m.homeColors, null))} />
        <div style={{ minWidth: 0 }}>
          <div className="tn">{m.home}</div>
          <div className="cbar" style={{ background: accent(m.homeColors) }} />
        </div>
      </button>
      <div className="mid">
        {m.finished && m.result
          ? <><div className="score">{m.result[0]}–{m.result[1]}</div><div className="kick">final</div></>
          : m.markets?.marcador
            ? <><div className="pred">{m.markets.marcador}</div><div className="kick">previsto</div></>
            : <div className="kick">{fmtKick(m.kickoff)}</div>}
      </div>
      <button type="button" className="team away team-button" onClick={() => onTeam && onTeam(m.away)} disabled={!onTeam} aria-label={`Ver perfil de ${m.away}`}>
        <img className="crest" src={crestFor(m.away, m.awayColors, m.awayCrest)}
          alt="" onError={(e) => (e.target.src = crestFor(m.away, m.awayColors, null))} />
        <div style={{ minWidth: 0 }}>
          <div className="tn">{m.away}</div>
          <div className="cbar" style={{ background: accent(m.awayColors) }} />
        </div>
      </button>
    </div>
  );
}

function Heat({ M }) {
  // Mini mapa de calor de los marcadores 0..5.
  const max = Math.max(...M.slice(0, 6).map((r) => Math.max(...r.slice(0, 6))));
  return (
    <div className="heat">
      <div className="hh"></div>
      {[0, 1, 2, 3, 4, 5].map((y) => <div key={y} className="hh">{y}</div>)}
      {[0, 1, 2, 3, 4, 5].map((x) => (
        <Fragment key={"r" + x}>
          <div className="hh">{x}</div>
          {[0, 1, 2, 3, 4, 5].map((y) => {
            const v = M[x][y]; const a = Math.min(1, v / max);
            return <div key={x + "-" + y}
              style={{ background: `rgba(34,201,138,${a.toFixed(2)})`, color: a > 0.5 ? "#04110b" : "var(--muted)" }}>
              {(v * 100).toFixed(0)}</div>;
          })}
        </Fragment>
      ))}
    </div>
  );
}

function MarketMovement({ odds }) {
  const rows = marketMovementRows(odds);
  if (!rows.length) return null;
  return (
    <div className="market-movement" aria-label="Movimiento de cuotas 1X2">
      <div className="lbl">Movimiento del mercado 1X2</div>
      <div className="market-movement-grid">
        {rows.map((row) => (
          <div className={`market-move ${row.direction}`} key={row.selection}>
            <b>{row.selection}</b>
            <span>{row.opening.toFixed(2)} → {row.latest.toFixed(2)}</span>
            <small>{row.movementPct > 0 ? "+" : ""}{row.movementPct.toFixed(1)}%</small>
          </div>
        ))}
      </div>
      <p className="note source-note">Apertura → última cuota {marketMovementSourceLabel(odds)} · football-data.co.uk. Una bajada indica mayor apoyo del mercado; una subida, menor apoyo.</p>
    </div>
  );
}

function TacticalProfile({ matchup, home, away }) {
  if (!matchup) return null;
  const dimensions = [
    ["attack_volume", "Volumen ofensivo"],
    ["territorial_pressure", "Presión territorial"],
    ["defensive_exposure", "Exposición defensiva"],
    ["finishing_efficiency", "Eficacia de remate"],
    ["contact_intensity", "Contacto"],
  ];
  const column = (label, side, color) => (
    <div className="style-column">
      <div className="tn">{label}</div>
      {dimensions.map(([key, fallback]) => {
        const row = side?.style_vector?.[key] || {};
        const score = Number.isFinite(row.score) ? row.score : 0;
        return <div className="style-row" key={key}>
          <div><span>{row.label || fallback}</span><b>{row.score ?? "—"}</b></div>
          <div className="style-track" aria-label={`${row.label || fallback}: percentil ${row.score ?? "sin datos"}`}><i style={{ width: `${score}%`, background: color }} /></div>
          <small>{row.observed ?? "—"} {row.unit || ""}</small>
        </div>;
      })}
    </div>
  );
  return <div className="tactical-profile">
    <div className="style-grid">
      {column(home, matchup.home, "var(--green)")}
      {column(away, matchup.away, "var(--blue)")}
    </div>
    {(matchup.style_clashes || []).length > 0 && <div className="clash-list">
      {(matchup.style_clashes || []).map((clash) => <span className="chip" key={clash.edge}>⚔ {clash.label} · <b>{clash.strength}/100</b></span>)}
    </div>}
  </div>;
}

function LineupImpact({ impact, home, away }) {
  if (!impact) return null;
  const side = (label, row) => <div className="impact-side">
    <div className="tn">{label}</div>
    <div className="impact-kpis">
      <span><b>{row.expected_minutes_avg ?? "—"}</b><small>min previstos</small></span>
      <span><b>{row.starter_probability_avg_pct ?? "—"}%</b><small>prob. titular</small></span>
      <span><b>{row.attack_presence_index ?? "—"}</b><small>presencia ataque</small></span>
      <span><b>{row.official_absences ?? 0}</b><small>bajas oficiales</small></span>
    </div>
  </div>;
  return <div className="card">
    <div className="row-between"><div className="lbl">Impacto del once</div><span className="pill">evidencia {impact.evidence}</span></div>
    <div className="impact-grid">{side(home, impact.home || {})}{side(away, impact.away || {})}</div>
    <div className="kv"><span>Penalización de confianza</span><b>{impact.confidence_penalty_pp ?? 0} pp</b></div>
    <p className="note source-note">{impact.method}</p>
  </div>;
}

function StateSimulation({ simulation }) {
  if (!simulation?.probabilities) return null;
  const probs = simulation.probabilities;
  const assumptions = simulation.assumptions || {};
  return <div className="card scenario-card">
    <div className="row-between"><div className="lbl">Simulador de estados</div><span className="pill">escenario, no pick</span></div>
    <div className="scenario-probs">
      {[['1', probs['1']], ['X', probs.X], ['2', probs['2']]].map(([sign, value]) => <span key={sign}><b>{Math.round((value || 0) * 100)}%</b><small>{sign}</small></span>)}
    </div>
    <div className="chips">
      <span className="chip">Goles medios <b>{simulation.expected_total_goals}</b></span>
      <span className="chip">Rango 80% <b>{simulation.total_goals_range_80?.join("–")}</b></span>
      <span className="chip">Over 2.5 <b>{Math.round((simulation.over_2_5 || 0) * 100)}%</b></span>
      <span className="chip">BTTS <b>{Math.round((simulation.btts || 0) * 100)}%</b></span>
    </div>
    <p className="note source-note">{simulation.simulations?.toLocaleString("es-ES")} simulaciones · ritmo climático ×{assumptions.pace_multiplier ?? 1}{assumptions.estimated_goal_delta_vs_neutral ? ` · ${assumptions.estimated_goal_delta_vs_neutral} goles vs clima neutro` : ""}. {assumptions.state_effects}</p>
  </div>;
}

const FALLBACK_POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"];
const POSITION_LINE = {
  POR: 0,
  LI: 1, DFC: 1, LD: 1, CAI: 1, CAD: 1,
  MCD: 2, MC: 2, MI: 2, MD: 2, MP: 2,
  EI: 3, DC: 3, ED: 3,
};
const POSITION_ORDER = {
  POR: 3,
  LI: 1, CAI: 1, DFC: 3, CAD: 5, LD: 5,
  MI: 1, MCD: 3, MC: 3, MP: 3, MD: 5,
  EI: 1, DC: 3, ED: 5,
};

/* Respeta línea y lateralidad real; los feeds antiguos caen a un 4-3-3 seguro. */
function _lines(xi, positions) {
  const players = (xi || []).slice(0, 11).map((name, index) => {
    const supplied = positions?.[index];
    return {
      name,
      position: POSITION_LINE[supplied] != null ? supplied : FALLBACK_POSITIONS[index],
      index,
    };
  });
  if (!players.length) return [];
  const lines = [0, 1, 2, 3].map((line) => players
    .filter((player) => (POSITION_LINE[player.position] ?? Math.min(3, Math.floor(player.index / 3))) === line)
    .sort((a, b) => (POSITION_ORDER[a.position] ?? 3) - (POSITION_ORDER[b.position] ?? 3) || a.index - b.index));
  return lines.filter((line) => line.length);
}

function _short(name) {
  const parts = String(name).trim().split(/\s+/);
  return parts.length > 1 ? parts[parts.length - 1] : parts[0];
}

function TeamHalf({ xi, positions, side, color }) {
  const lines = _lines(xi, positions);
  // Local: portero arriba (su portería) → delanteros hacia el centro.
  // Visitante: se invierte para que ataque hacia el centro también.
  const ordered = side === "home" ? lines : lines.slice().reverse();
  if (!lines.length) return <div className="pitch-half empty">once sin confirmar</div>;
  return (
    <div className={"pitch-half " + side}>
      {ordered.map((line, li) => (
        <div className="pitch-line" key={li}>
          {(side === "away" ? line.slice().reverse() : line).map((p) => (
            <div className="player" key={p.name} title={`${p.name} · ${p.position}`}>
              <span className="dot" style={{ background: color }} />
              <span className="pn">{_short(p.name)}</span>
              <span className="pp">{p.position}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function PropsTable({ title, clave, best }) {
  if (!(clave || []).length) return null;
  const highlighted = new Set((best || []).map((item) => item.jugador));
  const realRows = clave.filter((row) => row?.source === "API-Football · players").length;
  const coverageLabel = realRows === clave.length
    ? `titulares con muestra real ${realRows}/11`
    : "jugadores clave";
  return (
    <div className="xi-props">
      <div className="xi-props-h">{title} · {coverageLabel}</div>
      <table className="props-tbl">
        <thead><tr><th className="tl">Jugador</th><th title="Minutos previstos">MIN</th><th title="Probabilidad de ser titular">TIT</th><th title="Goles">G</th><th title="Asistencias">A</th><th title="Remates">R</th><th title="Remates a puerta">AP</th><th title="Faltas cometidas">FC</th><th title="Faltas recibidas">FR</th><th title="Tarjetas">T</th></tr></thead>
        <tbody>
          {clave.map((p, i) => (
            <tr key={i} className={highlighted.has(p.jugador) ? "best-prop" : ""}>
              <td className="tl" title={p.source ? `${p.source}${p.sample_minutes ? ` · ${p.sample_minutes} min de muestra` : ""}` : undefined}>{highlighted.has(p.jugador) ? "★ " : ""}{p.jugador}{p.source && <div className="mk-sub">{p.source}{p.sample_minutes ? ` · ${p.sample_minutes} min · per-90 × min previstos` : ""}</div>}</td>
              <td>{p.min ?? "–"}</td><td>{p.tit != null ? `${Math.round(p.tit * 100)}%` : "–"}</td>
              <td>{p.g ?? "–"}</td><td>{p.a ?? "–"}</td><td>{p.r ?? "–"}</td><td>{p.rp ?? "–"}</td><td>{p.fc ?? p.f ?? "–"}</td><td>{p.fr ?? "–"}</td><td>{p.t ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Availability({ title, rows, legacy }) {
  const items = (rows || []).length ? rows : (legacy || []).map((detail) => ({ detail }));
  if (!items.length) return null;
  return (
    <div className="xi-bajas">
      <b>{title}:</b>
      {items.map((item, index) => (
        <div key={index} style={{ marginTop: 3 }}>
          {item.detalle || item.jugador}
          {item.estado && <span className="dim"> · {item.estado}</span>}
          {item.source && <span className="dim"> · {item.source}</span>}
          {item.source_updated_at && <span className="dim"> · {new Date(item.source_updated_at).toLocaleString("es-ES")}</span>}
        </div>
      ))}
    </div>
  );
}

/* Once probable sobre el campo + bajas + jugadores clave con props (IA). */
function Alineacion({ m, a, canProps = true, onUpgrade }) {
  const provider = a.provider || a.fuente || "IA";
  const completeness = a.quality?.score != null ? ` · completitud ${Math.round(a.quality.score * 100)}%` : "";
  const status = a.status || (provider === "Motor estadístico local" ? "estimado" : "probable");
  const updated = a.source_updated_at || a.generated_at || a.ts;
  const isOfficial = status === "confirmado";
  return (
    <div className="card">
      <div className="row-between">
        <div className="lbl">👥 Once {status}</div>
        <div className="chips">
          <span className={"pill " + (isOfficial ? "y" : "")}>{status}</span>
          {a.cache_status && <span className="chip">recuperado de caché</span>}
        </div>
      </div>
      <div className="pitch">
        <div className="pitch-names">
          <span>{m.home}{a.formacion_local ? ` · ${a.formacion_local}` : ""}</span>
          <span>{m.away}{a.formacion_visitante ? ` · ${a.formacion_visitante}` : ""}</span>
        </div>
        <div className="pitch-grass">
          <div className="pitch-mid" />
          <div className="pitch-circle" />
          <TeamHalf xi={a.local} positions={a.posiciones_local} side="home" color="var(--green)" />
          <TeamHalf xi={a.visitante} positions={a.posiciones_visitante} side="away" color="var(--blue)" />
        </div>
      </div>
      {((a.bajas_local || []).length > 0 || (a.bajas_visitante || []).length > 0 || (a.disponibilidad_local || []).length > 0 || (a.disponibilidad_visitante || []).length > 0) && (
        <div className="xi-grid" style={{ marginTop: 10 }}>
          <Availability title={`Disponibilidad ${m.home}`} rows={a.disponibilidad_local} legacy={a.bajas_local} />
          <Availability title={`Disponibilidad ${m.away}`} rows={a.disponibilidad_visitante} legacy={a.bajas_visitante} />
        </div>
      )}
      {!canProps ? (
        <button type="button" className="props-locked" onClick={onUpgrade}>
          🔒 Player props (goles, tiros, tarjetas por jugador) · función <b>Pro</b> — pulsa para desbloquear
        </button>
      ) : <>
        {(a.best_props || []).length > 0 && (
          <div className="chips" style={{ marginTop: 10 }}>
            {(a.best_props || []).map((item) => <span className="chip" key={`${item.lado}-${item.jugador}`} title="Ventaja estadística interna; no incluye cuota de casa">★ {item.jugador} · {item.motivo}</span>)}
          </div>
        )}
        {((a.clave_local || []).length > 0 || (a.clave_visitante || []).length > 0) ? <div className="xi-grid" style={{ marginTop: 10 }}>
          <PropsTable title={m.home} clave={a.clave_local} best={a.best_props} />
          <PropsTable title={m.away} clave={a.clave_visitante} best={a.best_props} />
        </div> : <div className="note" style={{ marginTop: 10 }}>Props numéricos: sin datos reales suficientes. La IA no rellena estimaciones individuales.</div>}
      </>}
      <p className="note" style={{ color: "var(--muted)", marginTop: 6 }}>
        {isOfficial ? "Once oficial" : "Estimación"} · fuente {provider}{updated ? ` · actualizada ${new Date(updated).toLocaleString("es-ES")}` : ""}{completeness}. Props: MIN minutos · TIT prob. de inicio · G goles · A asist. · R remates · AP a puerta · FC/FR faltas · T tarjetas. {!isOfficial && "La alineación todavía no es oficial; verifica antes de apostar."}
      </p>
    </div>
  );
}

/* Post-partido: tabla de stats esperadas vs reales con % de acierto. */
function PostMatchStats({ m }) {
  const sr = m.statsReal || {};
  const acc = (pred, real) => {
    const base = Math.max(Math.abs(real), Math.abs(pred), 1);
    return Math.max(0, Math.round(100 * (1 - Math.abs(real - pred) / base)));
  };
  const num = (v) => (v == null || v === "" ? null : +Number(v).toFixed(1));
  const rows = [];
  // Goles: previsto = xG total; real = marcador.
  if (m.xg || m.result) {
    rows.push({ k: "goals", lab: "Goles",
      pred: m.xg ? +(m.xg[0] + m.xg[1]).toFixed(1) : null,
      real: m.result ? m.result[0] + m.result[1] : null });
  }
  // Todas las métricas: se muestran aunque falte la real (queda pendiente).
  [["shots", "Remates"], ["sot", "Tiros a puerta"], ["corners", "Córners"],
   ["fouls", "Faltas"], ["yellows", "Amarillas"], ["reds", "Rojas"], ["offsides", "Fueras de juego"]].forEach(([k, lab]) => {
    const pred = num(m.stats?.[k]?.total);
    const real = num(sr[k]?.total);
    if (pred != null || real != null) rows.push({ k, lab, pred, real });
  });
  const scored = rows.filter((r) => Number.isFinite(r.pred) && Number.isFinite(r.real));
  const avg = scored.length ? Math.round(scored.reduce((s, r) => s + acc(r.pred, r.real), 0) / scored.length) : null;
  const anyReal = rows.some((r) => Number.isFinite(r.real) && r.k !== "goals");
  return (
    <div className="card">
      <div className="row-between">
        <div className="lbl">Predicho vs real</div>
        {avg != null && <span className="pill y">Acierto medio {avg}%</span>}
      </div>
      <div className="tbl-wrap">
        <table className="tbl-mk cmp-tbl">
          <thead><tr><th className="tl">Métrica</th><th>Previsto</th><th>Real</th><th>Dif.</th><th>Acierto</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const both = Number.isFinite(r.pred) && Number.isFinite(r.real);
              const dif = both ? +(r.real - r.pred).toFixed(1) : null;
              const a = both ? acc(r.pred, r.real) : null;
              return (
                <tr key={r.k}>
                  <td className="tl">{r.lab}</td>
                  <td>{r.pred != null ? r.pred : "—"}</td>
                  <td>{r.real != null ? <b>{r.real}</b> : <span className="dim">pendiente</span>}</td>
                  <td className={dif == null ? "dim" : dif > 0 ? "value-yes" : dif < 0 ? "value-no" : "dim"}>{dif == null ? "—" : (dif > 0 ? "+" : "") + dif}</td>
                  <td>{a == null ? <span className="dim">—</span> : <span className="acc-badge" style={{ "--acc": a + "%" }}>{a}%</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="note" style={{ color: "var(--muted)", marginTop: 6 }}>
        Reales (co.uk, ~1 día de retraso) frente a lo que estimó el modelo. Diferencia = real − previsto.
        {sr.meta?.referee && ` Árbitro: ${sr.meta.referee}.`}
        {!anyReal && " Las stats detalladas de este partido aún no están publicadas; se completan en la siguiente actualización."}
      </p>
    </div>
  );
}

/* Flecha de tendencia de una métrica esperada (↑/→/↓ + % y motivo). */
function TrendArrow({ t }) {
  // Siempre muestra algo: neutro (→) por defecto.
  const dir = t?.dir || "flat";
  const sym = dir === "up" ? "↑" : dir === "down" ? "↓" : "→";
  const cls = dir === "up" ? "trend-up" : dir === "down" ? "trend-down" : "trend-flat";
  const title = t?.reason || "neutro";
  return (
    <span className={"trend " + cls} title={title}>
      {sym}{dir !== "flat" ? ` ${t.pct > 0 ? "+" : ""}${t.pct}%` : ""}
    </span>
  );
}

export default function MatchDetail({ m, bankroll, onBack, onTeam, players, plan = "vip", onUpgrade }) {
  const canProps = hasAccess(plan, "props");
  const [ouL, setOuL] = useState(2.5);
  const [hcL, setHcL] = useState(-0.5);
  const [vSel, setVSel] = useState("1");
  const [vOdds, setVOdds] = useState(2.0);
  const [copied, setCopied] = useState(false);

  const conf = confidence(m);
  const cd = m.finished ? "" : countdown(m.kickoff);
  const surprise = isSurprise(m);
  const snapshot = m.prediction_snapshot;
  const history = Array.isArray(m.prediction_history) ? m.prediction_history : [];
  const previousSnapshot = history.length > 1 ? history[history.length - 2] : null;
  const probabilityDelta = previousSnapshot?.probs && snapshot?.probs
    ? snapshot.probs.map((value, i) => +(value - previousSnapshot.probs[i]).toFixed(1))
    : null;
  const share = async () => {
    const lines = [`${m.home} vs ${m.away} — ${m.league}${m.matchday ? " J" + m.matchday : ""}`];
    if (m.finished && m.result) lines.push(`Resultado: ${m.result[0]}-${m.result[1]}`);
    if (Array.isArray(m.probs)) lines.push(`Modelo 1X2: ${m.probs[0]}% / ${m.probs[1]}% / ${m.probs[2]}%`);
    if (m.markets?.marcador) lines.push(`Marcador previsto: ${m.markets.marcador}`);
    lines.push("— vía Fútbol Edge");
    try { await navigator.clipboard.writeText(lines.join("\n")); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* ignore */ }
  };

  // Matriz de marcadores si hay xG. Los partidos jugados también lo traen
  // (para comparar lo esperado con lo real), aunque hasPrediction los excluya.
  const M = useMemo(() => (Array.isArray(m.xg) && m.xg.length === 2 ? matrix(m.xg[0], m.xg[1]) : null), [m]);
  const p = M ? oneXtwo(M) : null;

  const md = m.matchday ? "J" + m.matchday : (m.stage || "");
  const bank = Number(bankroll) || 1000;
  const abstain = m.recommendation?.decision === "no_pick";
  const jump = (section) => document.getElementById(`match-${section}`)?.scrollIntoView({ behavior: "smooth", block: "start" });

  let vProb = 0;
  if (M) {
    if (vSel === "1") vProb = Array.isArray(m.probs) ? m.probs[0] / 100 : p[1];
    else if (vSel === "X") vProb = Array.isArray(m.probs) ? m.probs[1] / 100 : p.X;
    else if (vSel === "2") vProb = Array.isArray(m.probs) ? m.probs[2] / 100 : p[2];
    else if (vSel === "ov") vProb = over(M, ouL);
    else if (vSel === "un") vProb = 1 - over(M, ouL);
    else vProb = btts(M);
  }
  const edge = vProb * Number(vOdds) - 1;
  const stake = abstain ? 0 : Math.min(bank * kelly(vProb, Number(vOdds)) * 0.25, bank * 0.05);

  return (
    <div>
      <button type="button" className="back" onClick={onBack}>← Volver a la lista</button>
      <div className="card match-hero">
        <div className="ctop"><span>{m.league} · {md}</span><span>{fmtKick(m.kickoff)}</span></div>
        <Teams m={m} onTeam={onTeam} />
        <div className="chips" style={{ justifyContent: "center" }}>
          {cd && <span className="countdown">⏱ {cd}</span>}
          {conf && !m.finished && (
            <span className="chip" title={`Confianza ${conf.label} · favorito al ${conf.mx}% · desacuerdo DC/Elo ${(conf.disagreement * 100).toFixed(1)} pp`}>
              Confianza {conf.score != null ? <b>{conf.score}/100 </b> : null}<span className="conf-stars">{[1, 2, 3].map((i) => <span key={i} className={i <= conf.stars ? "on" : "off"}>★</span>)}</span>
            </span>
          )}
          {snapshot?.generated_at && <span className="chip" title="Snapshot inmutable utilizado para evaluar el modelo">Predicción <b>{snapshot.window || new Date(snapshot.generated_at).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}</b></span>}
          {surprise && !m.finished && <span className="pill y" title="El favorito del modelo no coincide con el del mercado">⚡ Sorpresa</span>}
          <button type="button" className="mini" onClick={share}>{copied ? "✓ Copiado" : "🔗 Compartir"}</button>
        </div>
      </div>

      <PredictionTimelinePanel m={m} />

      <nav className="match-nav" aria-label="Secciones del partido">
        {[['analysis', 'Previa'], ['lineup', 'Onces'], ['prediction', 'Pronóstico'], ['stats', 'Datos']].map(([key, label]) => (
          <button type="button" key={key} onClick={() => jump(key)}>{label}</button>
        ))}
      </nav>

      {abstain && (
        <div className="banner warn" role="status">
          <b>Sin apuesta recomendada.</b> {(m.recommendation?.reasons || []).join(" · ")}. Las probabilidades se muestran para análisis, no como pick.
        </div>
      )}

      {Array.isArray(m.h2h) && m.h2h.length > 0 && (
        <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
          <div className="lbl" style={{ padding: "6px 6px 0" }}>Cara a cara · últimos {m.h2h.length}</div>
          <table className="tbl-mk">
            <tbody>
              {m.h2h.slice().reverse().map((g, i) => (
                <tr key={i}>
                  <td className="tl">{g.home} <b>{g.hg}-{g.ag}</b> {g.away}</td>
                  <td className="dim" style={{ textAlign: "right" }}>{g.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {m.preview && (
        <div className="card section-anchor" id="match-analysis">
          <div className="lbl">📝 Análisis previo</div>
          {m.preview.split(/\n+/).filter(Boolean).map((par, i) => (
            <p key={i} style={{ margin: "0 0 8px", lineHeight: 1.55, color: "var(--text)" }}>{par}</p>
          ))}
          <p className="note" style={{ color: "var(--muted)", marginTop: 4 }}>Redactado por {m.preview_meta?.provider || "IA"} a partir de los números del modelo{m.preview_meta?.quality != null ? ` · calidad ${Math.round(m.preview_meta.quality * 100)}%` : ""}. No es información de fuentes; interpreta los datos.</p>
        </div>
      )}

      {(m.prediction_factors || []).length > 0 && (
        <div className="card">
          <div className="lbl">Factores del pronóstico</div>
          {(m.prediction_factors || []).map((factor) => (
            <div className="kv" key={factor.factor}><span>{factor.factor} <span className="dim">· {factor.detail}</span></span><b>{factor.impact}</b></div>
          ))}
          <p className="note" style={{ color: "var(--muted)", marginTop: 6 }}>Las bajas verificadas reducen la confianza. No cambian artificialmente el marcador si falta una valoración fiable del impacto del jugador.</p>
        </div>
      )}

      {(m.weather || m.tactical_matchup || m.venue_meta) && (
        <div className="card">
          <div className="lbl">Contexto del partido</div>
          {m.venue_meta && <div className="kv"><span>Estadio</span><b>{m.venue_meta.name} · {m.venue_meta.city}</b></div>}
          {m.official_context?.referee && <div className="kv"><span>Árbitro</span><b>{m.official_context.referee} · API-Football</b></div>}
          {m.weather && <>
            <div className="kv"><span>Tiempo al saque inicial</span><b>{m.weather.temperature_c} °C · sensación {m.weather.apparent_temperature_c} °C</b></div>
            <div className="kv"><span>Lluvia / viento</span><b>{m.weather.precipitation_probability_pct}% · {m.weather.wind_kmh} km/h</b></div>
            <div className="kv"><span>Estrés térmico</span><b>{m.weather.heat_stress?.level || "—"}</b></div>
          </>}
          {m.tactical_matchup && <>
            <div className="kv"><span>Volumen de remate proyectado</span><b>{m.tactical_matchup.expected_shot_pressure?.home ?? "—"} – {m.tactical_matchup.expected_shot_pressure?.away ?? "—"}</b></div>
            <div className="kv"><span>Fiabilidad del perfil</span><b>{m.tactical_matchup.reliability} · {m.tactical_matchup.minimum_samples} partidos por split</b></div>
            <TacticalProfile matchup={m.tactical_matchup} home={m.home} away={m.away} />
            {(m.tactical_matchup.notes || []).map((note) => <p className="mut" key={note}>• {note}</p>)}
          </>}
          <p className="note source-note">{m.weather ? `Open-Meteo · ${m.weather.license}${m.weather.source_updated_at ? ` · actualizada ${new Date(m.weather.source_updated_at).toLocaleString("es-ES")}` : ""}. ` : ""}El clima y el perfil táctico ajustan explicación/confianza; no alteran el marcador hasta superar validación histórica.</p>
        </div>
      )}

      <WeatherAdjustmentPanel adjustment={m.weather_adjustment} />
      <OfficialStatsPanel match={m} />

      {m.alineacion && <div className="section-anchor" id="match-lineup"><Alineacion m={m} a={m.alineacion} canProps={canProps} onUpgrade={onUpgrade} /></div>}
      <PlayerFairLines match={m} />
      <LineupImpact impact={m.lineup_impact} home={m.home} away={m.away} />

      {(players || m.alineacion) && (() => {
        const fromLineup = (names, keys) => (names || []).map((name) => {
          const prop = (keys || []).find((item) => item.jugador === name) || {};
          return { player: name, goals: prop.g || 0, assists: prop.a || 0,
            shots: prop.r || 0, yc: prop.t || 0, min: 0 };
        });
        const realHome = teamSquad(players, m.home), realAway = teamSquad(players, m.away);
        const hs = realHome.length ? realHome : fromLineup(m.alineacion?.local, m.alineacion?.clave_local);
        const as = realAway.length ? realAway : fromLineup(m.alineacion?.visitante, m.alineacion?.clave_visitante);
        if (!hs.length && !as.length) return null;
        const catLine = (icon, label, sq, key) => {
          const rows = sq.filter((p) => p[key] > 0).sort((a, b) => b[key] - a[key]).slice(0, 2);
          if (!rows.length) return null;
          return <div className="kv" style={{ padding: "5px 0" }}><span>{icon} {label}</span><span style={{ textAlign: "right", fontSize: ".82rem" }}>{rows.map((p) => `${p.player} (${p[key]})`).join(" · ")}</span></div>;
        };
        const col = (team, sq) => (
          <div style={{ flex: 1, minWidth: 150 }}>
            <div className="tn" style={{ marginBottom: 4 }}>{team}</div>
            {!sq.length ? <div className="dim" style={{ fontSize: ".8rem" }}>Sin datos de jugadores</div> : <>
              {catLine("⚽", "Gol", sq, "goals")}
              {catLine("🅰️", "Asist.", sq, "assists")}
              {catLine("🎯", "Remates", sq, "shots")}
              {catLine("🟨", "Tarjeta", sq, "yc")}
            </>}
          </div>
        );
        return (
          <div className="card">
            <div className="lbl">Jugadores a seguir <span className="dim">(quién suele hacer cada acción, por forma de la temporada)</span></div>
            <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
              {col(m.home, hs)}
              {col(m.away, as)}
            </div>
            {m.stats && (
              <p className="note" style={{ color: "var(--muted)" }}>
                Contexto del modelo (según rival): {m.home} ~{m.stats.shots?.home} remates y {m.stats.yellows?.home} tarjetas; {m.away} ~{m.stats.shots?.away} remates y {m.stats.yellows?.away} tarjetas.
              </p>
            )}
          </div>
        );
      })()}

      {m.finished && m.result && (
        <div className="card">
          <div className="lbl">Resultado real</div>
          <div className="score" style={{ textAlign: "center" }}>{m.result[0]} – {m.result[1]}</div>
          {m.probs && (() => {
            const outcome = m.result[0] > m.result[1] ? "1" : m.result[0] < m.result[1] ? "2" : "X";
            const favIdx = m.probs.indexOf(Math.max(...m.probs));
            const fav = ["1", "X", "2"][favIdx];
            const hit = fav === outcome;
            const pReal = m.probs[{ "1": 0, "X": 1, "2": 2 }[outcome]];
            return (
              <div style={{ marginTop: 12 }}>
                <div className="lbl">Lo que anticipaba el modelo <span className="dim">(incluye forma reciente)</span></div>
                <div className="chips">
                  {["1", "X", "2"].map((s, j) => (
                    <span key={s} className={"chip" + (s === outcome ? " value-yes" : "")}>{s} <b>{m.probs[j]}%</b></span>
                  ))}
                  {m.markets?.marcador && <span className="chip">Marcador previsto <b>{m.markets.marcador}</b></span>}
                </div>
                <div className="kv" style={{ marginTop: 8 }}><span>Pronóstico 1X2</span>
                  {hit ? <span className="pill y">✓ Acierto ({fav} era el favorito)</span>
                    : <span className="value-no">✗ Fallo (favorito {fav}, salió {outcome} · {pReal}%)</span>}</div>
              </div>
            );
          })()}
        </div>
      )}

      {!M && !m.finished && (
        <div className="card">
          <div className="note">⚠️ Todavía sin predicción del modelo para este partido
            {m.nota ? ` — ${m.nota}` : " (algún equipo está fuera de la liga base o falta muestra de la temporada)"}.</div>
          <div className="chips" style={{ marginTop: 10 }}>
            <span className="chip">Fecha <b>{fmtKick(m.kickoff)}</b></span>
            <span className="chip">Competición <b>{m.league}</b></span>
            <span className="chip">Jugadores <b>pendiente</b></span>
            <span className="chip">Cuotas <b>pendiente</b></span>
          </div>
        </div>
      )}

      {M && (
        <>
          {m.provisional && (
            <div className="card"><div className="note">⚠️ {m.nota || "Predicción provisional: algún equipo aún sin histórico (recién ascendido). Se afina según juegue."}</div></div>
          )}
          <div className="card section-anchor" id="match-prediction">
            <div className="row-between">
              <div className="lbl">{m.finished ? "1X2 que daba el modelo" : "Resultado 1X2"}{m.calibrated && <span className="dim" title="Probabilidad del modelo mezclada con la del mercado (calibrada)"> · calibrado</span>}</div>
              <span className="chip">Motor <b>{m.model_meta?.provider || m.engine}</b></span>
            </div>
            {probabilityDelta && probabilityDelta.some((value) => value !== 0) && (
              <div className="change-explanation">
                <b>Qué cambió desde {previousSnapshot?.window || "la revisión anterior"}</b>
                <span>1 {probabilityDelta[0] > 0 ? "+" : ""}{probabilityDelta[0]} pp · X {probabilityDelta[1] > 0 ? "+" : ""}{probabilityDelta[1]} pp · 2 {probabilityDelta[2] > 0 ? "+" : ""}{probabilityDelta[2]} pp</span>
                <small>{snapshot?.prediction_factors?.filter((factor) => factor.impact !== "pendiente").slice(0, 2).map((factor) => factor.factor).join(" · ") || "cambio de parámetros y datos disponibles"}</small>
              </div>
            )}
            {(() => {
              const hc = accent(m.homeColors), ac = accent(m.awayColors);
              const hs = hc && hc.startsWith("#") ? { background: hc, color: "#fff" } : {};
              const as = ac && ac.startsWith("#") ? { background: ac, color: "#fff" } : {};
              return (
                <div className="pbar">
                  <div className="seg s1" style={{ flex: m.probs[0], ...hs }} title={`Gana ${m.home}: ${m.probs[0]}%`}>{m.probs[0] > 8 ? m.probs[0] + "%" : ""}</div>
                  <div className="seg sx" style={{ flex: m.probs[1] }} title={`Empate: ${m.probs[1]}%`}>{m.probs[1] > 8 ? m.probs[1] + "%" : ""}</div>
                  <div className="seg s2" style={{ flex: m.probs[2], ...as }} title={`Gana ${m.away}: ${m.probs[2]}%`}>{m.probs[2] > 8 ? m.probs[2] + "%" : ""}</div>
                </div>
              );
            })()}
            <div className="chips">
              <span className="chip" title="Marcador exacto más probable según el modelo">Marcador <b>{m.markets.marcador}</b></span>
              <span className="chip help" title="Goles esperados (xG): calidad y cantidad de ocasiones que se esperan por equipo">xG <b>{m.xg[0]}–{m.xg[1]}</b></span>
              <span className="chip help" title="BTTS = ambos equipos marcan (Both Teams To Score)">BTTS <b>{Math.round(m.markets.btts * 100)}%</b></span>
              {m.score_distribution?.total_goals_p10_p50_p90 && <span className="chip" title="Percentiles 10, 50 y 90 de la distribución de goles">Rango goles P10–P90 <b>{m.score_distribution.total_goals_p10_p50_p90[0]}–{m.score_distribution.total_goals_p10_p50_p90[2]}</b></span>}
            </div>
            <MarketMovement odds={m.odds} />
            <div className="lbl">Mapa de marcadores (local ↓ / visitante →)</div>
            <Heat M={M} />
          </div>

          <StateSimulation simulation={m.state_simulation} />

          {!m.finished && (<>
          <div className="card">
            <div className="lbl">Over / Under goles</div>
            <div className="row">
              <input type="range" min="0.5" max="6.5" step="0.5" value={ouL} className="grow"
                aria-label="Línea de goles"
                onChange={(e) => setOuL(Number(e.target.value))} />
              <span className="pill y">{ouL}</span>
            </div>
            <div className="kv"><span>Over {ouL}</span><b>{(over(M, ouL) * 100).toFixed(1)}% · cuota {(1 / over(M, ouL)).toFixed(2)}</b></div>
            <div className="kv"><span>Under {ouL}</span><b>{((1 - over(M, ouL)) * 100).toFixed(1)}% · cuota {(1 / (1 - over(M, ouL))).toFixed(2)}</b></div>
          </div>

          <div className="card">
            <div className="lbl">Hándicap asiático (local)</div>
            <div className="row">
              <input type="range" min="-3" max="3" step="0.25" value={hcL} className="grow"
                aria-label="Línea de hándicap asiático local"
                onChange={(e) => setHcL(Number(e.target.value))} />
              <span className="pill y">{hcL > 0 ? "+" + hcL : hcL}</span>
            </div>
            {(() => { const r = ah(M, hcL, "home"); return (<>
              <div className="kv"><span>Gana</span><b>{(r.win * 100).toFixed(1)}%</b></div>
              <div className="kv"><span>Nulo (push)</span><b>{(r.push * 100).toFixed(1)}%</b></div>
              <div className="kv"><span>Pierde</span><b>{(r.lose * 100).toFixed(1)}%</b></div>
            </>); })()}
          </div>

          <div className="card">
            <div className="lbl">Calculadora de value</div>
            <div className="row">
              <select aria-label="Mercado de la calculadora de value" value={vSel} onChange={(e) => setVSel(e.target.value)}>
                <option value="1">1</option><option value="X">X</option><option value="2">2</option>
                <option value="ov">Over (línea de arriba)</option>
                <option value="un">Under (línea de arriba)</option>
                <option value="btts">BTTS Sí</option>
              </select>
              <input aria-label="Cuota de la calculadora de value" type="number" step="0.01" value={vOdds} style={{ width: 120 }}
                onChange={(e) => setVOdds(e.target.value)} />
            </div>
            <div className="kv"><span>Prob. modelo</span><b>{(vProb * 100).toFixed(1)}%</b></div>
            <div className="kv"><span>Cuota justa</span><b>{(1 / vProb).toFixed(2)}</b></div>
            <div className="kv"><span>Edge</span><b className={edge > 0 ? "value-yes" : "value-no"}>{(edge * 100).toFixed(1)}%</b></div>
            <div className="kv"><span>Recomendación</span>
              {abstain ? <span className="value-no">NO APOSTAR · confianza insuficiente</span> : edge > 0.02 ? <span className="pill y">APOSTAR · {stake.toFixed(2)}€</span> : <span className="value-no">Sin value</span>}</div>
          </div>
          </>)}

          {(m.statsReal || (m.finished && m.result)) ? (
            <PostMatchStats m={m} />
          ) : m.stats && (
            <div className="card section-anchor" id="match-stats">
              <div className="lbl">Estadísticas esperadas</div>
              <table>
                <thead><tr><th>Métrica</th><th>Local</th><th>Visit.</th><th>Total</th><th>Tend.</th></tr></thead>
                <tbody>
                  {[["goals", "Goles"], ["shots", "Remates"], ["sot", "Tiros a puerta"], ["corners", "Córners"],
                    ["fouls", "Faltas"], ["yellows", "Amarillas"], ["reds", "Rojas"], ["offsides", "Fueras de juego"]]
                    .filter(([k]) => m.stats[k]).map(([k, lab]) => (
                      <tr key={k}><td>{lab}</td><td>{m.stats[k].home}</td><td>{m.stats[k].away}</td><td><b>{m.stats[k].total}</b></td>
                        <td><TrendArrow t={m.tendencias?.[k]} /></td></tr>
                    ))}
                </tbody>
              </table>
              {m.tendencias && Object.values(m.tendencias).some((t) => t.dir !== "flat") && (
                <p className="mut" style={{ marginTop: 8 }}>
                  ↑/↓ = se espera más/menos de lo habitual según la forma reciente y el descanso.
                  {" "}{Object.values(m.tendencias).filter((t) => t.dir !== "flat").map((t) => `${t.label}: ${t.reason}`).join(" · ")}.
                </p>
              )}
            </div>
          )}

          <div className="card">
            <div className="lbl">Marcadores más probables</div>
            <div className="chips">
              {topScores(M, 6).map(([x, y, pr]) => (
                <span key={x + "-" + y} className="chip">{x}-{y} <b>{(pr * 100).toFixed(1)}%</b></span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
