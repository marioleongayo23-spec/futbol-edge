import { crestFor } from "./feed";
import PlayerAvatar from "./PlayerAvatar";
import { photoForPlayer } from "./mediaIdentity.js";
import { analyseLineup, confirmedLineup, lineupPlayerRecord } from "./lineupVisualData.js";
import "./lineup-v3.css";

const short = name => {
  const words=String(name||"").split(/\s+/).filter(Boolean);
  return words.length > 1 ? words.at(-1) : (words[0] || "?");
};
function PlayerSlot({ row, team, players, onPlayer }) {
  const record = lineupPlayerRecord(players, row.name, team);
  const photo = photoForPlayer(record);
  const candidate = record || { player:row.name, team, position:row.position || null };
  const content = <>
    <PlayerAvatar name={row.name} src={photo} />
    <span className="lineup-v3-name">{short(row.name)}</span>
    {row.position && <small className="lineup-v3-pos">{row.position}</small>}
  </>;
  return onPlayer
    ? <button type="button" onClick={() => onPlayer(candidate)} className="lineup-v3-slot" title={row.name}
        aria-label={`Ver ficha de ${row.name}, ${team}`}>{content}</button>
    : <div className="lineup-v3-slot" title={row.name}>{content}</div>;
}
function Half({ side, team, crest, colors, data, players, onPlayer }) {
  const isHome=side==="home";
  const orientedRows = isHome ? data.rows : data.rows.slice().reverse();
  return (
    <section className={"lineup-v3-half "+side} aria-label={`Alineación de ${team}`}>
      {data.canPlot
        ? orientedRows.map((line, i) => <div className="lineup-v3-row" key={i}>
          {line.map(p => <PlayerSlot key={p.index} row={p} team={team} players={players} onPlayer={onPlayer}/>)}
        </div>)
        : <div className="lineup-v3-list">
          {data.roster.length
            ? data.roster.map(p => <PlayerSlot key={p.index} row={p} team={team} players={players} onPlayer={onPlayer}/>)
            : <span className="lineup-v3-missing">Sin jugadores confirmados</span>}
        </div>}
      <div className="lineup-v3-team">
        <img src={crestFor(team,colors,crest)} alt="" loading="lazy"
          onError={e => { e.currentTarget.onerror=null; e.currentTarget.src=crestFor(team,colors,null); }}/>
        <div><strong>{team}</strong><span>{data.count}/11 jugadores {data.canPlot ? "· posiciones disponibles" : "· distribución no verificada"}</span></div>
      </div>
    </section>
  );
}
export default function LineupBoard({ match, lineup, players, onPlayer }) {
  const home=analyseLineup(lineup.local,lineup.posiciones_local);
  const away=analyseLineup(lineup.visitante,lineup.posiciones_visitante);
  const official=confirmedLineup(lineup);
  const verifiedPositions=home.canPlot&&away.canPlot;
  return (
    <div className="lineup-v3" data-testid="lineup-board">
      <div className="lineup-v3-heading">
        <div><span className="lineup-v3-eyebrow">MATCHDAY · PLAYER INTELLIGENCE</span>
          <h3>Alineaciones <span className={official?"lineup-v3-label official":"lineup-v3-label"}>{official?"XI oficial":lineup.status==="probable"?"Probable":"No confirmado"}</span></h3></div>
        <p>{verifiedPositions?"Posiciones registradas en el feed":"Cuando faltan posiciones fiables mostramos la lista sin inventar un dibujo táctico."}</p>
      </div>
      <div className={"lineup-v3-pitch"+(verifiedPositions?"":" lineup-v3-unpositioned")}>
        <div className="lineup-v3-markings" aria-hidden="true"><i/><span/></div>
        <Half side="home" team={match.home} crest={match.homeCrest} colors={match.homeColors} data={home} players={players} onPlayer={onPlayer}/>
        <div className="lineup-v3-midline" aria-hidden="true"><span/></div>
        <Half side="away" team={match.away} crest={match.awayCrest} colors={match.awayColors} data={away} players={players} onPlayer={onPlayer}/>
      </div>
      {(!home.full||!away.full)&&<p className="lineup-v3-warning" role="status">
        Alineación incompleta: {match.home} {home.count}/11 · {match.away} {away.count}/11. No se presenta como XI confirmado.</p>}
      {(home.duplicates > 0 || away.duplicates > 0) && <p className="lineup-v3-warning" role="status">Se han omitido nombres duplicados hasta verificar los datos.</p>}
      <p className="lineup-v3-footnote">Pulsa un jugador para abrir su ficha. Las imágenes aparecen solo cuando coincide la identidad completa con el equipo.</p>
    </div>
  );
}
