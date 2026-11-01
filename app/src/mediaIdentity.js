import mediaCatalog from "./verifiedPlayerMedia.js";

/** Media URL policy: never turn arbitrary feed text into a remote image request.
 * Provider-photo usage remains subject to the existing API subscription terms.
 * Curated Wikimedia assets must include credit/license before being cached.
 */
const HOSTS = new Set([
  "media.api-sports.io", "upload.wikimedia.org", "commons.wikimedia.org",
  "r2.thesportsdb.com", "www.thesportsdb.com"
]);
export function safePlayerPhoto(value) {
  if (typeof value !== "string" || value.length > 1500) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !HOSTS.has(url.hostname) || url.username || url.password) return null;
    return url.href;
  } catch { return null; }
}
export function initials(name) {
  const words=String(name||"").trim().split(/\s+/).filter(Boolean);
  return (words.length ? [words[0][0], ...(words.length>1?[words.at(-1)[0]]:[])] : ["?"]).join("").toLocaleUpperCase("es");
}
function normalizeIdentity(value) {
  return String(value || "").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
}

/** An image is eligible only when exactly one approved player AND club match. */
export function licensedPhotoRecord(row) {
  const player=normalizeIdentity(row?.player||row?.jugador||row?.name);
  const team=normalizeIdentity(row?.team||row?.equipo);
  if(!player||!team)return null;
  const matches=(mediaCatalog.entries||[]).filter(entry=>
    normalizeIdentity(entry.player)===player &&
    (entry.teams||[]).some(t=>normalizeIdentity(t)===team) &&
    safePlayerPhoto(entry.image_url) &&
    typeof entry.author==="string" && entry.author.length>0 &&
    entry.source_url?.startsWith("https://commons.wikimedia.org/wiki/File:") &&
    /^https:\\/\\/creativecommons\\.org\\/(?:licenses\\/(?:by|by-sa)\\/(?:3\\.0|4\\.0)\\/|publicdomain\\/(?:zero|mark)\\/1\\.0\\/)$/.test(entry.license_url||"")
  );
  return matches.length===1?matches[0]:null;
}

export function photoCreditForPlayer(row){
  const record=licensedPhotoRecord(row);
  return record ? {
    player:record.player, author:record.author, license:record.license,
    license_url:record.license_url, source_url:record.source_url,
    modifications:record.modifications
  } : null;
}

export function photoForPlayer(row) {
  // Curated Commons files are license-reviewed; provider photos remain only
  // when the existing feed already delivers them for the same rich identity.
  const curated=licensedPhotoRecord(row);
  return curated?.image_url || safePlayerPhoto(row?.profile?.photo || row?.photo || null);
}
