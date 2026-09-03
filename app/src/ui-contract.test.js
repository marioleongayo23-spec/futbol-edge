import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const SOURCES = ["App.jsx", "MatchDetail.jsx"].map((name) => ({
  name,
  source: readFileSync(new URL(`./${name}`, import.meta.url), "utf8"),
}));
const WEATHER_SOURCE = readFileSync(new URL("./WeatherAdjustmentPanel.jsx", import.meta.url), "utf8");

function tags(source, tag) {
  return [...source.matchAll(new RegExp(`<${tag}\\b[\\s\\S]*?(?:/>|>)`, "g"))].map((match) => match[0]);
}

test("todos los botones declarados tienen tipo y una acción", () => {
  for (const { name, source } of SOURCES) {
    const lines = source.split("\n").filter((line) => line.includes("<button"));
    assert.ok(lines.length > 0, `${name}: no se encontraron botones`);
    for (const line of lines) {
      assert.match(line, /type="button"/, `${name}: botón sin type=button: ${line.trim()}`);
      assert.match(line, /onClick=/, `${name}: botón sin acción: ${line.trim()}`);
    }
  }
});

test("inputs y selectores tienen nombre accesible y manejador", () => {
  for (const { name, source } of SOURCES) {
    for (const tag of tags(source, "select")) {
      assert.match(tag, /aria-label=/, `${name}: selector sin nombre accesible: ${tag}`);
      assert.match(tag, /onChange=/, `${name}: selector sin manejador: ${tag}`);
    }
    for (const tag of tags(source, "input")) {
      assert.ok(
        /aria-label=|placeholder=/.test(tag),
        `${name}: input sin nombre accesible: ${tag}`,
      );
      if (!tag.includes("theme-toggle")) {
        assert.match(tag, /onChange=/, `${name}: input sin manejador: ${tag}`);
      }
    }
  }
});

test("las filas interactivas son utilizables con teclado", () => {
  for (const { name, source } of SOURCES) {
    const rows = source.split("\n").filter((line) => line.includes('<tr') && line.includes('role="button"'));
    for (const row of rows) {
      assert.match(row, /tabIndex=\{0\}/, `${name}: fila interactiva fuera del tabulador`);
      assert.match(row, /onKeyDown=/, `${name}: fila interactiva sin teclado`);
      assert.match(row, /onClick=/, `${name}: fila interactiva sin clic`);
    }
  }
});

test("el clima identifica explícitamente la previsión usada a la hora del partido", () => {
  assert.match(WEATHER_SOURCE, /Previsión para la hora del partido/);
  assert.match(WEATHER_SOURCE, /weather_forecast_for/);
  assert.match(WEATHER_SOURCE, /weather_temperature_c/);
  assert.match(WEATHER_SOURCE, /weather_precipitation_probability_pct/);
  assert.match(WEATHER_SOURCE, /weather_wind_kmh/);
  assert.match(WEATHER_SOURCE, /última consulta/);
});

test("el árbitro muestra la procedencia real en vez de fijar un proveedor", () => {
  const matchDetail = SOURCES.find(({ name }) => name === "MatchDetail.jsx").source;
  assert.match(matchDetail, /official_context\.provider \|\| m\.official_context\.source/);
  assert.doesNotMatch(matchDetail, /official_context\.referee\} · API-Football/);
});
