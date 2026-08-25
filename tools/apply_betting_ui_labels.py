from pathlib import Path

root = Path(__file__).resolve().parents[1]

# Etiquetas semánticas del timeline.
path = root / "app/src/predictionTimelineData.js"
text = path.read_text(encoding="utf-8")
text = text.replace(
'''  "T-6h": "T−6h",\n  official_lineup: "Once oficial",''',
'''  "T-6h": "T−6h",\n  "T-3h": "T−3h · sin pre-final",\n  "pre_final_T-3h": "PRE-FINAL · T−3h",\n  "final_T-60_official": "FINAL · XI T−60",\n  "final_T-30_official": "FINAL · XI T−30",\n  official_lineup: "XI oficial · legado",''')
text = text.replace(
'''      lineupStatus: item.alineacion?.status || null,\n      modelVersion: item.model_version || item.model_meta?.version || null,''',
'''      lineupStatus: item.alineacion?.status || null,\n      lineupPhase: item.alineacion?.phase || null,\n      sourceQuality: item.alineacion?.source_quality || null,\n      mediaSources: Array.isArray(item.alineacion?.media_sources) ? item.alineacion.media_sources : [],\n      officialPollWindow: item.alineacion?.official_poll_window || null,\n      modelVersion: item.model_version || item.model_meta?.version || null,''')
path.write_text(text, encoding="utf-8")

# Tests del etiquetado.
path = root / "app/src/predictionTimelineData.test.js"
text = path.read_text(encoding="utf-8")
text = text.replace('snapshot("official_lineup", "2026-08-24T19:45:00+02:00"', 'snapshot("final_T-60_official", "2026-08-24T20:00:00+02:00"')
text = text.replace('snapshot("official_lineup", "2026-08-24T19:45:00+02:00"', 'snapshot("final_T-60_official", "2026-08-24T20:00:00+02:00"')
text = text.replace('assert.equal(result.latestLabel, "Once oficial");', 'assert.equal(result.latestLabel, "FINAL · XI T−60");')
if 'PRE-FINAL · T−3h' not in text:
    text += '''\n\ntest("timeline distingue pre-final y final oficial", () => {\n  const pre = snapshot("pre_final_T-3h", "2026-08-24T18:00:00+02:00", [51, 29, 20], {\n    alineacion: { phase: "pre_final", status: "probable", source_quality: "media_grounded", media_sources: [{ source: "AS" }] },\n  });\n  const final = snapshot("final_T-30_official", "2026-08-24T20:30:00+02:00", [53, 28, 19], {\n    alineacion: { phase: "final", status: "confirmado", official_poll_window: "T-30" },\n  });\n  const points = predictionTimelinePoints({ kickoff, prediction_history: [pre, final], prediction_snapshot: final });\n  assert.equal(points[0].label, "PRE-FINAL · T−3h");\n  assert.equal(points[0].sourceQuality, "media_grounded");\n  assert.equal(points[1].label, "FINAL · XI T−30");\n  assert.equal(points[1].officialPollWindow, "T-30");\n});\n'''
path.write_text(text, encoding="utf-8")

# Resumen de versiones claramente visible encima del gráfico.
path = root / "app/src/PredictionTimelinePanel.jsx"
text = path.read_text(encoding="utf-8")
anchor = '''function PublishedBridge({ audit }) {'''
component = '''function VersionStrip({ points }) {\n  const initial = points.find((point) => point.window === "initial");\n  const prefinal = points.find((point) => point.window === "pre_final_T-3h");\n  const final = points.find((point) => point.window === "final_T-60_official" || point.window === "final_T-30_official");\n  const cell = (kind, title, point, fallback) => (\n    <div className={`betting-version ${kind} ${point ? "ready" : "pending"}`}>\n      <small>{title}</small>\n      <b>{point ? point.label : fallback}</b>\n      <span>{point ? `${point.probs[0].toFixed(0)} / ${point.probs[1].toFixed(0)} / ${point.probs[2].toFixed(0)} · ${point.lead || ""}` : "pendiente"}</span>\n      {point?.sourceQuality === "media_grounded" && <em>medios + modelo</em>}\n      {point?.officialPollWindow && <em>API-Football · {point.officialPollWindow}</em>}\n    </div>\n  );\n  return (\n    <div className="betting-version-strip" aria-label="Versiones de predicción para apostar">\n      {cell("initial", "INICIAL", initial, "primera captura")}\n      {cell("prefinal", "PRE-FINAL", prefinal, "objetivo T−3h")}\n      {cell("final", "FINAL", final, "XI oficial T−60 / T−30")}\n    </div>\n  );\n}\n\n'''
if component not in text:
    text = text.replace(anchor, component + anchor, 1)
text = text.replace(
'''      <HeroKpis m={m} audit={audit} points={points} />\n\n      {points.length > 0 ? (''',
'''      <HeroKpis m={m} audit={audit} points={points} />\n      <VersionStrip points={points} />\n\n      {points.length > 0 ? (''')
text = text.replace(
'''          <div className="mut">Evolución y explicación auditables · solo snapshots realmente capturados antes del partido</div>''',
'''          <div className="mut">Inicial → PRE-FINAL T−3h → FINAL con XI oficial T−60/T−30 · solo información realmente disponible antes del partido</div>''')
path.write_text(text, encoding="utf-8")

# CSS compacto y responsive para el strip.
path = root / "app/src/match-timeline.css"
text = path.read_text(encoding="utf-8")
extra = '.betting-version-strip{position:relative;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 14px}.betting-version{padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:rgba(9,18,31,.45)}.betting-version small,.betting-version span,.betting-version em{display:block}.betting-version small{font-size:.62rem;letter-spacing:.08em;color:var(--dim);font-weight:800}.betting-version b{display:block;margin:4px 0 2px;font-size:.82rem}.betting-version span{font-size:.67rem;color:var(--muted)}.betting-version em{margin-top:4px;font-size:.62rem;color:var(--green);font-style:normal}.betting-version.prefinal.ready{border-color:rgba(57,208,255,.3)}.betting-version.final.ready{border-color:rgba(34,201,138,.38);box-shadow:inset 0 0 0 1px rgba(34,201,138,.05)}.betting-version.pending{opacity:.64}@media(max-width:640px){.betting-version-strip{grid-template-columns:1fr}.betting-version{padding:9px 10px}}'
if '.betting-version-strip{' not in text:
    text += extra + "\n"
path.write_text(text, encoding="utf-8")
