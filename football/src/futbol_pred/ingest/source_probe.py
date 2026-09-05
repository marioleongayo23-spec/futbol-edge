"""Probe READ-ONLY de fuentes de datos candidatas: SofaScore, BeSoccer y
FlashScore.

No integra NADA en el feed. Solo intenta acceder a cada fuente y reporta —en
stdout y en ``data/source_probe_report.json``— qué se puede sacar realmente:
acceso (público / muro / requiere key) y catálogo de campos valiosos (árbitro,
notas de jugador, xG, bajas, estadísticas detalladas, momentum, cuotas).

Por qué así: el proxy del entorno de desarrollo bloquea estos hosts, de modo
que la verificación tiene que ser empírica desde el cron (salida abierta), igual
que el scraper de árbitros por Google News. Este módulo se ejecuta con
``python -m futbol_pred.ingest.source_probe`` desde un workflow propio y nunca
lanza: cualquier fallo se captura y se refleja en el informe.

Solo stdlib (urllib) para no depender de instalar paquetes en el workflow.
"""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_COMMON = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def _get(url: str, headers: dict | None = None, timeout: int = 15) -> dict:
    """GET defensivo. Devuelve un dict con status/latencia/cuerpo; nunca lanza."""

    hdrs = dict(_COMMON)
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    ctx = ssl.create_default_context()
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read()
            return {
                "url": url,
                "ok": True,
                "status": getattr(resp, "status", 200),
                "ms": int((time.time() - t0) * 1000),
                "len": len(body),
                "ctype": resp.headers.get("Content-Type"),
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        snippet = b""
        try:
            snippet = exc.read()[:1500]
        except Exception:
            pass
        return {
            "url": url,
            "ok": False,
            "status": exc.code,
            "ms": int((time.time() - t0) * 1000),
            "len": len(snippet),
            "reason": str(exc.reason),
            "body": snippet,
        }
    except Exception as exc:  # timeout, DNS, TLS, reset…
        return {
            "url": url,
            "ok": False,
            "status": None,
            "ms": int((time.time() - t0) * 1000),
            "error": type(exc).__name__,
            "detail": str(exc)[:200],
        }


def _as_json(res: dict):
    if not res.get("ok") or not res.get("body"):
        return None
    try:
        return json.loads(res["body"].decode("utf-8", "replace"))
    except Exception:
        return None


def _brief(res: dict) -> dict:
    """Resumen serializable de una respuesta (sin el cuerpo binario)."""

    out = {k: res.get(k) for k in ("url", "ok", "status", "ms", "len", "ctype",
                                   "reason", "error", "detail")}
    return {k: v for k, v in out.items() if v is not None}


# --------------------------------------------------------------------------- #
# Summarizers PUROS (testeables sin red): reciben JSON ya parseado.
# --------------------------------------------------------------------------- #
def summarize_sofascore_event(detail: dict, lineups: dict, statistics: dict) -> dict:
    """Qué campos valiosos trae SofaScore para un partido concreto."""

    found = {}
    ev = (detail or {}).get("event") or {}
    ref = ev.get("referee") or {}
    if ref.get("name"):
        found["referee"] = ref.get("name")
    if ev.get("homeTeam", {}).get("name") and ev.get("awayTeam", {}).get("name"):
        found["match"] = f"{ev['homeTeam']['name']} vs {ev['awayTeam']['name']}"

    lu = lineups or {}
    players = []
    for side in ("home", "away"):
        players += (lu.get(side) or {}).get("players") or []
    if lu.get("confirmed") is not None:
        found["lineups_confirmed"] = lu.get("confirmed")
    if players:
        found["lineup_players"] = len(players)
        rated = [p for p in players
                 if isinstance(p.get("statistics"), dict)
                 and p["statistics"].get("rating") is not None]
        if rated:
            sample = rated[0]
            found["player_ratings"] = True
            found["player_rating_sample"] = {
                "player": (sample.get("player") or {}).get("name"),
                "rating": sample["statistics"].get("rating"),
            }
        # bajas / ausencias
        missing = [p for p in players if p.get("missing") or p.get("reason")]
        if any((lu.get(s) or {}).get("missingPlayers") for s in ("home", "away")):
            found["missing_players"] = True
        formations = [(lu.get(s) or {}).get("formation") for s in ("home", "away")]
        if any(formations):
            found["formations"] = [f for f in formations if f]

    stats = (statistics or {}).get("statistics") or []
    groups = []
    xg = None
    for period in stats:
        if period.get("period") != "ALL":
            continue
        for group in period.get("groups") or []:
            groups.append(group.get("groupName"))
            for item in group.get("statisticsItems") or []:
                name = (item.get("name") or "").lower()
                if "expected goals" in name or item.get("key") == "expectedGoals":
                    xg = {"home": item.get("home"), "away": item.get("away")}
    if groups:
        found["stat_groups"] = [g for g in groups if g]
    if xg:
        found["xg"] = xg
    return found


def summarize_flashscore(feed_res: dict) -> dict:
    body = feed_res.get("body") or b""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    return {
        "status": feed_res.get("status"),
        "len": feed_res.get("len"),
        # el feed propietario usa separadores tipo ¬ y ~ (ofuscado, no JSON)
        "looks_like_fs_feed": ("¬" in text or "÷" in text or "~" in text),
        "looks_like_json": text.strip()[:1] in ("{", "["),
        "sample": text[:220],
    }


# --------------------------------------------------------------------------- #
# Probes por fuente (hacen red; llaman a los summarizers puros).
# --------------------------------------------------------------------------- #
def probe_sofascore() -> dict:
    report = {"source": "sofascore", "endpoints": [], "data_available": {}, "verdict": ""}
    base = "https://api.sofascore.com/api/v1"

    live = _get(f"{base}/sport/football/events/live")
    report["endpoints"].append(_brief(live))
    live_json = _as_json(live)
    if live_json is not None:
        report["data_available"]["live_events"] = len(live_json.get("events") or [])

    # LaLiga = unique-tournament 8. Buscamos la temporada vigente y un partido.
    event_id = None
    seasons = _get(f"{base}/unique-tournament/8/seasons")
    report["endpoints"].append(_brief(seasons))
    sj = _as_json(seasons)
    if sj and sj.get("seasons"):
        sid = sj["seasons"][0].get("id")
        for slot in ("next", "last"):
            nxt = _get(f"{base}/unique-tournament/8/season/{sid}/events/{slot}/0")
            report["endpoints"].append(_brief(nxt))
            nj = _as_json(nxt)
            evs = (nj or {}).get("events") or []
            if evs:
                event_id = evs[-1].get("id")
                break

    if event_id:
        report["probe_event_id"] = event_id
        detail = _get(f"{base}/event/{event_id}")
        lineups = _get(f"{base}/event/{event_id}/lineups")
        stats = _get(f"{base}/event/{event_id}/statistics")
        odds = _get(f"{base}/event/{event_id}/odds/1/all")
        for r in (detail, lineups, stats, odds):
            report["endpoints"].append(_brief(r))
        report["data_available"].update(
            summarize_sofascore_event(_as_json(detail) or {},
                                      _as_json(lineups) or {},
                                      _as_json(stats) or {})
        )
        odds_json = _as_json(odds)
        if odds_json and odds_json.get("markets"):
            report["data_available"]["odds_markets"] = len(odds_json["markets"])

    ok = any(e.get("ok") and e.get("status") == 200 for e in report["endpoints"])
    report["accessible"] = ok
    report["verdict"] = (
        "API pública accesible; " + ", ".join(sorted(report["data_available"]))
        if ok and report["data_available"]
        else "sin acceso (posible Cloudflare/403 desde datacenter) — ver endpoints"
    )
    return report


def probe_besoccer() -> dict:
    report = {"source": "besoccer", "endpoints": [], "verdict": ""}
    web = _get("https://www.besoccer.com/")
    report["endpoints"].append(_brief(web))
    # API oficial: requiere key; sin ella debe responder 401/403/400.
    api = _get("https://api.besoccer.com/scraper/matches")
    report["endpoints"].append(_brief(api))
    web_ok = web.get("ok") and web.get("status") == 200
    report["accessible_web"] = bool(web_ok)
    report["api_needs_key"] = api.get("status") in (400, 401, 403)
    if web_ok:
        report["verdict"] = "web accesible (revisar si trae árbitro/alineaciones en HTML)"
    elif web.get("status") == 406:
        report["verdict"] = "web con WAF (406, fingerprint) — solo API de pago con key"
    else:
        report["verdict"] = f"web status={web.get('status')} — probable muro; API requiere key"
    return report


def probe_flashscore() -> dict:
    report = {"source": "flashscore", "endpoints": [], "verdict": ""}
    home = _get("https://www.flashscore.com/")
    report["endpoints"].append(_brief(home))
    # Feed propietario: requiere la cabecera x-fsign (valor público conocido).
    feed = _get(
        "https://www.flashscore.com/x/feed/f_1_0_3_es_1",
        headers={"x-fsign": "SW9D1eZo", "Referer": "https://www.flashscore.com/"},
    )
    report["endpoints"].append(_brief(feed))
    report["feed"] = summarize_flashscore(feed)
    report["accessible"] = bool(feed.get("ok") and feed.get("status") == 200)
    if report["accessible"] and report["feed"].get("looks_like_fs_feed"):
        report["verdict"] = "feed accesible pero OFUSCADO (parser propietario ¬÷~, alto coste)"
    elif report["accessible"]:
        report["verdict"] = "feed responde; revisar formato"
    else:
        report["verdict"] = f"feed status={feed.get('status')} — bloqueado o requiere token dinámico"
    return report


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    print(f"[probe] inicio {started}")
    report = {"generated_at": started, "sources": {}}
    for name, fn in (("sofascore", probe_sofascore),
                     ("besoccer", probe_besoccer),
                     ("flashscore", probe_flashscore)):
        try:
            res = fn()
        except Exception as exc:  # el probe jamás debe tumbar el workflow
            res = {"source": name, "error": type(exc).__name__, "detail": str(exc)[:200]}
        report["sources"][name] = res
        print(f"\n===== {name.upper()} =====")
        print(f"[probe] veredicto: {res.get('verdict') or res.get('error')}")
        for ep in res.get("endpoints", []):
            print(f"[probe]   {ep.get('status')}  {ep.get('ms')}ms  {ep.get('url')}"
                  + (f"  ({ep.get('error') or ep.get('reason')})" if not ep.get('ok') else ""))
        da = res.get("data_available")
        if da:
            print(f"[probe]   data: {json.dumps(da, ensure_ascii=False)}")
        if res.get("feed"):
            print(f"[probe]   feed: {json.dumps(res['feed'], ensure_ascii=False)[:400]}")

    try:
        with open("data/source_probe_report.json", "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print("\n[probe] informe escrito en data/source_probe_report.json")
    except Exception as exc:
        print(f"\n[probe] no se pudo escribir el informe: {exc}")
    print("[probe] fin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
