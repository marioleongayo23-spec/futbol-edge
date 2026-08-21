import { useEffect, useMemo, useState } from "react";
import { accent, CREST_FALLBACK, feedAgeHours, fmtKick, hasPrediction, isStale, loadFeed } from "./feed";
import { entropy, fairProbs, kelly, overround, plenoSign } from "./poisson";
import { leaguesIn, projectedTable } from "./standings";
import MatchDetail from "./MatchDetail";
import { ALLOWED_EMAIL, authEnabled, sendMagicLink, signOut, useSession } from "./supabase";

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

/* ---------- Skeleton de carga ---------- */
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

function Login() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const submit = async () => {
    setErr("");
    if (ALLOWED_EMAIL && email.trim().toLowerCase() !== ALLOWED_EMAIL.toLowerCase()) {
      setErr("Ese correo no está autorizado."); return;
    }
    const { error } = await sendMagicLink(email.trim());
    if (error) setErr(error.message); else setSent(true);
  };
  return (
    <div className="login">
      <h1>⚽ Fútbol Edge</h1>
      <p style={{ color: "var(--muted)" }}>Acceso privado. Te enviamos un enlace de entrada al correo.</p>
      {sent ? <p className="pill y">Revisa tu email y pulsa el enlace.</p> : <>
        <input placeholder="tu@email.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button onClick={submit}>Enviar enlace de acceso</button>
        {err && <p className="note">{err}</p>}
      </>}
    </div>
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
        <p className="note" style={{ color: "var(--muted)" }}>
          Puntos = reales de lo jugado + esperados del modelo (3·P(gana)+1·P(empata)) en los partidos con predicción.
        </p>
        {ligas.length > 1 && (
          <select value={liga} onChange={(e) => setLiga(e.target.value)} style={{ marginTop: 6 }}>
            {ligas.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        )}
      </div>
      <div className="card" style={{ padding: "6px 10px", overflowX: "auto" }}>
        <table className="tbl-cls">
          <thead>
            <tr><th>#</th><th className="tl">Equipo</th><th>PJ</th><th>Pts</th><th>Proy.</th><th>DG*</th></tr>
          </thead>
          <tbody>
            {table.map((t, i) => (
              <tr key={t.name} className={i < 4 ? "row-ucl" : i < 6 ? "row-eur" : i >= table.length - 3 ? "row-desc" : ""}>
                <td>{i + 1}</td>
                <td className="tl">
                  <div className="cls-team">
                    <img className="crest sm" alt="" loading="lazy" src={t.crest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} />
                    <span className="tn">{t.name}</span>
                  </div>
                  <div className="cls-bar"><span style={{ width: (t.ptsProy / maxPts * 100).toFixed(1) + "%" }} /></div>
                </td>
                <td>{t.pj}</td>
                <td>{t.ptsReal}</td>
                <td><b>{t.ptsProy}</b></td>
                <td className={t.difGoles >= 0 ? "value-yes" : "value-no"}>{t.difGoles > 0 ? "+" : ""}{t.difGoles}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="foot" style={{ marginTop: 8 }}>
        <span className="dot d-ucl" /> Champions · <span className="dot d-eur" /> Europa · <span className="dot d-desc" /> Descenso ·
        &nbsp;*DG = diferencia de goles proyectada (real + xG del modelo).
      </div>
    </>
  );
}

/* ---------- Quiniela (14 + Pleno al 15, dobles/triples y exportar) ---------- */
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

  // Pleno al 15: marcador exacto (0/1/2/M por equipo).
  const plenoScore = pleno?.markets?.marcador?.split("-").map((n) => parseInt(n, 10));
  const plenoSigns = plenoScore ? [plenoSign(plenoScore[0]), plenoSign(plenoScore[1])] : null;

  const copy = async () => {
    const lines = fc.map((f, i) => {
      const sel = mult[i] || [f.best];
      return `${i + 1}. ${f.m.home} - ${f.m.away}  →  ${sel.join("/")}`;
    });
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
          {ms.length < 14 && <span className="chip">Solo <b>{ms.length}</b>/14 con predicción (pretemporada / falta Segunda)</span>}
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
            <div className="chips">
              <span className="chip">1 <b>{f.m.probs[0]}%</b></span>
              <span className="chip">X <b>{f.m.probs[1]}%</b></span>
              <span className="chip">2 <b>{f.m.probs[2]}%</b></span>
            </div>
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

/* ---------- Value bets (quita el margen y calcula edge) ---------- */
function ValueBets({ matches, bankroll }) {
  const ms = matches.filter(hasPrediction);
  const [odds, setOdds] = useState({});
  const bank = Number(bankroll) || 1000;
  if (!ms.length) return <div className="state">No hay partidos con predicción.</div>;

  const rows = ms.map((m, i) => {
    const pr = [m.probs[0] / 100, m.probs[1] / 100, m.probs[2] / 100];
    const o = ["1", "X", "2"].map((s) => Number(odds[i + s]));
    const haveAll = o.every((x) => x > 1);
    const fair = haveAll ? fairProbs(o) : null;
    const vig = haveAll ? overround(o) : null;
    let best = null;
    o.forEach((oo, j) => { if (oo > 1) { const e = pr[j] * oo - 1; if (!best || e > best.e) best = { j, s: ["1", "X", "2"][j], o: oo, e }; } });
    const stake = best ? Math.min(bank * kelly(pr[best.j], best.o) * 0.25, bank * 0.05) : 0;
    return { m, i, pr, o, fair, vig, best, stake };
  });
  const nValue = rows.filter((r) => r.best && r.best.e > 0.02).length;
  const nWithOdds = rows.filter((r) => r.best).length;

  return (
    <>
      <div className="card">
        <div className="chips" style={{ marginTop: 0 }}>
          <span className="chip">Con cuota <b>{nWithOdds}</b></span>
          <span className="chip">Value (edge &gt; 2%) <b className={nValue ? "value-yes" : ""}>{nValue}</b></span>
          <span className="chip">Bankroll <b>{bank.toLocaleString("es-ES")}€</b></span>
        </div>
        <p className="note" style={{ color: "var(--muted)" }}>Introduce las 3 cuotas: se quita el margen y se compara la probabilidad justa con la del modelo. Stake = Kelly ¼ (máx. 5%).</p>
      </div>
      {rows.map((r) => (
        <div className="card" key={r.i}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="tn" style={{ flex: 1 }}>{r.m.home} vs {r.m.away}</div>
            <div className="chips">
              {["1", "X", "2"].map((s, j) => (
                <span key={s} className="chip">{s} <b>{r.m.probs[j]}%</b>{r.fair ? <span className="dim"> / {(r.fair[j] * 100).toFixed(0)}%</span> : null}</span>
              ))}
            </div>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            {["1", "X", "2"].map((s, j) => {
              const e = r.o[j] > 1 ? r.pr[j] * r.o[j] - 1 : null;
              return (
                <div key={s} className="odds-in">
                  <input type="number" step="0.01" placeholder={"Cuota " + s} style={{ width: 92 }}
                    value={odds[r.i + s] || ""} onChange={(ev) => setOdds({ ...odds, [r.i + s]: ev.target.value })} />
                  {e != null && <span className={"edge " + (e > 0.02 ? "value-yes" : "value-no")}>{e > 0 ? "+" : ""}{(e * 100).toFixed(1)}%</span>}
                </div>
              );
            })}
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            {r.vig != null && <span className="chip">Margen casa <b>{(r.vig * 100).toFixed(1)}%</b></span>}
            {r.best && r.best.e > 0.02
              ? <span className="pill y">VALUE {r.best.s}: edge {(r.best.e * 100).toFixed(1)}% · apostar {r.stake.toFixed(2)}€</span>
              : r.best ? <span className="value-no">Sin value (mejor {r.best.s}: {(r.best.e * 100).toFixed(1)}%)</span> : null}
          </div>
        </div>
      ))}
    </>
  );
}

export default function App() {
  const { session, ready } = useSession();
  const [theme, toggleTheme] = useTheme();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("jornada");
  const [sel, setSel] = useState(null);
  const [md, setMd] = useState("");
  const [st, setSt] = useState("upcoming");
  const [q, setQ] = useState("");
  const [league, setLeague] = useState("");
  const [bank, setBank] = useState(1000);
  const [tri, setTri] = useState(2);
  const [dob, setDob] = useState(4);

  useEffect(() => {
    if (authEnabled && !session) return;
    loadFeed().then((d) => {
      setData(d);
      // Salto inteligente a la próxima jornada con partidos por jugar.
      const next = d.matches.filter((m) => !m.finished).map((m) => m.matchday).filter((x) => x != null).sort((a, b) => a - b)[0];
      if (next != null) setMd(String(next));
    }).catch((e) => setErr(e.message));
  }, [session]);

  const matches = useMemo(() => data?.matches || [], [data]);
  const ligas = useMemo(() => leaguesIn(matches), [matches]);
  const matchdays = useMemo(() => [...new Set(matches.map((m) => m.matchday).filter((x) => x != null))].sort((a, b) => a - b), [matches]);
  const filtered = matches.filter((m) => {
    if (league && m.league !== league) return false;
    if (md && String(m.matchday) !== md) return false;
    if (st === "upcoming" && m.finished) return false;
    if (st === "done" && !m.finished) return false;
    if (q && !((m.home + " " + m.away).toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  });

  if (!ready) return <div className="state">Cargando…</div>;
  if (authEnabled && !session) return <Login />;

  const c = data?.counts || {};
  const ageH = data ? feedAgeHours(data) : null;
  const tabs = [["jornada", "📅 Jornada"], ["clasificacion", "🏆 Clasificación"], ["quiniela", "🎫 Quiniela"], ["value", "💰 Value bets"]];

  return (
    <>
      <header><div className="wrap h-in">
        <div className="h-top">
          <h1 onClick={() => { setSel(null); setTab("jornada"); }}>⚽ Fútbol Edge</h1>
          <button className="theme-btn" onClick={toggleTheme} title="Cambiar tema" aria-label="Cambiar tema">{theme === "dark" ? "☀️" : "🌙"}</button>
        </div>
        <div className="h-sub">
          {data ? `Actualizado ${new Date(data.generated_at).toLocaleString("es-ES")} · Temporada ${data.season}` : "Cargando…"}
          {authEnabled && <> · <a onClick={signOut} style={{ cursor: "pointer" }}>salir</a></>}
        </div>
        <div className="counts">
          <div className="kpi"><b>{c.total || 0}</b><span>partidos</span></div>
          <div className="kpi"><b>{c.con_prediccion || 0}</b><span>con predicción</span></div>
          <div className="kpi"><b>{c.jugados || 0}</b><span>jugados</span></div>
        </div>
      </div></header>

      {!sel && (
        <nav><div className="wrap">
          {tabs.map(([k, l]) => (
            <button key={k} className={"tab" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div></nav>
      )}

      <main className="wrap">
        {data && isStale(data) && (
          <div className="banner warn">⚠️ El feed puede estar desactualizado (hace {Math.round(ageH)} h). El cron lo refresca cada 12 h.</div>
        )}
        {data?._fromFallback && (
          <div className="banner">Mostrando copia local del feed (no se pudo cargar el remoto).</div>
        )}
        {err && <div className="state">No se pudo cargar el feed.<br />{err}</div>}
        {!data && !err && <Skeletons n={5} />}

        {data && sel && <MatchDetail m={sel} bankroll={bank} onBack={() => setSel(null)} />}

        {data && !sel && tab === "jornada" && <>
          <div className="controls">
            {ligas.length > 1 && (
              <select value={league} onChange={(e) => setLeague(e.target.value)}>
                <option value="">Todas las ligas</option>
                {ligas.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            )}
            <select value={md} onChange={(e) => setMd(e.target.value)}>
              <option value="">Toda la jornada</option>
              {matchdays.map((x) => <option key={x} value={x}>Jornada {x}</option>)}
            </select>
            <select value={st} onChange={(e) => setSt(e.target.value)}>
              <option value="upcoming">Próximos</option><option value="all">Todos</option><option value="done">Jugados</option>
            </select>
            <input className="grow" placeholder="Buscar equipo…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {filtered.length ? filtered.map((m) => <MatchCard key={m.id} m={m} onOpen={setSel} />)
            : <div className="state">No hay partidos para este filtro.</div>}
        </>}

        {data && !sel && tab === "clasificacion" && <Clasificacion matches={matches} />}

        {data && !sel && tab === "quiniela" && <Quiniela matches={matches} tri={tri} dob={dob} setTri={setTri} setDob={setDob} />}

        {data && !sel && tab === "value" && <>
          <div className="card"><div className="lbl">Bankroll (€)</div><input type="number" value={bank} style={{ width: 130 }} onChange={(e) => setBank(e.target.value)} /></div>
          <ValueBets matches={matches} bankroll={bank} />
        </>}

        {data && <div className="foot">{data.disclaimer}<br />Fuentes: {Object.values(data.data_sources || {}).join(" · ")}</div>}
      </main>
    </>
  );
}
