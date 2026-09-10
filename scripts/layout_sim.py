#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Backtest con exit configurabili per le strategie dai layout XAU (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════════
SOLO RICERCA. Riusa il cost model / resolve_intrabar / walk_forward_report di
strategy-engine-v2.py, ma con una lifecycle di uscita PARAMETRIZZABILE (skill
`exit-strategies`): hard stop ATR → break-even → trailing (fisso o Chandelier) →
time-stop, con parziale opzionale a 1R. BE + trailing sempre presenti (vincolo utente).

Due sorgenti di segnale:
  • evaluate_ml(tf, thL, thS, exit_cfg)          — soglia sulle prob del classificatore
  • evaluate_confluence(tf, weights, thr, cfg)   — punteggio pesato di confluenza indicatori

Ritorna un dict `ev` compatibile con opt_harness.is_promotable / dsr_check / pbo_check.
"""
import json, os, sys, importlib.util, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from layout_features import build_features, SESS_LONDON, SESS_NY

_SE2 = None
def SE2():
    global _SE2
    if _SE2 is None:
        _real = sys.stdout
        spec = importlib.util.spec_from_file_location('se2_sim', os.path.join(HERE, 'strategy-engine-v2.py'))
        m = importlib.util.module_from_spec(spec); saved = sys.argv; sys.argv = ['x']
        try:
            spec.loader.exec_module(m)
        finally:
            sys.argv = saved
            try:
                if sys.stdout is not _real: sys.stdout.detach()
            except Exception: pass
            sys.stdout = _real
        _SE2 = m
    return _SE2

DATA = {tf: os.path.join(HERE, '..', 'data', f'xauusd_{tf.lower()}_mt5.json') for tf in ('M15','M30','H1','H4')}
LIVE_WINDOW = ('2026-04-14', '2026-07-10')
TF_LOOKAHEAD = {'M15': 120, 'M30': 60, 'H1': 30, 'H4': 30}

_CACHE = {}
def _prep(tf):
    if tf in _CACHE:
        return _CACHE[tf]
    se2 = SE2()
    candles, _ = se2.load_from_file(DATA[tf])
    ind = se2.compute_all(candles)
    X, names, T, C = build_features(candles, ind)
    atr = np.array([ind['atr'][i] or np.nan for i in range(len(candles))])
    _CACHE[tf] = (candles, ind, X, names, T, C, atr)
    return _CACHE[tf]


DEFAULT_EXIT = dict(
    tp_mult=3.0, sl_mult=1.5,
    be_trigger_r=0.8, be_offset_atr=0.05,
    trail_trigger_r=1.2, trail_give_r=0.7, trail_type='fixed',
    chand_mult=2.5, chand_lb=8,
    time_stop_bars=0, partial_r=0.0,
)


def sim_one(candles, i, sig, atr0, cfg, lookahead, n):
    """Simula un trade aperto sul segnale a bar i (entry = open di i+1). Ritorna trade dict o None."""
    se2 = SE2()
    if i + 1 >= n:
        return None
    entry = candles[i + 1]['o']
    is_buy = sig == 'buy'
    tp_d = cfg['tp_mult'] * atr0
    sl_d = cfg['sl_mult'] * atr0
    R = sl_d
    tp_p = entry + tp_d if is_buy else entry - tp_d
    sl_dyn = entry - sl_d if is_buy else entry + sl_d
    booked = 0.0; part_done = False; hh = entry; ll = entry
    exit_kind = None; close_price = None
    for k, j in enumerate(range(i + 1, min(i + lookahead, n))):
        jh = candles[j]['h']; jl = candles[j]['l']; jc = candles[j]['c']
        hh = max(hh, jh); ll = min(ll, jl)
        profit = (jc - entry) if is_buy else (entry - jc)
        # parziale a partial_r → chiudi 50%, porta a BE
        if cfg['partial_r'] > 0 and not part_done and profit >= cfg['partial_r'] * R:
            booked = 0.5 * cfg['partial_r'] * R
            part_done = True
            sl_dyn = (entry + cfg['be_offset_atr'] * atr0) if is_buy else (entry - cfg['be_offset_atr'] * atr0)
        # break-even
        if profit >= cfg['be_trigger_r'] * R:
            be = (entry + cfg['be_offset_atr'] * atr0) if is_buy else (entry - cfg['be_offset_atr'] * atr0)
            sl_dyn = max(sl_dyn, be) if is_buy else min(sl_dyn, be)
        # trailing
        if profit >= cfg['trail_trigger_r'] * R:
            if cfg['trail_type'] == 'chandelier':
                cand = (hh - cfg['chand_mult'] * atr0) if is_buy else (ll + cfg['chand_mult'] * atr0)
            else:
                cand = (jc - cfg['trail_give_r'] * R) if is_buy else (jc + cfg['trail_give_r'] * R)
            sl_dyn = max(sl_dyn, cand) if is_buy else min(sl_dyn, cand)
        res = se2.resolve_intrabar(jh, jl, tp_p, sl_dyn, is_buy)
        if res == 'win':
            close_price = tp_p; exit_kind = 'tp'; break
        if res == 'loss':
            close_price = sl_dyn; exit_kind = 'sl'; break
        if cfg['time_stop_bars'] and k + 1 >= cfg['time_stop_bars']:
            close_price = jc; exit_kind = 'time'; break
    if close_price is None:
        return None
    move = (close_price - entry) if is_buy else (entry - close_price)
    pnl = (booked + (1.0 - (0.5 if part_done else 0.0)) * move) if cfg['partial_r'] > 0 else move
    pnl -= se2.trade_cost(exit_kind == 'sl')
    dt = datetime.datetime.utcfromtimestamp(candles[i]['t'])
    return {'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour, 'dir': sig,
            'entry': entry, 'outcome': 'win' if pnl > 0 else 'loss',
            'pnl': round(pnl, 2), 'exit': exit_kind}


def _ev_from_trades(trades, folds=4):
    se2 = SE2()
    wf = se2.walk_forward_report(trades, folds=folds, holdout_frac=0.2)
    lo, hi = LIVE_WINDOW
    live = se2.stats([t for t in trades if lo <= t['date'] <= hi])
    return {
        'full': wf['full'] if wf else se2.stats(trades),
        'folds': wf['folds'] if wf else [],
        'holdout': wf['holdout'] if wf else se2.stats([]),
        'holdout_start': wf['holdout_start'] if wf else None,
        'live': live, 'n_trades': len(trades), 'trades': trades,
    }


def sim_one_x(candles, i, sig, atr0, cfg, lookahead, n):
    """come sim_one ma ritorna anche l'indice di barra in cui il trade si chiude (per one-at-a-time)."""
    se2 = SE2()
    if i + 1 >= n:
        return None, i
    entry = candles[i + 1]['o']; is_buy = sig == 'buy'
    R = cfg['sl_mult'] * atr0
    tp_p = entry + cfg['tp_mult'] * atr0 if is_buy else entry - cfg['tp_mult'] * atr0
    sl_dyn = entry - R if is_buy else entry + R
    booked = 0.0; part_done = False; hh = entry; ll = entry
    close_price = None; exit_kind = None; jj = i + 1
    for k, j in enumerate(range(i + 1, min(i + lookahead, n))):
        jj = j
        jh = candles[j]['h']; jl = candles[j]['l']; jc = candles[j]['c']
        hh = max(hh, jh); ll = min(ll, jl)
        profit = (jc - entry) if is_buy else (entry - jc)
        if cfg['partial_r'] > 0 and not part_done and profit >= cfg['partial_r'] * R:
            booked = 0.5 * cfg['partial_r'] * R; part_done = True
            sl_dyn = (entry + cfg['be_offset_atr'] * atr0) if is_buy else (entry - cfg['be_offset_atr'] * atr0)
        if profit >= cfg['be_trigger_r'] * R:
            be = (entry + cfg['be_offset_atr'] * atr0) if is_buy else (entry - cfg['be_offset_atr'] * atr0)
            sl_dyn = max(sl_dyn, be) if is_buy else min(sl_dyn, be)
        if profit >= cfg['trail_trigger_r'] * R:
            if cfg['trail_type'] == 'chandelier':
                cand = (hh - cfg['chand_mult'] * atr0) if is_buy else (ll + cfg['chand_mult'] * atr0)
            else:
                cand = (jc - cfg['trail_give_r'] * R) if is_buy else (jc + cfg['trail_give_r'] * R)
            sl_dyn = max(sl_dyn, cand) if is_buy else min(sl_dyn, cand)
        res = se2.resolve_intrabar(jh, jl, tp_p, sl_dyn, is_buy)
        if res == 'win':
            close_price = tp_p; exit_kind = 'tp'; break
        if res == 'loss':
            close_price = sl_dyn; exit_kind = 'sl'; break
        if cfg['time_stop_bars'] and k + 1 >= cfg['time_stop_bars']:
            close_price = jc; exit_kind = 'time'; break
    if close_price is None:
        return None, jj
    move = (close_price - entry) if is_buy else (entry - close_price)
    pnl = (booked + (0.5 if part_done else 1.0) * move) if cfg['partial_r'] > 0 else move
    pnl -= se2.trade_cost(exit_kind == 'sl')
    dt = datetime.datetime.utcfromtimestamp(candles[i]['t'])
    return {'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour, 'dir': sig, 'entry': entry,
            'outcome': 'win' if pnl > 0 else 'loss', 'pnl': round(pnl, 2), 'exit': exit_kind}, jj


def _run_signal(tf, sig_at, exit_cfg, session=None, one_at_a_time=True, max_day=6,
                cooldown_bars=2, direction=None, regime_gate=None):
    """direction: None | 'long' | 'short'  ·  regime_gate: None | 'trend' | 'range'"""
    candles, ind, X, names, T, C, atr = _prep(tf)
    n = len(candles)
    cfg = dict(DEFAULT_EXIT); cfg.update(exit_cfg or {})
    la = TF_LOOKAHEAD[tf]
    adx_a = np.array([ind['adx'][k] or np.nan for k in range(n)])
    trades = []; busy_until = -1; last_entry = -10 ** 9; day_n = {}
    for i in range(260, n - 2):
        if i <= busy_until or i - last_entry < cooldown_bars:
            continue
        a0 = atr[i]
        if not np.isfinite(a0) or a0 <= 0:
            continue
        dt = datetime.datetime.utcfromtimestamp(candles[i]['t'])
        if session is not None and not (session[0] <= dt.hour < session[1]):
            continue
        if regime_gate == 'trend' and not (np.isfinite(adx_a[i]) and adx_a[i] >= 22):
            continue
        if regime_gate == 'range' and not (np.isfinite(adx_a[i]) and adx_a[i] < 20):
            continue
        dk = dt.strftime('%Y-%m-%d')
        if day_n.get(dk, 0) >= max_day:
            continue
        sig = sig_at(i)
        if sig is None or (direction == 'long' and sig != 'buy') or (direction == 'short' and sig != 'sell'):
            continue
        tr, jj = sim_one_x(candles, i, sig, a0, cfg, la, n)
        if tr is None:
            busy_until = jj; continue
        trades.append(tr)
        day_n[dk] = day_n.get(dk, 0) + 1
        last_entry = i
        if one_at_a_time:
            busy_until = jj
    return _ev_from_trades(trades)


# ── sorgenti di segnale ──────────────────────────────────────────────────────
def _load_probs(tf):
    p = os.path.join(HERE, '..', 'data', f'layout_ml_probs_{tf.lower()}.json')
    with open(p) as f:
        d = json.load(f)
    return np.array([np.nan if x is None else x for x in d['prob_up']], float)


def evaluate_ml(tf, thL=0.62, thS=0.38, exit_cfg=None, session=None, probs=None, **kw):
    if probs is None:
        probs = _load_probs(tf)
    def sig_at(i):
        p = probs[i] if i < len(probs) else np.nan
        if not np.isfinite(p):
            return None
        if p >= thL:
            return 'buy'
        if p <= thS:
            return 'sell'
        return None
    return _run_signal(tf, sig_at, exit_cfg, session=session, **kw)


# confluence: punteggio pesato
CONF_KEYS = ['tlb', 'pivot', 'ema', 'keylevel', 'session', 'regime']

def evaluate_confluence(tf, weights, threshold=3.0, exit_cfg=None, session=(7, 20),
                        adx_gate=0, **kw):
    candles, ind, X, names, T, C, atr = _prep(tf)
    n = len(candles)
    idx = {k: names.index(k) for k in names}
    w = {k: weights.get(k, 0.0) for k in CONF_KEYS}

    def sig_at(i):
        row = X[i]
        if not np.isfinite(row).all():
            return None
        adx = row[idx['adx']]
        if adx_gate and np.isfinite(adx) and adx < adx_gate:
            return None
        up = dn = 0.0
        # trendline break (stretto) concorde
        if X[i][idx['tlb_up_break_s']] > 0: up += w['tlb']
        if X[i][idx['tlb_dn_break_s']] > 0: dn += w['tlb']
        # pivot: prezzo appena oltre P nella direzione + bias
        dP = row[idx['dist_P']]
        if np.isfinite(dP):
            if 0 < dP < 0.5: up += w['pivot']
            if -0.5 < dP < 0: dn += w['pivot']
        if row[idx['above_P']] > 0: up += 0.5 * w['pivot']
        else: dn += 0.5 * w['pivot']
        # EMA200 allineamento
        de = row[idx['ema200_dist']]
        if np.isfinite(de):
            if de > 0: up += w['ema']
            else: dn += w['ema']
        # key level: reclaim di PWL (buy) / rifiuto PWH (sell)
        if np.isfinite(row[idx['dist_pwl']]) and 0 < row[idx['dist_pwl']] < 0.6: up += w['keylevel']
        if np.isfinite(row[idx['dist_pwh']]) and -0.6 < row[idx['dist_pwh']] < 0: dn += w['keylevel']
        # sessione
        insess = row[idx['sess_london']] > 0 or row[idx['sess_ny']] > 0
        if insess:
            up += w['session']; dn += w['session']
        # regime: ADX alto favorisce continuazione (trend)
        if np.isfinite(adx) and adx >= 22:
            up += w['regime'] if row[idx['di_spread']] > 0 else 0
            dn += w['regime'] if row[idx['di_spread']] < 0 else 0
        if up >= threshold and up > dn:
            return 'buy'
        if dn >= threshold and dn > up:
            return 'sell'
        return None
    return _run_signal(tf, sig_at, exit_cfg, session=session, **kw)


if __name__ == '__main__':
    import opt_harness as OH
    for tf in ('H1', 'M30'):
        ev = evaluate_ml(tf, 0.62, 0.38)
        OH.print_eval(f"ML {tf} th 0.62/0.38 default-exit", ev)
