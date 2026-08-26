import test from "node:test";
import assert from "node:assert/strict";
import { hasAccess, rank, resolvePlan, PLANS, FEATURE_PLAN } from "./plans.js";

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

test("resolvePlan: sin sesión → free por defecto", () => {
  assert.equal(resolvePlan(null), "free");
  assert.equal(resolvePlan({}), "free");
});

test("resolvePlan: plan en metadatos de Supabase manda", () => {
  assert.equal(resolvePlan({ user: { app_metadata: { plan: "pro" } } }), "pro");
  assert.equal(resolvePlan({ user: { user_metadata: { plan: "vip" } } }), "vip");
});

test("resolvePlan: plan inválido en metadatos cae a free", () => {
  assert.equal(resolvePlan({ user: { app_metadata: { plan: "hacker" } } }), "free");
});

test("cada plan tiene precio coherente (anual < 12 meses salvo free)", () => {
  for (const p of Object.values(PLANS)) {
    if (p.priceMonthly > 0) assert.ok(p.priceYearly < p.priceMonthly * 12);
  }
});
