import assert from "node:assert/strict";
import test from "node:test";

import { normalizeFeedForDisplay } from "./feed.js";


test("muestra primero el nombre del jugador en disponibilidad", () => {
  const feed = normalizeFeedForDisplay({
    matches: [{
      id: "m1",
      alineacion: {
        model: "fuente-real",
        status: "probable",
        disponibilidad_local: [{
          name: "Jugador Ejemplo",
          detalle: "Hamstring Injury",
          estado: "injury",
          source: "API-Football",
        }],
      },
    }],
  });

  const row = feed.matches[0].alineacion.disponibilidad_local[0];
  assert.equal(row.jugador, "Jugador Ejemplo");
  assert.equal(row.detalle, "Jugador Ejemplo");
  assert.match(row.estado, /Hamstring Injury/);
  assert.equal(row.raw_detalle, "Hamstring Injury");
});


test("no dibuja un once squad-only como probable", () => {
  const feed = normalizeFeedForDisplay({
    matches: [{
      id: "m1",
      alineacion: {
        model: "squad-only-v3",
        status: "estimado",
        provider: "Motor estadístico local",
        local: Array.from({ length: 11 }, (_, i) => `Local ${i}`),
        visitante: Array.from({ length: 11 }, (_, i) => `Visitante ${i}`),
        posiciones_local: Array(11).fill("MC"),
        posiciones_visitante: Array(11).fill("MC"),
        formacion_local: "4-3-3",
        formacion_visitante: "4-3-3",
      },
    }],
  });

  const lineup = feed.matches[0].alineacion;
  assert.equal(lineup.status, "sin confirmar");
  assert.equal(lineup.display_withheld, true);
  assert.equal(lineup.lineup_kind, "squad_only_withheld");
  assert.deepEqual(lineup.local, []);
  assert.deepEqual(lineup.visitante, []);
  assert.match(lineup.provider, /sin fuente fiable/i);
});


test("rebaja feeds antiguos model-only a estimado", () => {
  const feed = normalizeFeedForDisplay({
    matches: [{
      id: "m2",
      alineacion: {
        model: "gemini",
        status: "probable",
        source_quality: "model_only",
        local: Array.from({ length: 11 }, (_, i) => `Local ${i}`),
        visitante: Array.from({ length: 11 }, (_, i) => `Visitante ${i}`),
      },
    }],
  });

  const lineup = feed.matches[0].alineacion;
  assert.equal(lineup.status, "estimado");
  assert.equal(lineup.lineup_kind, "model_estimate");
  assert.match(lineup.display_warning, /no existe evidencia externa suficiente/i);
});


test("un check parcial de XI no se muestra como publicado", () => {
  const feed = normalizeFeedForDisplay({
    matches: [{
      id: "m3",
      operational_checks: {
        lineup_checked_at: "2026-08-26T19:00:00+02:00",
        lineup_check_result: "published",
      },
      alineacion: {
        model: "fuente-real",
        status: "probable",
        source_quality: "media_grounded",
        local: Array.from({ length: 11 }, (_, i) => `Local ${i}`),
        visitante: Array.from({ length: 11 }, (_, i) => `Visitante ${i}`),
      },
    }],
  });

  assert.equal(feed.matches[0].operational_checks.lineup_check_result, "partial");
});


test("un XI confirmado conserva el resultado published", () => {
  const feed = normalizeFeedForDisplay({
    matches: [{
      id: "m4",
      operational_checks: {
        lineup_checked_at: "2026-08-26T19:00:00+02:00",
        lineup_check_result: "published",
      },
      alineacion: {
        status: "confirmado",
        lineup_kind: "official",
        local: Array.from({ length: 11 }, (_, i) => `Local ${i}`),
        visitante: Array.from({ length: 11 }, (_, i) => `Visitante ${i}`),
      },
    }],
  });

  assert.equal(feed.matches[0].operational_checks.lineup_check_result, "published");
});
