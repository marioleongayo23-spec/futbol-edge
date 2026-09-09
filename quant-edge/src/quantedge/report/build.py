"""Orquestador del estudio: de datos a decisión SUPERADO / NO DEMOSTRADO.

Encadena: datos (2 fuentes reconciliadas) -> walk-forward anidado por instrumento
-> agregación multi-mercado -> benchmark -> estrés de costes/latencia -> paper
trading en sombra -> robustez estadística (DSR, PBO, bootstrap) -> puerta.

Escribe artefactos reproducibles (hashes, métricas, libro en sombra, decisión).
"""
from __future__ import annotations

import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..costs.model import InstrumentCosts
from ..data.dual_source import make_vendor_copy, reconcile
from ..data.synthetic import SYNTHETIC_WARNING, default_universe
from ..gate.evaluate import GateInput, evaluate_gate
from ..paper.shadow import run_shadow
from ..strategies.library import BuyAndHold, all_candidates
from ..utils.hashing import hash_dataframe, hash_obj
from ..validation.bootstrap import bootstrap_ci, monte_carlo
from ..validation.metrics import geometric_mean, summarize
from ..validation.multiple_testing import pbo_cscv
from ..validation.metrics import deflated_sharpe_ratio
from ..validation.splitters import holdout_split
from ..validation.walkforward import (
    candidate_matrix,
    nested_walk_forward,
    replay_oos,
)

DEFAULT_THRESHOLDS = {
    "target_daily": 0.004,
    "aspiration_daily": 0.006,
    "median_monthly_min": 0.0,
    "max_drawdown_limit": 0.15,
    "min_markets": 3,
    "max_single_month_share": 0.5,
    "min_future_sessions": 60,
    "dsr_min": 0.95,
    "pbo_max": 0.5,
    "bootstrap_geo_daily_lb_min": 0.0,
    "cost_stress_factors": [1.5, 2.0],
}


def _aggregate_portfolio(series_by_instrument: dict[str, pd.Series]) -> pd.Series:
    """Cartera equiponderada: media diaria entre instrumentos disponibles."""
    df = pd.DataFrame(series_by_instrument)
    return df.mean(axis=1, skipna=True).dropna()


def _single_month_stats(returns: pd.Series) -> tuple[float, float]:
    """(aporte del mejor mes al log-retorno total, media geométrica sin ese mes)."""
    if len(returns) == 0:
        return float("inf"), float("nan")
    periods = returns.index.to_period("M")
    month_log = returns.groupby(periods).apply(lambda s: float(np.sum(np.log1p(s.to_numpy()))))
    total = float(month_log.sum())
    max_share = float(month_log.max() / total) if total > 0 else float("inf")
    best_month = month_log.idxmax()
    ex = returns[periods != best_month]
    geo_ex = geometric_mean(ex.to_numpy()) if len(ex) else float("nan")
    return max_share, geo_ex


def run_study(
    out_dir: str | Path = "quant-edge/reports",
    n_days: int = 1000,
    holdout_frac: float = 0.25,
    n_outer: int = 5,
    inner_splits: int = 4,
    embargo: float = 0.01,
    label_horizon: int = 1,
    thresholds: dict | None = None,
    costs: InstrumentCosts | None = None,
) -> dict:
    thr = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    costs = costs or InstrumentCosts()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    params = {
        "n_days": n_days, "holdout_frac": holdout_frac, "n_outer": n_outer,
        "inner_splits": inner_splits, "embargo": embargo, "label_horizon": label_horizon,
        "thresholds": thr, "costs": asdict(costs),
    }

    # 1) Datos: universo sintético + dos fuentes reconciliadas.
    universe = default_universe(n_days)
    clean: dict[str, pd.DataFrame] = {}
    data_hashes: dict[str, str] = {}
    reconcile_reports: dict[str, dict] = {}
    for i, (name, df_true) in enumerate(universe.items()):
        a = make_vendor_copy(df_true, seed=1001 + i)
        b = make_vendor_copy(df_true, seed=2001 + i)
        cln, rep = reconcile(a, b)
        clean[name] = cln
        data_hashes[name] = hash_dataframe(cln)
        reconcile_reports[name] = asdict(rep)

    candidates = all_candidates()

    # Holdout idéntico para todos (misma rejilla temporal).
    n = n_days
    dev_idx, hold_idx = holdout_split(n, holdout_frac, embargo, label_horizon)

    # 2) Walk-forward anidado por instrumento (solo sobre DEV).
    oos_by_instr: dict[str, pd.Series] = {}
    wf_by_instr = {}
    per_market: dict[str, dict] = {}
    dev_matrices = []
    for name, df in clean.items():
        dev = df.iloc[dev_idx]
        wf = nested_walk_forward(dev, candidates, costs, n_outer, inner_splits, embargo, label_horizon)
        oos_by_instr[name] = wf.oos_returns
        wf_by_instr[name] = wf
        per_market[name] = summarize(wf.oos_returns, thr["target_daily"]).to_dict()
        dev_matrices.append(candidate_matrix(dev, candidates, costs).returns_matrix)

    # 3) Cartera OOS agregada (multi-mercado, equiponderada).
    oos_portfolio = _aggregate_portfolio(oos_by_instr)
    oos_summary = summarize(oos_portfolio, thr["target_daily"])

    # 4) Benchmark: buy&hold equiponderado neto sobre las mismas fechas OOS.
    from ..backtest.engine import run_backtest

    bh_by_instr = {}
    for name, df in clean.items():
        bh = run_backtest(df, BuyAndHold(), costs).net_returns_after_tax
        bh_by_instr[name] = bh.reindex(oos_portfolio.index)
    bench_portfolio = _aggregate_portfolio(bh_by_instr)
    bench_geo = geometric_mean(bench_portfolio.to_numpy())

    # 5) Robustez estadística: PBO y DSR sobre carteras de candidatos.
    min_len = min(m.shape[0] for m in dev_matrices)
    port_matrix = np.mean([m[:min_len] for m in dev_matrices], axis=0)  # (T_dev x N)
    from ..validation.metrics import sharpe_per_observation

    cand_sharpes = np.array([sharpe_per_observation(port_matrix[:, j]) for j in range(port_matrix.shape[1])])
    sr_variance = float(np.nanvar(cand_sharpes, ddof=1))
    n_trials = port_matrix.shape[1]
    pbo = pbo_cscv(port_matrix, n_groups=10)
    dsr = deflated_sharpe_ratio(oos_portfolio.to_numpy(), n_trials, sr_variance)
    ci = bootstrap_ci(oos_portfolio.to_numpy(), geometric_mean, n_boot=1500, mean_block=10.0)
    mc = monte_carlo(oos_portfolio.to_numpy(), n_paths=3000, target_daily=thr["target_daily"])

    # 6) Estrés de costes/latencia (mismas decisiones, peor fricción).
    cost_stress = {"1.0": oos_summary.geo_daily_mean}
    for f in thr["cost_stress_factors"]:
        scaled = costs.scaled(float(f))
        stressed = {name: replay_oos(clean[name], wf_by_instr[name], scaled) for name in clean}
        cost_stress[str(f)] = geometric_mean(_aggregate_portfolio(stressed).to_numpy())

    # 7) Paper trading SHADOW_ONLY sobre el holdout oculto (modelo final por instrumento).
    shadow_by_instr = {}
    shadow_frames = []
    all_shadow = True
    holdout_dates = clean[next(iter(clean))].index[hold_idx]
    for name, df in clean.items():
        final_model = wf_by_instr[name].selected_objs[-1]
        # Se ejecuta sobre el prefijo hasta el fin del holdout (warmup correcto de
        # las medias/ventanas) y luego se conservan solo las sesiones del holdout.
        prefix = df.iloc[: int(hold_idx[-1]) + 1]
        sr_full = run_shadow(prefix, final_model, costs, instrument=name)
        sess = sr_full.sessions[sr_full.sessions["date"].isin(holdout_dates)].reset_index(drop=True)
        shadow_by_instr[name] = sr_full.returns.reindex(holdout_dates)
        shadow_frames.append(sess)
        all_shadow = all_shadow and bool((sess["mode"] == "SHADOW_ONLY").all())
    shadow_portfolio = _aggregate_portfolio(shadow_by_instr)
    shadow_summary = summarize(shadow_portfolio, thr["target_daily"])
    n_future_sessions = int(shadow_portfolio.shape[0])

    # 8) Multi-mercado: nº de instrumentos que cumplen el objetivo en OOS.
    n_markets_meeting = sum(
        1 for m in per_market.values() if m["monthly_geo_daily_mean_mean"] >= thr["target_daily"]
    )
    max_share, geo_ex_best = _single_month_stats(oos_portfolio)

    # 9) Puerta de aplicación.
    gate_input = GateInput(
        oos_monthly_geo_daily_mean_mean=oos_summary.monthly_geo_daily_mean_mean,
        oos_monthly_geo_daily_mean_median=oos_summary.monthly_geo_daily_mean_median,
        oos_max_drawdown=oos_summary.max_drawdown,
        oos_geo_daily_mean=oos_summary.geo_daily_mean,
        benchmark_geo_daily_mean=bench_geo,
        deflated_sharpe=dsr,
        pbo=pbo["pbo"],
        bootstrap_geo_daily_lb=ci.lo,
        n_markets_total=len(per_market),
        n_markets_meeting_target=n_markets_meeting,
        max_single_month_share=max_share,
        geo_daily_leave_best_out=geo_ex_best,
        cost_stress=cost_stress,
        n_future_sessions=n_future_sessions,
        all_shadow_only=all_shadow,
        data_is_real_dual_source=False,   # datos SINTÉTICOS en esta ejecución
        forward_sessions_are_live=False,  # holdout histórico, no vivo
    )
    gate = evaluate_gate(gate_input, thr)

    # --- Artefactos ---
    metrics = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "synthetic_warning": SYNTHETIC_WARNING,
        "params": params,
        "params_sha256": hash_obj(params),
        "data_sha256": data_hashes,
        "reconcile_reports": reconcile_reports,
        "oos_portfolio": oos_summary.to_dict(),
        "benchmark_geo_daily_mean": bench_geo,
        "per_market": per_market,
        "statistical_robustness": {
            "n_trials": n_trials,
            "sr_variance_trials": sr_variance,
            "deflated_sharpe": dsr,
            "pbo": pbo,
            "bootstrap_geo_daily_ci95": {"point": ci.point, "lo": ci.lo, "hi": ci.hi},
            "monte_carlo": mc.to_dict(),
        },
        "cost_stress_geo_daily": cost_stress,
        "single_month": {"max_share": max_share, "geo_daily_leave_best_out": geo_ex_best},
        "shadow": {
            "n_future_sessions": n_future_sessions,
            "all_shadow_only": all_shadow,
            "summary": shadow_summary.to_dict(),
        },
        "gate": gate.to_dict(),
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "decision.json").write_text(json.dumps(gate.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    oos_portfolio.to_frame("net_return").to_csv(out / "oos_portfolio.csv")
    shadow_all = pd.concat(shadow_frames, ignore_index=True)
    shadow_all.to_csv(out / "shadow_ledger.csv", index=False)

    manifest = {
        "params_sha256": hash_obj(params),
        "data_sha256": data_hashes,
        # Hash determinista de las métricas excluyendo la marca temporal.
        "metrics_sha256": hash_obj({k: v for k, v in metrics.items() if k != "generated_utc"}),
        "decision": gate.decision,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    _write_markdown(out / "RESUMEN.md", metrics, gate)
    return {"decision": gate.decision, "metrics": metrics, "out_dir": str(out)}


def _write_markdown(path: Path, metrics: dict, gate) -> None:
    o = metrics["oos_portfolio"]
    lines = [
        "# Resumen de ejecución — quant-edge",
        "",
        f"> ⚠️ {metrics['synthetic_warning']}",
        "",
        f"**Decisión: {gate.decision}**",
        "",
        "## Cartera fuera de muestra (neta, tras costes e impuestos)",
        f"- Media diaria geométrica mensual (media): `{o['monthly_geo_daily_mean_mean']:.4%}` (objetivo 0,40%)",
        f"- Mediana mensual: `{o['monthly_geo_daily_mean_median']:.4%}`",
        f"- Media geométrica diaria global: `{o['geo_daily_mean']:.4%}`",
        f"- Drawdown máximo: `{o['max_drawdown']:.2%}`",
        f"- Sharpe anualizado: `{o['ann_sharpe']:.2f}`",
        f"- Meses cumpliendo objetivo: `{o['months_hitting_target']:.0%}`",
        f"- Benchmark (buy&hold) media diaria: `{metrics['benchmark_geo_daily_mean']:.4%}`",
        "",
        "## Robustez estadística",
        f"- Nº de configuraciones probadas (pruebas): `{metrics['statistical_robustness']['n_trials']}`",
        f"- Sharpe Desinflado (DSR): `{metrics['statistical_robustness']['deflated_sharpe']:.3f}` (umbral 0,95)",
        f"- PBO: `{metrics['statistical_robustness']['pbo']['pbo']:.2%}` (umbral 50%)",
        f"- IC95 media diaria (bootstrap): `[{metrics['statistical_robustness']['bootstrap_geo_daily_ci95']['lo']:.4%}, {metrics['statistical_robustness']['bootstrap_geo_daily_ci95']['hi']:.4%}]`",
        f"- Monte Carlo P(alcanzar objetivo): `{metrics['statistical_robustness']['monte_carlo']['prob_hit_target']:.1%}`",
        "",
        "## Condiciones de la puerta",
    ]
    for c in gate.conditions:
        mark = "✅" if c.passed else "❌"
        lines.append(f"- {mark} **{c.name}** — {c.detail}")
    lines += ["", "## Evidencia que falta"]
    if gate.missing_evidence:
        lines += [f"- {m}" for m in gate.missing_evidence]
    else:
        lines.append("- (ninguna)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
