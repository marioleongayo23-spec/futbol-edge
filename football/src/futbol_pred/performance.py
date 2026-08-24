"""Rendimiento auditable del modelo usando exclusivamente snapshots prepartido."""

from __future__ import annotations

import math
from collections import defaultdict

from .backtest.metrics import aggregate
from .prediction_snapshots import latest_pre_match_snapshot

SIGNS = ("1", "X", "2")


def _sign(result: list[int]) -> str:
    return "1" if result[0] > result[1] else "2" if result[0] < result[1] else "X"


def _confidence(probs: list[float]) -> str:
    maximum = max(probs)
    return "alta" if maximum >= 55 else "media" if maximum >= 45 else "baja"


def _brier(probs: list[float], outcome: str) -> float:
    target = {"1": [1, 0, 0], "X": [0, 1, 0], "2": [0, 0, 1]}[outcome]
    scale = 100 if max(probs) > 1 else 1
    return sum((value / scale - target[index]) ** 2 for index, value in enumerate(probs)) / 3


def _probability_dict(values) -> dict[str, float] | None:
    """Normaliza listas 0-100 o dicts 0-1 sin aceptar valores rotos."""

    try:
        if isinstance(values, list) and len(values) == 3:
            raw = {sign: float(values[index]) for index, sign in enumerate(SIGNS)}
        elif isinstance(values, dict) and all(sign in values for sign in SIGNS):
            raw = {sign: float(values[sign]) for sign in SIGNS}
        else:
            return None
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value < 0 for value in raw.values()):
        return None
    if max(raw.values(), default=0.0) > 1.0:
        raw = {sign: value / 100.0 for sign, value in raw.items()}
    total = sum(raw.values())
    if total <= 0:
        return None
    return {sign: raw[sign] / total for sign in SIGNS}


def _quality(rows: list[tuple[dict[str, float], str]]) -> dict | None:
    if not rows:
        return None
    metrics = aggregate(rows)
    return {
        "n": metrics["n"],
        "log_loss": round(metrics["log_loss"], 4),
        "brier": round(metrics["brier"], 4),
        "rps": round(metrics["rps"], 4),
        "accuracy": round(metrics["accuracy"] * 100, 1),
    }


def _paired_comparison(
    candidate_rows: list[tuple[dict[str, float], str]],
    baseline_rows: list[tuple[dict[str, float], str]],
    baseline_label: str,
) -> dict | None:
    """Compara dos capas sobre exactamente la misma muestra; delta < 0 mejora."""

    if not candidate_rows or len(candidate_rows) != len(baseline_rows):
        return None
    candidate = aggregate(candidate_rows)
    baseline = aggregate(baseline_rows)
    return {
        "baseline": baseline_label,
        "n": len(candidate_rows),
        "log_loss_delta": round(candidate["log_loss"] - baseline["log_loss"], 4),
        "brier_delta": round(candidate["brier"] - baseline["brier"], 4),
        "rps_delta": round(candidate["rps"] - baseline["rps"], 4),
        "improved_both": (
            candidate["log_loss"] < baseline["log_loss"]
            and candidate["rps"] < baseline["rps"]
        ),
    }


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
    """ROI, calibración y calidad probabilística sobre snapshots prepartido."""

    bets, brier_rows, window_pairs = [], [], []
    published_rows: list[tuple[dict[str, float], str]] = []
    model_rows: list[tuple[dict[str, float], str]] = []
    market_rows: list[tuple[dict[str, float], str]] = []
    published_vs_model_published: list[tuple[dict[str, float], str]] = []
    published_vs_model_model: list[tuple[dict[str, float], str]] = []
    published_vs_market_published: list[tuple[dict[str, float], str]] = []
    published_vs_market_market: list[tuple[dict[str, float], str]] = []

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

        published = _probability_dict(probs)
        model_only = _probability_dict((snapshot or {}).get("model_probs"))
        odds = (snapshot or {}).get("odds")
        market = _probability_dict(
            ((odds.get("1x2") or {}).get("fair")) if isinstance(odds, dict) else None
        )
        if published:
            published_rows.append((published, outcome))
        if model_only:
            model_rows.append((model_only, outcome))
        if market:
            market_rows.append((market, outcome))
        if published and model_only:
            published_vs_model_published.append((published, outcome))
            published_vs_model_model.append((model_only, outcome))
        if published and market:
            published_vs_market_published.append((published, outcome))
            published_vs_market_market.append((market, outcome))

        by_market = {}
        for value in ((snapshot or {}).get("value") or []):
            try:
                edge, odds_value = float(value["edge"]), float(value["odds"])
            except (KeyError, TypeError, ValueError):
                continue
            market_name = value.get("market")
            if market_name not in {"1x2", "ou25"} or edge <= 0.02:
                continue
            if market_name not in by_market or edge > by_market[market_name][0]:
                by_market[market_name] = (edge, value, odds_value)
        for market_name, (_, value, odds_value) in by_market.items():
            hit = _settled(str(value.get("selection")), market_name, result)
            bets.append({
                "market": "1X2" if market_name == "1x2" else "Más/menos 2,5",
                "league": match.get("league") or "Sin competición",
                "confidence": _confidence(probs),
                "hit": int(hit), "profit": odds_value - 1 if hit else -1,
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
    probability_quality = {
        "published": _quality(published_rows),
        "model_only": _quality(model_rows),
        "market": _quality(market_rows),
        "published_vs_model": _paired_comparison(
            published_vs_model_published, published_vs_model_model, "model_only"
        ),
        "published_vs_market": _paired_comparison(
            published_vs_market_published, published_vs_market_market, "market"
        ),
    }
    return {
        "method": "snapshots prepartido · 1 unidad por selección con edge > 2%",
        "overall": _summary(bets),
        "by_market": _group(bets, "market"),
        "by_league": _group(bets, "league"),
        "by_confidence": by_confidence,
        "probability_quality": probability_quality,
        "initial_vs_10_15": comparison,
        "weak_segments": weak,
    }
