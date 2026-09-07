#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Studio del setup tecnico dietro i segnali storici Telegram (2026-09-07)

Allinea data/telegram_signals.json (estratti da parse_telegram_signals.py — SOLO numeri,
niente testo del canale) ai dati storici XAU H1, e confronta lo stato degli indicatori
(stessa feature matrix di feature_screen.py, ATR-normalizzata) nei bar immediatamente
precedenti ai segnali BUY/SELL del canale contro un baseline (tutti i bar) — per capire
se dietro le chiamate del canale c'è un setup tecnico sistematico e riproducibile.

Metodologia: effect size (Cohen's d) per feature, BUY-preceding vs baseline e SELL-preceding
vs baseline — non un classificatore black-box, per restare interpretabile e permettere di
tradurre subito il risultato in una funzione segnale esplicita in signals.py, coerente con
lo stile del progetto.

USO:
    python telegram_signal_study.py --tf H1 --top 25
"""
import argparse
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

from feature_screen import build_features  # riusa la stessa feature matrix di oggi
import key_levels as kl
import opt_harness as oh  # riusa il loader di strategy-engine-v2.py già collaudato (gestisce lo stdout wrapper)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
SE2 = oh.SE2


def load_signals(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)['signals']


def align_to_bars(signals, candle_times):
    """Per ogni segnale, indice dell'ultimo bar con t <= ts_unix (nearest-before, causale)."""
    idx = np.searchsorted(candle_times, [s['ts_unix'] for s in signals], side='right') - 1
    return idx


def cohens_d(a, b):
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return np.nan
    pooled_std = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    if pooled_std == 0:
        return 0.0
    return (a.mean() - b.mean()) / pooled_std


def study(tf='H1', min_bars=233, top=25, with_key_levels=True):
    path = os.path.join(DATA, f'xauusd_{tf.lower()}_mt5.json')
    candles, _ = SE2.load_from_file(path)
    ind = SE2.compute_all(candles)
    candle_times = np.array([c['t'] for c in candles])

    signals = load_signals(os.path.join(DATA, 'telegram_signals.json'))
    bar_idx = align_to_bars(signals, candle_times)

    X = build_features(ind)

    if with_key_levels:
        d1_path = os.path.join(DATA, 'xauusd_d1_mt5.json')
        d1_candles, _ = SE2.load_from_file(d1_path)
        kl_feats = kl.build_key_level_features(ind['H'], ind['L'], ind['C'], candle_times,
                                                ind['atr'], d1_candles)
        for name, arr in kl_feats.items():
            X[name] = arr

    buy_rows, sell_rows = [], []
    for s, bi in zip(signals, bar_idx):
        if bi < min_bars or bi >= len(X):
            continue
        (buy_rows if s['direction'] == 'buy' else sell_rows).append(bi)

    print(f"Segnali allineati: buy={len(buy_rows)} sell={len(sell_rows)} (su {len(X)} bar totali {tf})")

    baseline = X.iloc[min_bars:]
    Xbuy = X.iloc[buy_rows]
    Xsell = X.iloc[sell_rows]

    results = []
    for col in X.columns:
        d_buy = cohens_d(Xbuy[col].values, baseline[col].values)
        d_sell = cohens_d(Xsell[col].values, baseline[col].values)
        results.append({'feature': col, 'cohens_d_buy': d_buy, 'cohens_d_sell': d_sell,
                        'abs_max': max(abs(d_buy) if not np.isnan(d_buy) else 0,
                                       abs(d_sell) if not np.isnan(d_sell) else 0)})

    df = pd.DataFrame(results).sort_values('abs_max', ascending=False)
    print(f"\nTop {top} feature per |Cohen's d| (segnale vs baseline, {tf}):")
    print(df.head(top).to_string(index=False))
    return df, Xbuy, Xsell, baseline


def classify_check(X, positive_idx, holdout_frac=0.2, label=""):
    """RF + permutation importance, y=1 sui bar-segnale vs y=0 sul resto — stesso schema
    80/20 holdout out-of-sample di feature_screen.py. Verifica se una combinazione
    multivariata di feature deboli riesce comunque a distinguere i bar-segnale dal resto,
    anche quando nessuna feature singola mostra un Cohen's d forte. `X` deve già essere
    filtrato/allineato (righe con indicatori validi, min_bars già escluso a monte)."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score

    y = pd.Series(0, index=X.index)
    y.loc[positive_idx] = 1
    df = X.replace([np.inf, -np.inf], np.nan)
    mask = df.notna().all(axis=1)
    df, y = df[mask], y[mask]

    split = int(len(df) * (1 - holdout_frac))
    Xtr, ytr = df.iloc[:split], y.iloc[:split]
    Xho, yho = df.iloc[split:], y.iloc[split:]
    if ytr.sum() < 10 or yho.sum() < 5:
        print(f"[{label}] campione positivo insufficiente per split 80/20 — salto")
        return None

    clf = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=20,
                                  class_weight='balanced', random_state=42, n_jobs=-1)
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xho)[:, 1]
    auc = roc_auc_score(yho, proba)
    perm = permutation_importance(clf, Xho, yho, n_repeats=10, random_state=42, n_jobs=-1)
    imp = pd.DataFrame({'feature': Xho.columns, 'importance': perm.importances_mean}
                       ).sort_values('importance', ascending=False)
    print(f"\n=== Classificatore '{label}' — bar-segnale vs resto ===")
    print(f"n_train={len(Xtr)} (positivi={int(ytr.sum())}) n_holdout={len(Xho)} (positivi={int(yho.sum())})")
    print(f"Holdout AUC (out-of-sample): {auc:.3f}  (0.5 = indistinguibile dal caso)")
    print(imp.head(12).to_string(index=False))
    return auc, imp


def run_tf(tf, top):
    print(f"\n{'='*70}\nTIMEFRAME {tf}\n{'='*70}")
    df, Xbuy, Xsell, baseline = study(tf, top=top)
    X_full = pd.concat([Xbuy, Xsell, baseline]).sort_index()
    X_full = X_full[~X_full.index.duplicated()]
    auc_buy = classify_check(X_full, Xbuy.index, label=f"BUY {tf}")
    auc_sell = classify_check(X_full, Xsell.index, label=f"SELL {tf}")
    kl_top = df[df['feature'].str.contains(
        'pdh|pdl|pwh|pwl|pivot|r1|s1|r2|s2|round|swing|fib', regex=True)].head(5)
    return {
        'tf': tf,
        'auc_buy': auc_buy[0] if auc_buy else None,
        'auc_sell': auc_sell[0] if auc_sell else None,
        'top_key_level_features': kl_top[['feature', 'abs_max']].to_dict('records'),
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--tf', default='H1')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--all-tf', action='store_true',
                     help='Esegue lo studio su M5/M15/M30/H1/H4 in sequenza')
    args = ap.parse_args()

    if args.all_tf:
        summary = [run_tf(tf, args.top) for tf in ['M5', 'M15', 'M30', 'H1', 'H4']]
        print(f"\n{'='*70}\nRIEPILOGO TUTTI I TIMEFRAME\n{'='*70}")
        for s in summary:
            print(f"{s['tf']:4} AUC buy={s['auc_buy']} sell={s['auc_sell']}  "
                  f"top key-level: {s['top_key_level_features']}")
    else:
        run_tf(args.tf, args.top)
