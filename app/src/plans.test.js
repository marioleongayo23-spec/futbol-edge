import test from "node:test";
import assert from "node:assert/strict";
import { hasAccess, rank, resolvePlan, PLANS, FEATURE_PLAN, MONETIZATION_ON } from "./plans.js";

test("jerarquía de planes: free < pro < vip", () => {
  assert.ok(rank("free") < rank("pro"));
  assert.ok(rank("pro") < rank("vip"));
  assert.equal(rank("desconocido"), 0);
});

test("free no accede a features de pago", () => {
  assert.equal(hasAccess("free", "value"), false);
  assert.equal(hasAccess("free", "quiniela"), false);
});

test("free sí accede a lo gratuito (feature no listada)", () => {
  assert.equal(hasAccess("free", "resumen"), true);
  assert.equal(hasAccess("free", "clasificacion"), true);
});

test("pro accede a pro pero no a vip", () => {
  assert.equal(hasAccess("pro", "value"), true);
  assert.equal(hasAccess("pro", "cartera"), true);
  assert.equal(hasAccess("pro", "quiniela"), false);
  assert.equal(hasAccess("pro", "datos"), false);
});

test("vip accede a todo", () => {
  for (const feature of Object.keys(FEATURE_PLAN)) {
    assert.equal(hasAccess("vip", feature), true);
  }
});

test("sin monetización configurada la app queda abierta (todo VIP)", () => {
  // En el entorno de test no hay VITE_STRIPE_* ni VITE_DEFAULT_PLAN, así que la
  // monetización está apagada y nada se bloquea.
  assert.equal(MONETIZATION_ON, false);
  assert.equal(resolvePlan(null), "vip");
  assert.equal(resolvePlan({}), "vip");
});

test("resolvePlan: plan en metadatos de Supabase manda", () => {
  assert.equal(resolvePlan({ user: { app_metadata: { plan: "pro" } } }), "pro");
  assert.equal(resolvePlan({ user: { user_metadata: { plan: "vip" } } }), "vip");
});

test("resolvePlan: plan inválido en metadatos se ignora", () => {
  // Sin monetización activa cae al modo abierto (vip); el valor inválido no pasa.
  assert.equal(resolvePlan({ user: { app_metadata: { plan: "hacker" } } }), "vip");
});

test("cada plan tiene precio coherente (anual < 12 meses salvo free)", () => {
  for (const p of Object.values(PLANS)) {
    if (p.priceMonthly > 0) assert.ok(p.priceYearly < p.priceMonthly * 12);
  }
});
