"""CLI de quant-edge.

Uso:
    python -m quantedge.cli demo            # ejecuta el estudio completo (sintético)
    python -m quantedge.cli demo --n-days 1200 --out quant-edge/reports

Requiere PYTHONPATH=quant-edge/src (o instalar el paquete).
"""
from __future__ import annotations

import argparse
import json
import sys

from .report.build import run_study


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="quantedge", description="Marco de validación de estrategias")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="Ejecuta el estudio de extremo a extremo sobre datos sintéticos")
    d.add_argument("--n-days", type=int, default=1000)
    d.add_argument("--holdout-frac", type=float, default=0.25)
    d.add_argument("--n-outer", type=int, default=5)
    d.add_argument("--out", type=str, default="quant-edge/reports")

    args = p.parse_args(argv)
    if args.cmd == "demo":
        res = run_study(
            out_dir=args.out,
            n_days=args.n_days,
            holdout_frac=args.holdout_frac,
            n_outer=args.n_outer,
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
        print("-" * 64)
        print(f"DECISIÓN: {res['decision']}")
        print("-" * 64)
        if m["gate"]["missing_evidence"]:
            print("Evidencia que falta:")
            for miss in m["gate"]["missing_evidence"]:
                print(f"  - {miss}")
        print(f"\nArtefactos en: {res['out_dir']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
