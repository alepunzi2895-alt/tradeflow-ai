#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Feature screening ML per generazione ipotesi (skill signal-classification
+ ta-lib, 2026-09-07)

NON produce un modello da mettere in produzione — è uno strumento di RICERCA che, dati N
indicatori (i ~44 già calcolati da strategy-engine-v2.py::compute_all) + i 61 pattern
candlestick di TA-Lib, dice quali hanno potere predittivo reale sui return futuri, PRIMA
di scrivere a mano una nuova funzione segnale in signals.py. Il segnale finale resta
sempre rule-based esplicito (coerente con l'architettura del progetto) — questo script
serve solo a decidere DOVE guardare.

Metodologia (per evitare gli stessi errori già scoperti in questo progetto):
  - Feature basate su prezzo (EMA, Bollinger, Keltner, VWAP, Alligator, MACD) sono
    normalizzate come distanza in unità di ATR — usare il prezzo grezzo come feature
    farebbe "imparare" al modello solo il drift secolare (stesso bug del Hurst exponent
    su prezzi grezzi, vedi directives/02_strategies.md 2026-09-07).
  - Importanza feature misurata con permutation_importance SOLO sull'holdout (ultimo 20%
    cronologico, mai visto in training) — stesso schema 80/20 usato in tutto il resto del
    progetto (opt_harness.py). Feature importance calcolata in-sample sarebbe ottimistica.
  - Il conteggio di questa sessione va registrato in research_trials.py (asset+TF+horizon
    = 1 trial) prima di usare qualsiasi risultato per decisioni di promozione altrove.

USO:
    cd scripts
    python feature_screen.py --asset XAU --tf H1 --horizon 10
    python feature_screen.py --asset US30 --tf H4 --horizon 6

Dipendenze: scikit-learn, TA-Lib (pip install TA-Lib — wheel precompilato disponibile
per Windows/Python 3.12+, non serve compilare la libreria C a mano).
"""
import argparse
import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import talib
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

import extra_indicators as ei

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

_spec = importlib.util.spec_from_file_location("se2_fs", os.path.join(HERE, "strategy-engine-v2.py"))
SE2 = importlib.util.module_from_spec(_spec)
sys.modules["se2_fs"] = SE2
_saved_argv = sys.argv
sys.argv = [_saved_argv[0]]
try:
    _spec.loader.exec_module(SE2)
finally:
    sys.argv = _saved_argv

ASSET_FILE = {
    'XAU':  lambda tf: os.path.join(DATA, f'xauusd_{tf.lower()}_mt5.json'),
    'US30': lambda tf: os.path.join(DATA, f'us30_{tf.lower()}_mt5.json'),
}

# Feature price-based → normalizzate come (C - livello) / ATR
_PRICE_LEVEL_KEYS = ['e13', 'e34', 'e89', 'e233', 'e20', 'e50', 'e100', 'e200',
                     'bb_up', 'bb_mid', 'bb_lo', 'kc_up', 'kc_mid', 'kc_lo',
                     'vwap', 'jaw', 'teeth', 'lips']
# Oscillatori già stazionari → usati as-is
_OSCILLATOR_KEYS = ['adx', 'dip', 'dim', 'rsi', 'srsi_k', 'srsi_d', 'wpr', 'cci', 'st']
# Scala-prezzo ma non "livello" → normalizzate da ATR
_ATR_SCALE_KEYS = ['macd', 'macd_sig', 'macd_hist', 'mom']
_BOOL_KEYS = ['ob_bull', 'ob_bear', 'fvg_bull', 'fvg_bear']

_PATTERN_FUNCS = talib.get_function_groups()['Pattern Recognition']


def build_features(ind: dict) -> pd.DataFrame:
    """Costruisce la matrice feature (stazionaria) da compute_all() + pattern TA-Lib."""
    n = ind['n']
    C = np.asarray(ind['C'], dtype=float)
    O = np.asarray(ind['O'], dtype=float)
    H = np.asarray(ind['H'], dtype=float)
    L = np.asarray(ind['L'], dtype=float)
    atr = np.asarray([x if x else np.nan for x in ind['atr']], dtype=float)

    cols = {}
    for k in _PRICE_LEVEL_KEYS:
        level = np.asarray([x if x is not None else np.nan for x in ind[k]], dtype=float)
        cols[f'{k}_atr_dist'] = (C - level) / atr
    for k in _ATR_SCALE_KEYS:
        v = np.asarray([x if x is not None else np.nan for x in ind[k]], dtype=float)
        cols[f'{k}_atr_norm'] = v / atr
    for k in _OSCILLATOR_KEYS:
        cols[k] = np.asarray([x if x is not None else np.nan for x in ind[k]], dtype=float)
    for k in _BOOL_KEYS:
        cols[k] = np.asarray([1.0 if x else 0.0 for x in ind[k]], dtype=float)
    cols['bb_width_ratio'] = np.asarray(ind['bb_w'], dtype=float) / np.asarray(
        [x if x else np.nan for x in ind['bb_w_avg']], dtype=float)
    cols['atr_regime'] = atr / np.asarray([x if x else np.nan for x in ind['atr30']], dtype=float)

    for fn_name in _PATTERN_FUNCS:
        fn = getattr(talib, fn_name)
        cols[f'pat_{fn_name}'] = fn(O, H, L, C).astype(float)

    V = np.asarray(ind.get('V', [0.0] * n), dtype=float)

    # ── 18 indicatori extra (scripts/extra_indicators.py, catalogo standard TradingView) ──
    tenkan, kijun, senkou_a, senkou_b = ei.ichimoku(H, L, C)
    for name, level in [('ichi_tenkan', tenkan), ('ichi_kijun', kijun),
                        ('ichi_senkou_a', senkou_a), ('ichi_senkou_b', senkou_b)]:
        cols[f'{name}_atr_dist'] = (C - level) / atr

    cols['psar_atr_dist'] = (C - ei.parabolic_sar(H, L)) / atr
    cols['awesome_osc_atr_norm'] = ei.awesome_oscillator(H, L) / atr
    cols['mfi'] = ei.mfi(H, L, C, V)
    cols['cmf'] = ei.cmf(H, L, C, V)
    aroon_up, aroon_down = ei.aroon(H, L)
    cols['aroon_up'] = aroon_up
    cols['aroon_down'] = aroon_down
    vip, vim = ei.vortex(H, L, C)
    cols['vortex_vip'] = vip
    cols['vortex_vim'] = vim
    cols['trix'] = ei.trix(C)
    cols['ultimate_osc'] = ei.ultimate_oscillator(H, L, C)
    cols['choppiness'] = ei.choppiness_index(H, L, C)
    bull_p, bear_p = ei.elder_ray(H, L, C)
    cols['elder_bull_atr_norm'] = bull_p / atr
    cols['elder_bear_atr_norm'] = bear_p / atr
    _force_raw = pd.Series(ei.force_index(C, V))
    cols['force_index_z'] = ((_force_raw - _force_raw.rolling(100).mean())
                              / _force_raw.rolling(100).std()).values
    cols['coppock'] = ei.coppock_curve(C)
    cols['dpo_atr_norm'] = ei.dpo(C) / atr
    donch_up, donch_lo, donch_mid = ei.donchian(H, L)
    cols['donch_up_atr_dist'] = (C - donch_up) / atr
    cols['donch_lo_atr_dist'] = (C - donch_lo) / atr
    cols['donch_mid_atr_dist'] = (C - donch_mid) / atr
    chand_long, chand_short = ei.chandelier_exit(H, L, C)
    cols['chandelier_long_atr_dist'] = (C - chand_long) / atr
    cols['chandelier_short_atr_dist'] = (C - chand_short) / atr
    cols['hist_volatility'] = ei.historical_volatility(C)
    cols['fisher_transform'] = ei.fisher_transform(H, L)

    return pd.DataFrame(cols)


def build_labels(C: np.ndarray, atr: np.ndarray, horizon: int, atr_mult: float = 0.5) -> np.ndarray:
    """Label ternaria: +1 se il forward return supera +atr_mult*ATR, -1 se sotto
    -atr_mult*ATR, NaN (scartata) nella zona centrale — isola le mosse "vere" dal rumore."""
    n = len(C)
    fwd = np.full(n, np.nan)
    fwd[:n - horizon] = C[horizon:] - C[:n - horizon]
    thresh = atr_mult * atr
    y = np.full(n, np.nan)
    y[fwd > thresh] = 1.0
    y[fwd < -thresh] = 0.0
    return y


def screen(asset: str, tf: str, horizon: int, atr_mult: float = 0.5, holdout_frac: float = 0.2):
    path = ASSET_FILE[asset](tf)
    candles, _ = SE2.load_from_file(path)
    ind = SE2.compute_all(candles)
    C = np.asarray(ind['C'], dtype=float)
    atr = np.asarray([x if x else np.nan for x in ind['atr']], dtype=float)

    X = build_features(ind)
    y = build_labels(C, atr, horizon, atr_mult)

    df = X.copy()
    df['__y__'] = y
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    n = len(df)
    if n < 200:
        print(f"Dati insufficienti dopo il filtro NaN/label (n={n}) — servono più barre o horizon più corto.")
        return None

    split = int(n * (1 - holdout_frac))
    train, hold = df.iloc[:split], df.iloc[split:]
    Xtr, ytr = train.drop(columns='__y__'), train['__y__']
    Xho, yho = hold.drop(columns='__y__'), hold['__y__']

    clf = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=20,
                                  random_state=42, n_jobs=-1)
    clf.fit(Xtr, ytr)

    proba = clf.predict_proba(Xho)[:, 1]
    auc = roc_auc_score(yho, proba) if len(set(yho)) > 1 else float('nan')

    perm = permutation_importance(clf, Xho, yho, n_repeats=15, random_state=42, n_jobs=-1)
    imp = pd.DataFrame({
        'feature': Xho.columns,
        'importance_mean': perm.importances_mean,
        'importance_std': perm.importances_std,
    }).sort_values('importance_mean', ascending=False)

    return {
        'asset': asset, 'tf': tf, 'horizon': horizon, 'atr_mult': atr_mult,
        'n_total': n, 'n_train': len(train), 'n_holdout': len(hold),
        'holdout_auc': auc, 'importance': imp,
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Feature screening ML — N indicatori + pattern TA-Lib")
    ap.add_argument('--asset', choices=['XAU', 'US30'], default='XAU')
    ap.add_argument('--tf', default='H1')
    ap.add_argument('--horizon', type=int, default=10, help='barre avanti per il forward return')
    ap.add_argument('--atr-mult', type=float, default=0.5, help='soglia mossa "vera" in unità ATR')
    ap.add_argument('--top', type=int, default=25)
    args = ap.parse_args()

    res = screen(args.asset, args.tf, args.horizon, args.atr_mult)
    if res is None:
        sys.exit(1)

    print(f"\n=== Feature screening {res['asset']} {res['tf']} horizon={res['horizon']} "
          f"atr_mult={res['atr_mult']} ===")
    print(f"n totale={res['n_total']} (train={res['n_train']} holdout={res['n_holdout']})")
    print(f"Holdout AUC (out-of-sample): {res['holdout_auc']:.3f}  "
          f"(0.5 = nessun potere predittivo, {'>' if res['holdout_auc'] > 0.5 else '<='}0.55 "
          f"{'notevole per un singolo modello RF grezzo' if res['holdout_auc'] > 0.55 else 'debole/nullo'})")
    print(f"\nTop {args.top} feature per permutation importance (holdout, out-of-sample):")
    print(res['importance'].head(args.top).to_string(index=False))
