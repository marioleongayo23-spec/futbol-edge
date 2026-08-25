from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"No encuentro ancla para {label}")
    return text.replace(old, new, 1)


def patch_api_players() -> None:
    path = Path("football/src/futbol_pred/ingest/api_football_players.py")
    text = path.read_text()
    old = '''            "extended": extended,\n        }'''
    new = '''            "extended": extended,\n            "season": {\n                "minutes": history.get("minutes"),\n                "appearances": history.get("appearances"),\n                "starts": history.get("starts"),\n                "starter_rate": history.get("starter_rate"),\n                "expected_start_minutes": history.get("expected_start_minutes"),\n                "per90": dict(per90),\n                "per90_extended": dict(history.get("per90_extended") or {}),\n            },\n        }'''
    text = replace_once(text, old, new, "season player profile")
    path.write_text(text)


def patch_dashboard() -> None:
    path = Path("football/src/futbol_pred/dashboard.py")
    text = path.read_text()
    marker = "def _merge_lineup_players(players: dict | None, matches: list[dict]) -> dict:"
    start = text.index(marker)
    end = text.index("\n\ndef _fill_missing_free_squads", start)
    new_func = '''def _merge_lineup_players(players: dict | None, matches: list[dict]) -> dict:\n    """Indexa y enriquece jugadores mostrados en onces con evidencia real de API-Football.\n\n    Nunca sustituye acumulados de Understat por expectativas de un único partido.\n    Los datos de temporada, perfil y rol se añaden en campos separados para UI y\n    futuros challengers. Si un jugador ya existe, se enriquece en lugar de saltarlo.\n    """\n\n    out = players or {}\n    league_keys = {\n        "LaLiga": "laliga", "LaLiga Hypermotion": "segunda",\n        "Champions League": "champions",\n    }\n    labels = {"laliga": "LaLiga", "segunda": "LaLiga Hypermotion", "champions": "Champions League"}\n    for match in matches:\n        lineup = match.get("alineacion") or {}\n        if not lineup:\n            continue\n        league = league_keys.get(match.get("league"), "segunda")\n        bucket = out.setdefault(league, {"label": labels.get(league, league), "rankings": {}, "players": []})\n        flat = bucket.setdefault("players", [])\n        positions_by_key = {\n            (str(row.get("team")).casefold(), str(row.get("player")).casefold()): i\n            for i, row in enumerate(flat)\n        }\n        for side, team, positions, props in (\n            (lineup.get("local") or [], match.get("home"), lineup.get("posiciones_local") or [], lineup.get("clave_local") or []),\n            (lineup.get("visitante") or [], match.get("away"), lineup.get("posiciones_visitante") or [], lineup.get("clave_visitante") or []),\n        ):\n            prop_by_name = {str(row.get("jugador")).casefold(): row for row in props if isinstance(row, dict)}\n            for index, name in enumerate(side):\n                if not team or not name:\n                    continue\n                key = (str(team).casefold(), str(name).casefold())\n                prop = prop_by_name.get(str(name).casefold()) or {}\n                expected = {\n                    k: prop.get(k) for k in ("g", "a", "r", "rp", "fc", "fr", "t")\n                    if prop.get(k) is not None\n                }\n                if prop.get("extended"):\n                    expected["extended"] = prop.get("extended")\n                rich = {\n                    "player_id": prop.get("player_id"),\n                    "profile": prop.get("profile") or None,\n                    "api_position": prop.get("position"),\n                    "rating": prop.get("rating"),\n                    "pass_accuracy_pct": prop.get("pass_accuracy_pct"),\n                    "expected_minutes": prop.get("min"),\n                    "starter_probability": prop.get("tit"),\n                    "sample_minutes": prop.get("sample_minutes"),\n                    "season": prop.get("season") or None,\n                    "expected_match": expected or None,\n                    "rich_source": prop.get("source"),\n                    "lineup_status": lineup.get("status") or "estimado",\n                }\n                if key in positions_by_key:\n                    row = flat[positions_by_key[key]]\n                    if not row.get("position"):\n                        row["position"] = (positions[index] if index < len(positions) else None) or prop.get("position") or ""\n                    for field, value in rich.items():\n                        if value not in (None, {}, []):\n                            row[field] = value\n                    continue\n\n                season = prop.get("season") or {}\n                row = {\n                    "player": name, "team": team,\n                    "position": (positions[index] if index < len(positions) else None) or prop.get("position") or "",\n                    "goals": 0, "assists": 0, "shots": 0, "yc": 0,\n                    "min": season.get("minutes") or prop.get("sample_minutes") or 0,\n                    "source": lineup.get("provider") or "once cacheado",\n                }\n                for field, value in rich.items():\n                    if value not in (None, {}, []):\n                        row[field] = value\n                positions_by_key[key] = len(flat)\n                flat.append(row)\n    return out\n'''
    text = text[:start] + new_func + text[end:]
    path.write_text(text)


def patch_app() -> None:
    path = Path("app/src/App.jsx")
    text = path.read_text()
    text = replace_once(text, 'import MatchDetail from "./MatchDetail";\n', 'import MatchDetail from "./MatchDetail";\nimport PlayerProfile from "./PlayerProfile";\n', "PlayerProfile import")
    text = replace_once(text, 'function Jugadores({ players }) {', 'function Jugadores({ players, onPlayer }) {', "Jugadores props")
    text = replace_once(
        text,
        '<tr key={p.rank}>\n                    <td style={{ width: 22, color: "var(--dim)" }}>{p.rank}</td>',
        '<tr key={p.rank} role="button" tabIndex={0} onClick={() => onPlayer?.(p)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onPlayer?.(p); }}>\n                    <td style={{ width: 22, color: "var(--dim)" }}>{p.rank}</td>',
        "ranking player links",
    )
    text = replace_once(text, 'function TeamPage({ team, matches, players, onBack, onOpen, isFav, onFav }) {', 'function TeamPage({ team, matches, players, onBack, onOpen, onPlayer, isFav, onFav }) {', "TeamPage props")
    text = replace_once(
        text,
        '''              {squad.map((s, i) => (\n                <tr key={i}>\n                  <td className="tl"><b>{s.player}</b></td>''',
        '''              {squad.map((s, i) => (\n                <tr key={i} className="team-player-row" role="button" tabIndex={0} onClick={() => onPlayer?.(s)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onPlayer?.(s); }}>\n                  <td className="tl"><b>{s.player}</b></td>''',
        "team player links",
    )
    text = replace_once(text, '  const [teamSel, setTeamSel] = useState(null);\n', '  const [teamSel, setTeamSel] = useState(null);\n  const [playerSel, setPlayerSel] = useState(null);\n', "player state")
    text = replace_once(
        text,
        '''  const open = (m) => { setSel(m); window.scrollTo(0, 0); };\n  const openTeam = (name) => { setTeamSel(name); setSel(null); setQ(""); window.scrollTo(0, 0); };\n  const onFav = (name) => setFavs(new Set(toggleFav(name)));\n  const goto = (v) => { setView(v); setSel(null); setTeamSel(null); setMenuOpen(false); window.scrollTo(0, 0); };''',
        '''  const open = (m) => { setPlayerSel(null); setSel(m); window.scrollTo(0, 0); };\n  const openTeam = (name) => { setPlayerSel(null); setTeamSel(name); setSel(null); setQ(""); window.scrollTo(0, 0); };\n  const openPlayer = (player) => { setPlayerSel(player); setSel(null); setQ(""); window.scrollTo(0, 0); };\n  const onFav = (name) => setFavs(new Set(toggleFav(name)));\n  const goto = (v) => { setView(v); setSel(null); setTeamSel(null); setPlayerSel(null); setMenuOpen(false); window.scrollTo(0, 0); };''',
        "navigation player state",
    )
    text = replace_once(text, 'onChange={(e) => { const v = e.target.value; setQ(v); if (v.trim()) { setSel(null); setTeamSel(null); setView("partidos"); } }}', 'onChange={(e) => { const v = e.target.value; setQ(v); if (v.trim()) { setPlayerSel(null); setSel(null); setTeamSel(null); setView("partidos"); } }}', "search player reset")
    text = replace_once(
        text,
        '''          {data && sel && <MatchDetail m={sel} bankroll={bank} onBack={() => setSel(null)} onTeam={openTeam} players={data.players} />}\n\n          {data && !sel && teamSel && <TeamPage team={teamSel} matches={matches} players={data.players} onBack={() => setTeamSel(null)} onOpen={open} isFav={favs.has(teamSel)} onFav={onFav} />}\n\n          {data && !sel && !teamSel && (''',
        '''          {data && playerSel && <PlayerProfile candidate={playerSel} players={data.players} matches={matches} onBack={() => setPlayerSel(null)} onTeam={openTeam} />}\n\n          {data && !playerSel && sel && <MatchDetail m={sel} bankroll={bank} onBack={() => setSel(null)} onTeam={openTeam} players={data.players} />}\n\n          {data && !playerSel && !sel && teamSel && <TeamPage team={teamSel} matches={matches} players={data.players} onBack={() => setTeamSel(null)} onOpen={open} onPlayer={openPlayer} isFav={favs.has(teamSel)} onFav={onFav} />}\n\n          {data && !playerSel && !sel && !teamSel && (''',
        "player profile render",
    )
    text = replace_once(text, '{view === "jugadores" && <Jugadores players={data.players} />}', '{view === "jugadores" && <Jugadores players={data.players} onPlayer={openPlayer} />}', "Jugadores callback")
    path.write_text(text)


if __name__ == "__main__":
    patch_api_players()
    patch_dashboard()
    patch_app()
    print("Player profiles patch applied")
