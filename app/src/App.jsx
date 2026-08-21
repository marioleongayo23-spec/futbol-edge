import { useEffect, useMemo, useState } from "react";
import { CREST_FALLBACK, feedAgeHours, fmtKick, hasPrediction, isStale, loadFeed } from "./feed";
import { entropy, fairProbs, kelly, overround, plenoSign } from "./poisson";
import { leaguesIn, projectedTable } from "./standings";
import MatchDetail from "./MatchDetail";
import { authEnabled, signOut, useSession } from "./supabase";

/* ---------- Tema claro/oscuro ---------- */
function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("theme") || "dark"; } catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
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

/* Fila compacta de partido para el calendario */
function MatchRow({ m, onOpen }) {
  const pred = hasPrediction(m);
  const best = pred ? ["1", "X", "2"][m.probs.indexOf(Math.max(...m.probs))] : null;
  return (
    <button className="mrow" onClick={() => onOpen(m)}>
      <span className="mrow-time">{m.finished ? "FT" : hhmm(m.kickoff)}</span>
      <span className="mrow-body">
        <span className="mrow-line">
          <span className="mrow-team"><img className="crest xs" alt="" loading="lazy" src={m.homeCrest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} /><span className="tn">{m.home}</span></span>
          <span className="mrow-cen">{m.finished && m.result ? `${m.result[0]}–${m.result[1]}` : (m.markets?.marcador || "·")}</span>
          <span className="mrow-team rev"><span className="tn">{m.away}</span><img className="crest xs" alt="" loading="lazy" src={m.awayCrest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} /></span>
        </span>
        {pred && (
          <span className="mrow-bar">
            <i className="s1" style={{ flex: m.probs[0] }} /><i className="sx" style={{ flex: m.probs[1] }} /><i className="s2" style={{ flex: m.probs[2] }} />
          </span>
        )}
      </span>
      <span className="mrow-tag">{m.league.replace("LaLiga", "1ª").replace("Hypermotion", "").replace("Champions League", "UCL")}{best ? ` · ${best}` : ""}</span>
    </button>
  );
}

/* ---------- Resumen: dashboard de calendario por días ---------- */
function Resumen({ matches, onOpen, goto }) {
  const days = useMemo(() => [...new Set(matches.map((m) => m.date).filter(Boolean))].sort(), [matches]);
  const startIdx = useMemo(() => {
    const t = todayKey();
    const i = days.findIndex((d) => d >= t);
    return i < 0 ? Math.max(0, days.length - 1) : i;
  }, [days]);
  const [idx, setIdx] = useState(startIdx);

  const day = days[idx];
  const dayMatches = useMemo(() => matches.filter((m) => m.date === day).sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || "")), [matches, day]);
  const predicted = dayMatches.filter(hasPrediction);
  const pick = predicted
    .map((m) => { const mx = Math.max(...m.probs); return { m, mx, s: ["1", "X", "2"][m.probs.indexOf(mx)] }; })
    .sort((a, b) => b.mx - a.mx)[0];
  const strong = predicted.filter((m) => Math.max(...m.probs) >= 55).length;
  const goalsDay = predicted.length ? (predicted.reduce((s, m) => s + (m.xg ? m.xg[0] + m.xg[1] : 0), 0) / predicted.length) : 0;

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
      </div>

      <div className="cal">
        <div className="cal-nav">
          <button className="cal-btn" disabled={idx <= 0} onClick={() => setIdx((i) => Math.max(0, i - 1))} aria-label="Día anterior">‹</button>
          <div className="cal-title"><b>{dayLong(day)}</b>{day === t && <span className="cal-today">HOY</span>}</div>
          <button className="cal-btn" disabled={idx >= days.length - 1} onClick={() => setIdx((i) => Math.min(days.length - 1, i + 1))} aria-label="Día siguiente">›</button>
          <button className="cal-btn wide" onClick={() => setIdx(startIdx)}>Hoy</button>
        </div>
        <div className="cal-strip">
          {strip.map((d) => {
            const n = matches.filter((m) => m.date === d).length;
            return (
              <button key={d} className={"cal-day" + (d === day ? " on" : "") + (d === t ? " today" : "")} onClick={() => setIdx(days.indexOf(d))}>
                <span className="cd-wd">{dayWd(d)}</span>
                <span className="cd-dm">{dayNum(d)}</span>
                <span className="cd-n">{n}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="day-matches">
        {dayMatches.length ? dayMatches.map((m) => <MatchRow key={m.id} m={m} onOpen={onOpen} />)
          : <div className="state">No hay partidos este día.</div>}
      </div>

      <div className="sec-h" style={{ marginTop: 18 }}>
        <h2>Explora</h2>
      </div>
      <div className="quick-links">
        <button className="qlink" onClick={() => goto("partidos")}><Icon name="partidos" /><span>Partidos y mercados</span></button>
        <button className="qlink" onClick={() => goto("clasificacion")}><Icon name="clasificacion" /><span>Clasificación</span></button>
        <button className="qlink" onClick={() => goto("value")}><Icon name="value" /><span>Value bets</span></button>
        <button className="qlink" onClick={() => goto("quiniela")}><Icon name="quiniela" /><span>Quiniela</span></button>
      </div>
    </>
  );
}

/* ---------- Clasificación proyectada ---------- */
function Clasificacion({ matches }) {
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
            <button className={mode === "real" ? "on" : ""} onClick={() => setMode("real")}>Real</button>
            <button className={mode === "proy" ? "on" : ""} onClick={() => setMode("proy")}>Proyección</button>
          </div>
          {ligas.length > 1 && <select value={liga} onChange={(e) => setLiga(e.target.value)}>{ligas.map((l) => <option key={l} value={l}>{l}</option>)}</select>}
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
                  <td className="tl"><div className="cls-team"><img className="crest sm" alt="" loading="lazy" src={t.crest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} /><span className="tn">{t.name}</span></div></td>
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
  const ms = matches.filter(hasPrediction).filter((m) => !q || (m.home + " " + m.away + " " + m.league).toLowerCase().includes(q.toLowerCase()));
  if (!ms.length) return <div className="state">No hay partidos con mercados para “{q}”.</div>;
  const sign = (m) => { const p = [m.probs[0], m.probs[1], m.probs[2]]; const i = p.indexOf(Math.max(...p)); return ["1", "X", "2"][i]; };
  return (
    <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
      <table className="tbl-mk">
        <thead><tr><th className="tl">Partido</th><th>1X2</th><th>Marcador</th><th>O2.5</th><th>U2.5</th><th>BTTS</th><th></th></tr></thead>
        <tbody>
          {ms.map((m) => {
            const o25 = m.markets?.over_2_5 ?? null;
            return (
              <tr key={m.id} className="click" onClick={() => onOpen(m)}>
                <td className="tl"><div className="mk-team"><b>{m.home}</b> <span className="dim">vs</span> {m.away}<div className="mk-sub">{m.league} · J{m.matchday || ""} · {fmtKick(m.kickoff)}</div></div></td>
                <td><span className={"q-" + sign(m)} style={{ fontWeight: 800 }}>{sign(m)}</span></td>
                <td>{m.markets?.marcador || "—"}</td>
                <td>{o25 != null ? Math.round(o25 * 100) + "%" : "—"}</td>
                <td>{o25 != null ? Math.round((1 - o25) * 100) + "%" : "—"}</td>
                <td>{m.markets?.btts != null ? Math.round(m.markets.btts * 100) + "%" : "—"}</td>
                <td className="dim">›</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Jugadores (fuente de pago pendiente) ---------- */
function Jugadores() {
  return (
    <div className="card">
      <div className="lbl">Jugadores</div>
      <p className="note">⚠️ Los datos por jugador (alineaciones, lesiones, minutos, xG individual) requieren una <b>fuente de pago</b> (API-Football). Están marcados como <code>pendiente</code> en el feed.</p>
      <p style={{ color: "var(--muted)", fontSize: ".85rem" }}>
        Cuando añadas <code>API_FOOTBALL_KEY</code> en los secrets del repo, el cron podrá enriquecer el feed con datos de jugadores y esta sección se activará automáticamente.
      </p>
    </div>
  );
}

/* ---------- Quiniela ---------- */
function Quiniela({ matches, tri, dob, setTri, setDob }) {
  const [copied, setCopied] = useState(false);
  const pool = matches.filter(hasPrediction).slice(0, 15);
  const ms = pool.slice(0, 14);
  const pleno = pool[14];
  const fc = ms.map((m) => {
    const pr = { 1: m.probs[0] / 100, X: m.probs[1] / 100, 2: m.probs[2] / 100 };
    const best = Object.keys(pr).reduce((a, b) => (pr[a] > pr[b] ? a : b));
    return { m, pr, best, ent: entropy(pr) };
  });
  const ranked = [...fc.keys()].sort((a, b) => fc[b].ent - fc[a].ent);
  const mult = {};
  ranked.slice(0, tri).forEach((i) => (mult[i] = ["1", "X", "2"]));
  let d = 0;
  for (const i of ranked) { if (d >= dob) break; if (mult[i]) continue; mult[i] = Object.keys(fc[i].pr).sort((a, b) => fc[i].pr[b] - fc[i].pr[a]).slice(0, 2); d++; }
  let cost = 1; fc.forEach((_, i) => (cost *= mult[i] ? mult[i].length : 1));
  let pAll = 1; fc.forEach((f, i) => { const sel = mult[i] || [f.best]; pAll *= sel.reduce((s, x) => s + f.pr[x], 0); });
  const plenoScore = pleno?.markets?.marcador?.split("-").map((n) => parseInt(n, 10));
  const plenoSigns = plenoScore ? [plenoSign(plenoScore[0]), plenoSign(plenoScore[1])] : null;
  const copy = async () => {
    const lines = fc.map((f, i) => { const sel = mult[i] || [f.best]; return `${i + 1}. ${f.m.home} - ${f.m.away}  →  ${sel.join("/")}`; });
    if (pleno && plenoSigns) lines.push(`P15. ${pleno.home} - ${pleno.away}  →  ${plenoSigns[0]} - ${plenoSigns[1]}`);
    lines.push(`Coste: ${cost} columnas`);
    try { await navigator.clipboard.writeText(lines.join("\n")); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* ignore */ }
  };
  return (
    <>
      <div className="card">
        <div className="row">
          <div className="grow"><div className="lbl">Triples</div><input type="range" min="0" max="8" value={tri} className="grow" onChange={(e) => setTri(+e.target.value)} /> {tri}</div>
          <div className="grow"><div className="lbl">Dobles</div><input type="range" min="0" max="8" value={dob} className="grow" onChange={(e) => setDob(+e.target.value)} /> {dob}</div>
        </div>
        <div className="chips">
          {ms.length < 14 && <span className="chip">Solo <b>{ms.length}</b>/14 con predicción</span>}
          <span className="chip">Coste <b>{cost}</b> columnas</span>
          <span className="chip">Prob. pleno al {ms.length} <b>{(pAll * 100).toFixed(3)}%</b></span>
          <button className="mini" onClick={copy}>{copied ? "✓ Copiado" : "📋 Copiar quiniela"}</button>
        </div>
      </div>
      {fc.map((f, i) => {
        const sel = mult[i] || [f.best];
        return (
          <div className="card" key={i} style={{ padding: "10px 14px" }}>
            <div className="ctop"><span>{i + 1} · {f.m.league} J{f.m.matchday || ""}</span><span>{fmtKick(f.m.kickoff)}</span></div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="tn" style={{ flex: 1 }}>{f.m.home} <span style={{ color: "var(--dim)" }}>vs</span> {f.m.away}</div>
              <div className="q-sign">{sel.map((s) => <span key={s} className={"q-" + s}>{s}</span>)}</div>
            </div>
            <div className="chips"><span className="chip">1 <b>{f.m.probs[0]}%</b></span><span className="chip">X <b>{f.m.probs[1]}%</b></span><span className="chip">2 <b>{f.m.probs[2]}%</b></span></div>
          </div>
        );
      })}
      {pleno && plenoSigns && (
        <div className="card pleno" style={{ padding: "12px 14px" }}>
          <div className="ctop"><span>🏆 Pleno al 15 · {pleno.league} J{pleno.matchday || ""}</span><span>{fmtKick(pleno.kickoff)}</span></div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="tn" style={{ flex: 1 }}>{pleno.home} <span style={{ color: "var(--dim)" }}>vs</span> {pleno.away}</div>
            <div className="q-sign pleno-sc">{plenoSigns[0]} <span style={{ color: "var(--dim)" }}>-</span> {plenoSigns[1]}</div>
          </div>
          <div className="chips"><span className="chip">Marcador previsto <b>{pleno.markets.marcador}</b></span></div>
        </div>
      )}
    </>
  );
}

/* ---------- Value bets ---------- */
function ValueBets({ matches, bank, setBank }) {
  const ms = matches.filter(hasPrediction);
  const [odds, setOdds] = useState({});
  const bankN = Number(bank) || 1000;
  const rows = ms.map((m, i) => {
    const pr = [m.probs[0] / 100, m.probs[1] / 100, m.probs[2] / 100];
    const o = ["1", "X", "2"].map((s) => Number(odds[i + s]));
    const haveAll = o.every((x) => x > 1);
    const fair = haveAll ? fairProbs(o) : null;
    const vig = haveAll ? overround(o) : null;
    let best = null;
    o.forEach((oo, j) => { if (oo > 1) { const e = pr[j] * oo - 1; if (!best || e > best.e) best = { j, s: ["1", "X", "2"][j], o: oo, e }; } });
    const stake = best ? Math.min(bankN * kelly(pr[best.j], best.o) * 0.25, bankN * 0.05) : 0;
    return { m, i, pr, o, fair, vig, best, stake };
  });
  const nValue = rows.filter((r) => r.best && r.best.e > 0.02).length;
  const nWithOdds = rows.filter((r) => r.best).length;
  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div><div className="lbl">Bankroll (€)</div><input type="number" value={bank} style={{ width: 130 }} onChange={(e) => setBank(e.target.value)} /></div>
          <div className="chips">
            <span className="chip">Con cuota <b>{nWithOdds}</b></span>
            <span className="chip">Value (edge&gt;2%) <b className={nValue ? "value-yes" : ""}>{nValue}</b></span>
          </div>
        </div>
        <p className="note" style={{ color: "var(--muted)" }}>Introduce las 3 cuotas: se quita el margen y se compara la probabilidad justa con la del modelo. Stake = Kelly ¼ (máx. 5%).</p>
      </div>
      {!ms.length && <div className="state">No hay partidos con predicción.</div>}
      {rows.map((r) => (
        <div className="card" key={r.i}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="tn" style={{ flex: 1 }}>{r.m.home} vs {r.m.away}</div>
            <div className="chips">{["1", "X", "2"].map((s, j) => <span key={s} className="chip">{s} <b>{r.m.probs[j]}%</b>{r.fair ? <span className="dim"> / {(r.fair[j] * 100).toFixed(0)}%</span> : null}</span>)}</div>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            {["1", "X", "2"].map((s, j) => {
              const e = r.o[j] > 1 ? r.pr[j] * r.o[j] - 1 : null;
              return (
                <div key={s} className="odds-in">
                  <input type="number" step="0.01" placeholder={"Cuota " + s} style={{ width: 92 }} value={odds[r.i + s] || ""} onChange={(ev) => setOdds({ ...odds, [r.i + s]: ev.target.value })} />
                  {e != null && <span className={"edge " + (e > 0.02 ? "value-yes" : "value-no")}>{e > 0 ? "+" : ""}{(e * 100).toFixed(1)}%</span>}
                </div>
              );
            })}
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            {r.vig != null && <span className="chip">Margen casa <b>{(r.vig * 100).toFixed(1)}%</b></span>}
            {r.best && r.best.e > 0.02 ? <span className="pill y">VALUE {r.best.s}: edge {(r.best.e * 100).toFixed(1)}% · apostar {r.stake.toFixed(2)}€</span>
              : r.best ? <span className="value-no">Sin value (mejor {r.best.s}: {(r.best.e * 100).toFixed(1)}%)</span> : null}
          </div>
        </div>
      ))}
    </>
  );
}

/* ---------- Datos y modelos ---------- */
function Datos({ data }) {
  const ds = data.data_sources || {};
  const ageH = feedAgeHours(data);
  return (
    <>
      <div className="card">
        <div className="lbl">Motor y estado</div>
        <div className="chips">
          <span className="chip">Motor <b>{data.engine || "dixon-coles"} + Elo</b></span>
          <span className="chip">Schema <b>v{data.schema_version}</b></span>
          <span className="chip">Temporada <b>{data.season}</b></span>
          <span className="chip">Generado <b>{new Date(data.generated_at).toLocaleString("es-ES")}</b></span>
          {ageH != null && <span className={"chip"}>Antigüedad <b className={isStale(data) ? "value-no" : "value-yes"}>{Math.round(ageH)} h</b></span>}
        </div>
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
          <li><b>Dixon-Coles</b> con ponderación temporal y corrección de resultados bajos.</li>
          <li><b>Elo</b> dinámico para fuerza de equipos.</li>
          <li><b>Matriz de goles Poisson</b> en cliente → cualquier mercado (over/under, hándicap, BTTS, marcador exacto).</li>
          <li><b>Value</b>: edge = prob·cuota − 1, staking con Kelly fraccionado.</li>
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
    if (!(odds > 1) || !(stake > 0) || !f.match.trim()) return;
    setBets([{ id: Date.now(), date: new Date().toISOString().slice(0, 10), match: f.match.trim(), sel: f.sel, odds, stake, result: "open" }, ...bets]);
    setF({ match: "", sel: "1", odds: "", stake: "" });
  };
  const settle = (id, result) => setBets(bets.map((b) => b.id === id ? { ...b, result } : b));
  const del = (id) => setBets(bets.filter((b) => b.id !== id));

  return (
    <>
      <div className="stat-tiles">
        <div className="stat"><span className="stat-k">Bankroll</span><b className="stat-v">{bank.toFixed(0)}€</b><span className="stat-s">inicio {Number(bank0).toFixed(0)}€</span></div>
        <div className="stat"><span className="stat-k">Beneficio</span><b className={"stat-v " + (profit >= 0 ? "accent" : "")} style={profit < 0 ? { color: "var(--red)" } : null}>{profit >= 0 ? "+" : ""}{profit.toFixed(2)}€</b><span className="stat-s">{settled.length} apuestas cerradas</span></div>
        <div className="stat"><span className="stat-k">ROI / Yield</span><b className="stat-v" style={{ color: roi >= 0 ? "var(--green)" : "var(--red)" }}>{roi >= 0 ? "+" : ""}{roi.toFixed(1)}%</b><span className="stat-s">{staked.toFixed(0)}€ apostados</span></div>
        <div className="stat"><span className="stat-k">Acierto</span><b className="stat-v">{hit.toFixed(0)}%</b><span className="stat-s">{wins}/{settled.length} ganadas</span></div>
      </div>

      <div className="card">
        <div className="lbl">Evolución del beneficio</div>
        <Sparkline points={curve} />
      </div>

      <div className="card">
        <div className="lbl">Registrar apuesta</div>
        <div className="row">
          <input className="grow" list="fe-matches" placeholder="Partido (o texto libre)" value={f.match} onChange={(e) => setF({ ...f, match: e.target.value })} />
          <datalist id="fe-matches">{suggestions.map((s) => <option key={s} value={s} />)}</datalist>
          <select value={f.sel} onChange={(e) => setF({ ...f, sel: e.target.value })}>
            <option value="1">1</option><option value="X">X</option><option value="2">2</option>
            <option value="Over">Over</option><option value="Under">Under</option><option value="BTTS">BTTS</option><option value="Otro">Otro</option>
          </select>
          <input type="number" step="0.01" placeholder="Cuota" style={{ width: 90 }} value={f.odds} onChange={(e) => setF({ ...f, odds: e.target.value })} />
          <input type="number" step="1" placeholder="Stake €" style={{ width: 90 }} value={f.stake} onChange={(e) => setF({ ...f, stake: e.target.value })} />
          <button className="add-btn" onClick={add}>Añadir</button>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="lbl" style={{ margin: 0 }}>Bankroll inicial</span>
          <input type="number" style={{ width: 110 }} value={bank0} onChange={(e) => setBank0(e.target.value)} />
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
                        <button className="s-won" onClick={() => settle(b.id, "won")}>✓</button>
                        <button className="s-lost" onClick={() => settle(b.id, "lost")}>✗</button>
                        <button className="s-void" onClick={() => settle(b.id, "void")}>N</button>
                      </span>
                    ) : <span className={"pill " + (b.result === "won" ? "y" : "")}>{b.result === "won" ? "Ganada" : b.result === "lost" ? "Perdida" : "Nula"}</span>}
                  </td>
                  <td><button className="s-del" onClick={() => del(b.id)}>🗑</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

const NAV = [
  ["resumen", "Resumen"], ["partidos", "Partidos"], ["clasificacion", "Clasificación"],
  ["value", "Value bets"], ["cartera", "Mi cartera"], ["quiniela", "Quiniela"],
  ["jugadores", "Jugadores"], ["datos", "Datos y modelos"],
];

export default function App() {
  const { session } = useSession();
  const [theme, toggleTheme] = useTheme();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [view, setView] = useState("resumen");
  const [sel, setSel] = useState(null);
  const [q, setQ] = useState("");
  const [bank, setBank] = useState(1000);
  const [tri, setTri] = useState(2);
  const [dob, setDob] = useState(4);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => { loadFeed().then(setData).catch((e) => setErr(e.message)); }, []);
  const matches = useMemo(() => data?.matches || [], [data]);

  const open = (m) => { setSel(m); window.scrollTo(0, 0); };
  const goto = (v) => { setView(v); setSel(null); setMenuOpen(false); window.scrollTo(0, 0); };
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
            <button key={k} className={"snav-item" + (view === k && !sel ? " on" : "")} onClick={() => goto(k)}>
              <Icon name={k === "clasificacion" ? "clasificacion" : k === "value" ? "value" : k} /> <span>{l}</span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="cal-card">
            <div className="cal-h">Calendario <b className="value-yes">conectado</b></div>
            <div className="cal-bar"><span /></div>
            <div className="cal-sub">Fuente: {data?.data_sources?.fixtures || "Calendario verificado"}<br />Motor: {data?.engine || "Dixon-Coles"} + Elo</div>
          </div>
          <div className="user">
            <div className="avatar">{userName.slice(0, 2).toUpperCase()}</div>
            <div><div className="uname">{userName}</div><div className="usub">Acceso {authEnabled ? "privado" : "abierto"} · {authEnabled ? <a onClick={signOut} style={{ cursor: "pointer" }}>salir</a> : "demo"}</div></div>
          </div>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <button className="burger" onClick={() => setMenuOpen((v) => !v)} aria-label="Menú">☰</button>
          <div className="search"><Icon name="search" /><input placeholder="Buscar equipo o competición…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="top-right">
            <span className="badge-cal"><span className="dot d-ucl" /> {data ? "Calendario verificado" : "Cargando…"}</span>
            <button className="theme-btn" onClick={toggleTheme} title="Cambiar tema" aria-label="Cambiar tema">{theme === "dark" ? "☀️" : "🌙"}</button>
          </div>
        </header>

        <main className="content">
          {data && isStale(data) && <div className="banner warn">⚠️ El feed puede estar desactualizado (hace {Math.round(feedAgeHours(data))} h). El cron lo refresca cada 12 h.</div>}
          {data?._fromFallback && <div className="banner">Mostrando copia local del feed (no se pudo cargar el remoto).</div>}
          {err && <div className="state">No se pudo cargar el feed.<br />{err}</div>}
          {!data && !err && <Skeletons n={5} />}

          {data && sel && <MatchDetail m={sel} bankroll={bank} onBack={() => setSel(null)} />}

          {data && !sel && (
            <>
              <h1 className="view-title">{(NAV.find(([k]) => k === view) || [null, "Resumen"])[1]}</h1>
              {view === "resumen" && <Resumen data={data} matches={matches} q={q} onOpen={open} goto={goto} />}
              {view === "clasificacion" && <Clasificacion matches={matches} />}
              {view === "partidos" && <Mercados matches={matches} q={q} onOpen={open} />}
              {view === "jugadores" && <Jugadores />}
              {view === "value" && <ValueBets matches={matches} bank={bank} setBank={setBank} />}
              {view === "cartera" && <Cartera matches={matches} />}
              {view === "quiniela" && <Quiniela matches={matches} tri={tri} dob={dob} setTri={setTri} setDob={setDob} />}
              {view === "datos" && <Datos data={data} />}
            </>
          )}
        </main>
      </div>
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}
    </div>
  );
}
