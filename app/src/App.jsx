import { useEffect, useMemo, useState } from "react";
import { accent, CREST_FALLBACK, fmtKick, hasPrediction, loadFeed } from "./feed";
import { entropy, kelly } from "./poisson";
import MatchDetail from "./MatchDetail";
import { ALLOWED_EMAIL, authEnabled, sendMagicLink, signOut, useSession } from "./supabase";

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
          <img className="crest" src={m.homeCrest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} />
          <div style={{ minWidth: 0 }}><div className="tn">{m.home}</div><div className="cbar" style={{ background: accent(m.homeColors) }} /></div>
        </div>
        <div className="mid">
          {m.finished && m.result ? <><div className="score">{m.result[0]}–{m.result[1]}</div><div className="kick">final</div></>
            : m.markets?.marcador ? <><div className="pred">{m.markets.marcador}</div><div className="kick">previsto</div></>
              : <div className="kick">{fmtKick(m.kickoff)}</div>}
        </div>
        <div className="team away">
          <img className="crest" src={m.awayCrest || CREST_FALLBACK} onError={(e) => (e.target.src = CREST_FALLBACK)} />
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

function Quiniela({ matches, tri, dob, setTri, setDob }) {
  const ms = matches.filter(hasPrediction).slice(0, 14);
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
    </>
  );
}

function ValueBets({ matches, bankroll }) {
  const ms = matches.filter(hasPrediction);
  const [odds, setOdds] = useState({});
  const bank = Number(bankroll) || 1000;
  if (!ms.length) return <div className="state">No hay partidos con predicción.</div>;
  return ms.map((m, i) => {
    const pr = { 1: m.probs[0] / 100, X: m.probs[1] / 100, 2: m.probs[2] / 100 };
    let best = null;
    ["1", "X", "2"].forEach((s) => {
      const o = Number(odds[i + s]);
      if (o > 1) { const e = pr[s] * o - 1; if (!best || e > best.e) best = { s, o, e }; }
    });
    const stake = best ? Math.min(bank * kelly(pr[best.s], best.o) * 0.25, bank * 0.05) : 0;
    return (
      <div className="card" key={i}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="tn" style={{ flex: 1 }}>{m.home} vs {m.away}</div>
          <div className="chips">
            <span className="chip">1 <b>{m.probs[0]}%</b></span><span className="chip">X <b>{m.probs[1]}%</b></span><span className="chip">2 <b>{m.probs[2]}%</b></span>
          </div>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {["1", "X", "2"].map((s) => (
            <input key={s} type="number" step="0.01" placeholder={"Cuota " + s} style={{ width: 96 }}
              value={odds[i + s] || ""} onChange={(e) => setOdds({ ...odds, [i + s]: e.target.value })} />
          ))}
          <span className="grow">
            {best && best.e > 0.02 ? <span className="pill y">VALUE {best.s}: edge {(best.e * 100).toFixed(1)}% · {stake.toFixed(2)}€</span>
              : best ? <span className="value-no">Sin value (mejor {best.s}: {(best.e * 100).toFixed(1)}%)</span> : null}
          </span>
        </div>
      </div>
    );
  });
}

export default function App() {
  const { session, ready } = useSession();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("jornada");
  const [sel, setSel] = useState(null);
  const [md, setMd] = useState("");
  const [st, setSt] = useState("upcoming");
  const [q, setQ] = useState("");
  const [bank, setBank] = useState(1000);
  const [tri, setTri] = useState(2);
  const [dob, setDob] = useState(4);

  useEffect(() => {
    if (authEnabled && !session) return;
    loadFeed().then(setData).catch((e) => setErr(e.message));
  }, [session]);

  const matches = data?.matches || [];
  const matchdays = useMemo(() => [...new Set(matches.map((m) => m.matchday).filter((x) => x != null))].sort((a, b) => a - b), [data]);
  const filtered = matches.filter((m) => {
    if (md && String(m.matchday) !== md) return false;
    if (st === "upcoming" && m.finished) return false;
    if (st === "done" && !m.finished) return false;
    if (q && !((m.home + " " + m.away).toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  });

  if (!ready) return <div className="state">Cargando…</div>;
  if (authEnabled && !session) return <Login />;

  const c = data?.counts || {};
  return (
    <>
      <header><div className="wrap h-in">
        <h1 onClick={() => { setSel(null); setTab("jornada"); }}>⚽ Fútbol Edge</h1>
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
          {[["jornada", "📅 Jornada"], ["quiniela", "🎫 Quiniela"], ["value", "💰 Value bets"]].map(([k, l]) => (
            <button key={k} className={"tab" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div></nav>
      )}

      <main className="wrap">
        {err && <div className="state">No se pudo cargar el feed.<br />{err}</div>}
        {!data && !err && <div className="state">Cargando datos reales…</div>}

        {data && sel && <MatchDetail m={sel} bankroll={bank} onBack={() => setSel(null)} />}

        {data && !sel && tab === "jornada" && <>
          <div className="controls">
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
