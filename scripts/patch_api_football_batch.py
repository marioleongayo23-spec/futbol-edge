from pathlib import Path
import re

path = Path("football/src/futbol_pred/ingest/api_football.py")
text = path.read_text(encoding="utf-8")

new_details = '''    def get_fixture_details(self, fixture_ids: list[int]) -> dict[int, dict]:
        """Recupera fixtures detallados en lotes de 20 sin truncar la entrada.

        API-Football permite ``/fixtures?ids=...`` con hasta 20 ids por petición.
        Un fallo de un lote no descarta los lotes que sí respondieron.
        """

        ids = [int(value) for value in dict.fromkeys(fixture_ids) if value]
        if self.offline or not ids:
            return {}
        out: dict[int, dict] = {}
        for start in range(0, len(ids), 20):
            chunk = ids[start:start + 20]
            try:
                response = self._get(
                    "fixtures", {"ids": "-".join(map(str, chunk))}
                ).get("response") or []
            except Exception:
                continue
            for item in response:
                fixture_id = (item.get("fixture") or {}).get("id")
                if fixture_id:
                    out[int(fixture_id)] = item
        return out

'''

pattern_details = re.compile(
    r"    def get_fixture_details\(self, fixture_ids: list\[int\]\) -> dict\[int, dict\]:\n.*?(?=    def lineup_from_fixture)",
    re.S,
)
text, count = pattern_details.subn(new_details, text, count=1)
if count != 1:
    raise SystemExit(f"get_fixture_details patch count={count}")

new_context = '''    @staticmethod
    def _stat_value(value):
        """Convierte porcentajes/cadenas numéricas del proveedor en números."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.endswith("%"):
                raw = raw[:-1].strip()
            try:
                return float(raw)
            except ValueError:
                return value
        return value

    @staticmethod
    def fixture_context(item: dict | None) -> dict:
        """Normaliza árbitro, sede y estadísticas embebidas del batch.

        Las estadísticas son live/post-partido y permanecen separadas del
        snapshot prepartido para impedir leakage.
        """

        item = item or {}
        fixture = item.get("fixture") or {}
        venue = fixture.get("venue") or {}
        context = {
            "provider": "API-Football",
            "referee": fixture.get("referee"),
            "venue": venue.get("name"),
            "city": venue.get("city"),
        }
        statistics = {}
        aliases = {
            "Total Shots": "shots", "Shots on Goal": "sot",
            "Shots off Goal": "shots_off_target", "Blocked Shots": "shots_blocked",
            "Shots insidebox": "shots_inside_box", "Shots outsidebox": "shots_outside_box",
            "Corner Kicks": "corners", "Fouls": "fouls",
            "Yellow Cards": "yellows", "Red Cards": "reds",
            "Offsides": "offsides", "Ball Possession": "possession",
            "Goalkeeper Saves": "saves", "Total passes": "passes",
            "Passes accurate": "passes_accurate", "Passes %": "pass_accuracy",
        }
        for team in item.get("statistics") or []:
            name = str((team.get("team") or {}).get("name") or "").strip()
            values = {}
            for row in team.get("statistics") or []:
                key = aliases.get(row.get("type"))
                if key and row.get("value") is not None:
                    values[key] = ApiFootballClient._stat_value(row["value"])
            if name and values:
                statistics[name] = values
        if statistics:
            context["live_or_post_stats"] = statistics
        return {
            key: value for key, value in context.items()
            if value is not None and value != "" and value != {}
        }

'''

pattern_context = re.compile(
    r"    @staticmethod\n    def fixture_context\(item: dict \| None\) -> dict:\n.*?(?=    @classmethod\n    def _parse_lineups)",
    re.S,
)
text, count = pattern_context.subn(new_context, text, count=1)
if count != 1:
    raise SystemExit(f"fixture_context patch count={count}")

path.write_text(text, encoding="utf-8")
