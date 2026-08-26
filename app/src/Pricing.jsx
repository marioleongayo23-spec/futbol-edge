// Página de precios: los tres planes, toggle mensual/anual y CTA de pago.
//
// El pago sale por Stripe Payment Links (sin backend). Si el enlace no está
// configurado, el botón lo indica en vez de romper. El plan activo se marca y su
// botón queda deshabilitado.

import { useState } from "react";
import { PLANS, PLAN_ORDER, checkoutUrl, rank, yearlyDiscount } from "./plans";

function Price({ plan, cycle }) {
  if (!plan.priceMonthly) return <div className="pr-price">Gratis</div>;
  const value = cycle === "year" ? plan.priceYearly : plan.priceMonthly;
  return (
    <div className="pr-price">
      {value.toLocaleString("es-ES", { minimumFractionDigits: cycle === "year" ? 0 : 2 })} €
      <span>/{cycle === "year" ? "año" : "mes"}</span>
    </div>
  );
}

export default function Pricing({ current = "free", session, authEnabled, onLogin }) {
  const [cycle, setCycle] = useState("month");

  const go = (planId) => {
    const url = checkoutUrl(planId, cycle, session);
    if (authEnabled && !session) return onLogin?.();
    if (!url) {
      window.alert("El pago aún no está configurado. Configura los enlaces de Stripe (VITE_STRIPE_*) para activarlo.");
      return;
    }
    window.location.assign(url);
  };

  return (
    <div className="pricing">
      <div className="pr-head">
        <h2>Elige tu plan</h2>
        <p>Prueba el modelo gratis. Sube a Pro o VIP cuando quieras el edge completo.</p>
        <div className="pr-toggle" role="tablist" aria-label="Ciclo de facturación">
          <button type="button" role="tab" aria-selected={cycle === "month"} className={cycle === "month" ? "on" : ""} onClick={() => setCycle("month")}>Mensual</button>
          <button type="button" role="tab" aria-selected={cycle === "year"} className={cycle === "year" ? "on" : ""} onClick={() => setCycle("year")}>
            Anual <span className="pr-save">−{yearlyDiscount("pro")}%</span>
          </button>
        </div>
      </div>

      <div className="pr-grid">
        {PLAN_ORDER.map((id) => {
          const plan = PLANS[id];
          const isCurrent = id === current;
          const isDowngrade = rank(id) < rank(current);
          return (
            <div key={id} className={"pr-card" + (plan.highlight ? " feat" : "") + (isCurrent ? " current" : "")}>
              {plan.highlight && <div className="pr-tag">Más popular</div>}
              <div className="pr-name" style={{ color: plan.accent }}>{plan.name}</div>
              <div className="pr-tagline">{plan.tagline}</div>
              <Price plan={plan} cycle={cycle} />
              {plan.priceMonthly > 0 && cycle === "year" && (
                <div className="pr-permonth">≈ {(plan.priceYearly / 12).toLocaleString("es-ES", { maximumFractionDigits: 2 })} €/mes</div>
              )}
              <ul className="pr-feats">
                {plan.features.map((f) => <li key={f}>{f}</li>)}
              </ul>
              {isCurrent ? (
                <button type="button" className="pr-btn cur" disabled>Tu plan actual</button>
              ) : id === "free" ? (
                <button type="button" className="pr-btn ghost" disabled={isDowngrade}>
                  {isDowngrade ? "Incluido" : "Empieza gratis"}
                </button>
              ) : (
                <button type="button" className="pr-btn" style={{ background: plan.accent }} onClick={() => go(id)}>
                  {isDowngrade ? "Incluido" : `Elegir ${plan.name}`}
                </button>
              )}
            </div>
          );
        })}
      </div>

      <p className="pr-legal">
        Pago seguro con Stripe · cancela cuando quieras · sin permanencia. Fútbol Edge ofrece
        probabilidades y ventaja estadística, no certezas. Juega con responsabilidad (+18).
      </p>
    </div>
  );
}
