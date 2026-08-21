"""Interfaz de línea de comandos.

Ejemplos:
    python -m futbol_pred.cli run --league laliga
    python -m futbol_pred.cli value --probs 0.5,0.3,0.2 --odds 2.1,3.6,3.4
"""

from __future__ import annotations

import argparse
import json

from .pipeline import run_backtest, run_pipeline, value_report


def _cmd_run(args) -> None:
    report = run_pipeline(league=args.league, season=args.season)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _cmd_backtest(args) -> None:
    report = run_backtest(league=args.league, season=args.season)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _cmd_value(args) -> None:
    probs = [float(x) for x in args.probs.split(",")]
    odds = [float(x) for x in args.odds.split(",")]
    keys = args.selections.split(",") if args.selections else ["1", "X", "2"]
    report = value_report(dict(zip(keys, probs)), dict(zip(keys, odds)), args.market)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="futbol_pred")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Ejecuta el pipeline de una liga")
    p_run.add_argument("--league", default="laliga",
                       choices=["laliga", "segunda", "champions"])
    p_run.add_argument("--season", type=int, default=None)
    p_run.set_defaults(func=_cmd_run)

    p_bt = sub.add_parser("backtest", help="Walk-forward: baseline vs Elo vs Dixon-Coles")
    p_bt.add_argument("--league", default="laliga",
                      choices=["laliga", "segunda", "champions"])
    p_bt.add_argument("--season", type=int, default=None)
    p_bt.set_defaults(func=_cmd_backtest)

    p_val = sub.add_parser("value", help="Detecta value bets dado probs y cuotas")
    p_val.add_argument("--probs", required=True, help="Probabilidades separadas por coma")
    p_val.add_argument("--odds", required=True, help="Cuotas separadas por coma")
    p_val.add_argument("--selections", default="", help="Etiquetas (por defecto 1,X,2)")
    p_val.add_argument("--market", default="1x2")
    p_val.set_defaults(func=_cmd_value)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
