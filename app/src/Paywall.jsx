// Bloqueo de features premium: en lugar del contenido de pago, un usuario sin
// plan suficiente ve un aviso claro con lo que se pierde y un CTA a los planes.

import { PLANS, planFor } from "./plans";

const WHY = {
  value: "Detecta apuestas con ventaja real: comparamos la probabilidad del modelo con la cuota de mercado y te marcamos solo las de edge positivo.",
  cartera: "Gestiona tu bankroll con staking Kelly y sigue el rendimiento (ROI, aciertos) de tus apuestas en el tiempo.",
  props: "Player props por partido: tarjetas, goles y tiros esperados de cada jugador, con su tasa por 90 minutos.",
  clv: "Closing Line Value: comprueba si cierras por delante del mercado, la métrica que separa al apostante rentable del que no.",
  quiniela: "Quiniela optimizada: triples y dobles repartidos por valor esperado, con Pleno al 15 sugerido.",
  datos: "Datos y modelos: calibración, backtest y calidad de probabilidades del motor Dixon-Coles + Elo.",
  value_global: "Ranking de value de toda la jornada, ordenado por edge, en una sola pantalla.",
};

export default function Paywall({ feature, plan, onUpgrade }) {
  const needed = planFor(feature);
  const target = PLANS[needed] || PLANS.pro;
  return (
    <div className="paywall">
      <div className="paywall-card">
        <div className="paywall-lock" style={{ color: target.accent }}>🔒</div>
        <div className="paywall-badge" style={{ background: target.accent }}>
          Función {target.name}
        </div>
        <p className="paywall-why">{WHY[feature] || "Esta sección está disponible en un plan superior."}</p>
        <div className="paywall-price">
          {target.priceMonthly.toLocaleString("es-ES", { minimumFractionDigits: 2 })} €
          <span>/mes</span>
        </div>
        <button type="button" className="btn-upgrade" style={{ background: target.accent }} onClick={onUpgrade}>
          Desbloquear con {target.name}
        </button>
        <div className="paywall-foot">
          Tu plan actual: <b>{PLANS[plan]?.name || "Free"}</b> · cancela cuando quieras
        </div>
      </div>
    </div>
  );
}
