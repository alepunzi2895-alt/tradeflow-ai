#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Backtest harness delle strategie dai layout XAU_M15 / XAU_M30 /
XAU_H1_Volumes (2026-09-10).

Gira ESATTAMENTE il codice di produzione (signals.s3?_scan / s3?_manage_step) —
nessuna logica duplicata (regola CLAUDE.md). Modellato su layout_smart.py::
evaluate_ls_frozen.

  ev = evaluate_s3x('S32', tf='M5', P={...override di signals.S32_PARAMS...})
  ev = evaluate_s3x('S33', tf='M30')
  ev = evaluate_s3x('S34', tf='H1', P={'use_session_profile': False})

`ev` è compatibile con opt_harness (is_promotable / dsr_check / pbo_check).

CLI:
  python layout_s3x.py                 # baseline dei 3 sui TF dei layout
  python layout_s3x.py S33 M30         # solo uno

────────────────────────────────────────────────────────────────────────────────
VERDETTO 2026-09-10 (dopo ~195 trial + gate regime ADX, num_trials cumulativo 1687)

  S32_ORDERFLOW_SCALP  (XAU_M15) — NESSUN edge meccanico. 2 modelli provati
    (pullback-to-OB/FVG e liquidity-sweep-reversal), 4 TF (M5/M15/M30/H1): PF < 1
    o n<20. La "ICT Institutional Order Flow" non è replicabile in modo meccanico
    con OB/FVG proxy. → SOLO score in dashboard.

  S33_TREND_MOMENTUM   (XAU_M30→H1) — di superficie buono (full PF 1.72, 4/4 fold+,
    holdout PF 1.59, per-anno tutti +), MA **PBO = 1.00** (max overfit) e DSR
    p-value 0.000 @1687 trial. Il gate ADX che "sistemava" il 2025 era esso stesso
    curve-fit. → SOLO score in dashboard (no capitale).

  S34_VOLUME_AUCTION   (XAU_H1_Volumes) — full PF 2.16 ma fold 2 PF 0.13, n=36
    (1.5/mese, troppo sottile), **PBO = 0.93**, holdout troppo corto per DSR.
    → SOLO score in dashboard (no capitale).

  Confronto: S31_LAYOUT_SMART shippato con PBO 0.33. S32/33/34 stanno a 0.93-1.00.
  Coerente col dead-end da 1500 trial della sessione precedente e con
  directives/07_self_learning_log.md ("edge decaduto, NON tuning").

  Le 3 signal-core (s3?_scan / s3?_status) restano: alimentano gli score-card della
  dashboard (bias + regime + livelli + fase setup) — utili per il trading
  DISCREZIONALE su quei layout, non per ordini automatici.
────────────────────────────────────────────────────────────────────────────────
"""
import os, sys, importlib.util, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_SE2 = None


def SE2():
    global _SE2
    if _SE2 is None:
        _real = sys.stdout
        spec = importlib.util.spec_from_file_location('se2_s3x', os.path.join(HERE, 'strategy-engine-v2.py'))
        m = importlib.util.module_from_spec(spec)
        saved = sys.argv
        sys.argv = ['x']
        try:
            spec.loader.exec_module(m)
        finally:
            sys.argv = saved
            try:
                if sys.stdout is not _real:
                    sys.stdout.detach()
            except Exception:
                pass
            sys.stdout = _real
        _SE2 = m
    return _SE2


DATA = {tf: os.path.join(HERE, '..', 'data', f'xauusd_{tf.lower()}_mt5.json')
        for tf in ('M5', 'M15', 'M30', 'H1', 'H4')}
LIVE_WINDOW = ('2026-04-14', '2026-07-10')
# lookahead (barre max in trade) per TF — coerente con run_one dell'engine
TF_LOOKAHEAD = {'M5': 360, 'M15': 160, 'M30': 90, 'H1': 48, 'H4': 24}

_CACHE = {}


def _prep(tf):
    if tf in _CACHE:
        return _CACHE[tf]
    se2 = SE2()
    candles, _ = se2.load_from_file(DATA[tf])
    ind = se2.compute_all(candles)
    n = len(candles)
    O = np.array([c['o'] for c in candles]); H = np.array([c['h'] for c in candles])
    L = np.array([c['l'] for c in candles]); C = np.array([c['c'] for c in candles])
    T = np.array([c['t'] for c in candles], np.int64)
    _CACHE[tf] = (candles, ind, O, H, L, C, T, n)
    return _CACHE[tf]


# ── strategie registrate ─────────────────────────────────────────────────────
SPECS = {
    'S32': dict(tf='M5',  tag='S32_ORDERFLOW_SCALP'),
    'S33': dict(tf='M30', tag='S33_TREND_MOMENTUM'),
    'S34': dict(tf='H1',  tag='S34_VOLUME_AUCTION'),
}


def _get_i(ind, key, i):
    a = ind.get(key)
    if a is None or i >= len(a):
        return None
    return a[i]


def evaluate_s3x(strat, tf=None, P=None, folds=4, cooldown_bars=None):
    """Backtest realistico + walk-forward + holdout + finestra live, via signals.py."""
    import signals as SIG
    se2 = SE2()
    strat = strat.upper()
    spec_meta = SPECS[strat]
    tf = tf or spec_meta['tf']
    candles, ind, O, H, L, C, T, n = _prep(tf)

    base_params = {'S32': SIG.S32_PARAMS, 'S33': SIG.S33_PARAMS, 'S34': SIG.S34_PARAMS}[strat]
    PP = dict(base_params)
    if P:
        PP.update(P)
    cd = cooldown_bars if cooldown_bars is not None else PP.get('cooldown_bars', 3)
    la = TF_LOOKAHEAD[tf]

    scan = {'S32': SIG.s32_scan, 'S33': SIG.s33_scan, 'S34': SIG.s34_scan}[strat]
    e20 = ind.get('e20')
    trades = []
    state = {}
    pos = None
    last_exit = -10 ** 9

    for i in range(320, n - 2):
        atr_i = _get_i(ind, 'atr', i)
        if pos is not None:
            jh, jl, jc = H[i], L[i], C[i]
            if strat == 'S32':
                cp_, ek = SIG.s32_manage_step(pos, jh, jl, jc,
                                              e20[i] if e20 else None, atr_i, PP)
            elif strat == 'S33':
                ind_i = {'st': _get_i(ind, 'st', i), 'jaw': _get_i(ind, 'jaw', i),
                         'teeth': _get_i(ind, 'teeth', i), 'lips': _get_i(ind, 'lips', i)}
                cp_, ek = SIG.s33_manage_step(pos, jh, jl, jc, ind_i, atr_i, PP)
            else:
                lb = 5
                sl_lo = float(np.min(L[max(0, i - lb):i + 1]))
                sl_hi = float(np.max(H[max(0, i - lb):i + 1]))
                cp_, ek = SIG.s34_manage_step(pos, jh, jl, jc, sl_lo, sl_hi, atr_i, PP)
            if cp_ is None and (i - pos['ebar']) >= la:
                cp_, ek = jc, 'maxbars'
            if cp_ is not None:
                d = pos['dir']
                move = (cp_ - pos['entry']) if d == 'buy' else (pos['entry'] - cp_)
                rem = (1.0 - PP.get('tp1_frac', 0.5)) if pos['part'] else 1.0
                pnl = pos['booked'] + rem * move - se2.trade_cost(ek == 'sl')
                trades.append({'date': pos['date'], 'hour': pos['hour'], 'dir': d,
                               'entry': pos['entry'], 'outcome': 'win' if pnl > 0 else 'loss',
                               'pnl': round(pnl, 2), 'exit': ek})
                pos = None
                last_exit = i
            continue

        if i - last_exit < cd:
            continue
        if not (np.isfinite(atr_i or np.nan) and (atr_i or 0) > 0):
            continue
        dt = datetime.datetime.utcfromtimestamp(int(T[i]))
        sp = scan(ind, i, state, dt=dt, P=PP)
        if sp is None:
            continue
        entry = candles[i + 1]['o']
        d = sp['dir']; sgn = 1 if d == 'buy' else -1
        sl = sp['sl']
        risk = abs(entry - sl)
        if risk <= 0 or risk > PP['stop_max'] * atr_i:
            continue
        tp1 = entry + sgn * risk * PP['tp1_r']
        tp2 = sp['tp2']
        if not ((d == 'buy' and entry < tp1 <= tp2) or (d == 'sell' and entry > tp1 >= tp2)):
            tp2 = entry + sgn * risk * PP['tp2_r']
        pos = {'dir': d, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
               'part': False, 'booked': 0.0, 'hh': entry, 'll': entry, 'ebar': i + 1,
               'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour}

    wf = se2.walk_forward_report(trades, folds=folds, holdout_frac=0.2)
    lo, hi = LIVE_WINDOW
    live = se2.stats([t for t in trades if lo <= t['date'] <= hi])
    return {'full': wf['full'] if wf else se2.stats(trades), 'folds': wf['folds'] if wf else [],
            'holdout': wf['holdout'] if wf else se2.stats([]),
            'holdout_start': wf['holdout_start'] if wf else None,
            'live': live, 'n_trades': len(trades), 'trades': trades}


if __name__ == '__main__':
    import opt_harness as OH
    args = [a.upper() for a in sys.argv[1:]]
    if args:
        strat = args[0]
        tf = args[1] if len(args) > 1 else SPECS[strat]['tf']
        OH.print_eval(f"{strat} {tf}", evaluate_s3x(strat, tf), num_trials=1)
    else:
        for s, meta in SPECS.items():
            OH.print_eval(f"{s} {meta['tf']} · baseline (default params)",
                          evaluate_s3x(s, meta['tf']), num_trials=1)
