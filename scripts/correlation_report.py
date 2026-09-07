#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Rolling correlation XAU/USD vs US30 (skill correlation-analysis, 2026-09-07)

Con 2 asset live (XAU via S20_FIB_CONFLUENCE, US30 via S30_DOW_DIP, entrambi blocchi isolati
a lotto fisso) questo script quantifica se le due strategie rischiano di correlare in regime
di risk-off — la correlation guard esistente (has_position_in_direction) è per-simbolo, non
copre il rischio cross-asset. Solo monitoraggio: NON blocca l'apertura di trade.

Uso:
    python scripts/correlation_report.py                  # H4, finestra 20 barre (default)
    python scripts/correlation_report.py --window 60 --tf h4
"""
import argparse
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')


def _load_closes(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    candles = data['candles'] if isinstance(data, dict) and 'candles' in data else data
    return {c['t']: c['c'] for c in candles}


def aligned_returns(path_a, path_b):
    """Log-return delle due serie, allineate sui timestamp comuni."""
    a = _load_closes(path_a)
    b = _load_closes(path_b)
    common = sorted(set(a) & set(b))
    closes_a = np.array([a[t] for t in common], dtype=float)
    closes_b = np.array([b[t] for t in common], dtype=float)
    ret_a = np.diff(np.log(closes_a))
    ret_b = np.diff(np.log(closes_b))
    return ret_a, ret_b, common[1:]


def rolling_correlation(ret_a, ret_b, window=20):
    """Serie di correlazione Pearson rolling su `window` barre (NaN dove non calcolabile)."""
    n = len(ret_a)
    corr = np.full(n, np.nan)
    for i in range(window, n + 1):
        a = ret_a[i - window:i]
        b = ret_b[i - window:i]
        if a.std() > 0 and b.std() > 0:
            corr[i - 1] = np.corrcoef(a, b)[0, 1]
    return corr


def report(window=20, tf='h4'):
    """Correlazione rolling attuale XAU/US30 + z-score vs distribuzione storica.
    `elevated=True` se |z-score| > 1.5 (regime di correlazione anomalo rispetto allo storico)."""
    path_a = os.path.join(DATA, f'xauusd_{tf}_mt5.json')
    path_b = os.path.join(DATA, f'us30_{tf}_mt5.json')
    ret_a, ret_b, ts = aligned_returns(path_a, path_b)
    corr = rolling_correlation(ret_a, ret_b, window)
    valid = corr[~np.isnan(corr)]
    latest = float(corr[-1]) if len(valid) else None
    hist_mean = float(valid.mean()) if len(valid) else None
    hist_std = float(valid.std()) if len(valid) else None
    z = (latest - hist_mean) / hist_std if (latest is not None and hist_std) else None
    return {
        'window': window, 'tf': tf.upper(), 'n_bars': len(ret_a),
        'latest_corr': round(latest, 3) if latest is not None else None,
        'hist_mean': round(hist_mean, 3) if hist_mean is not None else None,
        'hist_std': round(hist_std, 3) if hist_std is not None else None,
        'z_score': round(z, 2) if z is not None else None,
        'elevated': bool(z is not None and abs(z) > 1.5),
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Rolling correlation XAU/USD vs US30")
    ap.add_argument('--window', type=int, default=20)
    ap.add_argument('--tf', default='h4')
    args = ap.parse_args()

    r = report(args.window, args.tf)
    print(f"XAU/USD vs US30 — correlazione rolling {r['window']} barre {r['tf']}")
    print(f"  n barre disponibili: {r['n_bars']}")
    print(f"  corr attuale: {r['latest_corr']}")
    print(f"  media storica: {r['hist_mean']} ± {r['hist_std']}")
    flag = '  ⚠️ REGIME DI CORRELAZIONE ELEVATO' if r['elevated'] else ''
    print(f"  z-score: {r['z_score']}{flag}")
