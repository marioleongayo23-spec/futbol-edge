"""Detalle por partido para auditar predicción vs resultado/estadística real."""

from __future__ import annotations

from .prediction_snapshots import latest_pre_match_snapshot

STAT_LABELS = {
    "goals": "Goles",
    "shots": "Remates",
    "sot": "Tiros a puerta",
    "corners": "Córners",
    "fouls": "Faltas",
    "yellows": "Amarillas",
    "reds": "Rojas",
}


def _sign(home, away) -> str:
    return "1" if home > away else "2" if away > home else "X"


def _triple(value) -> tuple[float, float, float] | None:
    try:
        if isinstance(value, dict):
            home = float(value["home"])
            away = float(value["away"])
            total = float(value.get("total", home + away))
        else:
            home, away = float(value[0]), float(value[1])
            total = home + away
        return home, away, total
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def build_accuracy_details(matches: list[dict]) -> list[dict]:
    """Comparación visible usando exclusivamente el último snapshot prepartido."""

    rows = []
    for match in matches:
        result = match.get("result")
        if not match.get("finished") or not isinstance(result, (list, tuple)) or len(result) != 2:
            continue
        snapshot = latest_pre_match_snapshot(match)
        if not snapshot:
            continue
        probs = snapshot.get("probs")
        predicted_sign = None
        if isinstance(probs, list) and len(probs) == 3:
            predicted_sign = ("1", "X", "2")[max(range(3), key=lambda index: probs[index])]
        actual_sign = _sign(result[0], result[1])

        stats = []
        predicted_stats = snapshot.get("stats") or {}
        actual_stats = match.get("statsReal") or {}
        for key, label in STAT_LABELS.items():
            predicted = _triple(predicted_stats.get(key))
            actual = _triple(actual_stats.get(key))
            if predicted is None or actual is None:
                continue
            stats.append({
                "key": key,
                "label": label,
                "predicted": {
                    "home": round(predicted[0], 2),
                    "away": round(predicted[1], 2),
                    "total": round(predicted[2], 2),
                },
                "actual": {
                    "home": round(actual[0], 2),
                    "away": round(actual[1], 2),
                    "total": round(actual[2], 2),
                },
                "delta": {
                    "home": round(actual[0] - predicted[0], 2),
                    "away": round(actual[1] - predicted[1], 2),
                    "total": round(actual[2] - predicted[2], 2),
                },
                "abs_error_total": round(abs(actual[2] - predicted[2]), 2),
            })

        rows.append({
            "id": match.get("id"),
            "date": match.get("date") or str(match.get("kickoff") or "")[:10],
            "home": match.get("home"),
            "away": match.get("away"),
            "result": [result[0], result[1]],
            "predicted_sign": predicted_sign,
            "actual_sign": actual_sign,
            "hit_1x2": predicted_sign == actual_sign if predicted_sign else None,
            "snapshot_at": snapshot.get("generated_at"),
            "stats_source": match.get("statsRealSource") or "football-data.co.uk",
            "stats_updated_at": match.get("statsRealUpdatedAt"),
            "stats": stats,
        })
    return sorted(rows, key=lambda row: (row.get("date") or "", row.get("id") or ""), reverse=True)


def enrich_accuracy(aggregate: dict | None, matches: list[dict]) -> dict | None:
    if not aggregate:
        return None
    return {**aggregate, "matches": build_accuracy_details(matches)}
