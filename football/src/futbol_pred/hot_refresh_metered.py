"""Hot-refresh con telemetría persistente de cuota de API-Football.

Mide las peticiones HTTP reales, conserva los headers de rate-limit y persiste
la última cuota conocida en ``source_health.api_football``. El siguiente run
puede así reducir polling antes de agotar el plan diario.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Callable

import requests

from . import hot_refresh_batched as hot_refresh
from .feed_quality import load_feed, write_feed_safely
from .ingest.api_football import BASE_URL as API_FOOTBALL_BASE_URL


RATE_HEADERS = {
    "daily_limit": "x-ratelimit-requests-limit",
    "daily_remaining": "x-ratelimit-requests-remaining",
    "minute_limit": "x-ratelimit-limit",
    "minute_remaining": "x-ratelimit-remaining",
}


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ApiFootballUsageMeter:
    """Envuelve ``requests.get`` sin alterar la respuesta del proveedor."""

    def __init__(self, getter: Callable = requests.get):
        self.getter = getter
        self.calls = Counter()
        self.rate_limit = {key: None for key in RATE_HEADERS}

    @staticmethod
    def _endpoint(url: str) -> str | None:
        raw = str(url or "")
        base = API_FOOTBALL_BASE_URL.rstrip("/") + "/"
        if not raw.startswith(base):
            return None
        return raw[len(base):].split("?", 1)[0].strip("/") or "root"

    def request(self, url, *args, **kwargs):
        response = self.getter(url, *args, **kwargs)
        endpoint = self._endpoint(url)
        if endpoint is None:
            return response

        self.calls[endpoint] += 1
        headers = {
            str(key).lower(): value
            for key, value in getattr(response, "headers", {}).items()
        }
        for key, header in RATE_HEADERS.items():
            value = _as_int(headers.get(header))
            if value is not None:
                self.rate_limit[key] = value
        return response

    def snapshot(self) -> dict:
        return {
            "requests_total": sum(self.calls.values()),
            "requests_by_endpoint": dict(sorted(self.calls.items())),
            **self.rate_limit,
        }


def _persist_usage(usage: dict) -> tuple[bool, list]:
    if not usage.get("requests_total"):
        return False, []
    path = hot_refresh.legacy.OUTPUT
    previous = load_feed(path)
    if not previous:
        return False, []
    candidate = deepcopy(previous)
    health = dict(candidate.get("source_health") or {})
    health["api_football"] = {
        **usage,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "policy": "polling prepartido prioritario + backoff por cuota restante",
    }
    candidate["source_health"] = health
    ok, report = write_feed_safely(path, candidate, previous=previous)
    return bool(ok), report.get("issues") or []


def run_metered() -> tuple[bool, dict, dict]:
    """Ejecuta el hot-refresh y guarda la cuota observada para la siguiente pasada."""
    original_get = requests.get
    meter = ApiFootballUsageMeter(original_get)
    requests.get = meter.request
    try:
        ok, stats = hot_refresh.run()
    finally:
        requests.get = original_get
    usage = meter.snapshot()
    persisted, issues = _persist_usage(usage)
    if persisted:
        ok = True
    if issues:
        stats["feed_issues"] = list(dict.fromkeys((stats.get("feed_issues") or []) + issues))
    stats["usage_persisted"] = persisted
    return ok, stats, usage


def main() -> int:
    ok, stats, usage = run_metered()
    print(json.dumps(
        {"written": ok, **stats, "api_football_usage": usage},
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
