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
export function photoForPlayer(row) {
  // No fuzzy matching here: caller must have an exact identity match first.
  return safePlayerPhoto(row?.profile?.photo || row?.photo || null);
}
