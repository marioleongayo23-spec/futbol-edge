import { Fragment, useMemo, useState } from "react";
import { accent, CREST_FALLBACK, fmtKick, hasPrediction } from "./feed";
import { ah, btts, kelly, matrix, oneXtwo, over, topScores } from "./poisson";

function Teams({ m }) {
  return (
    <div className="teams">
      <div className="team">
        <img className="crest" src={m.homeCrest || CREST_FALLBACK}
          onError={(e) => (e.target.src = CREST_FALLBACK)} />
        <div style={{ minWidth: 0 }}>
          <div className="tn">{m.home}</div>
          <div className="cbar" style={{ background: accent(m.homeColors) }} />
        </div>
      </div>
      <div className="mid">
        {m.finished && m.result
          ? <><div className="score">{m.result[0]}–{m.result[1]}</div><div className="kick">final</div></>
          : m.markets?.marcador
            ? <><div className="pred">{m.markets.marcador}</div><div className="kick">previsto</div></>
            : <div className="kick">{fmtKick(m.kickoff)}</div>}
      </div>
      <div className="team away">
        <img className="crest" src={m.awayCrest || CREST_FALLBACK}
          onError={(e) => (e.target.src = CREST_FALLBACK)} />
        <div style={{ minWidth: 0 }}>
          <div className="tn">{m.away}</div>
          <div className="cbar" style={{ background: accent(m.awayColors) }} />
        </div>
      </div>
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

export default function MatchDetail({ m, bankroll, onBack }) {
  const [ouL, setOuL] = useState(2.5);
  const [hcL, setHcL] = useState(-0.5);
  const [vSel, setVSel] = useState("1");
  const [vOdds, setVOdds] = useState(2.0);

  const M = useMemo(() => (hasPrediction(m) ? matrix(m.xg[0], m.xg[1]) : null), [m]);
  const p = M ? oneXtwo(M) : null;

  const md = m.matchday ? "J" + m.matchday : (m.stage || "");
  const bank = Number(bankroll) || 1000;

  let vProb = 0;
  if (M) {
    if (vSel === "1") vProb = p[1];
    else if (vSel === "X") vProb = p.X;
    else if (vSel === "2") vProb = p[2];
    else if (vSel === "ov") vProb = over(M, ouL);
    else if (vSel === "un") vProb = 1 - over(M, ouL);
    else vProb = btts(M);
  }
  const edge = vProb * Number(vOdds) - 1;
  const stake = Math.min(bank * kelly(vProb, Number(vOdds)) * 0.25, bank * 0.05);

  return (
    <div>
      <button className="back" onClick={onBack}>← Volver a la lista</button>
      <div className="card">
        <div className="ctop"><span>{m.league} · {md}</span><span>{fmtKick(m.kickoff)}</span></div>
        <Teams m={m} />
      </div>

      {m.finished && m.result && (
        <div className="card"><div className="lbl">Resultado real</div>
          <div className="score" style={{ textAlign: "center" }}>{m.result[0]} – {m.result[1]}</div></div>
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
          <div className="card">
            <div className="lbl">Resultado 1X2</div>
            <div className="pbar">
              <div className="seg s1" style={{ flex: m.probs[0] }}>{m.probs[0] > 8 ? m.probs[0] + "%" : ""}</div>
              <div className="seg sx" style={{ flex: m.probs[1] }}>{m.probs[1] > 8 ? m.probs[1] + "%" : ""}</div>
              <div className="seg s2" style={{ flex: m.probs[2] }}>{m.probs[2] > 8 ? m.probs[2] + "%" : ""}</div>
            </div>
            <div className="chips">
              <span className="chip">Marcador <b>{m.markets.marcador}</b></span>
              <span className="chip">xG <b>{m.xg[0]}–{m.xg[1]}</b></span>
              <span className="chip">BTTS <b>{Math.round(m.markets.btts * 100)}%</b></span>
            </div>
            <div className="lbl">Mapa de marcadores (local ↓ / visitante →)</div>
            <Heat M={M} />
          </div>

          <div className="card">
            <div className="lbl">Over / Under goles</div>
            <div className="row">
              <input type="range" min="0.5" max="6.5" step="0.5" value={ouL} className="grow"
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
              <select value={vSel} onChange={(e) => setVSel(e.target.value)}>
                <option value="1">1</option><option value="X">X</option><option value="2">2</option>
                <option value="ov">Over (línea de arriba)</option>
                <option value="un">Under (línea de arriba)</option>
                <option value="btts">BTTS Sí</option>
              </select>
              <input type="number" step="0.01" value={vOdds} style={{ width: 120 }}
                onChange={(e) => setVOdds(e.target.value)} />
            </div>
            <div className="kv"><span>Prob. modelo</span><b>{(vProb * 100).toFixed(1)}%</b></div>
            <div className="kv"><span>Cuota justa</span><b>{(1 / vProb).toFixed(2)}</b></div>
            <div className="kv"><span>Edge</span><b className={edge > 0 ? "value-yes" : "value-no"}>{(edge * 100).toFixed(1)}%</b></div>
            <div className="kv"><span>Recomendación</span>
              {edge > 0.02 ? <span className="pill y">APOSTAR · {stake.toFixed(2)}€</span> : <span className="value-no">Sin value</span>}</div>
          </div>

          {m.stats && (
            <div className="card">
              <div className="lbl">Estadísticas esperadas</div>
              <table>
                <thead><tr><th>Métrica</th><th>Local</th><th>Visit.</th><th>Total</th></tr></thead>
                <tbody>
                  {[["goals", "Goles"], ["shots", "Remates"], ["sot", "Tiros a puerta"], ["corners", "Córners"],
                    ["fouls", "Faltas"], ["yellows", "Amarillas"], ["reds", "Rojas"]]
                    .filter(([k]) => m.stats[k]).map(([k, lab]) => (
                      <tr key={k}><td>{lab}</td><td>{m.stats[k].home}</td><td>{m.stats[k].away}</td><td><b>{m.stats[k].total}</b></td></tr>
                    ))}
                </tbody>
              </table>
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
