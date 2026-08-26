function fmtDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function cleanSource(source) {
  if (!source || typeof source !== "object") return null;
  return {
    source: source.source || "Fuente externa",
    title: source.title || null,
    publishedAt: source.published_at || null,
    publishedLabel: fmtDate(source.published_at),
    url: source.url || null,
    evidenceLevel: source.evidence_level || null,
    evidenceRank: source.evidence_rank ?? null,
  };
}

function sideRow(side, team, raw) {
  const sources = (raw?.sources || []).map(cleanSource).filter(Boolean);
  return {
    side,
    team,
    grounded: Boolean(raw?.grounded),
    sources,
    state: raw?.grounded ? "grounded" : "missing",
    label: raw?.grounded ? "respaldado" : "sin evidencia externa",
  };
}

export function lineupEvidenceView(match) {
  const lineup = match?.alineacion || {};
  const status = String(lineup.status || "").toLowerCase();
  const official = status === "confirmado"
    && (lineup.local || []).length === 11
    && (lineup.visitante || []).length === 11;

  if (official) {
    const checkedAt = lineup.official_poll_at || lineup.source_updated_at || lineup.generated_at || lineup.ts || null;
    return {
      mode: "official",
      level: "official_lineup",
      levelLabel: "XI oficial",
      policy: "official_overrides_prefinal",
      complete: true,
      checkedAt,
      checkedLabel: fmtDate(checkedAt),
      provider: lineup.provider || "API-Football",
      sides: [
        { side: "local", team: match?.home, grounded: true, state: "official", label: "oficial", sources: [] },
        { side: "visitante", team: match?.away, grounded: true, state: "official", label: "oficial", sources: [] },
      ],
    };
  }

  const evidence = lineup.lineup_evidence || null;
  if (evidence) {
    const local = sideRow("local", match?.home, evidence.local);
    const away = sideRow("visitante", match?.away, evidence.visitante);
    const both = local.grounded && away.grounded;
    const partial = local.grounded || away.grounded;
    return {
      mode: both ? "media_both" : partial ? "media_partial" : "model_only",
      level: evidence.level || lineup.evidence_scope || (both ? "trusted_media_both_sides" : partial ? "trusted_media_partial" : "model_only"),
      levelLabel: both ? "Medios recientes · ambos equipos" : partial ? "Medios recientes · cobertura parcial" : "Sin evidencia externa",
      policy: evidence.policy || "both_sides_required_for_probable",
      complete: both,
      checkedAt: lineup.prefinal_refresh_at || lineup.source_updated_at || lineup.generated_at || lineup.ts || null,
      checkedLabel: fmtDate(lineup.prefinal_refresh_at || lineup.source_updated_at || lineup.generated_at || lineup.ts),
      provider: lineup.provider || lineup.fuente || "Motor/IA",
      sides: [local, away],
    };
  }

  // Compatibilidad con feeds anteriores a P1.2: se muestran las fuentes que
  // existan, pero no se atribuyen a un lado si el backend todavía no lo hizo.
  const legacySources = (lineup.media_sources || []).map(cleanSource).filter(Boolean);
  return {
    mode: legacySources.length ? "legacy_unscoped" : "model_only",
    level: lineup.source_quality || "model_only",
    levelLabel: legacySources.length ? "Fuentes antiguas sin atribución por equipo" : "Sin evidencia externa",
    policy: "both_sides_required_for_probable",
    complete: false,
    checkedAt: lineup.source_updated_at || lineup.generated_at || lineup.ts || null,
    checkedLabel: fmtDate(lineup.source_updated_at || lineup.generated_at || lineup.ts),
    provider: lineup.provider || lineup.fuente || "Motor/IA",
    sides: [
      { side: "local", team: match?.home, grounded: false, state: "unknown", label: "sin atribución fiable", sources: legacySources },
      { side: "visitante", team: match?.away, grounded: false, state: "unknown", label: "sin atribución fiable", sources: [] },
    ],
  };
}

export function evidenceSymbol(row) {
  if (row?.state === "official" || row?.grounded) return "✓";
  if (row?.state === "unknown") return "◷";
  return "✕";
}
