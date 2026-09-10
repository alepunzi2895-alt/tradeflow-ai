#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Classificatore direzione da feature dei layout TradingView XAU (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════════
SOLO RICERCA. Pipeline skill `signal-classification` + `walk-forward-validation`:
  1. build_features (layout_features.py) — feature causali dai 4 indicatori del layout
  2. label = segno del ritorno forward oltre k·ATR (zona neutra scartata)
  3. walk-forward ROLLING (train ~180g / test ~30g / embargo = horizon) — no lookahead
  4. LightGBM per fold → prob OOS concatenate per ogni barra
  5. AUC OOS + feature importance (gain + permutation su OOS)
  6. salva data/layout_ml_probs_<tf>.json = {"t":[...], "prob_up":[...]}  (allineato ai bar)

USO:
    python layout_ml.py --tf H1 --horizon 10 --k-neutral 0.3
    python layout_ml.py --tf M30 --horizon 12
"""
import argparse, json, os, sys, importlib.util
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from layout_features import build_features, forward_return_labels

import lightgbm as lgb
from sklearn.metrics import roc_auc_score, accuracy_score
from sklearn.inspection import permutation_importance

# bar/giorno per TF (XAU ~23-24h) → finestre walk-forward
TF_CFG = {
    'M15': dict(horizon=16, bars_day=92,  train_d=180, test_d=30),
    'M30': dict(horizon=12, bars_day=46,  train_d=180, test_d=30),
    'H1':  dict(horizon=10, bars_day=23,  train_d=200, test_d=35),
    'H4':  dict(horizon=6,  bars_day=6,   train_d=300, test_d=60),
}

LGB_PARAMS = dict(
    objective='binary', n_estimators=300, max_depth=5, num_leaves=24,
    learning_rate=0.03, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
    min_child_samples=40, reg_lambda=1.0, class_weight='balanced',
    n_jobs=-1, verbosity=-1,
)


_SE2 = None

def _load_engine():
    global _SE2
    if _SE2 is not None:
        return _SE2
    _real = sys.stdout
    spec = importlib.util.spec_from_file_location('se2_ml', os.path.join(HERE, 'strategy-engine-v2.py'))
    se2 = importlib.util.module_from_spec(spec)
    saved = sys.argv; sys.argv = ['x']
    try:
        spec.loader.exec_module(se2)
    finally:
        sys.argv = saved
        try:
            if sys.stdout is not _real:
                sys.stdout.detach()
        except Exception:
            pass
        sys.stdout = _real
    _SE2 = se2
    return se2


def run(tf, horizon=None, k_neutral=0.3, lgb_overrides=None, quiet=False):
    cfg = TF_CFG[tf]
    horizon = horizon or cfg['horizon']
    se2 = _load_engine()
    candles, _ = se2.load_from_file(os.path.join(HERE, '..', 'data', f'xauusd_{tf.lower()}_mt5.json'))
    ind = se2.compute_all(candles)
    n = len(candles)
    X, names, T, C = build_features(candles, ind)
    atr = np.array([ind['atr'][i] or np.nan for i in range(n)])
    y, fwd = forward_return_labels(C, atr, horizon, k_neutral)

    train_sz = cfg['train_d'] * cfg['bars_day']
    test_sz  = cfg['test_d'] * cfg['bars_day']
    embargo  = horizon

    params = dict(LGB_PARAMS); params.update(lgb_overrides or {})

    prob_oos = np.full(n, np.nan)
    fold_auc = []; gains = np.zeros(len(names)); n_fold = 0
    last_fold = None

    start = 0
    while start + train_sz + embargo + test_sz <= n:
        tr = np.arange(start, start + train_sz)
        te0 = start + train_sz + embargo
        te = np.arange(te0, min(te0 + test_sz, n))
        # purge: scarta gli ultimi `horizon` bar del train (label sconfina nell'embargo)
        tr = tr[:-horizon] if horizon > 0 else tr
        m_tr = np.isfinite(X[tr]).all(1) & np.isfinite(y[tr])
        m_te = np.isfinite(X[te]).all(1)
        if m_tr.sum() < 300 or m_te.sum() < 20:
            start += test_sz; continue
        Xtr, ytr = X[tr][m_tr], y[tr][m_tr]
        model = lgb.LGBMClassifier(**params)
        model.fit(Xtr, ytr)
        p = model.predict_proba(X[te][m_te])[:, 1]
        idx = te[m_te]
        prob_oos[idx] = p
        yy = y[idx]
        mv = np.isfinite(yy)
        if mv.sum() > 10:
            try:
                fold_auc.append(roc_auc_score(yy[mv], p[mv]))
            except ValueError:
                pass
        gains += model.booster_.feature_importance(importance_type='gain')
        n_fold += 1
        last_fold = (X[te][m_te], yy, p)
        start += test_sz

    # metriche OOS aggregate
    mask = np.isfinite(prob_oos) & np.isfinite(y)
    auc = roc_auc_score(y[mask], prob_oos[mask]) if mask.sum() > 50 else float('nan')
    acc = accuracy_score(y[mask], (prob_oos[mask] > 0.5).astype(float)) if mask.sum() > 50 else float('nan')

    # sanity trading (LORDO, non il vero backtest): long se prob>0.6, short se <0.4
    def _gross_pf(thL, thS):
        long_m = mask & (prob_oos >= thL); short_m = mask & (prob_oos <= thS)
        r = np.concatenate([fwd[long_m], -fwd[short_m]])
        r = r[np.isfinite(r)]
        if len(r) < 20: return (0.0, 0)
        gw = r[r > 0].sum(); gl = -r[r < 0].sum()
        return (gw / gl if gl > 0 else 0.0, len(r))

    gain_imp = sorted(zip(names, gains / max(n_fold, 1)), key=lambda x: -x[1])

    perm_top = []
    if last_fold is not None:
        Xf, yf, _ = last_fold
        mv = np.isfinite(yf)
        if mv.sum() > 30:
            mdl = lgb.LGBMClassifier(**params)
            tr = np.arange(0, n)
            m = np.isfinite(X).all(1) & np.isfinite(y)
            mdl.fit(X[m][:-test_sz] if m.sum() > test_sz else X[m], y[m][:-test_sz] if m.sum() > test_sz else y[m])
            try:
                pi = permutation_importance(mdl, Xf[mv], yf[mv], n_repeats=8, random_state=0, scoring='roc_auc')
                perm_top = sorted(zip(names, pi.importances_mean), key=lambda x: -x[1])[:12]
            except Exception as e:
                perm_top = [('perm_failed', 0.0)]

    out = {
        'tf': tf, 'horizon': horizon, 'k_neutral': k_neutral,
        'n_folds': n_fold, 'n_oos': int(mask.sum()),
        'auc_oos': round(float(auc), 4), 'acc_oos': round(float(acc), 4),
        'fold_auc': [round(a, 3) for a in fold_auc],
        'gross_pf_60_40': [round(_gross_pf(0.60, 0.40)[0], 3), _gross_pf(0.60, 0.40)[1]],
        'gross_pf_65_35': [round(_gross_pf(0.65, 0.35)[0], 3), _gross_pf(0.65, 0.35)[1]],
        'gross_pf_70_30': [round(_gross_pf(0.70, 0.30)[0], 3), _gross_pf(0.70, 0.30)[1]],
        'gain_top': [(k, round(v, 1)) for k, v in gain_imp[:15]],
        'perm_top': [(k, round(v, 4)) for k, v in perm_top],
    }

    probs_path = os.path.join(HERE, '..', 'data', f'layout_ml_probs_{tf.lower()}.json')
    with open(probs_path, 'w') as f:
        json.dump({'t': T.tolist(), 'prob_up': [None if not np.isfinite(x) else round(float(x), 5)
                                                for x in prob_oos]}, f)
    if not quiet:
        print(json.dumps(out, indent=2))
        print(f"\nprob OOS salvate → {probs_path}")
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--tf', default='H1')
    ap.add_argument('--horizon', type=int, default=None)
    ap.add_argument('--k-neutral', type=float, default=0.3)
    a = ap.parse_args()
    run(a.tf, a.horizon, a.k_neutral)
