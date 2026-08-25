from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"No encuentro ancla para {label}")
    return text.replace(old, new, 1)


path = Path("app/src/MatchDetail.jsx")
text = path.read_text()
text = replace_once(
    text,
    'import { teamSquad } from "./teams";\n',
    'import { teamSquad } from "./teams";\nimport PredictionTimelinePanel from "./PredictionTimelinePanel";\n',
    "PredictionTimelinePanel import",
)
text = replace_once(
    text,
    '''      </div>\n\n      <nav className="match-nav" aria-label="Secciones del partido">''',
    '''      </div>\n\n      <PredictionTimelinePanel m={m} />\n\n      <nav className="match-nav" aria-label="Secciones del partido">''',
    "prediction timeline render",
)
path.write_text(text)
print("Match timeline integration applied")
