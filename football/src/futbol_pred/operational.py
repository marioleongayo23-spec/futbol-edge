"""Control operativo: onces oficiales, completitud y alertas del feed."""
from __future__ import annotations

from datetime import datetime
import re
import unicodedata
from zoneinfo import ZoneInfo

from .ingest.api_football import ApiFootballClient
from .ingest.api_football_players import fetch_team_player_rates, props_for_official_starters
from .ingest.lineups_ai import _best_props, _fallback_props, _formation
from .model.state_simulator import simulate_match_states

MADRID = ZoneInfo("Europe/Madrid")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=MADRID)


def _parse(value) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(str(value))).astimezone(MADRID)
    except (TypeError, ValueError):
        return None


def _key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _side_for(team: str, home: str, away: str) -> str | None:
    target = _key(team)
    if target and (target in _key(home) or _key(home) in target): return "local"
    if target and (target in _key(away) or _key(away) in target): return "visitante"
    return None


def _league_id(match: dict) -> int | None:
    label = str(match.get("league") or "").casefold()
    if "hypermotion" in label or "segunda" in label: return 141
    if "champions" in label or "ucl" in label: return 2
    if "laliga" in label or "primera" in label: return 140
    return None


def _season_for(match: dict, kickoff: datetime) -> int:
    try:
        season = int(match.get("season"))
        if 2000 <= season <= 2100: return season
    except (TypeError, ValueError):
        pass
    local = _aware(kickoff).astimezone(MADRID)
    return local.year if local.month >= 7 else local.year - 1


def _real_props(client, match, team, starters, kickoff):
    try:
        rates = fetch_team_player_rates(client, team, _season_for(match, kickoff), _league_id(match), 2)
        props = props_for_official_starters(starters, rates, 5)
        return props if len(props) >= 3 else None
    except Exception:
        return None


def _starter_props(existing, starters, side, match):
    wanted = {_key(n) for n in starters}
    kept = [r for r in (existing or []) if _key(r.get("jugador")) in wanted]
    return kept[:5] if len(kept) >= 3 else _fallback_props(starters, side, match)


def _merge_absences(lineup, match, absences, now):
    if not lineup or not absences: return
    for side, team in (("local", match.get("home", "")), ("visitante", match.get("away", ""))):
        rows = [dict(x, source_updated_at=now.isoformat()) for x in absences if _side_for(x.get("team", ""), team, "") == "local"]
        if rows:
            lineup[f"disponibilidad_{side}"] = rows
            lineup[f"bajas_{side}"] = [f"{x['jugador']} ({x['detalle']})" for x in rows]


def attach_official_context(matches: list[dict], now: datetime, client: ApiFootballClient | None = None, limit: int = 8) -> int:
    client = client or ApiFootballClient()
    if client.offline: return 0
    now_local = _aware(now).astimezone(MADRID)
    candidates = []
    for match in matches:
        ko = _parse(match.get("kickoff"))
        if not ko or ko.date() != now_local.date(): continue
        delta = (ko - now_local).total_seconds()
        lineup = match.get("alineacion") or {}
        polled = _parse(lineup.get("official_poll_at"))
        if -10800 <= delta <= 7200 and lineup.get("status") != "confirmado" and not (polled and (now_local-polled).total_seconds() < 2700):
            candidates.append((ko, match))
    resolved = []
    for ko, match in sorted(candidates, key=lambda x: x[0])[:limit]:
        fixture = client.find_fixture(match.get("home", ""), match.get("away", ""), ko)
        fid = ((fixture or {}).get("fixture") or {}).get("id")
        if fid: resolved.append((ko, match, int(fid), fixture))
    details = client.get_fixture_details([x[2] for x in resolved]) if hasattr(client, "get_fixture_details") else {}
    updated = 0
    for ko, match, fid, fixture in resolved:
        detail = details.get(fid) or fixture
        official = client.lineup_from_fixture(detail) if hasattr(client, "lineup_from_fixture") and details else client.get_official_lineup(fid)
        absences = client.get_absences(fid)
        old = match.get("alineacion") or {}
        old["official_poll_at"] = now_local.isoformat(); match["alineacion"] = old
        if hasattr(client, "fixture_context"):
            ctx = client.fixture_context(detail)
            if ctx:
                ctx["source_updated_at"] = now_local.isoformat(); match["official_context"] = ctx
        if not official:
            _merge_absences(old, match, absences, now_local); continue
        by_side = {}
        for team in official:
            side = _side_for(team.get("team", ""), match.get("home", ""), match.get("away", ""))
            if side: by_side[side] = team
        if set(by_side) != {"local", "visitante"}: continue
        local = [x["name"] for x in by_side["local"]["starters"]]; visitor = [x["name"] for x in by_side["visitante"]["starters"]]
        pl = _real_props(client, match, match.get("home", ""), local, ko); pv = _real_props(client, match, match.get("away", ""), visitor, ko)
        kl = pl or _starter_props(old.get("clave_local"), local, "home", match); kv = pv or _starter_props(old.get("clave_visitante"), visitor, "away", match)
        real_n = (len(pl) if pl else 0) + (len(pv) if pv else 0)
        src = "API-Football · players" if pl and pv else "mixta: API-Football + fallback" if pl or pv else "fallback estadístico/IA"
        pos_l = [x["position"] for x in by_side["local"]["starters"]]; pos_v = [x["position"] for x in by_side["visitante"]["starters"]]
        stamp = now_local.isoformat()
        lineup = {**old, "local": local, "visitante": visitor, "posiciones_local": pos_l, "posiciones_visitante": pos_v,
            "formacion_local": by_side["local"].get("formation") or _formation(pos_l), "formacion_visitante": by_side["visitante"].get("formation") or _formation(pos_v),
            "positions_inferred": False, "clave_local": kl, "clave_visitante": kv, "best_props": _best_props(kl, kv), "status": "confirmado",
            "provider": "API-Football", "model": "alineación oficial", "fuente": "API-Football · fixtures/lineups", "player_props_source": src,
            "source_updated_at": stamp, "generated_at": stamp, "ts": stamp, "official_fixture_id": fid,
            "quality": {"complete": True, "lineup_players": 22, "positions_players": 22, "props_players": len(kl)+len(kv), "score": 1.0, "official": True, "real_player_props": real_n, "player_props_source": src}}
        _merge_absences(lineup, match, absences, now_local); match["alineacion"] = lineup; updated += 1
    return updated


def content_audit(matches, players, now):
    today = _aware(now).astimezone(MADRID).date(); team_players = set()
    for bucket in (players or {}).values():
        for row in bucket.get("players") or []:
            if row.get("team") and row.get("player"): team_players.add(_key(row["team"]))
    checked, incomplete = 0, []
    for match in matches:
        ko = _parse(match.get("kickoff"))
        if not ko or ko.date() != today: continue
        checked += 1; reasons = []; lineup = match.get("alineacion") or {}
        if len(str(match.get("preview") or "").split()) < 90: reasons.append("previa")
        if len(lineup.get("local") or []) != 11 or len(lineup.get("visitante") or []) != 11: reasons.append("once")
        if len(lineup.get("posiciones_local") or []) != 11 or len(lineup.get("posiciones_visitante") or []) != 11: reasons.append("posiciones")
        if len(lineup.get("clave_local") or []) < 3 or len(lineup.get("clave_visitante") or []) < 3: reasons.append("props")
        if _key(match.get("home")) not in team_players or _key(match.get("away")) not in team_players: reasons.append("jugadores")
        if reasons: incomplete.append({"id": match.get("id"), "partido": f"{match.get('home')} - {match.get('away')}", "missing": reasons})
    local = _aware(now).astimezone(MADRID)
    return {"window": f"{local.hour:02d}:15" if local.hour in {0,10} else "continuo", "checked_at": local.isoformat(), "matches_today": checked,
            "complete": checked-len(incomplete), "incomplete": incomplete, "status": "ok" if not incomplete else "warning"}


def _lineup_side_impact(lineup, side):
    props = [r for r in lineup.get(f"clave_{side}") or [] if isinstance(r, dict)]; availability = [r for r in lineup.get(f"disponibilidad_{side}") or [] if isinstance(r, dict)]
    minutes = [float(r["min"]) for r in props if r.get("min") is not None]; starts = [float(r["tit"]) for r in props if r.get("tit") is not None]; attack = []
    for r in props:
        try: attack.append((3*float(r.get("g",0))+2*float(r.get("a",0))+float(r.get("r",0))+1.5*float(r.get("rp",0)))*min(1,float(r.get("min",0))/90)*min(1,float(r.get("tit",0))))
        except (TypeError,ValueError): pass
    penalty = 0.0; official = 0
    for r in availability:
        state = str(r.get("estado") or "").casefold(); is_official = bool(r.get("official")); official += int(is_official); weight = 1.5 if "duda" in state or "doubt" in state else 2.0
        if any(x in state for x in ("sanc","susp","les","injur")): weight = 3.0
        elif "rota" in state: weight = 1.0
        penalty += weight if is_official else weight*.35
    return {"key_players":len(props),"expected_minutes_avg":round(sum(minutes)/len(minutes),1) if minutes else None,"starter_probability_avg_pct":round(100*sum(starts)/len(starts)) if starts else None,
            "attack_presence_index":round(sum(attack),2) if attack else None,"listed_absences":len(availability),"official_absences":official,"confidence_penalty_pp":round(min(12,penalty),1)}


def lineup_impact(lineup):
    home = _lineup_side_impact(lineup,"local"); away = _lineup_side_impact(lineup,"visitante"); status = lineup.get("status") or "estimado"
    total = min(20,{"confirmado":0,"probable":2,"estimado":5}.get(status,5)+home["confidence_penalty_pp"]+away["confidence_penalty_pp"])
    edge = round(home["attack_presence_index"]-away["attack_presence_index"],2) if home["attack_presence_index"] is not None and away["attack_presence_index"] is not None else None
    return {"status":status,"evidence":"alta" if status=="confirmado" else "media" if status=="probable" else "baja","home":home,"away":away,"attack_presence_edge":edge,
            "confidence_penalty_pp":round(total,1),"probability_adjustment":"not_applied","method":"minutos × probabilidad de titularidad × producción observada; las bajas oficiales penalizan confianza. No altera el 1X2 sin validación histórica."}


def attach_state_simulations(matches):
    n=0
    for match in matches:
        xg=match.get("xg")
        if match.get("finished") or not isinstance(xg,list) or len(xg)!=2: continue
        try:
            weather=match.get("weather") or {}; yellows=((match.get("stats") or {}).get("yellows") or {}).get("total")
            match["state_simulation"]=simulate_match_states(float(xg[0]),float(xg[1]),seed=match.get("id") or match.get("kickoff") or "match",temperature_c=float(weather["temperature_c"]) if weather.get("temperature_c") is not None else None,expected_yellows=float(yellows) if yellows is not None else None); n+=1
        except (TypeError,ValueError): pass
    return n


def annotate_prediction_context(matches):
    for match in matches:
        probs=match.get("probs")
        if not isinstance(probs,list) or len(probs)!=3: continue
        lineup=match.get("alineacion") or {}; impact=lineup_impact(lineup) if lineup else None
        if impact: match["lineup_impact"]=impact
        trends=match.get("tendencias") or {}; tactical=match.get("tactical_matchup") or {}; weather=match.get("weather") or {}; heat=weather.get("heat_stress") or {}
        components=(match.get("model_meta") or {}).get("components") or {}; dc=components.get("dixon_coles") or {}; elo=components.get("elo") or {}
        disagreement=max((abs(float(dc.get(k,0))-float(elo.get(k,0))) for k in ("1","X","2")),default=0); penalty=min(20,(impact.get("confidence_penalty_pp",5) if impact else 5)+(4 if heat.get("level")=="alto" else 0)); score=max(0,min(100,round(max(probs)+35-disagreement*100-penalty)))
        evidence={"probabilities":True,"model_agreement":bool(components),"form_and_splits":bool(trends),"tactical_profile":bool(tactical),"lineup":bool(lineup),"official_lineup":lineup.get("status")=="confirmado","weather":bool(weather),"market_odds":isinstance(match.get("odds"),dict)}
        weights={"probabilities":25,"model_agreement":20,"form_and_splits":15,"tactical_profile":15,"lineup":10,"official_lineup":5,"weather":5,"market_odds":5}; completeness=sum(weights[k] for k,v in evidence.items() if v)
        match["prediction_confidence"]={"score":score,"level":"alta" if score>=72 else "media" if score>=55 else "baja","model_disagreement_pp":round(disagreement*100,1),"availability_penalty_pp":penalty,"data_completeness_pct":completeness,"evidence":evidence}
        factors=[{"factor":"local/visitante","impact":"incluido","detail":"parámetros separados de ataque y defensa en casa/fuera"},{"factor":"fuerza del rival","impact":"incluido","detail":"Dixon-Coles contrastado con Elo"}]
        if lineup.get("player_props_source"): factors.append({"factor":"props de jugadores","impact":"datos reales" if lineup.get("quality",{}).get("real_player_props") else "provisional","detail":lineup["player_props_source"]})
        match["prediction_factors"]=factors
        reasons=[]
        if score<48: reasons.append("confianza insuficiente")
        if disagreement>=.18: reasons.append("desacuerdo alto entre modelos")
        if completeness<55: reasons.append("datos incompletos")
        match["recommendation"]={"decision":"no_pick" if reasons else "eligible","label":"Sin apuesta recomendada" if reasons else "Pronóstico publicable","reasons":reasons,"policy":"abstención automática por incertidumbre o falta de evidencia"}


def build_alerts(previous,audit,ai_events,now):
    alerts=[]; stamp=_aware(now).astimezone(MADRID).isoformat()
    if audit.get("incomplete"): alerts.append({"severity":"critical","code":"today_content_incomplete","message":f"{len(audit['incomplete'])} partido(s) del día siguen incompletos","match_ids":[x["id"] for x in audit["incomplete"]],"at":stamp})
    failed={e.get("provider") for e in ai_events if e.get("status")=="failed"}
    if {"Gemini","Groq"}.issubset(failed): alerts.append({"severity":"critical","code":"all_ai_providers_failed","message":"Fallaron Gemini y Groq; se conserva caché o cálculo local","at":stamp})
    elif failed: alerts.append({"severity":"warning","code":"ai_provider_failed","message":f"Falló {', '.join(sorted(failed))}; el fallback siguió activo","at":stamp})
    old=_parse((previous or {}).get("generated_at"))
    if old and (_aware(now).astimezone(MADRID)-old).total_seconds()>7200: alerts.append({"severity":"warning","code":"previous_feed_stale","message":"El feed anterior tenía más de 2 horas de antigüedad","at":stamp})
    return alerts
