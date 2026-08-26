import assert from "node:assert/strict";
import test from "node:test";

import { evidenceSymbol, lineupEvidenceView } from "./lineupEvidence.js";


test("XI oficial prevalece sobre evidencia prefinal", () => {
  const match = {
    home: "Local", away: "Visitante",
    alineacion: {
      status: "confirmado",
      local: Array.from({ length: 11 }, (_, i) => `L${i}`),
      visitante: Array.from({ length: 11 }, (_, i) => `V${i}`),
      provider: "API-Football",
      official_poll_at: "2026-08-26T20:05:00+02:00",
      lineup_evidence: { level: "trusted_media_partial" },
    },
  };
  const view = lineupEvidenceView(match);
  assert.equal(view.mode, "official");
  assert.equal(view.complete, true);
  assert.equal(view.level, "official_lineup");
  assert.equal(view.sides[0].label, "oficial");
  assert.equal(evidenceSymbol(view.sides[0]), "✓");
});


test("evidencia de ambos equipos se separa por lado y conserva fuente y fecha", () => {
  const match = {
    home: "Local", away: "Visitante",
    alineacion: {
      status: "probable",
      provider: "Gemini",
      source_updated_at: "2026-08-26T18:00:00+02:00",
      lineup_evidence: {
        policy: "both_sides_required_for_probable",
        level: "trusted_media_both_sides",
        local: { grounded: true, sources: [{ source: "AS", title: "Once Local", published_at: "2026-08-26T17:30:00+02:00", url: "https://example.com/local" }] },
        visitante: { grounded: true, sources: [{ source: "MARCA", title: "Once Visitante", published_at: "2026-08-26T17:40:00+02:00", url: "https://example.com/away" }] },
      },
    },
  };
  const view = lineupEvidenceView(match);
  assert.equal(view.mode, "media_both");
  assert.equal(view.complete, true);
  assert.equal(view.sides[0].team, "Local");
  assert.equal(view.sides[0].sources[0].source, "AS");
  assert.match(view.sides[0].sources[0].publishedLabel, /26\/08/);
  assert.equal(view.sides[1].sources[0].source, "MARCA");
});


test("evidencia parcial deja visible qué equipo no está respaldado", () => {
  const match = {
    home: "Local", away: "Visitante",
    alineacion: {
      status: "estimado",
      lineup_evidence: {
        level: "trusted_media_partial",
        local: { grounded: true, sources: [{ source: "AS", title: "Once Local" }] },
        visitante: { grounded: false, sources: [] },
      },
    },
  };
  const view = lineupEvidenceView(match);
  assert.equal(view.mode, "media_partial");
  assert.equal(view.complete, false);
  assert.equal(view.sides[0].label, "respaldado");
  assert.equal(view.sides[1].label, "sin evidencia externa");
  assert.equal(evidenceSymbol(view.sides[1]), "✕");
});


test("feed antiguo con media_sources no inventa atribución por equipo", () => {
  const match = {
    home: "Local", away: "Visitante",
    alineacion: {
      status: "probable",
      source_quality: "media_grounded",
      media_sources: [{ source: "AS", title: "Posibles onces" }],
    },
  };
  const view = lineupEvidenceView(match);
  assert.equal(view.mode, "legacy_unscoped");
  assert.equal(view.complete, false);
  assert.equal(view.sides[0].state, "unknown");
  assert.equal(view.sides[1].grounded, false);
});
