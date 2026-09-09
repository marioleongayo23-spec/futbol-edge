"""CLI de quant-edge.

    python -m quantedge.cli demo             # estudio completo (sintético) + congelado + ensayo forward
    python -m quantedge.cli providers-check  # comprueba acceso a proveedores reales (aquí: bloqueado)
    python -m quantedge.cli forward-replay   # reproduce el holdout como sesiones forward (ensayo en seco)
    python -m quantedge.cli gate             # evalúa la puerta desde un libro forward + robustez guardada

Requiere PYTHONPATH=quant-edge/src (o instalar el paquete).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .report.build import load_configs, run_study


def _cmd_demo(args) -> int:
    thr, costs = ({}, None)
    if args.use_config:
        thr, costs = load_configs(args.config_dir)
    res = run_study(
        out_dir=args.out, n_days=args.n_days, holdout_frac=args.holdout_frac,
        n_outer=args.n_outer, thresholds=thr or None, costs=costs,
    )
    m = res["metrics"]
    o = m["oos_portfolio"]
    print("=" * 64)
    print("⚠️ ", m["synthetic_warning"])
    print("=" * 64)
    print(f"Media diaria geométrica mensual (OOS): {o['monthly_geo_daily_mean_mean']:.4%}  (objetivo 0,40%)")
    print(f"Mediana mensual OOS:                   {o['monthly_geo_daily_mean_median']:.4%}")
    print(f"Drawdown máximo OOS:                   {o['max_drawdown']:.2%}")
    print(f"DSR:  {m['statistical_robustness']['deflated_sharpe']:.3f}   "
          f"PBO: {m['statistical_robustness']['pbo']['pbo']:.2%}")
    print(f"IC95 media diaria: [{m['statistical_robustness']['bootstrap_geo_daily_ci95']['lo']:.4%}, "
          f"{m['statistical_robustness']['bootstrap_geo_daily_ci95']['hi']:.4%}]")
    print(f"Ensayo forward (holdout, is_live={m['forward_replay']['is_live']}): "
          f"{m['forward_replay']['n_sessions']} sesiones -> {m['forward_replay']['decision']}")
    print("-" * 64)
    print(f"DECISIÓN (estudio): {res['decision']}")
    print("-" * 64)
    for miss in m["gate"]["missing_evidence"]:
        print(f"  - {miss}")
    print(f"\nArtefactos en: {res['out_dir']}")
    return 0


def _cmd_providers_check(args) -> int:
    from .data.loader import build_default_providers, providers_status

    providers = build_default_providers(cache_dir=args.cache, csv_root=args.csv_root)
    print("Estado de proveedores de datos reales:")
    for row in providers_status(providers):
        mark = "✅" if row["ok"] else "❌"
        print(f"  {mark} {row['provider']:10s} — {row['detail']}")
    print("\nNota: en este entorno la política de egress bloquea los feeds de mercado (403).")
    return 0


def _cmd_forward_replay(args) -> int:
    from .model.frozen import FrozenModel
    from .paper.forward import ForwardLedger, combined_gate, replay_forward
    from .data.synthetic import default_universe
    from .data.dual_source import make_vendor_copy, reconcile
    from .validation.splitters import holdout_split
    import pandas as pd

    frozen = FrozenModel.load(args.model)
    universe = default_universe(args.n_days)
    clean = {}
    for i, (name, df_true) in enumerate(universe.items()):
        a = make_vendor_copy(df_true, seed=1001 + i)
        b = make_vendor_copy(df_true, seed=2001 + i)
        clean[name], _ = reconcile(a, b)
    n = args.n_days
    _, hold_idx = holdout_split(n, 0.25, 0.01, 1)
    holdout_dates = clean[next(iter(clean))].index[hold_idx]
    ledger_path = Path(args.ledger)
    if ledger_path.exists():
        ledger_path.unlink()
    ledger = ForwardLedger(ledger_path)
    replay_forward(frozen, clean, holdout_dates, ledger)
    print(f"Sesiones forward registradas: {ledger.portfolio_returns().shape[0]} "
          f"(is_live={ledger.is_live()}, all_shadow={ledger.all_shadow()})")
    print(f"Libro: {ledger_path}")
    return 0


def _cmd_gate(args) -> int:
    from .paper.forward import ForwardLedger, combined_gate

    dev = json.loads(Path(args.robustness).read_text(encoding="utf-8")) if args.robustness else {}
    ledger = ForwardLedger(args.ledger)
    res = combined_gate(ledger, dev, {"target_daily": 0.004}, args.benchmark)
    print(f"DECISIÓN: {res.decision}")
    for miss in res.missing_evidence:
        print(f"  - {miss}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="quantedge", description="Marco de validación de estrategias")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="Estudio de extremo a extremo (sintético) + congelado + ensayo forward")
    d.add_argument("--n-days", type=int, default=1000)
    d.add_argument("--holdout-frac", type=float, default=0.25)
    d.add_argument("--n-outer", type=int, default=5)
    d.add_argument("--out", type=str, default="quant-edge/reports")
    d.add_argument("--use-config", action="store_true", help="Cargar config/gate.yaml y config/costs.yaml")
    d.add_argument("--config-dir", type=str, default="quant-edge/config")
    d.set_defaults(func=_cmd_demo)

    pc = sub.add_parser("providers-check", help="Comprueba acceso/credenciales de proveedores reales")
    pc.add_argument("--cache", type=str, default="quant-edge/data_cache")
    pc.add_argument("--csv-root", type=str, default=None)
    pc.set_defaults(func=_cmd_providers_check)

    fr = sub.add_parser("forward-replay", help="Reproduce el holdout como sesiones forward (ensayo en seco)")
    fr.add_argument("--model", type=str, default="quant-edge/reports/frozen_model.json")
    fr.add_argument("--ledger", type=str, default="quant-edge/reports/forward_ledger.jsonl")
    fr.add_argument("--n-days", type=int, default=1000)
    fr.set_defaults(func=_cmd_forward_replay)

    g = sub.add_parser("gate", help="Evalúa la puerta desde un libro forward")
    g.add_argument("--ledger", type=str, default="quant-edge/reports/forward_ledger.jsonl")
    g.add_argument("--robustness", type=str, default=None, help="JSON con robustez de desarrollo")
    g.add_argument("--benchmark", type=float, default=0.0)
    g.set_defaults(func=_cmd_gate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
