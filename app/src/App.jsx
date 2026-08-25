import { useEffect, useMemo, useState } from "react";
import { crestFor, feedAgeHours, fmtKick, hasPrediction, isStale, loadFeed } from "./feed";
import { entropy, fairProbs, kelly, overround, plenoSign } from "./poisson";
import { leaguesIn, projectedTable } from "./standings";
import { teamProfile, teamSquad } from "./teams";
import { bestValue, countdown, getFavs, modelAccuracy, recentForm, toggleFav, topValueBets } from "./insights";
import MatchDetail from "./MatchDetail";
import PlayerProfile from "./PlayerProfile";
import ProbabilityQualityPanel from "./ProbabilityQualityPanel";
import ClvPanel from "./ClvPanel";
import GlobalValuePanel from "./GlobalValuePanel";
import HistoricalQualityPanel from "./HistoricalQualityPanel";
import AccuracyMatchDetails from "./AccuracyMatchDetails";
import { authEnabled, signOut, useSession } from "./supabase";

function savedLightTheme() {
  try { return localStorage.getItem("theme") === "light"; } catch { return false; }
}

/* ---------- Iconos de la barra lateral ---------- */
function Icon({ name }) {
  const p = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" };
  const paths = {
    resumen: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
    clasificacion: <><line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="17" x2="14" y2="17" /></>,
    mercados: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.2" /><circle cx="12" cy="12" r="0.4" fill="currentColor" /></>,
    partidos: <><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17M3.5 12h17" /><path d="M12 3.5a13 8.5 0 0 0 0 17M12 3.5a13 8.5 0 0 1 0 17" /></>,
    jugadores: <><circle cx="9" cy="8" r="3.2" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0" /><path d="M16 5.2a3.2 3.2 0 0 1 0 6M17.5 20a5.5 5.5 0 0 0-2.6-4.7" /></>,
    value: <><path d="M4 16l5-5 3 3 7-8" /><path d="M16 6h4v4" /></>,
    quiniela: <><path d="M7 4h10v3a5 5 0 0 1-10 0V4z" /><path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3" /><path d="M10 15v3M14 15v3M8 21h8" /></>,
    datos: <><ellipse cx="12" cy="5.5" rx="7" ry="2.8" /><path d="M5 5.5v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6" /><path d="M5 11.5v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6" /></>,
    cartera: <><rect x="3" y="6" width="18" height="13" rx="2.5" /><path d="M3 9h18" /><circle cx="16.5" cy="13.5" r="1.3" fill="currentColor" /></>,
    search: <><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>,
  };
  return <svg {...p} aria-hidden="true">{paths[name]}</svg>;
}

/* ---------- Skeleton ---------- */
function Skeletons({ n = 5 }) {
  return (
    <>
      {Array.from({ length: n }).map((_, i) => (
        <div className="card" key={i} aria-hidden="true">
          <div className="skel" style={{ width: "45%", height: 12 }} />
          <div className="skel" style={{ width: "100%", height: 40, marginTop: 14 }} />
          <div className="skel" style={{ width: "100%", height: 30, marginTop: 12 }} />
        </div>
      ))}
    </>
  );
}


/* ---------- Utilidades de calendario ---------- */
const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const dayLong = (s) => { try { return new Date(s + "T12:00:00").toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" }); } catch { return s; } };
const dayWd = (s) => { try { return new Date(s + "T12:00:00").toLocaleDateString("es-ES", { weekday: "short" }); } catch { return ""; } };
const dayNum = (s) => { try { return new Date(s + "T12:00:00").toLocaleDateString("es-ES", { day: "2-digit" }); } catch { return s; } };
const hhmm = (iso) => { try { return new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

/* Puntos de forma reciente (V/E/D) */
function FormDots({ form }) {
  if (!form || !form.length) return null;
  return (
    <span className="form-dots" title="Forma reciente (izq→der, más antiguo→reciente)">
      {form.map((f, i) => <i key={i} className={"fdot f-" + f} />)}
    </span>
  );
}

/* Fila compacta de partido para el calendario */
function MatchRow({ m, onOpen, formMap }) {
  const pred = hasPrediction(m);
  const best = pred ? ["1", "X", "2"][m.probs.indexOf(Math.max(...m.probs))] : null;
  const val = bestValue(m);
  return (
    <button type="button" className="mrow" onClick={() => onOpen(m)}>
      <span className="mrow-time">{m.finished ? "FT" : hhmm(m.kickoff)}</span>
      <span className="mrow-body">
        <span className="mrow-line">
          <span className="mrow-team"><img className="crest xs" alt="" loading="lazy" src={crestFor(m.home, m.homeColors, m.homeCrest)} onError={(e) => (e.target.src = crestFor(m.home, m.homeColors, null))} /><span className="tn">{m.home}</span>{formMap && <FormDots form={formMap[m.home]} />}</span>
          <span className="mrow-cen">{m.finished && m.result ? `${m.result[0]}–${m.result[1]}` : (m.markets?.marcador || "·")}</span>
          <span className="mrow-team rev"><span className="tn">{m.away}</span>{formMap && <FormDots form={formMap[m.away]} />}<img className="crest xs" alt="" loading="lazy" src={crestFor(m.away, m.awayColors, m.awayCrest)} onError={(e) => (e.target.src = crestFor(m.away, m.awayColors, null))} /></span>
        </span>
        {pred && (
          <span className="mrow-bar">
            <i className="s1" style={{ flex: m.probs[0] }} /><i className="sx" style={{ flex: m.probs[1] }} /><i className="s2" style={{ flex: m.probs[2] }} />
          </span>
        )}
      </span>
      <span className="mrow-tag">
        {val && <span className="tag-val" title={`Value ${val.selection}: edge ${(val.edge * 100).toFixed(1)}%`}>◆</span>}
        {m.league.replace("LaLiga", "1ª").replace("Hypermotion", "").replace("Champions League", "UCL")}{best ? ` · ${best}` : ""}
      </span>
    </button>
  );
}

/* ---------- Resumen: dashboard de calendario por días ---------- */
function Resumen({ matches, onOpen, goto, favs, onTeam }) {
  const days = useMemo(() => [...new Set(matches.map((m) => m.date).filter(Boolean))].sort(), [matches]);
  const startIdx = useMemo(() => {
    const t = todayKey();
    const i = days.findIndex((d) => d >= t);
    return i < 0 ? Math.max(0, days.length - 1) : i;
  }, [days]);
  const [idx, setIdx] = useState(startIdx);
  const [renderedAt] = useState(() => Date.now());

  const day = days[idx];
  const dayMatches = useMemo(() => matches.filter((m) => m.date === day).sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || "")), [matches, day]);
  const predicted = dayMatches.filter(hasPrediction);
  const pick = predicted
    .map((m) => { const mx = Math.max(...m.probs); return { m, mx, s: ["1", "X", "2"][m.probs.indexOf(mx)] }; })
    .sort((a, b) => b.mx - a.mx)[0];
  const strong = predicted.filter((m) => Math.max(...m.probs) >= 55).length;
  const goalsDay = predicted.length ? (predicted.reduce((s, m) => s + (m.xg ? m.xg[0] + m.xg[1] : 0), 0) / predicted.length) : 0;
  const acc = useMemo(() => modelAccuracy(matches), [matches]);
  const formMap = useMemo(() => {
    const map = {};
    for (const m of dayMatches) { map[m.home] ??= recentForm(matches, m.home); map[m.away] ??= recentForm(matches, m.away); }
    return map;
  }, [matches, dayMatches]);
  const dayValue = useMemo(() => topValueBets(dayMatches, 3), [dayMatches]);
  const favList = useMemo(() => {
    if (!favs || !favs.size) return [];
    return [...favs].map((t) => {
      const fx = matches.filter((m) => m.home === t || m.away === t).sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || ""));
      const next = fx.find((m) => new Date(m.kickoff).getTime() >= renderedAt) || fx[fx.length - 1];
      return { team: t, m: next };
    }).filter((x) => x.m);
  }, [favs, matches, renderedAt]);

  const win = 9;
  const start = Math.max(0, Math.min(idx - 4, Math.max(0, days.length - win)));
  const strip = days.slice(start, start + win);
  const t = todayKey();

  return (
    <>
      <div className="stat-tiles">
        <div className="stat"><span className="stat-k">Partidos</span><b className="stat-v">{dayMatches.length}</b><span className="stat-s">{dayLong(day)}</span></div>
        <div className="stat"><span className="stat-k">Pick del día</span><b className="stat-v accent">{pick ? `${pick.s} · ${pick.mx}%` : "—"}</b><span className="stat-s">{pick ? `${pick.m.home}–${pick.m.away}` : "sin predicción"}</span></div>
        <div className="stat"><span className="stat-k">Picks fuertes</span><b className="stat-v">{strong}</b><span className="stat-s">confianza ≥ 55%</span></div>
        <div className="stat"><span className="stat-k">Goles esperados</span><b className="stat-v">{goalsDay.toFixed(2)}</b><span className="stat-s">media xG por partido</span></div>
        <div className="stat" title="Aciertos 1X2 del modelo en partidos ya jugados esta temporada"><span className="stat-k">Acierto modelo</span><b className="stat-v accent">{acc.pct != null ? acc.pct + "%" : "—"}</b><span className="stat-s">{acc.total ? `${acc.hits}/${acc.total} aciertos 1X2` : "sin datos aún"}</span></div>
      </div>

      {dayValue.length > 0 && (
        <div className="card">
          <div className="lbl">◆ Value del día <span className="dim">(modelo vs mercado)</span></div>
          {dayValue.map(({ m, selection, edge, odds }) => (
            <button type="button" key={m.id} className="vd-row click row-button" onClick={() => onOpen(m)}>
              <span className="vd-team">{m.home} <span className="dim">vs</span> {m.away}</span>
              <span className="chips">
                <span className="chip">Apuesta <b>{selection}</b></span>
                <span className="chip">Cuota <b>{odds}</b></span>
                <span className="pill y">+{(edge * 100).toFixed(1)}%</span>
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="cal">
        <div className="cal-nav">
          <button type="button" className="cal-btn" disabled={idx <= 0} onClick={() => setIdx((i) => Math.max(0, i - 1))} aria-label="Día anterior">‹</button>
          <div className="cal-title"><b>{dayLong(day)}</b>{day === t && <span className="cal-today">HOY</span>}</div>
          <button type="button" className="cal-btn" disabled={idx >= days.length - 1} onClick={() => setIdx((i) => Math.min(days.length - 1, i + 1))} aria-label="Día siguiente">›</button>
          <button type="button" className="cal-btn wide" onClick={() => setIdx(startIdx)}>Hoy</button>
        </div>
        <div className="cal-strip">
          {strip.map((d) => {
            const n = matches.filter((m) => m.date === d).length;
            return (
              <button type="button" key={d} className={"cal-day" + (d === day ? " on" : "") + (d === t ? " today" : "")} onClick={() => setIdx(days.indexOf(d))}>
                <span className="cd-wd">{dayWd(d)}</span>
                <span className="cd-dm">{dayNum(d)}</span>
                <span className="cd-n">{n}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="day-matches">
        {dayMatches.length ? dayMatches.map((m) => <MatchRow key={m.id} m={m} onOpen={onOpen} formMap={formMap} />)
          : <div className="state">No hay partidos este día.</div>}
      </div>

      {favList.length > 0 && (
        <div className="card">
          <div className="lbl">★ Tus equipos</div>
          {favList.map(({ team, m }) => (
            <div key={team} className="vd-row">
              <button type="button" className="vd-team click text-button" onClick={() => onTeam && onTeam(team)}>{team}</button>
              <span className="chips">
                <button type="button" className="chip click" onClick={() => onOpen(m)}>{m.finished && m.result ? `${m.result[0]}-${m.result[1]}` : (m.markets?.marcador || "·")} · {m.home === team ? "vs " + m.away : "@ " + m.home}</button>
                <span className="dim" style={{ fontSize: ".72rem" }}>{m.finished ? "FT" : (countdown(m.kickoff) || fmtKick(m.kickoff))}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="sec-h" style={{ marginTop: 18 }}>
        <h2>Explora</h2>
      </div>
      <div className="quick-links">
        <button type="button" className="qlink" onClick={() => goto("partidos")}><Icon name="partidos" /><span>Partidos y mercados</span></button>
        <button type="button" className="qlink" onClick={() => goto("clasificacion")}><Icon name="clasificacion" /><span>Clasificación</span></button>
        <button type="button" className="qlink" onClick={() => goto("value")}><Icon name="value" /><span>Value bets</span></button>
        <button type="button" className="qlink" onClick={() => goto("quiniela")}><Icon name="quiniela" /><span>Quiniela</span></button>
      </div>
    </>
  );
}

/* ---------- Clasificación proyectada ---------- */
function Clasificacion({ matches, onTeam }) {
  const ligas = useMemo(() => leaguesIn(matches), [matches]);
  const [liga, setLiga] = useState(ligas[0] || "");
  const [mode, setMode] = useState("real"); // real | proy
  const proj = useMemo(() => projectedTable(matches, liga || ligas[0]), [matches, liga, ligas]);
  // Tabla REAL: ordenada por puntos reales y diferencia de goles real.
  const real = useMemo(
    () => [...proj].sort((a, b) => b.ptsReal - a.ptsReal || (b.gf - b.ga) - (a.gf - a.ga) || a.name.localeCompare(b.name)),
    [proj]
  );
  const table = mode === "real" ? real : proj;
  if (!table.length) return <div className="state">Sin datos de clasificación.</div>;
  const projPos = new Map(proj.map((t, i) => [t.name, i + 1]));
  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="seg-toggle">
            <button type="button" className={mode === "real" ? "on" : ""} aria-pressed={mode === "real"} onClick={() => setMode("real")}>Real</button>
            <button type="button" className={mode === "proy" ? "on" : ""} aria-pressed={mode === "proy"} onClick={() => setMode("proy")}>Proyección</button>
          </div>
          {ligas.length > 1 && <select aria-label="Competición de la clasificación" value={liga} onChange={(e) => setLiga(e.target.value)}>{ligas.map((l) => <option key={l} value={l}>{l}</option>)}</select>}
        </div>
        <p className="note" style={{ color: "var(--muted)" }}>
          {mode === "real"
            ? "Clasificación real por jornadas jugadas. La columna Proy = posición proyectada a fin de temporada por el modelo."
            : "Proyección a fin de temporada: puntos reales + esperados del modelo (3·P(gana)+1·P(empata))."}
        </p>
      </div>
      <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
        <table className="tbl-cls">
          <thead><tr><th>#</th><th className="tl">Equipo</th><th>PJ</th><th>G</th><th>E</th><th>P</th><th>GF</th><th>GC</th><th>DG</th><th>Pts</th><th>{mode === "real" ? "Proy" : "Real"}</th></tr></thead>
          <tbody>
            {table.map((t, i) => {
              const gd = t.gf - t.ga;
              return (
                <tr key={t.name} className={i < 4 ? "row-ucl" : i < 6 ? "row-eur" : i >= table.length - 3 ? "row-desc" : ""}>
                  <td>{i + 1}</td>
                  <td className="tl"><button type="button" className="cls-team click text-button" onClick={() => onTeam && onTeam(t.name)}><img className="crest sm" alt="" loading="lazy" src={crestFor(t.name, t.colors, t.crest)} onError={(e) => (e.target.src = crestFor(t.name, t.colors, null))} /><span className="tn">{t.name}</span></button></td>
                  <td>{t.pj}</td><td>{t.w}</td><td>{t.d}</td><td>{t.l}</td><td>{t.gf}</td><td>{t.ga}</td>
                  <td className={gd >= 0 ? "value-yes" : "value-no"}>{gd > 0 ? "+" : ""}{gd}</td>
                  <td><b>{mode === "real" ? t.ptsReal : t.ptsProy}</b></td>
                  <td className="dim">{mode === "real" ? projPos.get(t.name) : t.ptsReal}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="foot" style={{ marginTop: 8 }}>
        <span className="dot d-ucl" /> Champions · <span className="dot d-eur" /> Europa · <span className="dot d-desc" /> Descenso
        {mode === "real" ? " · Proy = posición proyectada a fin de temporada" : " · Real = puntos ya sumados"}
      </div>
    </>
  );
}

/* ---------- Mercados ---------- */
function Mercados({ matches, q, onOpen }) {
  const [liga, setLiga] = useState("");
  const [onlyVal, setOnlyVal] = useState(false);
  const ligas = useMemo(() => leaguesIn(matches), [matches]);
  // Al buscar, incluimos también los jugados (cualquiera con predicción);
  // navegando sin buscar, solo los próximos con predicción.
  const base = q.trim() ? matches.filter((m) => Array.isArray(m.probs)) : matches.filter(hasPrediction);
  const ms = base
    .filter((m) => !q || (m.home + " " + m.away + " " + m.league).toLowerCase().includes(q.toLowerCase()))
    .filter((m) => !liga || m.league === liga)
    .filter((m) => !onlyVal || bestValue(m));
  const sign = (m) => { const p = [m.probs[0], m.probs[1], m.probs[2]]; const i = p.indexOf(Math.max(...p)); return ["1", "X", "2"][i]; };
  return (
    <>
      <div className="controls">
        {ligas.length > 1 && (
          <select aria-label="Filtrar partidos por competición" value={liga} onChange={(e) => setLiga(e.target.value)}>
            <option value="">Todas las ligas</option>
            {ligas.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        )}
        <button type="button" className={"seg-toggle-btn" + (onlyVal ? " on" : "")} aria-pressed={onlyVal} onClick={() => setOnlyVal((v) => !v)}>◆ Solo value</button>
      </div>
      {!ms.length ? <div className="state">{q ? `No hay partidos para “${q}”.` : "No hay partidos con estos filtros."}</div> : (
      <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
      <table className="tbl-mk">
        <thead><tr><th className="tl">Partido</th><th>1X2</th><th>Marcador</th><th>O2.5</th><th>U2.5</th><th>BTTS</th><th>◆</th><th></th></tr></thead>
        <tbody>
          {ms.map((m) => {
            const o25 = m.markets?.over_2_5 ?? null;
            const val = bestValue(m);
            return (
              <tr key={m.id} className="click" role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(m); }} onClick={() => onOpen(m)}>
                <td className="tl"><div className="mk-team"><b>{m.home}</b> <span className="dim">vs</span> {m.away}<div className="mk-sub">{m.league} · J{m.matchday || ""} · {fmtKick(m.kickoff)}</div></div></td>
                <td><span className={"q-" + sign(m)} style={{ fontWeight: 800 }}>{sign(m)}</span></td>
                <td>{m.markets?.marcador || "—"}</td>
                <td>{o25 != null ? Math.round(o25 * 100) + "%" : "—"}</td>
                <td>{o25 != null ? Math.round((1 - o25) * 100) + "%" : "—"}</td>
                <td>{m.markets?.btts != null ? Math.round(m.markets.btts * 100) + "%" : "—"}</td>
                <td>{val ? <span className="value-yes" title={`Value ${val.selection}: +${(val.edge * 100).toFixed(1)}%`}>{val.selection} +{(val.edge * 100).toFixed(0)}%</span> : <span className="dim">—</span>}</td>
                <td className="dim">›</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
      )}
    </>
  );
}

/* ---------- Jugadores (fuente de pago pendiente) ---------- */
function Jugadores({ players, onPlayer }) {
  const ligas = players ? Object.keys(players) : [];
  const [liga, setLiga] = useState(ligas[0] || "");
  if (!players || !ligas.length) {
    return (
      <div className="card">
        <div className="lbl">Jugadores</div>
        <p className="note">⚠️ Aún sin datos de jugadores en el feed. El cron los obtiene de football-data.org (goleadores y asistencias); aparecerán tras la próxima actualización.</p>
      </div>
    );
  }
  const cur = players[liga] || players[ligas[0]];
  const rankings = cur.rankings || {};
  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="lbl" style={{ margin: 0 }}>Ranking de jugadores · {cur.label}</div>
          {ligas.length > 1 && <select aria-label="Competición del ranking de jugadores" value={liga} onChange={(e) => setLiga(e.target.value)}>{ligas.map((l) => <option key={l} value={l}>{players[l].label}</option>)}</select>}
        </div>
        <p className="note" style={{ color: "var(--muted)" }}>Fuente: Understat (goles, asistencias, remates, xG y tarjetas por jugador de LaLiga). Se actualiza con el scraper local. Segunda y faltas por jugador no disponibles gratis.</p>
      </div>
      <div className="players-grid">
        {Object.entries(rankings).map(([slug, rk]) => (
          <div className="card" key={slug} style={{ padding: "10px 12px" }}>
            <div className="lbl" style={{ marginTop: 4 }}>{rk.label}</div>
            <table className="tbl-mk">
              <tbody>
                {rk.players.slice(0, 10).map((p) => (
                  <tr key={p.rank} role="button" tabIndex={0} onClick={() => onPlayer?.(p)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onPlayer?.(p); }}>
                    <td style={{ width: 22, color: "var(--dim)" }}>{p.rank}</td>
                    <td className="tl"><b>{p.player}</b><div className="mk-sub">{p.team}</div></td>
                    <td style={{ textAlign: "right" }}><b className="value-yes">{p.value != null ? (Number.isInteger(p.value) ? p.value : p.value.toFixed(0)) : "—"}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </>
  );
}

/* ---------- Quiniela ---------- */
const Q_STOP = new Set(["cf", "fc", "cd", "ud", "sd", "rc", "cp", "club", "de", "la", "el", "los", "real"]);
const qNorm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9 ]/g, " ");
const qTokens = (s) => qNorm(s).split(/\s+/).filter((t) => t.length >= 3 && !Q_STOP.has(t));
const qTeamMatch = (a, b) => { const A = new Set(qTokens(a)); return qTokens(b).some((t) => A.has(t)); };
const qFindMatch = (local, visit, list) => list.find((m) => qTeamMatch(local, m.home) && qTeamMatch(visit, m.away));

function Quiniela({ matches, quiniela, tri, dob, setTri, setDob }) {
  const [copied, setCopied] = useState(false);
  const predicted = useMemo(() => matches.filter(hasPrediction), [matches]);
  const official = quiniela && Array.isArray(quiniela.partidos) && quiniela.partidos.length >= 14 ? quiniela : null;

  const items = official
    ? quiniela.partidos.slice(0, 15).map((p) => ({ local: p.local, visitante: p.visitante, m: qFindMatch(p.local, p.visitante, predicted) }))
    : predicted.slice(0, 15).map((m) => ({ local: m.home, visitante: m.away, m }));
  const ms = items.slice(0, 14);
  const pleno = items[14];

  const fc = ms.map((it) => {
    if (!it.m) return { it, pr: null, best: "1", ent: -1 };
    const pr = { 1: it.m.probs[0] / 100, X: it.m.probs[1] / 100, 2: it.m.probs[2] / 100 };
    const best = Object.keys(pr).reduce((a, b) => (pr[a] > pr[b] ? a : b));
    return { it, pr, best, ent: entropy(pr) };
  });
  const ranked = [...fc.keys()].filter((i) => fc[i].pr).sort((a, b) => fc[b].ent - fc[a].ent);
  const mult = {};
  ranked.slice(0, tri).forEach((i) => (mult[i] = ["1", "X", "2"]));
  let d = 0;
  for (const i of ranked) { if (d >= dob) break; if (mult[i]) continue; mult[i] = Object.keys(fc[i].pr).sort((a, b) => fc[i].pr[b] - fc[i].pr[a]).slice(0, 2); d++; }
  let cost = 1; fc.forEach((_, i) => (cost *= mult[i] ? mult[i].length : 1));
  let pAll = 1; fc.forEach((f, i) => { if (!f.pr) return; const sel = mult[i] || [f.best]; pAll *= sel.reduce((s, x) => s + f.pr[x], 0); });
  const nPred = fc.filter((f) => f.pr).length;
  const plenoScore = pleno?.m?.markets?.marcador?.split("-").map((n) => parseInt(n, 10));
  const plenoSigns = plenoScore ? [plenoSign(plenoScore[0]), plenoSign(plenoScore[1])] : null;

  const copy = async () => {
    const lines = fc.map((f, i) => { const sel = f.pr ? (mult[i] || [f.best]) : ["-"]; return `${i + 1}. ${f.it.local} - ${f.it.visitante}  →  ${sel.join("/")}`; });
    if (pleno) lines.push(`P15. ${pleno.local} - ${pleno.visitante}  →  ${plenoSigns ? plenoSigns.join(" - ") : "-"}`);
    lines.push(`Coste: ${cost} columnas`);
    try { await navigator.clipboard.writeText(lines.join("\n")); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* ignore */ }
  };

  return (
    <>
      <div className="card">
        {official
          ? <div className="lbl">🎫 Quiniela oficial{quiniela.jornada ? ` · Jornada ${quiniela.jornada}` : ""} con los signos del modelo</div>
          : <div className="lbl">Quiniela del modelo (15 partidos con predicción). Añade <code>football/data/quiniela.json</code> para usar la combinación oficial de LAE.</div>}
        <div className="row">
          <div className="grow"><div className="lbl">Triples</div><input aria-label="Número de triples" type="range" min="0" max="8" value={tri} className="grow" onChange={(e) => setTri(+e.target.value)} /> {tri}</div>
          <div className="grow"><div className="lbl">Dobles</div><input aria-label="Número de dobles" type="range" min="0" max="8" value={dob} className="grow" onChange={(e) => setDob(+e.target.value)} /> {dob}</div>
        </div>
        <div className="chips">
          {nPred < ms.length && <span className="chip">{ms.length - nPred} sin predicción del modelo</span>}
          <span className="chip">Coste <b>{cost}</b> columnas</span>
          <span className="chip">Prob. pleno <b>{(pAll * 100).toFixed(3)}%</b></span>
          <button type="button" className="mini" onClick={copy}>{copied ? "✓ Copiado" : "📋 Copiar quiniela"}</button>
        </div>
      </div>
      {fc.map((f, i) => {
        const sel = f.pr ? (mult[i] || [f.best]) : null;
        return (
          <div className="card" key={i} style={{ padding: "10px 14px" }}>
            <div className="ctop"><span>{i + 1}{f.it.m ? ` · ${f.it.m.league} J${f.it.m.matchday || ""}` : ""}</span><span>{f.it.m ? fmtKick(f.it.m.kickoff) : ""}</span></div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="tn" style={{ flex: 1 }}>{f.it.local} <span style={{ color: "var(--dim)" }}>vs</span> {f.it.visitante}</div>
              <div className="q-sign">{sel ? sel.map((s) => <span key={s} className={"q-" + s}>{s}</span>) : <span className="dim">sin pred.</span>}</div>
            </div>
            {f.pr && <div className="chips"><span className="chip">1 <b>{f.it.m.probs[0]}%</b></span><span className="chip">X <b>{f.it.m.probs[1]}%</b></span><span className="chip">2 <b>{f.it.m.probs[2]}%</b></span></div>}
          </div>
        );
      })}
      {pleno && (
        <div className="card pleno" style={{ padding: "12px 14px" }}>
          <div className="ctop"><span>🏆 Pleno al 15{pleno.m ? ` · ${pleno.m.league} J${pleno.m.matchday || ""}` : ""}</span><span>{pleno.m ? fmtKick(pleno.m.kickoff) : ""}</span></div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="tn" style={{ flex: 1 }}>{pleno.local} <span style={{ color: "var(--dim)" }}>vs</span> {pleno.visitante}</div>
            <div className="q-sign pleno-sc">{plenoSigns ? <>{plenoSigns[0]} <span style={{ color: "var(--dim)" }}>-</span> {plenoSigns[1]}</> : <span className="dim">sin pred.</span>}</div>
          </div>
          {pleno.m?.markets?.marcador && <div className="chips"><span className="chip">Marcador previsto <b>{pleno.m.markets.marcador}</b></span></div>}
        </div>
      )}
    </>
  );
}

/* ---------- Value bets ---------- */
function ValueBets({ matches, bank, setBank, globalValue }) {
  const ms = matches.filter(hasPrediction).filter((m) => !m.finished);
  const [odds, setOdds] = useState({});
  const bankN = Number(bank) || 1000;
  let rows = ms.map((m, i) => {
    const pr = [m.probs[0] / 100, m.probs[1] / 100, m.probs[2] / 100];
    const blocked = m.recommendation?.decision === "no_pick";
    const reasons = m.recommendation?.reasons || [];
    // Cuotas reales de mercado (media de casas, co.uk) cargadas del feed;
    // el usuario puede sobrescribirlas escribiendo en el input.
    const feedO = m.odds?.["1x2"]?.odds || null;
    const o = ["1", "X", "2"].map((s) => {
      const v = odds[i + s];
      return Number(v != null && v !== "" ? v : (feedO ? feedO[s] : NaN));
    });
    const haveAll = o.every((x) => x > 1);
    const fair = haveAll ? fairProbs(o) : null;
    const vig = haveAll ? overround(o) : null;
    let best = null;
    if (!blocked) {
      o.forEach((oo, j) => { if (oo > 1) { const e = pr[j] * oo - 1; if (!best || e > best.e) best = { j, s: ["1", "X", "2"][j], o: oo, e }; } });
    }
    const stake = !blocked && best ? Math.min(bankN * kelly(pr[best.j], best.o) * 0.25, bankN * 0.05) : 0;
    return { m, i, pr, o, feedO, fair, vig, best, stake, blocked, reasons, haveAll };
  });
  rows = rows.sort((a, b) => Number(a.blocked) - Number(b.blocked) || (b.best?.e ?? -9) - (a.best?.e ?? -9));
  const nValue = rows.filter((r) => !r.blocked && r.best && r.best.e > 0.02).length;
  const nWithOdds = rows.filter((r) => r.haveAll).length;
  return (
    <>
      <GlobalValuePanel rows={globalValue} />
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div><div className="lbl">Bankroll (€)</div><input aria-label="Bankroll para calcular stakes" type="number" value={bank} style={{ width: 130 }} onChange={(e) => setBank(e.target.value)} /></div>
          <div className="chips">
            <span className="chip">Con cuota <b>{nWithOdds}</b></span>
            <span className="chip">Value elegible (edge&gt;2%) <b className={nValue ? "value-yes" : ""}>{nValue}</b></span>
          </div>
        </div>
        <p className="note" style={{ color: "var(--muted)" }}>Cuotas de mercado (media de casas, co.uk) cargadas automáticamente; puedes sobrescribirlas. Se quita el margen y se compara con el modelo. Solo los partidos elegibles calculan edge y stake = Kelly ¼ (máx. 5%).</p>
      </div>
      {!ms.length && <div className="state">No hay partidos con predicción.</div>}
      {rows.map((r) => (
        <div className="card" key={r.i} data-recommendation={r.blocked ? "no_pick" : "eligible"}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="tn" style={{ flex: 1 }}>{r.m.home} vs {r.m.away}</div>
            <div className="chips">{["1", "X", "2"].map((s, j) => <span key={s} className="chip">{s} <b>{r.m.probs[j]}%</b>{r.fair ? <span className="dim"> / {(r.fair[j] * 100).toFixed(0)}%</span> : null}</span>)}</div>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            {["1", "X", "2"].map((s, j) => {
              const e = !r.blocked && r.o[j] > 1 ? r.pr[j] * r.o[j] - 1 : null;
              return (
                <div key={s} className="odds-in">
                  <input type="number" step="0.01" placeholder={"Cuota " + s} style={{ width: 92 }} value={odds[r.i + s] ?? (r.feedO ? r.feedO[s] : "")} onChange={(ev) => setOdds({ ...odds, [r.i + s]: ev.target.value })} />
                  {e != null && <span className={"edge " + (e > 0.02 ? "value-yes" : "value-no")}>{e > 0 ? "+" : ""}{(e * 100).toFixed(1)}%</span>}
                </div>
              );
            })}
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            {r.vig != null && <span className="chip">Margen casa <b>{(r.vig * 100).toFixed(1)}%</b></span>}
            {r.blocked ? <span className="value-no">Sin apuesta recomendada{r.reasons.length ? ` · ${r.reasons.join(" · ")}` : ""}</span>
              : r.best && r.best.e > 0.02 ? <span className="pill y">VALUE {r.best.s}: edge {(r.best.e * 100).toFixed(1)}% · apostar {r.stake.toFixed(2)}€</span>
              : r.best ? <span className="value-no">Sin value (mejor {r.best.s}: {(r.best.e * 100).toFixed(1)}%)</span> : null}
          </div>
        </div>
      ))}
    </>
  );
}

/* ---------- Datos y modelos ---------- */
/* Diagrama de fiabilidad: prob. predicha (x) vs frecuencia real (y). */
function CalibDiagram({ table, w = 300, h = 300 }) {
  const pad = 34;
  const iw = w - pad * 2, ih = h - pad * 2;
  const X = (p) => pad + p * iw;
  const Y = (p) => pad + (1 - p) * ih;
  const maxN = Math.max(1, ...table.map((b) => b.n));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="calib-svg" role="img" aria-label="Diagrama de calibración">
      <rect x={pad} y={pad} width={iw} height={ih} className="calib-box" />
      {[0.25, 0.5, 0.75].map((g) => (
        <g key={g}>
          <line x1={X(g)} y1={pad} x2={X(g)} y2={pad + ih} className="calib-grid" />
          <line x1={pad} y1={Y(g)} x2={pad + iw} y2={Y(g)} className="calib-grid" />
        </g>
      ))}
      <line x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(1)} className="calib-diag" />
      {table.map((b) => (
        <circle key={b.bin} cx={X(b.avg_pred)} cy={Y(b.obs_freq)} r={4 + 8 * (b.n / maxN)} className="calib-dot">
          <title>{`${b.bin} · n=${b.n} · pred ${(b.avg_pred * 100).toFixed(0)}% → real ${(b.obs_freq * 100).toFixed(0)}%`}</title>
        </circle>
      ))}
      <text x={pad + iw / 2} y={h - 6} className="calib-axis" textAnchor="middle">prob. predicha →</text>
      <text x={12} y={pad + ih / 2} className="calib-axis" textAnchor="middle" transform={`rotate(-90 12 ${pad + ih / 2})`}>frecuencia real →</text>
    </svg>
  );
}

const METRIC_INFO = [
  ["rps", "RPS", "Ranked Probability Score (menor = mejor)"],
  ["brier", "Brier", "Error cuadrático (menor = mejor)"],
  ["log_loss", "LogLoss", "Pérdida logarítmica (menor = mejor)"],
  ["accuracy", "Acierto", "% de signos acertados (mayor = mejor)"],
];
const PRED_LABEL = { baseline: "Base (tasas)", elo: "Elo", dixon_coles: "Dixon-Coles", ensemble: "Ensemble calibrado", residual: "Residual challenger" };

function ModelReport({ model }) {
  const ligas = model ? Object.keys(model) : [];
  const [liga, setLiga] = useState(ligas[0]);
  if (!model || !ligas.length) return null;
  const rep = model[liga] || model[ligas[0]];
  const preds = rep.predictors || {};
  const names = Object.keys(preds);
  const ensembleActive = Boolean(rep.ensemble?.accepted);
  const residualActive = Boolean(rep.residual?.accepted);
  // Mejor (menor) por métrica descendente-mala; para accuracy, mayor es mejor.
  const best = {};
  for (const [key] of METRIC_INFO) {
    const vals = names.map((n) => preds[n][key]).filter((v) => v != null);
    if (!vals.length) continue;
    best[key] = key === "accuracy" ? Math.max(...vals) : Math.min(...vals);
  }
  const calib1 = (rep.calibration && rep.calibration["1"]) || [];
  return (
    <>
      <div className="card">
        <div className="row-between">
          <div className="lbl">Rendimiento del modelo (walk-forward)</div>
          {ligas.length > 1 && (
            <select aria-label="Competición del rendimiento del modelo" value={liga} onChange={(e) => setLiga(e.target.value)}>
              {ligas.map((l) => <option key={l} value={l}>{model[l].label}</option>)}
            </select>
          )}
        </div>
        <div className="mut" style={{ margin: "4px 0 10px" }}>
          Validación honesta: se entrena solo con el pasado y se predice cada jornada.
          {" "}<b>{rep.n_predicciones}</b> predicciones evaluadas{rep.evaluation_season ? ` en la temporada ${rep.evaluation_season}/${String(rep.evaluation_season + 1).slice(-2)}` : " esta temporada"}.
        </div>
        <div className="tbl-wrap">
          <table className="tbl-mk metrics-tbl">
            <thead>
              <tr>
                <th className="tl">Modelo</th>
                {METRIC_INFO.map(([k, lbl, tip]) => <th key={k} title={tip}>{lbl}</th>)}
              </tr>
            </thead>
            <tbody>
              {names.map((n) => (
                <tr key={n} className={(n === "ensemble" && ensembleActive) || (n === "residual" && residualActive) ? "row-live" : ""}>
                  <td className="tl">{PRED_LABEL[n] || n}{["ensemble", "residual"].includes(n) && <span className="tag-live">{(n === "ensemble" ? ensembleActive : residualActive) ? "EN USO" : "CANDIDATO"}</span>}</td>
                  {METRIC_INFO.map(([k]) => {
                    const v = preds[n][k];
                    const isBest = v != null && best[k] != null && v === best[k];
                    return <td key={k} className={isBest ? "cell-best" : ""}>{v == null ? "—" : (k === "accuracy" ? (v * 100).toFixed(0) + "%" : v.toFixed(3))}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rep.residual && <div className="mut" style={{ marginTop: 8 }}>
          Residual: <b>{rep.residual.accepted ? "gate superado" : "bloqueado"}</b> · {rep.residual.status === "blocked_insufficient_sample" ? `${rep.residual.n}/${rep.residual.minimum_required} partidos mínimos` : `${rep.residual.n_validation || 0} partidos de validación temporal`} · exige mejorar log loss y RPS frente a Dixon-Coles y Elo.
        </div>}
        <div className="mut" style={{ marginTop: 8 }}>Verde = mejor valor por columna. RPS es el estándar en fútbol; premia acercarse al resultado ordenado 1-X-2.</div>
      </div>
      {calib1.length > 0 && (
        <div className="card">
          <div className="lbl">Calibración (victoria local)</div>
          <div className="calib-wrap">
            <CalibDiagram table={calib1} />
            <div className="calib-legend">
              <p>Cada punto es un tramo de probabilidad. Si el modelo está bien calibrado, los puntos caen sobre la diagonal: cuando dice “45%”, acierta el 45% de las veces.</p>
              <p>El tamaño del punto refleja cuántos partidos hay en ese tramo.</p>
              <table className="tbl-mk calib-tbl">
                <thead><tr><th className="tl">Tramo</th><th>N</th><th>Predicha</th><th>Real</th></tr></thead>
                <tbody>
                  {calib1.map((b) => (
                    <tr key={b.bin}><td className="tl">{b.bin}</td><td>{b.n}</td><td>{(b.avg_pred * 100).toFixed(0)}%</td><td>{(b.obs_freq * 100).toFixed(0)}%</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/* Precisión histórica: acierto 1X2 y error medio por métrica (bucle de mejora). */
function AccuracyPanel({ acc }) {
  if (!acc || !acc.n_partidos) return null;
  const metrics = acc.metrics || [];
  return (
    <div className="card">
      <div className="lbl">Precisión histórica (predicho vs real)</div>
      <div className="mut" style={{ margin: "2px 0 12px" }}>
        Sobre <b>{acc.n_partidos}</b> snapshots guardados antes del saque inicial. El error medio por métrica dice
        en qué acierta el modelo y dónde se desvía — nunca se recalcula con el resultado conocido.
      </div>
      <div className="stat-tiles" style={{ marginBottom: 6 }}>
        <div className="stat">
          <span className="stat-k">Acierto 1X2</span>
          <b className="stat-v accent">{acc.pct_1x2 != null ? acc.pct_1x2 + "%" : "—"}</b>
          <span className="stat-s">{acc.aciertos_1x2}/{acc.n_1x2} partidos</span>
        </div>
        {metrics.slice(0, 3).map((mt) => (
          <div className="stat" key={mt.key}>
            <span className="stat-k">{mt.label} · error medio</span>
            <b className="stat-v">±{mt.mae}</b>
            <span className="stat-s">{mt.sesgo > 0 ? "se queda corto" : mt.sesgo < 0 ? "se pasa" : "centrado"} ({mt.sesgo > 0 ? "+" : ""}{mt.sesgo})</span>
          </div>
        ))}
      </div>
      {metrics.length > 0 && (
        <div className="tbl-wrap">
          <table className="tbl-mk">
            <thead><tr><th className="tl">Métrica</th><th>Error medio (MAE)</th><th>Sesgo</th><th>N</th></tr></thead>
            <tbody>
              {metrics.map((mt) => (
                <tr key={mt.key}>
                  <td className="tl">{mt.label}</td>
                  <td>±{mt.mae}</td>
                  <td className={mt.sesgo > 0 ? "value-yes" : mt.sesgo < 0 ? "value-no" : "dim"}>{mt.sesgo > 0 ? "+" : ""}{mt.sesgo}</td>
                  <td>{mt.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mut" style={{ marginTop: 8 }}>Sesgo + = el modelo predice de menos (hubo más en la realidad); − = predice de más.</div>
    </div>
  );
}

function Datos({ data }) {
  const ds = data.data_sources || {};
  const ageH = feedAgeHours(data);
  const perf = data.performance || { overall: { n: 0 }, by_market: [], by_league: [], weak_segments: [] };
  const audit = data.content_audit;
  const usage = data.ai_usage;
  const metricRows = [
    ["Mercado", perf?.by_market], ["Competición", perf?.by_league],
  ];
  return (
    <>
      <div className="card">
        <div className="row-between"><div className="lbl">Control de completitud</div><span className={"pill " + (audit?.status === "ok" ? "y" : "")}>{audit?.status === "ok" ? "completo" : "revisar"}</span></div>
        <div className="chips">
          <span className="chip">Partidos del día <b>{audit?.matches_today ?? 0}</b></span>
          <span className="chip">Completos <b>{audit?.complete ?? 0}</b></span>
          <span className="chip">Reintentos selectivos <b>{audit?.selective_retries ?? 0}</b></span>
          <span className="chip">Onces oficiales nuevos <b>{audit?.official_lineup_updates ?? 0}</b></span>
          <span className="chip">Clima actualizado <b>{audit?.weather_updates ?? 0}</b></span>
          {usage && <span className="chip">IA diaria <b>{usage.requests}/{usage.budget}</b></span>}
        </div>
        {(audit?.incomplete || []).map((item) => <div className="note value-no" key={item.id}>{item.partido}: falta {item.missing.join(", ")}</div>)}
      </div>
      <div className="card">
        <div className="lbl">Rendimiento real del modelo</div>
        <div className="chips">
          <span className="chip">Muestra <b>{perf.overall?.n ?? 0}</b></span>
          <span className="chip">Acierto <b>{perf.overall?.hit_rate ?? "—"}%</b></span>
          <span className="chip">ROI <b className={(perf.overall?.roi ?? 0) >= 0 ? "value-yes" : "value-no"}>{perf.overall?.roi ?? "—"}%</b></span>
          {perf.initial_vs_10_15 && <span className="chip">10:15 vs inicial <b className={perf.initial_vs_10_15.improved ? "value-yes" : "value-no"}>{perf.initial_vs_10_15.delta > 0 ? "+" : ""}{perf.initial_vs_10_15.delta} Brier</b></span>}
        </div>
        {metricRows.map(([title, rows]) => (rows || []).length > 0 && <div key={title} className="tbl-wrap" style={{ marginTop: 10 }}>
          <div className="mut">Por {title.toLowerCase()}</div>
          <table className="tbl-mk"><thead><tr><th className="tl">{title}</th><th>N</th><th>Acierto</th><th>ROI</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.label}><td className="tl">{row.label}</td><td>{row.n}</td><td>{row.hit_rate ?? "—"}%</td><td className={(row.roi ?? 0) >= 0 ? "value-yes" : "value-no"}>{row.roi ?? "—"}%</td></tr>)}</tbody>
          </table>
        </div>)}
        {(perf.weak_segments || []).length > 0 && <div className="note value-no">Segmentos a vigilar: {perf.weak_segments.map((row) => `${row.segment} (${row.roi}% ROI, n=${row.n})`).join(" · ")}</div>}
        {perf.overall?.n ? <div className="mut" style={{ marginTop: 8 }}>{perf.method}</div> : <div className="note" style={{ marginTop: 8 }}>Aún sin muestra válida: el panel se activará cuando terminen partidos que ya tengan snapshot prepartido, sin reconstruir predicciones a posteriori.</div>}
      </div>
      <ProbabilityQualityPanel quality={perf.probability_quality} />
      <HistoricalQualityPanel seeds={data.historical_seed} />
      <AccuracyPanel acc={data.accuracy} />
      <AccuracyMatchDetails rows={data.accuracy?.matches} />
      <ModelReport model={data.model} />
      <div className="card">
        <div className="lbl">Motor y estado</div>
        <div className="chips">
          <span className="chip">Motor <b>{data.engine === "residual" ? "Residual validado" : data.engine === "ensemble" ? "Dixon-Coles + Elo calibrado" : (data.engine || "Dixon-Coles")}</b></span>
          <span className="chip">Schema <b>v{data.schema_version}</b></span>
          <span className="chip">Temporada <b>{data.season}</b></span>
          <span className="chip">Generado <b>{new Date(data.generated_at).toLocaleString("es-ES")}</b></span>
          {ageH != null && <span className={"chip"}>Antigüedad <b className={isStale(data) ? "value-no" : "value-yes"}>{Math.round(ageH)} h</b></span>}
          <span className="chip">Calidad feed <b className={data.feed_quality?.valid ? "value-yes" : "value-no"}>{Math.round((data.feed_quality?.score ?? 0) * 100)}%</b></span>
        </div>
        {(data.feed_quality?.issues || []).length > 0 && <div className="note value-no">Incidencias: {data.feed_quality.issues.join(" · ")}</div>}
      </div>
      <div className="card">
        <div className="lbl">Fuentes de datos</div>
        <table className="tbl-mk">
          <thead><tr><th className="tl">Tipo</th><th className="tl">Fuente</th></tr></thead>
          <tbody>{Object.entries(ds).map(([k, v]) => <tr key={k}><td className="tl" style={{ textTransform: "capitalize" }}>{k}</td><td className="tl">{v}</td></tr>)}</tbody>
        </table>
      </div>
      <div className="card">
        <div className="lbl">Modelos activos</div>
        <ul className="mdl">
          <li><b>Ensemble Dixon-Coles + Elo</b> con pesos y temperatura aprendidos sobre predicciones walk-forward.</li>
          <li><b>Residual challenger</b>: corrige logits con el desacuerdo DC/Elo y solo entra en producción si mejora a ambos en una cola temporal.</li>
          <li><b>Simulador de estados</b>: explora calor, marcador, fatiga y expulsiones por tramos de cinco minutos; se muestra como escenario y no contamina el 1X2.</li>
          <li><b>Pseudo-xG gratuito</b> a partir de remates y tiros a puerta, regularizado y limitado para evitar saltos.</li>
          <li><b>Poisson / Negative Binomial</b> según la dispersión real de cada mercado de córners, tarjetas y remates.</li>
          <li><b>Snapshots 00:15 y 10:15</b>: cada predicción queda congelada antes del partido para medirla sin leakage.</li>
          <li><b>Calibración con el mercado</b>: con pocas jornadas jugadas la probabilidad se mezcla con la del mercado (sin margen) y va pesando más el modelo según avanza la liga. Evita edges inflados.</li>
          <li><b>Cara a cara (h2h)</b>: enfrentamientos directos pasados en el detalle del partido.</li>
          <li><b>Perfil ataque–defensa</b>: splits reales casa/fuera de volumen, concesión, córners, faltas y tarjetas; declara tamaño de muestra.</li>
          <li><b>Clima del estadio</b>: Open-Meteo cuantifica un ajuste conservador de xG, remates, faltas y tarjetas; el 1X2 queda intacto hasta validación histórica.</li>
          <li><b>Abstención</b>: bloquea el pick si la confianza, la completitud o el acuerdo entre modelos no alcanzan el mínimo.</li>
          <li><b>Value</b>: edge = prob·cuota − 1 (con la prob. calibrada), staking con Kelly fraccionado.</li>
        </ul>
      </div>
      <div className="foot">{data.disclaimer}</div>
    </>
  );
}

/* ---------- Mi cartera: registro de apuestas, ROI y bankroll ---------- */
const LS_BETS = "fe_bets_v1";
const LS_BANK0 = "fe_bank0_v1";
const loadLS = (k, def) => { try { const v = localStorage.getItem(k); return v == null ? def : JSON.parse(v); } catch { return def; } };
const saveLS = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } };

function Sparkline({ points, w = 260, h = 56 }) {
  if (points.length < 2) return <div className="spark-empty">Registra apuestas para ver tu evolución</div>;
  const min = Math.min(0, ...points), max = Math.max(0, ...points);
  const rng = max - min || 1;
  const step = w / (points.length - 1);
  const y = (v) => h - 6 - ((v - min) / rng) * (h - 12);
  const d = points.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" width="100%" height={h}>
      <line x1="0" y1={y(0)} x2={w} y2={y(0)} stroke="var(--line)" strokeDasharray="3 3" />
      <path d={d} fill="none" stroke={last >= 0 ? "var(--green)" : "var(--red)"} strokeWidth="2" />
    </svg>
  );
}

function Cartera({ matches }) {
  const [bets, setBets] = useState(() => loadLS(LS_BETS, []));
  const [bank0, setBank0] = useState(() => loadLS(LS_BANK0, 1000));
  const [f, setF] = useState({ match: "", sel: "1", odds: "", stake: "" });
  const [message, setMessage] = useState("");
  useEffect(() => saveLS(LS_BETS, bets), [bets]);
  useEffect(() => saveLS(LS_BANK0, bank0), [bank0]);

  const suggestions = useMemo(() => matches.filter(hasPrediction).slice(0, 200).map((m) => `${m.home} - ${m.away}`), [matches]);

  const pl = (b) => b.result === "won" ? b.stake * (b.odds - 1) : b.result === "lost" ? -b.stake : 0;
  const settled = bets.filter((b) => b.result !== "open");
  const staked = settled.reduce((s, b) => s + b.stake, 0);
  const profit = settled.reduce((s, b) => s + pl(b), 0);
  const roi = staked ? (profit / staked) * 100 : 0;
  const wins = settled.filter((b) => b.result === "won").length;
  const hit = settled.length ? (wins / settled.length) * 100 : 0;
  const bank = Number(bank0) + profit;
  const curve = useMemo(() => {
    const chrono = bets.filter((b) => b.result !== "open").slice().reverse();
    const val = (b) => b.result === "won" ? b.stake * (b.odds - 1) : b.result === "lost" ? -b.stake : 0;
    return chrono.map((_, i) => chrono.slice(0, i + 1).reduce((s, b) => s + val(b), 0));
  }, [bets]);

  const add = () => {
    const odds = Number(f.odds), stake = Number(f.stake);
    if (!(odds > 1) || !(stake > 0) || !f.match.trim()) {
      setMessage("Completa partido, cuota mayor que 1 y stake positivo.");
      return;
    }
    const linked = matches.find((match) => `${match.home} - ${match.away}` === f.match.trim());
    setBets([{ id: Date.now(), date: new Date().toISOString().slice(0, 10), match: f.match.trim(), matchId: linked?.id || null, sel: f.sel, odds, stake, result: "open" }, ...bets]);
    setF({ match: "", sel: "1", odds: "", stake: "" });
    setMessage("Apuesta añadida.");
  };
  const settle = (id, result) => setBets(bets.map((b) => b.id === id ? { ...b, result } : b));
  const del = (id) => {
    if (window.confirm("¿Eliminar esta apuesta?")) setBets(bets.filter((b) => b.id !== id));
  };

  return (
    <>
      <div className="stat-tiles">
        <div className="stat"><span className="stat-k">Bankroll</span><b className="stat-v">{bank.toFixed(0)}€</b><span className="stat-s">inicio {Number(bank0).toFixed(0)}€</span></div>
        <div className="stat"><span className="stat-k">Beneficio</span><b className={"stat-v " + (profit >= 0 ? "accent" : "")} style={profit < 0 ? { color: "var(--red)" } : null}>{profit >= 0 ? "+" : ""}{profit.toFixed(2)}€</b><span className="stat-s">{settled.length} apuestas cerradas</span></div>
        <div className="stat"><span className="stat-k">ROI / Yield</span><b className="stat-v" style={{ color: roi >= 0 ? "var(--green)" : "var(--red)" }}>{roi >= 0 ? "+" : ""}{roi.toFixed(1)}%</b><span className="stat-s">{staked.toFixed(0)}€ apostados</span></div>
        <div className="stat"><span className="stat-k">Acierto</span><b className="stat-v">{hit.toFixed(0)}%</b><span className="stat-s">{wins}/{settled.length} ganadas</span></div>
      </div>

      <ClvPanel bets={bets} matches={matches} />

      <div className="card">
        <div className="lbl">Evolución del beneficio</div>
        <Sparkline points={curve} />
      </div>

      <div className="card">
        <div className="lbl">Registrar apuesta</div>
        <div className="row">
          <input className="grow" list="fe-matches" placeholder="Partido (o texto libre)" value={f.match} onChange={(e) => setF({ ...f, match: e.target.value })} />
          <datalist id="fe-matches">{suggestions.map((s) => <option key={s} value={s} />)}</datalist>
          <select aria-label="Selección de la apuesta" value={f.sel} onChange={(e) => setF({ ...f, sel: e.target.value })}>
            <option value="1">1</option><option value="X">X</option><option value="2">2</option>
            <option value="Over">Over</option><option value="Under">Under</option><option value="BTTS">BTTS</option><option value="Otro">Otro</option>
          </select>
          <input type="number" step="0.01" placeholder="Cuota" style={{ width: 90 }} value={f.odds} onChange={(e) => setF({ ...f, odds: e.target.value })} />
          <input type="number" step="1" placeholder="Stake €" style={{ width: 90 }} value={f.stake} onChange={(e) => setF({ ...f, stake: e.target.value })} />
          <button type="button" className="add-btn" onClick={add}>Añadir</button>
        </div>
        {message && <div className="inline-status" role="status">{message}</div>}
        <div className="row" style={{ marginTop: 8 }}>
          <span className="lbl" style={{ margin: 0 }}>Bankroll inicial</span>
          <input aria-label="Bankroll inicial de la cartera" type="number" style={{ width: 110 }} value={bank0} onChange={(e) => setBank0(e.target.value)} />
        </div>
      </div>

      {bets.length === 0 ? <div className="state">Aún no has registrado apuestas.</div> : (
        <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
          <table className="tbl-mk">
            <thead><tr><th className="tl">Fecha · Partido</th><th>Sel</th><th>Cuota</th><th>Stake</th><th>P/L</th><th>Estado</th><th></th></tr></thead>
            <tbody>
              {bets.map((b) => (
                <tr key={b.id}>
                  <td className="tl"><b>{b.match}</b><div className="mk-sub">{b.date}</div></td>
                  <td><span className={"q-" + (b.sel === "1" ? "1" : b.sel === "2" ? "2" : "X")}>{b.sel}</span></td>
                  <td>{b.odds.toFixed(2)}</td><td>{b.stake}€</td>
                  <td className={pl(b) > 0 ? "value-yes" : pl(b) < 0 ? "value-no" : "dim"}>{b.result === "open" ? "—" : `${pl(b) >= 0 ? "+" : ""}${pl(b).toFixed(2)}€`}</td>
                  <td>
                    {b.result === "open" ? (
                      <span className="settle">
                        <button type="button" className="s-won" onClick={() => settle(b.id, "won")} aria-label={`Marcar ${b.match} como ganada`}>✓</button>
                        <button type="button" className="s-lost" onClick={() => settle(b.id, "lost")} aria-label={`Marcar ${b.match} como perdida`}>✗</button>
                        <button type="button" className="s-void" onClick={() => settle(b.id, "void")} aria-label={`Marcar ${b.match} como nula`}>N</button>
                      </span>
                    ) : <span className={"pill " + (b.result === "won" ? "y" : "")}>{b.result === "won" ? "Ganada" : b.result === "lost" ? "Perdida" : "Nula"}</span>}
                  </td>
                  <td><button type="button" className="s-del" onClick={() => del(b.id)} aria-label={`Eliminar apuesta ${b.match}`}>🗑</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/* ---------- Página de equipo ---------- */
const TEAM_STATS = { shots: "Remates", sot: "Tiros a puerta", corners: "Córners", fouls: "Faltas", yellows: "Amarillas" };
function TeamRec({ r, label }) {
  return (
    <div className="card" style={{ flex: 1, minWidth: 150 }}>
      <div className="lbl">{label}</div>
      <div className="chips">
        <span className="chip">PJ <b>{r.pj}</b></span>
        <span className="chip">{r.w}-{r.d}-{r.l}</span>
        <span className="chip">GF/GC <b>{r.gf}-{r.ga}</b></span>
        <span className="chip">Pts <b>{r.pts}</b></span>
      </div>
    </div>
  );
}
function TeamPage({ team, matches, players, onBack, onOpen, onPlayer, isFav, onFav }) {
  const p = useMemo(() => teamProfile(matches, team), [matches, team]);
  const squad = useMemo(() => teamSquad(players, team), [players, team]);
  return (
    <div>
      <button type="button" className="back" onClick={onBack}>← Volver</button>
      <div className="card">
        <div className="row" style={{ alignItems: "center", gap: 12 }}>
          <img className="crest" alt="" src={crestFor(p.name, p.colors, p.crest)} onError={(e) => (e.target.src = crestFor(p.name, p.colors, null))} />
          <div style={{ flex: 1 }}><div className="tn" style={{ fontSize: 20, fontWeight: 800 }}>{p.name}</div><div className="kick">{p.league}</div></div>
          <button type="button" className={"fav-btn" + (isFav ? " on" : "")} onClick={() => onFav && onFav(p.name)} aria-label={isFav ? `Quitar ${p.name} de favoritos` : `Añadir ${p.name} a favoritos`} title={isFav ? "Quitar de favoritos" : "Añadir a favoritos"}>{isFav ? "★" : "☆"}</button>
        </div>
        {p.form.length > 0 && (
          <div className="chips" style={{ marginTop: 10 }}>
            <span className="lbl" style={{ margin: 0 }}>Forma</span>
            {p.form.map((f, i) => <span key={i} className={"pill " + (f === "W" ? "y" : f === "L" ? "" : "")} style={f === "L" ? { background: "var(--red)", color: "#fff" } : f === "D" ? { opacity: .6 } : null}>{f === "W" ? "V" : f === "L" ? "D" : "E"}</span>)}
          </div>
        )}
      </div>
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <TeamRec r={p.overall} label="Total" />
        <TeamRec r={p.home} label="Local" />
        <TeamRec r={p.away} label="Visitante" />
      </div>
      {Object.keys(p.tendencies).length > 0 && (
        <div className="card">
          <div className="lbl">Tendencias por partido (media real)</div>
          <table>
            <thead><tr><th>Métrica</th><th>A favor</th><th>En contra</th></tr></thead>
            <tbody>
              {Object.entries(TEAM_STATS).filter(([k]) => p.tendencies[k]).map(([k, lab]) => (
                <tr key={k}><td>{lab}</td><td>{p.tendencies[k].for}</td><td>{p.tendencies[k].against}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {squad.length > 0 && (
        <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
          <div className="lbl" style={{ padding: "6px 6px 0" }}>Plantilla · {squad.length} jugadores <span className="dim">(Understat)</span></div>
          <table className="tbl-mk">
            <thead><tr><th className="tl">Jugador</th><th>Pos</th><th>G</th><th>A</th><th>Rem</th><th>xG</th><th>🟨</th></tr></thead>
            <tbody>
              {squad.map((s, i) => (
                <tr key={i} className="team-player-row" role="button" tabIndex={0} onClick={() => onPlayer?.(s)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onPlayer?.(s); }}>
                  <td className="tl"><b>{s.player}</b></td>
                  <td className="dim">{s.pos}</td>
                  <td>{s.goals || ""}</td>
                  <td>{s.assists || ""}</td>
                  <td>{s.shots || ""}</td>
                  <td className="dim">{s.xg || ""}</td>
                  <td>{s.yc || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
        <div className="lbl" style={{ padding: "6px 6px 0" }}>Partidos</div>
        <table className="tbl-mk">
          <tbody>
            {p.fixtures.map((m) => (
              <tr key={m.id} className="click" role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(m); }} onClick={() => onOpen(m)}>
                <td className="tl"><div className="mk-team"><b>{m.home}</b> <span className="dim">vs</span> {m.away}<div className="mk-sub">{m.league} · {fmtKick(m.kickoff)}</div></div></td>
                <td style={{ fontWeight: 700 }}>{m.finished && m.result ? `${m.result[0]}-${m.result[1]}` : (m.markets?.marcador || "—")}</td>
                <td className="dim">›</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const NAV = [
  ["resumen", "Resumen"], ["partidos", "Partidos"], ["clasificacion", "Clasificación"],
  ["value", "Value bets"], ["cartera", "Mi cartera"], ["quiniela", "Quiniela"],
  ["jugadores", "Jugadores"], ["datos", "Datos y modelos"],
];

export default function App() {
  const { session } = useSession();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [view, setView] = useState("resumen");
  const [sel, setSel] = useState(null);
  const [teamSel, setTeamSel] = useState(null);
  const [playerSel, setPlayerSel] = useState(null);
  const [favs, setFavs] = useState(getFavs);
  const [q, setQ] = useState("");
  const [bank, setBank] = useState(1000);
  const [tri, setTri] = useState(2);
  const [dob, setDob] = useState(4);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => { loadFeed().then(setData).catch((e) => setErr(e.message)); }, []);
  const matches = useMemo(() => data?.matches || [], [data]);

  const open = (m) => { setPlayerSel(null); setSel(m); window.scrollTo(0, 0); };
  const openTeam = (name) => { setPlayerSel(null); setTeamSel(name); setSel(null); setQ(""); window.scrollTo(0, 0); };
  const openPlayer = (player) => { setPlayerSel(player); setSel(null); setQ(""); window.scrollTo(0, 0); };
  const onFav = (name) => setFavs(new Set(toggleFav(name)));
  const goto = (v) => { setView(v); setSel(null); setTeamSel(null); setPlayerSel(null); setMenuOpen(false); window.scrollTo(0, 0); };
  const userName = session?.user?.email?.split("@")[0] || "Mario León";

  return (
    <div className={"layout" + (menuOpen ? " open" : "")}>
      <aside className="side">
        <div className="brand">
          <div className="logo">⚡</div>
          <div><div className="bname">Fútbol Edge</div><div className="btag">PRIVATE INTELLIGENCE</div></div>
        </div>
        <nav className="snav">
          {NAV.map(([k, l]) => (
            <button type="button" key={k} className={"snav-item" + (view === k && !sel ? " on" : "")} onClick={() => goto(k)}>
              <Icon name={k === "clasificacion" ? "clasificacion" : k === "value" ? "value" : k} /> <span>{l}</span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="cal-card">
            <div className="cal-h">Calendario <b className="value-yes">conectado</b></div>
            <div className="cal-bar"><span /></div>
            <div className="cal-sub">Fuente: {data?.data_sources?.fixtures || "Calendario verificado"}<br />Motor: {data?.engine === "ensemble" ? "Dixon-Coles + Elo calibrado" : (data?.engine || "Dixon-Coles")}</div>
          </div>
          <div className="user">
            <div className="avatar">{userName.slice(0, 2).toUpperCase()}</div>
            <div><div className="uname">{userName}</div><div className="usub">Acceso {authEnabled ? "privado" : "abierto"} · {authEnabled ? <button type="button" className="link-button" onClick={signOut}>salir</button> : "demo"}</div></div>
          </div>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <button type="button" className="burger" onClick={() => setMenuOpen((v) => !v)} aria-label="Abrir menú" aria-expanded={menuOpen}>☰</button>
          <div className="search"><Icon name="search" /><input aria-label="Buscar equipo o competición" placeholder="Buscar equipo o competición…" value={q}
            onChange={(e) => { const v = e.target.value; setQ(v); if (v.trim()) { setPlayerSel(null); setSel(null); setTeamSel(null); setView("partidos"); } }} /></div>
          <div className="top-right">
            <span className="badge-cal"><span className="dot d-ucl" /> {data ? "Calendario verificado" : "Cargando…"}</span>
            <input type="checkbox" className="theme-btn theme-toggle"
              defaultChecked={savedLightTheme()} title="Cambiar tema" aria-label="Alternar tema claro u oscuro" />
          </div>
        </header>

        <main className="content">
          {data && isStale(data) && <div className="banner warn">⚠️ El feed puede estar desactualizado (hace {Math.round(feedAgeHours(data))} h). Se revisa a las 00:15 y 10:15, con control adicional cuando hay onces oficiales.</div>}
          {data?.alerts?.some((item) => item.severity === "critical") && <div className="banner warn">⚠️ {data.alerts.filter((item) => item.severity === "critical").map((item) => item.message).join(" · ")}</div>}
          {data?._fromFallback && <div className="banner">Mostrando copia local del feed (no se pudo cargar el remoto).</div>}
          {err && <div className="state">No se pudo cargar el feed.<br />{err}</div>}
          {!data && !err && <Skeletons n={5} />}

          {data && playerSel && <PlayerProfile candidate={playerSel} players={data.players} matches={matches} onBack={() => setPlayerSel(null)} onTeam={openTeam} />}

          {data && !playerSel && sel && <MatchDetail m={sel} bankroll={bank} onBack={() => setSel(null)} onTeam={openTeam} players={data.players} />}

          {data && !playerSel && !sel && teamSel && <TeamPage team={teamSel} matches={matches} players={data.players} onBack={() => setTeamSel(null)} onOpen={open} onPlayer={openPlayer} isFav={favs.has(teamSel)} onFav={onFav} />}

          {data && !playerSel && !sel && !teamSel && (
            <>
              <h1 className="view-title">{(NAV.find(([k]) => k === view) || [null, "Resumen"])[1]}</h1>
              {view === "resumen" && <Resumen data={data} matches={matches} q={q} onOpen={open} goto={goto} favs={favs} onTeam={openTeam} />}
              {view === "clasificacion" && <Clasificacion matches={matches} onTeam={openTeam} />}
              {view === "partidos" && <Mercados matches={matches} q={q} onOpen={open} />}
              {view === "jugadores" && <Jugadores players={data.players} onPlayer={openPlayer} />}
              {view === "value" && <ValueBets matches={matches} bank={bank} setBank={setBank} globalValue={data.value_ranking} />}
              {view === "cartera" && <Cartera matches={matches} />}
              {view === "quiniela" && <Quiniela matches={matches} quiniela={data.quiniela} tri={tri} dob={dob} setTri={setTri} setDob={setDob} />}
              {view === "datos" && <Datos data={data} />}
            </>
          )}
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Navegación móvil">
        {[["resumen", "⌂", "Inicio"], ["partidos", "⚽", "Partidos"], ["value", "◆", "Value"], ["cartera", "▣", "Cartera"]].map(([key, icon, label]) => (
          <button type="button" key={key} className={view === key && !sel ? "on" : ""} onClick={() => goto(key)}><span>{icon}</span>{label}</button>
        ))}
      </nav>
      {menuOpen && <button type="button" className="scrim" onClick={() => setMenuOpen(false)} aria-label="Cerrar menú" />}
    </div>
  );
}
