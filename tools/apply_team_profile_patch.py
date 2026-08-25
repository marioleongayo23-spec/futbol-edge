from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"No encuentro ancla para {label}")
    return text.replace(old, new, 1)


path = Path("app/src/App.jsx")
text = path.read_text()
text = replace_once(
    text,
    'import PlayerProfile from "./PlayerProfile";\n',
    'import PlayerProfile from "./PlayerProfile";\nimport TeamIntelligencePanel from "./TeamIntelligencePanel";\n',
    "TeamIntelligencePanel import",
)
text = replace_once(
    text,
    '''      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>\n        <TeamRec r={p.overall} label="Total" />\n        <TeamRec r={p.home} label="Local" />\n        <TeamRec r={p.away} label="Visitante" />\n      </div>\n      {Object.keys(p.tendencies).length > 0 && (''',
    '''      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>\n        <TeamRec r={p.overall} label="Total" />\n        <TeamRec r={p.home} label="Local" />\n        <TeamRec r={p.away} label="Visitante" />\n      </div>\n      <TeamIntelligencePanel team={team} matches={matches} players={players} onPlayer={onPlayer} />\n      {Object.keys(p.tendencies).length > 0 && (''',
    "team intelligence render",
)
path.write_text(text)
print("Team profile patch applied")
