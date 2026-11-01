/** Read-only media coverage report. Does not fetch or redistribute any photo. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { analyseLineup, confirmedLineup } from "../src/lineupVisualData.js";
import { safePlayerPhoto } from "../src/mediaIdentity.js";
const path = process.argv[2] || fileURLToPath(new URL("../../football/data/dashboard.json",import.meta.url));
const feed = JSON.parse(readFileSync(path, "utf8"));
const matches = Array.isArray(feed.matches)?feed.matches:[];
const players = Object.values(feed.players||{}).flatMap(g=>Array.isArray(g?.players)?g.players:[]);
const withLineup=matches.filter(m=>m.alineacion);
const providedPhotos=players.map(p=>p.profile?.photo||p.photo).filter(x=>typeof x==="string"&&x.trim());
const photoHosts=providedPhotos.reduce((result,value)=>{
  let host="invalid";
  try {host=new URL(value).hostname||"invalid";} catch {host="invalid";}
  result[host]=(result[host]||0)+1;
  return result;
},{});
const report={
 generated_at:feed.generated_at || null,
 matches:matches.length,
 fixtures_with_both_crests:matches.filter(m=>m.homeCrest&&m.awayCrest).length,
 fixtures_with_lineup:withLineup.length,
 complete_lineups:withLineup.filter(m=>analyseLineup(m.alineacion.local).full&&analyseLineup(m.alineacion.visitante).full).length,
 official_complete_lineups:withLineup.filter(m=>confirmedLineup(m.alineacion)).length,
 positionally_verified_both:withLineup.filter(m=>analyseLineup(m.alineacion.local,m.alineacion.posiciones_local).canPlot&&
   analyseLineup(m.alineacion.visitante,m.alineacion.posiciones_visitante).canPlot).length,
 lineups_with_duplicate_names:withLineup.filter(m=>analyseLineup(m.alineacion.local).duplicates||analyseLineup(m.alineacion.visitante).duplicates).length,
 rich_player_records:players.length,
 rich_players_with_photo_field:providedPhotos.length,
 photo_origin_hosts:photoHosts,
 rich_players_with_safe_photo:players.filter(p=>safePlayerPhoto(p.profile?.photo || p.photo)).length,
};
console.log("EDGE_VISUAL_COVERAGE_JSON="+JSON.stringify(report));
