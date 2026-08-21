import { useEffect, useMemo, useState } from "react";
import { accent, CREST_FALLBACK, feedAgeHours, fmtKick, hasPrediction, isStale, loadFeed } from "./feed";
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
    jugadores: <><circle cx="9" cy="8" r="3.2" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0" /><path d="M16 5.2a3.2 3.2 0 0 1 0 6M17.5 20a5.5 5.5 0 0 0-2.6-4.7" /></>,
    value: <><path d="M4 16l5-5 3 3 7-8" /><path d="M16 6h4v4" /></>,
    quiniela: <><path d="M7 4h10v3a5 5 0 0 1-10 0V4z" /><path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3" /><path d="M10 15v3M14 15v3M8 21h8" /></>,
    datos: <><ellipse cx="12" cy="5.5" rx="7" ry="2.8" /><path d="M5 5.5v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6" /><path d="M5 11.5v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6" /></>,
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

function MatchCard({ m, onOpen }) {
  const md = m.matchday ? "J" + m.matchday : (m.stage || "");
  return (
    <div className="card click" onClick={() => onOpen(m)}>
      <div className="ctop">
        <span>{m.league} · {md} · {fmtKick(m.kickoff)}</span>
        {m.finished ? <span className="badge b-done">Final</span> : <span className="badge b-live">{m.status || "Programado"}</span>}
      </div>
      <div className="teams">
        <div className="team">
          <img className="crest" alt="" loading="lazy" src={m.homeCrest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} />
          <div style={{ minWidth: 0 }}><div className="tn">{m.home}</div><div className="cbar" style={{ background: accent(m.homeColors) }} /></div>
        </div>
        <div className="mid">
          {m.finished && m.result ? <><div className="score">{m.result[0]}–{m.result[1]}</div><div className="kick">final</div></>
            : m.markets?.marcador ? <><div className="pred">{m.markets.marcador}</div><div className="kick">previsto</div></>
              : <div className="kick">{fmtKick(m.kickoff)}</div>}
        </div>
        <div className="team away">
          <img className="crest" alt="" loading="lazy" src={m.awayCrest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} />
          <div style={{ minWidth: 0 }}><div className="tn">{m.away}</div><div className="cbar" style={{ background: accent(m.awayColors) }} /></div>
        </div>
      </div>
      {hasPrediction(m) && (
        <div className="pbar">
          <div className="seg s1" style={{ flex: m.probs[0] }}>{m.probs[0] > 8 ? m.probs[0] + "%" : ""}</div>
          <div className="seg sx" style={{ flex: m.probs[1] }}>{m.probs[1] > 8 ? m.probs[1] + "%" : ""}</div>
          <div className="seg s2" style={{ flex: m.probs[2] }}>{m.probs[2] > 8 ? m.probs[2] + "%" : ""}</div>
        </div>
      )}
      <div style={{ textAlign: "right", marginTop: 8, fontSize: ".75rem", color: "var(--blue)" }}>Ver análisis →</div>
    </div>
  );
}

/* ---------- Resumen (home) ---------- */
function Resumen({ data, matches, q, onOpen, goto }) {
  const c = data.counts || {};
  const upcoming = matches.filter((m) => !m.finished);
  const nextMd = upcoming.map((m) => m.matchday).filter((x) => x != null).sort((a, b) => a - b)[0];
  const shown = upcoming
    .filter((m) => (nextMd == null || m.matchday === nextMd))
    .filter((m) => !q || (m.home + " " + m.away + " " + m.league).toLowerCase().includes(q.toLowerCase()))
    .slice(0, 12);
  const table = useMemo(() => projectedTable(matches, leaguesIn(matches)[0]).slice(0, 5), [matches]);
  return (
    <>
      <div className="grid-kpi">
        <div className="kpi big"><b>{c.total || 0}</b><span>partidos</span></div>
        <div className="kpi big"><b>{c.con_prediccion || 0}</b><span>con predicción</span></div>
        <div className="kpi big"><b>{c.jugados || 0}</b><span>jugados</span></div>
        <div className="kpi big"><b>{c.proximos || 0}</b><span>próximos</span></div>
      </div>
      <div className="two-col">
        <div>
          <div className="sec-h"><h2>Próxima jornada{nextMd ? ` · J${nextMd}` : ""}</h2><button className="mini" onClick={() => goto("mercados")}>Ver mercados →</button></div>
          {shown.length ? shown.map((m) => <MatchCard key={m.id} m={m} onOpen={onOpen} />) : <div className="state">No hay partidos próximos para “{q}”.</div>}
        </div>
        <div>
          <div className="sec-h"><h2>Top clasificación</h2><button className="mini" onClick={() => goto("clasificacion")}>Ver tabla →</button></div>
          <div className="card" style={{ padding: "6px 10px" }}>
            <table className="tbl-cls">
              <thead><tr><th>#</th><th className="tl">Equipo</th><th>Proy.</th></tr></thead>
              <tbody>
                {table.map((t, i) => (
                  <tr key={t.name} className={i < 4 ? "row-ucl" : ""}>
                    <td>{i + 1}</td>
                    <td className="tl"><div className="cls-team"><img className="crest sm" alt="" loading="lazy" src={t.crest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} /><span className="tn">{t.name}</span></div></td>
                    <td><b>{t.ptsProy}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

/* ---------- Clasificación proyectada ---------- */
function Clasificacion({ matches }) {
  const ligas = useMemo(() => leaguesIn(matches), [matches]);
  const [liga, setLiga] = useState(ligas[0] || "");
  const table = useMemo(() => projectedTable(matches, liga || ligas[0]), [matches, liga, ligas]);
  if (!table.length) return <div className="state">Sin datos de clasificación.</div>;
  const maxPts = Math.max(...table.map((t) => t.ptsProy), 1);
  return (
    <>
      <div className="card">
        <div className="lbl">Clasificación proyectada a fin de temporada</div>
        <p className="note" style={{ color: "var(--muted)" }}>Puntos = reales de lo jugado + esperados del modelo (3·P(gana)+1·P(empata)) en los partidos con predicción.</p>
        {ligas.length > 1 && <select value={liga} onChange={(e) => setLiga(e.target.value)} style={{ marginTop: 6 }}>{ligas.map((l) => <option key={l} value={l}>{l}</option>)}</select>}
      </div>
      <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
        <table className="tbl-cls">
          <thead><tr><th>#</th><th className="tl">Equipo</th><th>PJ</th><th>Pts</th><th>Proy.</th><th>DG*</th></tr></thead>
          <tbody>
            {table.map((t, i) => (
              <tr key={t.name} className={i < 4 ? "row-ucl" : i < 6 ? "row-eur" : i >= table.length - 3 ? "row-desc" : ""}>
                <td>{i + 1}</td>
                <td className="tl">
                  <div className="cls-team"><img className="crest sm" alt="" loading="lazy" src={t.crest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} /><span className="tn">{t.name}</span></div>
                  <div className="cls-bar"><span style={{ width: (t.ptsProy / maxPts * 100).toFixed(1) + "%" }} /></div>
                </td>
                <td>{t.pj}</td><td>{t.ptsReal}</td><td><b>{t.ptsProy}</b></td>
                <td className={t.difGoles >= 0 ? "value-yes" : "value-no"}>{t.difGoles > 0 ? "+" : ""}{t.difGoles}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="foot" style={{ marginTop: 8 }}>
        <span className="dot d-ucl" /> Champions · <span className="dot d-eur" /> Europa · <span className="dot d-desc" /> Descenso · *DG = dif. de goles proyectada.
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

const NAV = [
  ["resumen", "Resumen"], ["clasificacion", "Clasificación"], ["mercados", "Mercados"],
  ["jugadores", "Jugadores"], ["value", "Value bets"], ["quiniela", "Quiniela"], ["datos", "Datos y modelos"],
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
              {view === "mercados" && <Mercados matches={matches} q={q} onOpen={open} />}
              {view === "jugadores" && <Jugadores />}
              {view === "value" && <ValueBets matches={matches} bank={bank} setBank={setBank} />}
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
