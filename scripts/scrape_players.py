#!/usr/bin/env python3
"""Scraper LOCAL de estadísticas de jugadores (LaLiga) desde Understat.

Understat expone por jugador: goles, asistencias, remates, xG, tarjetas,
minutos y posición. FBref (que además tiene faltas) bloquea a los scripts con
Cloudflare incluso desde IP residencial; Understat no, pero sirve los datos solo
a un navegador real → usamos Playwright (headless) en tu Mac.

Escribe football/data/players.json (override que consume el feed) con:
  laliga.rankings  -> top listas por categoría (para la vista Jugadores)
  laliga.players   -> lista completa con stats (para las hojas de equipo)

Uso (en tu Mac, una vez instalado Playwright):
    python -m playwright install chromium      # solo la primera vez
    python scripts/scrape_players.py [--season 2026]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "football" / "data" / "players.json"
UNDERSTAT = "https://understat.com/league/La_liga/{season}"


def _num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return 0


def fetch_players(season: int, timeout_ms: int = 45000) -> list[dict]:
    from playwright.sync_api import sync_playwright
    import time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(locale="es-ES").new_page()
        page.goto(UNDERSTAT.format(season=season), wait_until="domcontentloaded", timeout=timeout_ms)
        data = None
        for _ in range(10):
            time.sleep(1.5)
            data = page.evaluate("typeof playersData!=='undefined' ? playersData : null")
            if data:
                break
        browser.close()
    return data or []


def _ranking(players, key, label, top=25, cast=int, decimals=0):
    rows = []
    for p in players:
        v = _num(p.get(key), float)
        if v:
            rows.append((p.get("player_name", ""), p.get("team_title", ""), v))
    rows.sort(key=lambda r: r[2], reverse=True)
    out = []
    for i, (name, team, v) in enumerate(rows[:top]):
        val = round(v, decimals) if decimals else int(v)
        out.append({"rank": i + 1, "player": name, "team": team, "value": val})
    return {"label": label, "players": out} if out else None


def build(players: list[dict]) -> dict:
    rankings = {}
    for cat, key, label, dec in (
        ("goles", "goals", "Goleadores", 0),
        ("asistencias", "assists", "Asistencias", 0),
        ("remates", "shots", "Remates", 0),
        ("xg", "xG", "xG", 1),
        ("amarillas", "yellow_cards", "Amarillas", 0),
    ):
        r = _ranking(players, key, label, decimals=dec)
        if r:
            rankings[cat] = r

    full = []
    for p in players:
        full.append({
            "player": p.get("player_name", ""),
            "team": p.get("team_title", ""),
            "pos": p.get("position", ""),
            "min": _num(p.get("time"), int),
            "goals": _num(p.get("goals"), int),
            "assists": _num(p.get("assists"), int),
            "shots": _num(p.get("shots"), int),
            "xg": round(_num(p.get("xG"), float), 1),
            "yc": _num(p.get("yellow_cards"), int),
            "rc": _num(p.get("red_cards"), int),
        })
    full.sort(key=lambda x: (x["goals"], x["assists"]), reverse=True)
    return {"label": "LaLiga", "rankings": rankings, "players": full}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=int(__import__("os").getenv("SEASON", "2026")))
    args = ap.parse_args()

    print(f"[understat] descargando LaLiga temporada {args.season}…")
    try:
        players = fetch_players(args.season)
    except Exception as exc:
        print(f"[understat] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("¿Instalaste el navegador?  python -m playwright install chromium", file=sys.stderr)
        return 1
    if not players:
        print("[understat] no se obtuvieron jugadores (¿temporada sin datos aún?)", file=sys.stderr)
        return 2

    laliga = build(players)
    # Conserva otras ligas si ya existían en el override.
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    prev["laliga"] = laliga
    prev["_source"] = "understat"
    prev["_generated"] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = len(laliga["players"])
    cats = ", ".join(laliga["rankings"])
    print(f"[understat] OK: {n} jugadores, categorías: {cats}")
    print(f"[understat] escrito {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
