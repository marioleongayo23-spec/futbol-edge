import { Fragment, useMemo, useState } from "react";
import { accent, crestFor, fmtKick } from "./feed";
import { ah, btts, kelly, matrix, oneXtwo, over, topScores } from "./poisson";
import { confidence, countdown, isSurprise } from "./insights";

function Teams({ m, onTeam }) {
  const nameStyle = onTeam ? { cursor: "pointer" } : null;
  return (
    <div className="teams">
      <div className="team">
        <img className="crest" src={crestFor(m.home, m.homeColors, m.homeCrest)}
          onError={(e) => (e.target.src = crestFor(m.home, m.homeColors, null))}
          onClick={() => onTeam && onTeam(m.home)} style={nameStyle} />
        <div style={{ minWidth: 0 }}>
          <div className="tn" style={nameStyle} onClick={() => onTeam && onTeam(m.home)}>{m.home}</div>
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
        <img className="crest" src={crestFor(m.away, m.awayColors, m.awayCrest)}
          onError={(e) => (e.target.src = crestFor(m.away, m.awayColors, null))}
          onClick={() => onTeam && onTeam(m.away)} style={nameStyle} />
        <div style={{ minWidth: 0 }}>
          <div className="tn" style={nameStyle} onClick={() => onTeam && onTeam(m.away)}>{m.away}</div>
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

export default function MatchDetail({ m, bankroll, onBack, onTeam }) {
  const [ouL, setOuL] = useState(2.5);
  const [hcL, setHcL] = useState(-0.5);
  const [vSel, setVSel] = useState("1");
  const [vOdds, setVOdds] = useState(2.0);
  const [copied, setCopied] = useState(false);

  const conf = confidence(m);
  const cd = m.finished ? "" : countdown(m.kickoff);
  const surprise = isSurprise(m);
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
        <Teams m={m} onTeam={onTeam} />
        <div className="chips" style={{ justifyContent: "center" }}>
          {cd && <span className="countdown">⏱ {cd}</span>}
          {conf && !m.finished && (
            <span className="chip" title={`Confianza ${conf.label} · favorito al ${conf.mx}%`}>
              Confianza <span className="conf-stars">{[1, 2, 3].map((i) => <span key={i} className={i <= conf.stars ? "on" : "off"}>★</span>)}</span>
            </span>
          )}
          {surprise && !m.finished && <span className="pill y" title="El favorito del modelo no coincide con el del mercado">⚡ Sorpresa</span>}
          <button className="mini" onClick={share}>{copied ? "✓ Copiado" : "🔗 Compartir"}</button>
        </div>
      </div>

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
        <div className="card">
          <div className="lbl">📝 Análisis previo</div>
          {m.preview.split(/\n+/).filter(Boolean).map((par, i) => (
            <p key={i} style={{ margin: "0 0 8px", lineHeight: 1.55, color: "var(--text)" }}>{par}</p>
          ))}
          <p className="note" style={{ color: "var(--muted)", marginTop: 4 }}>Redactado por IA (Gemini) a partir de los números del modelo. No es información de fuentes; interpreta los datos.</p>
        </div>
      )}

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
          <div className="card">
            <div className="lbl">{m.finished ? "1X2 que daba el modelo" : "Resultado 1X2"}{m.calibrated && <span className="dim" title="Probabilidad del modelo mezclada con la del mercado (calibrada)"> · calibrado</span>}</div>
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
            </div>
            <div className="lbl">Mapa de marcadores (local ↓ / visitante →)</div>
            <Heat M={M} />
          </div>

          {!m.finished && (<>
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
          </>)}

          {m.statsReal ? (
            <div className="card">
              <div className="lbl">Estadísticas: real vs esperado</div>
              <table>
                <thead><tr><th>Métrica</th><th>Local</th><th>Visit.</th></tr></thead>
                <tbody>
                  {[["goals", "Goles"], ["shots", "Remates"], ["sot", "Tiros a puerta"], ["corners", "Córners"],
                    ["fouls", "Faltas"], ["yellows", "Amarillas"], ["reds", "Rojas"]]
                    .filter(([k]) => m.statsReal[k]).map(([k, lab]) => (
                      <tr key={k}>
                        <td>{lab}</td>
                        <td>{m.statsReal[k].home}{m.stats?.[k] && Math.abs(m.stats[k].home - m.statsReal[k].home) >= 0.5 ? <span className="dim"> · esp {m.stats[k].home}</span> : null}</td>
                        <td>{m.statsReal[k].away}{m.stats?.[k] && Math.abs(m.stats[k].away - m.statsReal[k].away) >= 0.5 ? <span className="dim"> · esp {m.stats[k].away}</span> : null}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <p className="note" style={{ color: "var(--muted)" }}>Reales (co.uk) frente a lo que esperaba el modelo. Fuente de stats con ~1 día de retraso.</p>
            </div>
          ) : m.stats && (
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
