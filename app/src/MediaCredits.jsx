import { photoCreditForPlayer } from "./mediaIdentity.js";

/** Credits next to each group of CC-licensed Wikimedia portraits. */
export default function MediaCredits({ players=[] }) {
 const credits=Array.from(new Map(players.map(photoCreditForPlayer)
   .filter(Boolean).map(c=>[c.source_url,c])).values());
 if(!credits.length)return null;
 return (
  <details className="edge-media-credits">
   <summary>Créditos de fotografías ({credits.length}) · Wikimedia Commons</summary>
   <ul>
    {credits.map(c=><li key={c.source_url}>
      <strong>{c.player}</strong> · {c.author} ·
      <a href={c.source_url} target="_blank" rel="noopener noreferrer">Archivo original</a> ·
      <a href={c.license_url} target="_blank" rel="noopener noreferrer">{c.license}</a>
      <small>{c.modifications}</small>
    </li>)}
   </ul>
  </details>
 );
}
