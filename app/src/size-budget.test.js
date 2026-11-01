import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import test from "node:test";

test("el build no empaqueta por error el feed histórico pesado", () => {
  const script = readFileSync(new URL("../../scripts/vercel-build.sh", import.meta.url), "utf8");
  assert.doesNotMatch(script, /^cp\s+football\/data\/dashboard\.json\s+app\/public\/dashboard\.json\s*$/m);
});
test("la copia offline versionada respeta el presupuesto de 2 MB", () => {
  const bytes = statSync(new URL("../public/dashboard.json", import.meta.url)).size;
  assert.ok(bytes < 2 * 1024 * 1024, `La copia offline pesa ${bytes} bytes`);
});
