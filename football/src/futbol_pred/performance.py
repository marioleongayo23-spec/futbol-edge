"""Rendimiento auditable del modelo usando exclusivamente snapshots prepartido."""

from __future__ import annotations

from collections import defaultdict

from .prediction_snapshots import latest_pre_match_snapshot


def _sign(result: list[int]) -> str:
    return "1" if result[0] > result[1] else "2" if result[0] < result[1] else "X"


def _confidence(probs: list[float]) -> str:
    maximum = max(probs)
    return "alta" if maximum >= 55 else "media" if maximum >= 45 else "baja"


def _brier(probs: list[float], outcome: str) -> float:
    target = {"1": [1, 0, 0], "X": [0, 1, 0], "2": [0, 0, 1]}[outcome]
    scale = 100 if max(probs) > 1 else 1
    return sum((value / scale - target[index]) ** 2 for index, value in enumerate(probs)) / 3


def _settled(selection: str, market: str, result: list[int]) -> bool:
    if market == "1x2":
        return selection == _sign(result)
    total = sum(result)
    return (selection == "over" and total > 2.5) or (selection == "under" and total < 2.5)


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    hits = sum(row["hit"] for row in rows)
    profit = sum(row["profit"] for row in rows)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": round(100 * hits / n, 1) if n else None,
        "profit_units": round(profit, 2),
        "roi": round(100 * profit / n, 1) if n else None,
    }


def _group(rows: list[dict], key: str) -> list[dict]:
    buckets = defaultdict(list)
    for row in rows:
        buckets[row[key]].append(row)
    return [dict(label=label, **_summary(items)) for label, items in sorted(buckets.items())]


def build_performance(matches: list[dict]) -> dict | None:
    """ROI, acierto, calibración por confianza y comparación inicial/10:15."""

    bets, brier_rows, window_pairs = [], [], []
    for match in matches:
        result = match.get("result")
        if not match.get("finished") or not isinstance(result, list) or len(result) != 2:
            continue
        snapshot = latest_pre_match_snapshot(match)
        probs = (snapshot or {}).get("probs")
        if not isinstance(probs, list) or len(probs) != 3:
            continue
        outcome = _sign(result)
        brier_rows.append({
            "league": match.get("league") or "Sin competición",
            "confidence": _confidence(probs),
            "brier": _brier(probs, outcome),
        })
        by_market = {}
        for value in (snapshot.get("value") or []):
            try:
                edge, odds = float(value["edge"]), float(value["odds"])
            except (KeyError, TypeError, ValueError):
                continue
            market = value.get("market")
            if market not in {"1x2", "ou25"} or edge <= 0.02:
                continue
            if market not in by_market or edge > by_market[market][0]:
                by_market[market] = (edge, value, odds)
        for market, (_, value, odds) in by_market.items():
            hit = _settled(str(value.get("selection")), market, result)
            bets.append({
                "market": "1X2" if market == "1x2" else "Más/menos 2,5",
                "league": match.get("league") or "Sin competición",
                "confidence": _confidence(probs),
                "hit": int(hit), "profit": odds - 1 if hit else -1,
            })

        history = [item for item in (match.get("prediction_history") or []) if isinstance(item, dict)]
        initial = next((item for item in history if item.get("window") == "initial"), None)
        ten = next((item for item in reversed(history) if item.get("window") in {"10:00", "10:15"}), None)
        if initial and ten and initial.get("probs") and ten.get("probs"):
            window_pairs.append({
                "initial": _brier(initial["probs"], outcome),
                "ten": _brier(ten["probs"], outcome),
            })
    if not brier_rows and not bets:
        return None
    by_confidence = []
    for label in ("alta", "media", "baja"):
        rows = [row for row in brier_rows if row["confidence"] == label]
        if rows:
            by_confidence.append({
                "label": label, "n": len(rows),
                "brier": round(sum(row["brier"] for row in rows) / len(rows), 4),
            })
    segments = _group(bets, "market") + _group(bets, "league") + _group(bets, "confidence")
    weak = [
        {"segment": row["label"], "n": row["n"], "roi": row["roi"]}
        for row in segments if row["n"] >= 5 and row["roi"] is not None and row["roi"] < -10
    ]
    comparison = None
    if window_pairs:
        initial = sum(row["initial"] for row in window_pairs) / len(window_pairs)
        ten = sum(row["ten"] for row in window_pairs) / len(window_pairs)
        comparison = {
            "n": len(window_pairs), "initial_brier": round(initial, 4),
            "ten_fifteen_brier": round(ten, 4), "delta": round(ten - initial, 4),
            "improved": ten < initial,
        }
    return {
        "method": "snapshots prepartido · 1 unidad por selección con edge > 2%",
        "overall": _summary(bets),
        "by_market": _group(bets, "market"),
        "by_league": _group(bets, "league"),
        "by_confidence": by_confidence,
        "initial_vs_10_15": comparison,
        "weak_segments": weak,
    }
