"""Puerta de aplicación: traduce el encargo a criterios ejecutables.

Si falla UNA sola condición -> NO DEMOSTRADO (no se aplica el modelo, no se
cambia beta). El veredicto lista exactamente qué evidencia falta. Ninguna
condición se relaja "eligiendo otro parámetro": eso convertiría el test en
entrenamiento y está prohibido.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SUPERADO = "SUPERADO"
NO_DEMOSTRADO = "NO DEMOSTRADO"


@dataclass
class Condition:
    name: str
    passed: bool
    value: Any
    threshold: Any
    detail: str


@dataclass
class GateResult:
    decision: str
    conditions: list[Condition] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "conditions": [asdict(c) for c in self.conditions],
            "missing_evidence": self.missing_evidence,
        }


@dataclass
class GateInput:
    # Resultado fuera de muestra (agregado, neto tras costes e impuestos)
    oos_monthly_geo_daily_mean_mean: float
    oos_monthly_geo_daily_mean_median: float
    oos_max_drawdown: float
    oos_geo_daily_mean: float
    benchmark_geo_daily_mean: float
    # Robustez estadística
    deflated_sharpe: float
    pbo: float
    bootstrap_geo_daily_lb: float          # límite inferior IC de la media diaria
    # Multi-mercado / régimen
    n_markets_total: int
    n_markets_meeting_target: int
    # Dependencia de un mes extremo
    max_single_month_share: float          # aporte del mejor mes al log-retorno total
    geo_daily_leave_best_out: float        # media geométrica quitando el MEJOR mes
    # Escenarios de estrés de costes/latencia (factor -> media diaria geométrica)
    cost_stress: dict[str, float]
    # Paper trading en sombra
    n_future_sessions: int
    all_shadow_only: bool
    # Naturaleza de los datos / de las sesiones (banderas de honestidad)
    data_is_real_dual_source: bool
    forward_sessions_are_live: bool


def evaluate_gate(inp: GateInput, thr: dict) -> GateResult:
    c: list[Condition] = []
    target = float(thr.get("target_daily", 0.004))

    c.append(Condition(
        "media_diaria_geometrica_mensual>=objetivo",
        inp.oos_monthly_geo_daily_mean_mean >= target,
        inp.oos_monthly_geo_daily_mean_mean, target,
        f"Media OOS {inp.oos_monthly_geo_daily_mean_mean:.4%} vs objetivo {target:.2%}",
    ))
    c.append(Condition(
        "supera_benchmark",
        inp.oos_geo_daily_mean > inp.benchmark_geo_daily_mean,
        inp.oos_geo_daily_mean, inp.benchmark_geo_daily_mean,
        f"OOS {inp.oos_geo_daily_mean:.4%}/día vs benchmark {inp.benchmark_geo_daily_mean:.4%}/día",
    ))
    c.append(Condition(
        "mediana_mensual_no_negativa",
        inp.oos_monthly_geo_daily_mean_median >= float(thr.get("median_monthly_min", 0.0)),
        inp.oos_monthly_geo_daily_mean_median, thr.get("median_monthly_min", 0.0),
        f"Mediana mensual {inp.oos_monthly_geo_daily_mean_median:.4%}",
    ))
    dd_lim = float(thr.get("max_drawdown_limit", 0.15))
    c.append(Condition(
        "drawdown_bajo_limite",
        inp.oos_max_drawdown <= dd_lim,
        inp.oos_max_drawdown, dd_lim,
        f"Drawdown máx {inp.oos_max_drawdown:.2%} vs límite {dd_lim:.2%}",
    ))
    stress_ok = all(v > 0 for v in inp.cost_stress.values()) if inp.cost_stress else False
    c.append(Condition(
        "escenarios_costes_latencia_positivos",
        stress_ok,
        inp.cost_stress, "todos > 0",
        "Media diaria geométrica > 0 en todos los escenarios de estrés de costes/latencia",
    ))
    min_markets = int(thr.get("min_markets", 3))
    c.append(Condition(
        "aparece_en_varios_mercados",
        inp.n_markets_meeting_target >= min_markets,
        inp.n_markets_meeting_target, min_markets,
        f"{inp.n_markets_meeting_target}/{inp.n_markets_total} mercados cumplen objetivo",
    ))
    max_share = float(thr.get("max_single_month_share", 0.5))
    no_single = (inp.max_single_month_share <= max_share) and (inp.geo_daily_leave_best_out >= 0.0)
    c.append(Condition(
        "no_depende_de_mes_extremo",
        no_single,
        {"max_month_share": inp.max_single_month_share, "geo_sin_mejor_mes": inp.geo_daily_leave_best_out},
        {"max_share<=": max_share, "geo_sin_mejor_mes>=": 0.0},
        "Robusto a quitar el mejor mes y ningún mes concentra el resultado",
    ))
    min_sessions = int(thr.get("min_future_sessions", 60))
    c.append(Condition(
        "supera_60_sesiones_futuras",
        inp.n_future_sessions >= min_sessions,
        inp.n_future_sessions, min_sessions,
        f"{inp.n_future_sessions} sesiones simuladas",
    ))
    c.append(Condition(
        "todas_SHADOW_ONLY",
        inp.all_shadow_only,
        inp.all_shadow_only, True,
        "Todas las operaciones registradas en modo SHADOW_ONLY",
    ))
    # Robustez estadística (corrección por pruebas múltiples + bootstrap)
    dsr_min = float(thr.get("dsr_min", 0.95))
    c.append(Condition(
        "sharpe_desinflado_significativo",
        inp.deflated_sharpe >= dsr_min,
        inp.deflated_sharpe, dsr_min,
        f"DSR {inp.deflated_sharpe:.3f} (corrige nº de pruebas)",
    ))
    pbo_max = float(thr.get("pbo_max", 0.5))
    c.append(Condition(
        "pbo_bajo",
        inp.pbo <= pbo_max,
        inp.pbo, pbo_max,
        f"Probabilidad de sobreajuste {inp.pbo:.2%}",
    ))
    lb_min = float(thr.get("bootstrap_geo_daily_lb_min", 0.0))
    c.append(Condition(
        "ic_bootstrap_media_diaria_positivo",
        inp.bootstrap_geo_daily_lb > lb_min,
        inp.bootstrap_geo_daily_lb, lb_min,
        f"Límite inferior IC95 media diaria {inp.bootstrap_geo_daily_lb:.4%}",
    ))
    # Condiciones de honestidad de la evidencia (bloqueantes)
    c.append(Condition(
        "datos_reales_dos_fuentes",
        inp.data_is_real_dual_source,
        inp.data_is_real_dual_source, True,
        "Datos intradía reales de >=2 fuentes independientes, point-in-time",
    ))
    c.append(Condition(
        "sesiones_futuras_en_vivo",
        inp.forward_sessions_are_live,
        inp.forward_sessions_are_live, True,
        "Las 60+ sesiones son paper trading hacia delante en vivo, no backtest histórico",
    ))

    missing = [f"{cond.name}: {cond.detail}" for cond in c if not cond.passed]
    decision = SUPERADO if not missing else NO_DEMOSTRADO
    return GateResult(decision=decision, conditions=c, missing_evidence=missing)
