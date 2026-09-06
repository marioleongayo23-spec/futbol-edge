"""Reproducible chronological comparison of the corrected and previous DC fit.

Usage: python scripts/audit_model_evaluation.py --csv SP1.csv --output report.json
CSV: football-data.co.uk season results. No odds or future statistics are used.
The last three chronological blocks are evaluated on identical games. This
isolates the likelihood fix; it does not certify the complete production stack.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import types

from futbol_pred.backtest.metrics import aggregate
from futbol_pred.model.dixon_coles import DixonColesModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-ref', default='598ada967ccd96f92892e5f472317907a5104825')
    args = parser.parse_args()
    source = args.csv.read_bytes()
    # utf-8-sig handles native provider BOM. A requests text export may contain
    # a decoded Latin-1 BOM, which only affects the unused Div column.
    data = list(csv.DictReader(io.StringIO(source.decode('utf-8-sig'))))
    rows = []
    for row in data:
        if not row.get('FTHG') or not row.get('FTAG'):
            continue
        date = datetime.strptime(row['Date'], '%d/%m/%Y').replace(tzinfo=timezone.utc)
        rows.append((date, row['HomeTeam'], row['AwayTeam'], int(row['FTHG']), int(row['FTAG'])))
    rows.sort(key=lambda r: r[0])
    if len(rows) < 100:
        raise ValueError('At least 100 completed fixtures are required')
    code = subprocess.check_output(['git', 'show', f'{args.baseline_ref}:football/src/futbol_pred/model/dixon_coles.py'], text=True)
    legacy = types.ModuleType('futbol_pred.model._audit_baseline')
    sys.modules[legacy.__name__] = legacy
    exec(compile(code, '<baseline-ref>', 'exec'), legacy.__dict__)
    predictions = {'previous': [], 'corrected': []}
    folds = []
    cuts = [round(len(rows) * x) for x in (.55, .70, .85)] + [len(rows)]
    for left, right in zip(cuts, cuts[1:]):
        cutoff = rows[left][0]
        train = [r for r in rows[:left] if r[0] < cutoff]
        test = rows[left:right]
        fold = {'train_n': len(train), 'test_n': len(test), 'cutoff': cutoff.isoformat()}
        for name, cls in [('previous', legacy.DixonColesModel), ('corrected', DixonColesModel)]:
            model = cls().fit([r[1] for r in train], [r[2] for r in train],
                              [r[3] for r in train], [r[4] for r in train])
            sample = [(model.predict_matrix(r[1], r[2]).one_x_two(), '1' if r[3] > r[4] else '2' if r[3] < r[4] else 'X') for r in test]
            predictions[name].extend(sample)
            fold[name] = aggregate(sample)
        folds.append(fold)
    metrics = {name: aggregate(sample) for name, sample in predictions.items()}
    report = {'dataset_sha256': hashlib.sha256(source).hexdigest(), 'rows': len(rows),
              'baseline_ref': args.baseline_ref, 'method': 'three expanding chronological blocks, identical evaluation fixtures',
              'scope': 'Dixon-Coles likelihood correction only; excludes Elo, pseudo-xG, market blending and betting returns',
              'folds': folds, 'metrics': metrics,
              'delta_corrected_minus_previous': {key: metrics['corrected'][key] - metrics['previous'][key] for key in ('log_loss', 'brier', 'rps', 'accuracy')}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'metrics': metrics, 'deltas': report['delta_corrected_minus_previous']}, indent=2))


if __name__ == '__main__':
    main()
