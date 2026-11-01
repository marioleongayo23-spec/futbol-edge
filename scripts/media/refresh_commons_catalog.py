"""Build a small verified, attribution-aware Wikimedia Commons portrait catalog.

Inputs MUST be a human-approved list of Wikidata QIDs and exact club aliases.
No fuzzy person searches, hidden websites, scraping or commercial-photo copying.
A rejected item stays a placeholder, never a guessed different footballer.

Run: python scripts/media/refresh_commons_catalog.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[2]
SEEDS = BASE / "football/data/media/approved_wikidata_players.json"
DEST = BASE / "app/src/verifiedPlayerMedia.js"
USER_AGENT = "FutbolEdge-CuratedMedia/1.0 (https://github.com/marioleongayo23-spec/futbol-edge; Commons image attribution)"
ALLOWED_LICENSES = re.compile(
    r"^https://creativecommons\.org/(?:licenses/(?:by|by-sa)/(?:3\.0|4\.0)/|publicdomain/(?:zero/1\.0/|mark/1\.0/))$",
    re.I,
)
QID = re.compile(r"^Q[1-9][0-9]{0,12}$")
ALLOWED_IMAGE_HOSTS = {"upload.wikimedia.org"}
MAX_SEEDS = 20


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []

    def handle_data(self, data):
        self.chunks.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(str(value or ""))
    return " ".join(unescape(" ".join(parser.chunks)).split())[:240]


def norm(value):
    import unicodedata
    v = unicodedata.normalize("NFD", str(value or ""))
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", v.lower()))


def get_json(url, *, opener=urlopen):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with opener(request, timeout=18) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError("HTTP status is not 200")
        return json.loads(response.read().decode("utf-8"))


def wikidata_url(qids):
    query = {
        "action": "wbgetentities", "ids": "|".join(qids),
        "props": "claims|labels|aliases", "languages": "en|es",
        "format": "json",
    }
    return "https://www.wikidata.org/w/api.php?" + urlencode(query)


def commons_url(filename):
    query = {
        "action": "query", "titles": "File:" + filename,
        "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": "240", "format": "json",
    }
    return "https://commons.wikimedia.org/w/api.php?" + urlencode(query)


def file_from_wikidata(entity, player):
    """Refuse QIDs with multiple conflicting images or a different identity."""
    labels = [row.get("value") for row in (entity.get("labels") or {}).values()]
    aliases = [
        row.get("value") for rows in (entity.get("aliases") or {}).values()
        for row in rows
    ]
    if norm(player) not in {norm(value) for value in labels + aliases}:
        return None
    image_claims = [
        c for c in entity.get("claims", {}).get("P18", [])
        if c.get("rank") != "deprecated"
        and c.get("mainsnak", {}).get("datavalue", {}).get("type") == "string"
    ]
    preferred = [c for c in image_claims if c.get("rank") == "preferred"]
    chosen = preferred or image_claims
    if not chosen:
        return None
    filename = chosen[0]["mainsnak"]["datavalue"]["value"]
    if not isinstance(filename, str) or not re.search(r"\.(jpe?g|png|webp)$", filename, re.I):
        return None
    return filename


def license_from_commons(payload):
    pages = list(payload.get("query", {}).get("pages", {}).values())
    if len(pages) != 1:
        return None
    info = pages[0].get("imageinfo") or []
    if len(info) != 1:
        return None
    image = info[0]
    ext = image.get("extmetadata") or {}
    meta = lambda key: (ext.get(key) or {}).get("value")
    license_url = str(meta("LicenseUrl") or "").strip()
    if not ALLOWED_LICENSES.fullmatch(license_url):
        return None
    author = plain(meta("Attribution") or meta("Artist"))
    license_short = plain(meta("LicenseShortName"))
    from urllib.parse import urlparse
    thumb = image.get("thumburl")
    attribution = image.get("descriptionurl")
    if (not isinstance(thumb, str) or urlparse(thumb).scheme != "https" or
            urlparse(thumb).hostname not in ALLOWED_IMAGE_HOSTS or
            not isinstance(attribution, str) or
            not attribution.startswith("https://commons.wikimedia.org/wiki/File:") or
            not author or not license_short):
        return None
    return {
        "image_url": thumb,
        "source_url": attribution,
        "license": license_short,
        "license_url": license_url,
        "author": author,
        "modifications": "Miniatura a 240 px generada por Wikimedia Commons; sin modificaciones adicionales.",
    }


def build_entries(seed, *, fetch=get_json, previous=None):
    approved = seed.get("players", [])
    if not isinstance(approved, list) or len(approved) > MAX_SEEDS or not approved:
        raise ValueError("Expected between one and twenty approved identities")
    qids = []
    keys = set()
    for row in approved:
        if (not isinstance(row, dict) or not QID.fullmatch(str(row.get("wikidata_qid", ""))) or
                not isinstance(row.get("player"), str) or
                not isinstance(row.get("teams"), list) or not row["teams"]):
            raise ValueError("Invalid reviewed QID/player/team record")
        for team in row["teams"]:
            key = (norm(row["player"]), norm(team))
            if not all(key) or key in keys:
                raise ValueError("Ambiguous or duplicate player-team pair")
            keys.add(key)
        qids.append(row["wikidata_qid"])
    if len(qids) != len(set(qids)):
        raise ValueError("Duplicate Wikidata QID in approved identities")

    entities = fetch(wikidata_url(qids)).get("entities") or {}
    prior = {
        row.get("wikidata_qid"): row for row in (previous or {}).get("entries", [])
        if isinstance(row, dict)
    }
    entries, rejected = [], []
    for row in approved:
        qid = row["wikidata_qid"]
        entity = entities.get(qid, {})
        filename = file_from_wikidata(entity, row["player"])
        if not filename:
            rejected.append({"player": row["player"], "reason": "missing image or mismatching entity name"})
            continue
        image = license_from_commons(fetch(commons_url(filename)))
        if not image:
            rejected.append({"player": row["player"], "reason": "unverifiable or incompatible file license"})
            continue
        record = {
            "player": row["player"],
            "teams": row["teams"],
            "wikidata_qid": qid,
            "file_name": filename,
            **image,
        }
        former = prior.get(qid)
        if former and all(former.get(k) == v for k, v in record.items()):
            record["checked_at"] = former.get("checked_at")
        else:
            record["checked_at"] = datetime.now(timezone.utc).isoformat()
        entries.append(record)

    if not entries:
        raise ValueError("Refusing to publish an empty player media catalog: " + json.dumps(rejected, ensure_ascii=False))
    return {"version": 1, "entries": entries}, rejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=Path, default=SEEDS)
    parser.add_argument("--output", type=Path, default=DEST)
    args = parser.parse_args()
    seed = json.loads(args.seeds.read_text(encoding="utf-8"))
    previous = (json.loads(args.output.read_text(encoding="utf-8").split("export default ", 1)[1].removesuffix(";\n"))
                if args.output.exists() and "export default " in args.output.read_text(encoding="utf-8") else {})
    catalog, rejected = build_entries(seed, previous=previous)
    text = "// Generated from reviewed Wikimedia Commons metadata. Do not edit by hand.\n" + (
        "export default " + json.dumps(catalog, indent=2, ensure_ascii=False) + ";\n"
    )
    if not args.output.exists() or args.output.read_text(encoding="utf-8") != text:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"published":len(catalog["entries"]), "rejected":rejected,
                      "output":str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
