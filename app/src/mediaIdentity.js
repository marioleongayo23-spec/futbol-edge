import mediaCatalog from "./verifiedPlayerMedia.js";

/** No arbitrary host can become an image source in the browser. */
const HOSTS=new Set(["media.api-sports.io","upload.wikimedia.org","commons.wikimedia.org","r2.thesportsdb.com","www.thesportsdb.com"]);
const LICENSES=new Set([
 "https://creativecommons.org/licenses/by/3.0/",
 "https://creativecommons.org/licenses/by/4.0/",
 "https://creativecommons.org/licenses/by-sa/3.0/",
 "https://creativecommons.org/licenses/by-sa/4.0/",
 "https://creativecommons.org/publicdomain/zero/1.0/",
 "https://creativecommons.org/publicdomain/mark/1.0/",
]);
export function safePlayerPhoto(value) {
 if(typeof value!=="string"||value.length>1500)return null;
 try{const url=new URL(value);
  if(url.protocol!=="https:"||!HOSTS.has(url.hostname)||url.username||url.password)return null;
  return url.href;
 }catch{return null;}
}
export function initials(name) {
 const words=String(name||"").trim().split(/\s+/).filter(Boolean);
 return (words.length?[words[0][0],...(words.length>1?[words.at(-1)[0]]:[])]:["?"]).join("").toLocaleUpperCase("es");
}
export function normalizeIdentity(value) {
 return String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
}

/** Accept only a unique curated full player name AND complete club identity. */
export function licensedPhotoRecord(row) {
 const player=normalizeIdentity(row?.player||row?.jugador||row?.name);
 const team=normalizeIdentity(row?.team||row?.equipo);
 if(!player||!team)return null;
 const matches=(mediaCatalog.entries||[]).filter(entry=>
  normalizeIdentity(entry.player)===player &&
  (entry.teams||[]).some(t=>normalizeIdentity(t)===team) &&
  safePlayerPhoto(entry.image_url) &&
  typeof entry.author==="string" && entry.author.length>0 &&
  typeof entry.source_url==="string" &&
  entry.source_url.startsWith("https://commons.wikimedia.org/wiki/File:") &&
  LICENSES.has(entry.license_url));
 return matches.length===1?matches[0]:null;
}
export function photoCreditForPlayer(row) {
 const record=licensedPhotoRecord(row);
 return record?{
  player:record.player,author:record.author,license:record.license,
  license_url:record.license_url,source_url:record.source_url,
  modifications:record.modifications
 }:null;
}
export function photoForPlayer(row) {
 const curated=licensedPhotoRecord(row);
 return curated?.image_url||safePlayerPhoto(row?.profile?.photo||row?.photo||null);
}
