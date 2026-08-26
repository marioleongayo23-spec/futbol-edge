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
          jugador: "Jugador Ejemplo",
          detalle: "Hamstring Injury",
          estado: "injury",
          source: "API-Football",
        }],
      },
    }],
  });

  const row = feed.matches[0].alineacion.disponibilidad_local[0];
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
  assert.deepEqual(lineup.local, []);
  assert.deepEqual(lineup.visitante, []);
  assert.match(lineup.provider, /sin fuente fiable/i);
});
