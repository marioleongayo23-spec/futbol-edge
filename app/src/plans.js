// Modelo de monetización freemium.
//
// Un único sitio define los planes, qué desbloquea cada uno y cómo se resuelve
// el plan de la sesión actual. El resto de la app solo pregunta `hasAccess`.
//
// Pago: enlaces de Stripe (Payment Links) por variable de entorno, sin backend
// propio. El plan del usuario se lee de los metadatos de Supabase
// (`app_metadata.plan` o `user_metadata.plan`), que un webhook de Stripe pone a
// "pro"/"vip" tras el cobro. Sin Supabase, la app usa `VITE_DEFAULT_PLAN`.

// Orden jerárquico: cada plan incluye lo del anterior.
export const PLAN_ORDER = ["free", "pro", "vip"];

export const PLANS = {
  free: {
    id: "free",
    name: "Free",
    tagline: "Sigue la liga con el modelo",
    priceMonthly: 0,
    priceYearly: 0,
    accent: "#7d8da3",
    features: [
      "Resultados y clasificación en vivo",
      "Probabilidades 1X2 del modelo",
      "Previa IA de cada partido",
      "Marcador y goles más probables",
    ],
  },
  pro: {
    id: "pro",
    name: "Pro",
    tagline: "El edge, para ti",
    priceMonthly: 12.99,
    priceYearly: 99,
    accent: "#5aa2ff",
    highlight: true,
    features: [
      "Todo lo de Free",
      "Value bets con edge y cuota real",
      "Player props (tarjetas, goles, tiros)",
      "Mi cartera: bankroll y staking Kelly",
      "CLV (closing line value) por apuesta",
      "Alertas de valor y de onces oficiales",
    ],
  },
  vip: {
    id: "vip",
    name: "VIP",
    tagline: "Todo el arsenal",
    priceMonthly: 29.99,
    priceYearly: 249,
    accent: "#e3b341",
    features: [
      "Todo lo de Pro",
      "Quiniela optimizada (triples y dobles)",
      "Datos y modelos: calibración y backtest",
      "Champions y Segunda al completo",
      "Ranking de value global de la jornada",
      "Exportar predicciones y prioridad de soporte",
    ],
  },
};

// Feature → plan mínimo que la desbloquea. Lo que no aparezca es gratis.
export const FEATURE_PLAN = {
  value: "pro",
  cartera: "pro",
  props: "pro",
  clv: "pro",
  alerts: "pro",
  quiniela: "vip",
  datos: "vip",
  value_global: "vip",
  export: "vip",
};

export function rank(plan) {
  const i = PLAN_ORDER.indexOf(plan);
  return i < 0 ? 0 : i;
}

// ¿El plan `current` alcanza la feature pedida?
export function hasAccess(current, feature) {
  const needed = FEATURE_PLAN[feature];
  if (!needed) return true; // gratis
  return rank(current) >= rank(needed);
}

export function planFor(feature) {
  return FEATURE_PLAN[feature] || "free";
}

const OWNER_EMAIL = (import.meta.env?.VITE_ALLOWED_EMAIL || "").toLowerCase();
const DEFAULT_PLAN = import.meta.env?.VITE_DEFAULT_PLAN || "free";

// Resuelve el plan efectivo de una sesión. El dueño (VITE_ALLOWED_EMAIL) siempre
// es VIP; si Supabase trae un plan en los metadatos, manda; si no, el de por
// defecto. Nunca lanza aunque no haya sesión.
export function resolvePlan(session) {
  const user = session?.user;
  const email = (user?.email || "").toLowerCase();
  if (OWNER_EMAIL && email && email === OWNER_EMAIL) return "vip";
  const meta = user?.app_metadata?.plan || user?.user_metadata?.plan;
  if (meta && PLAN_ORDER.includes(meta)) return meta;
  return PLAN_ORDER.includes(DEFAULT_PLAN) ? DEFAULT_PLAN : "free";
}

// Enlaces de pago de Stripe (Payment Links). Se rellenan por entorno; si faltan,
// el botón lleva a la sección de contacto/planes sin romper.
const LINKS = {
  pro_month: import.meta.env?.VITE_STRIPE_PRO_MONTH || "",
  pro_year: import.meta.env?.VITE_STRIPE_PRO_YEAR || "",
  vip_month: import.meta.env?.VITE_STRIPE_VIP_MONTH || "",
  vip_year: import.meta.env?.VITE_STRIPE_VIP_YEAR || "",
};

// Devuelve el enlace de pago para un plan y ciclo, añadiendo el email como
// `prefilled_email` y `client_reference_id` para que el webhook case al usuario.
export function checkoutUrl(planId, cycle, session) {
  const base = LINKS[`${planId}_${cycle === "year" ? "year" : "month"}`];
  if (!base) return "";
  const email = session?.user?.email;
  const uid = session?.user?.id;
  const url = new URL(base);
  if (email) url.searchParams.set("prefilled_email", email);
  if (uid) url.searchParams.set("client_reference_id", uid);
  return url.toString();
}

export function yearlyDiscount(plan) {
  const p = PLANS[plan];
  if (!p || !p.priceMonthly) return 0;
  return Math.round((1 - p.priceYearly / (p.priceMonthly * 12)) * 100);
}
