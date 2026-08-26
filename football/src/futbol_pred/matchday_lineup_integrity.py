"""Coherencia determinista del XI en la ventana crítica de partido.

Una alineación probable nunca puede mostrar como titular a un jugador que la
misma fuente oficial marca como baja segura. La prensa/IA intenta resolverlo
primero; esta capa es la última barrera antes de publicar.

Para XI NO oficiales:
- elimina duplicados de disponibilidad;
- detecta titulares que también son baja oficial (lesión/sanción, no mera duda);
- intenta sustituirlos por continuidad del XI oficial más reciente del equipo,
  priorizando la misma línea táctica;
- si no existe un sustituto fiable, publica ``Por confirmar`` en ese hueco en
  vez de afirmar un nombre incompatible;
- rebaja el XI a ``estimado`` tras una reparación determinista;
- recalcula props reales contra el XI ya saneado cuando hay muestra disponible.

El XI oficial siempre tiene prioridad: si API-Football publica 11+11, esta capa
no modifica sus titulares.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import unicodedata

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, _aware, _parse
from .ingest.api_football import ApiFootballClient
from .matchday_probable_refresh import _refresh_props

OUTPUT = DATA_DIR / "dashboard.json"

DEF = {"LI", "DFC", "LD", "CAI", "CAD"}
MID = {"MCD", "MC", "MI", "MD", "MP"}
ATT = {"EI", "ED", "DC"}


def _key(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _position_group(value: str | None) -> str:
    pos = str(value or "").upper()
    if pos == "POR":
        return "POR"
    if pos in DEF:
        return "DEF"
    if pos in MID:
        return "MID"
    if pos in ATT:
        return "ATT"
    return "UNK"


def _dedupe_availability(lineup: dict) -> bool:
    changed = False
    for side in ("local", "visitante"):
        field = f"disponibilidad_{side}"
        rows = lineup.get(field)
        if not isinstance(rows, list):
            continue
        out, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = (
                _key(row.get("jugador") or row.get("player") or row.get("name")),
                str(row.get("estado") or row.get("status") or "").strip().casefold(),
                str(row.get("detalle") or row.get("reason") or "").strip().casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        if len(out) != len(rows):
            lineup[field] = out
            lineup[f"bajas_{side}"] = [
                f"{row.get('jugador') or row.get('player') or row.get('name')} ({row.get('detalle') or row.get('estado') or 'baja'})"
                for row in out
                if row.get("jugador") or row.get("player") or row.get("name")
            ]
            changed = True
    return changed


def _blocked(lineup: dict, side: str) -> dict[str, dict]:
    out = {}
    for row in lineup.get(f"disponibilidad_{side}") or []:
        if not isinstance(row, dict) or not bool(row.get("official")):
            continue
        state = str(row.get("estado") or row.get("status") or "").casefold()
        detail = str(row.get("detalle") or row.get("reason") or "").casefold()
        text = f"{state} {detail}"
        # Questionable/duda no es una exclusión segura; lesión/sanción/missing sí.
        if any(token in text for token in ("duda", "doubt", "question")):
            continue
        name = row.get("jugador") or row.get("player") or row.get("name")
        if _key(name):
            out[_key(name)] = row
    return out


def _side_for_team(match: dict, team_name: str) -> str | None:
    target = _key(team_name)
    if target and target == _key(match.get("home")):
        return "local"
    if target and target == _key(match.get("away")):
        return "visitante"
    return None


def _history_candidates(matches: list[dict], target: dict, team: str) -> list[dict]:
    target_kickoff = _parse(target.get("kickoff"))
    candidates = []
    for match in matches:
        if match is target:
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or (target_kickoff and kickoff >= target_kickoff):
            continue
        lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
        if lineup.get("status") != "confirmado":
            continue
        side = _side_for_team(match, team)
        if not side:
            continue
        names = lineup.get(side) or []
        positions = lineup.get(f"posiciones_{side}") or []
        if len(names) != 11 or len(positions) != 11:
            continue
        candidates.append((kickoff, [
            {"name": str(name), "position": str(positions[index] or "")}
            for index, name in enumerate(names)
        ]))
    candidates.sort(key=lambda item: item[0], reverse=True)
    ordered, seen = [], set()
    for _, rows in candidates[:5]:
        for row in rows:
            key = _key(row["name"])
            if key and key not in seen:
                seen.add(key)
                ordered.append(row)
    return ordered


def _pick_replacement(history: list[dict], used: set[str], blocked: set[str], wanted_position: str) -> dict | None:
    wanted_group = _position_group(wanted_position)
    eligible = [row for row in history if _key(row.get("name")) not in used | blocked]
    exact = [row for row in eligible if str(row.get("position") or "").upper() == str(wanted_position or "").upper()]
    if exact:
        return exact[0]
    same_group = [row for row in eligible if _position_group(row.get("position")) == wanted_group]
    if same_group:
        return same_group[0]
    return eligible[0] if eligible else None


def _repair_side(all_matches: list[dict], match: dict, lineup: dict, side: str) -> list[dict]:
    names = list(lineup.get(side) or [])
    positions = list(lineup.get(f"posiciones_{side}") or [])
    if len(names) != 11 or len(positions) != 11:
        return []
    blocked_rows = _blocked(lineup, side)
    blocked_names = set(blocked_rows)
    if not blocked_names:
        return []
    team = match.get("home") if side == "local" else match.get("away")
    history = _history_candidates(all_matches, match, str(team or ""))
    used = {_key(name) for name in names}
    replacements = []
    for index, name in enumerate(list(names)):
        key = _key(name)
        if key not in blocked_names:
            continue
        wanted_position = positions[index]
        replacement = _pick_replacement(history, used, blocked_names, wanted_position)
        if replacement:
            used.discard(key)
            used.add(_key(replacement["name"]))
            names[index] = replacement["name"]
            if replacement.get("position"):
                positions[index] = replacement["position"]
            replacements.append({
                "side": side,
                "out": name,
                "in": replacement["name"],
                "position": positions[index],
                "reason": "baja oficial + continuidad del último XI oficial",
                "resolved": True,
            })
        else:
            names[index] = "Por confirmar"
            used.discard(key)
            replacements.append({
                "side": side,
                "out": name,
                "in": "Por confirmar",
                "position": wanted_position,
                "reason": "baja oficial sin sustituto histórico fiable",
                "resolved": False,
            })
    lineup[side] = names
    lineup[f"posiciones_{side}"] = positions
    return replacements


def refresh_payload(payload: dict, now: datetime | None = None, client: ApiFootballClient | None = None):
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    all_matches = payload.get("matches") or []
    client = client or ApiFootballClient()
    changed = False
    stats = {"audited": 0, "conflicts": 0, "repaired": 0, "unresolved": 0, "props_recalculated": 0}
    for match in all_matches:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if not -5 <= minutes <= 120:
            continue
        lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else None
        if not lineup:
            continue
        stats["audited"] += 1
        if _dedupe_availability(lineup):
            changed = True
        # XI oficial prevalece sobre cualquier estado previo de lesión.
        if lineup.get("status") == "confirmado":
            lineup.pop("integrity_conflicts", None)
            lineup.pop("integrity_replacements", None)
            match["alineacion"] = lineup
            continue

        replacements = []
        replacements.extend(_repair_side(all_matches, match, lineup, "local"))
        replacements.extend(_repair_side(all_matches, match, lineup, "visitante"))
        if not replacements:
            match["alineacion"] = lineup
            continue

        changed = True
        stats["conflicts"] += len(replacements)
        stats["repaired"] += sum(1 for row in replacements if row["resolved"])
        stats["unresolved"] += sum(1 for row in replacements if not row["resolved"])
        lineup["integrity_replacements"] = replacements
        lineup["integrity_checked_at"] = now_local.isoformat()
        lineup["integrity_conflicts"] = [
            f"{row['out']} figuraba en el XI pese a baja oficial"
            for row in replacements
        ]
        # Una reparación por continuidad histórica es útil, pero ya no es un XI
        # plenamente grounded en prensa para ambos lados: lo publicamos como estimado.
        lineup["status"] = "estimado"
        lineup["lineup_kind"] = "integrity_repaired_estimate"
        lineup["source_quality"] = "official_absence_repaired"
        lineup["display_warning"] = (
            "XI saneado automáticamente contra bajas oficiales; los sustitutos proceden de continuidad de XI oficiales previos."
            if all(row["resolved"] for row in replacements)
            else "XI saneado contra bajas oficiales; queda al menos una posición por confirmar."
        )
        match["alineacion"] = lineup
        # Las props anteriores pueden pertenecer al jugador que acaba de salir.
        if _refresh_props(payload, match, now_local, client):
            stats["props_recalculated"] += 1
        match["updatedAt"] = now_local.isoformat()

    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


def run(path=OUTPUT, now: datetime | None = None):
    previous = load_feed(path)
    if not previous:
        return False, {"error": "feed_missing"}
    candidate = deepcopy(previous)
    changed, stats = refresh_payload(candidate, now=now)
    if not changed:
        return False, stats
    ok, report = write_feed_safely(path, candidate, previous=previous)
    stats["feed_valid"] = bool(ok)
    stats["feed_issues"] = report.get("issues") or []
    return ok, stats


def main():
    ok, stats = run()
    print(json.dumps({"written": ok, **stats}, ensure_ascii=False, sort_keys=True))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
