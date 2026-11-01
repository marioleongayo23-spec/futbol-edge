#!/usr/bin/env python3
"""Audita el peso del dashboard sin modificar el feed ni consultar proveedores.

Uso: python scripts/audit_feed_payload.py football/data/dashboard.json
Se recomienda ejecutar manualmente después de regenerar el feed, antes de diseñar
un contrato de serving ligero. No se activa en cada refresco para ahorrar CPU.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path


def encoded_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def report(path: Path, top: int = 12) -> dict:
    with path.open(encoding="utf-8") as fh:
        feed = json.load(fh)
    matches = feed.get("matches") or []
    section_sizes = {key: encoded_size(value) for key, value in feed.items()}
    match_sections: dict[str, int] = defaultdict(int)
    for match in matches:
        if not isinstance(match, dict):
            continue
        for field, value in match.items():
            match_sections[field] += encoded_size(value)
    return {
        "file": str(path),
        "bytes": path.stat().st_size,
        "matches": len(matches),
        "top_level": sorted(section_sizes.items(), key=lambda pair: pair[1], reverse=True)[:top],
        "match_fields": sorted(match_sections.items(), key=lambda pair: pair[1], reverse=True)[:top],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=Path("football/data/dashboard.json"))
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(report(args.path, max(1, args.top)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
