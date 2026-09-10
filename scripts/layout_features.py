#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Feature matrix dagli indicatori dei layout TradingView XAU (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════
SOLO RICERCA — usato da layout_ml.py / layout_sim.py. NON importato da mt5-bot.py.

Trasforma gli array di compute_all() (strategy-engine-v2.py) — che includono i port
degli indicatori dei layout: Trendlines with Breaks [LuxAlgo] (tlb_*), Pivot Points
Standard Fibonacci (dpiv/dr1-3/ds1-3), Key Levels SpacemanBTC (pdh/pdl/pwh/pwl),
EMA200 — in una matrice di feature CAUSALI (nessun lookahead), tutte scala-invarianti
(distanze in unità ATR o 0/1) per non far imparare al modello il drift secolare
dell'oro (stesso principio di extra_indicators.py / feature_screen.py).

Sessioni LuxAlgo del layout (lette da data_get_indicator, chart tz UTC+2):
  London 09-18 local → 07-16 UTC · New York 14-23 local → 12-21 UTC
"""
import numpy as np

SESS_LONDON = (7, 16)     # UTC
SESS_NY     = (12, 21)    # UTC
SESS_OVERLAP = (12, 16)   # UTC — London+NY overlap (massima liquidità)

ATR_PCT_LB = 100          # lookback per il percentile ATR


def _safe(a, i):
    v = a[i] if (a is not None and i < len(a)) else None
    return np.nan if v is None else float(v)


def build_features(candles, ind, warmup=260):
    """Ritorna (X, names, times, close) con X shape (n, k), NaN dove non calcolabile.
    `warmup` = prime barre da marcare NaN (EMA200 + pivot daily + trendline lag)."""
    n = len(candles)
    C = np.array(ind['C'], float); H = np.array(ind['H'], float); L = np.array(ind['L'], float)
    O = np.array(ind['O'], float); V = np.array(ind['V'], float)
    T = np.array(ind['T'], np.int64)
    atr = np.array([_safe(ind['atr'], i) for i in range(n)])
    atr = np.where((atr <= 0) | ~np.isfinite(atr), np.nan, atr)

    hours = np.array([((t // 3600) % 24) for t in T], int)
    dow   = np.array([(((t // 86400) + 4) % 7) for t in T], int)  # 1970-01-01 = giovedì(3)? -> +4 => lun=0

    def arr(key):
        a = ind.get(key)
        return np.array([_safe(a, i) for i in range(n)]) if a is not None else np.full(n, np.nan)

    tlb_up = np.array([1.0 if (ind.get('tlb_up') and ind['tlb_up'][i]) else 0.0 for i in range(n)])
    tlb_dn = np.array([1.0 if (ind.get('tlb_dn') and ind['tlb_dn'][i]) else 0.0 for i in range(n)])
    tlb_up_s = np.array([1.0 if (ind.get('tlb_up_s') and ind['tlb_up_s'][i]) else 0.0 for i in range(n)])
    tlb_dn_s = np.array([1.0 if (ind.get('tlb_dn_s') and ind['tlb_dn_s'][i]) else 0.0 for i in range(n)])
    tlb_upper = arr('tlb_upper'); tlb_lower = arr('tlb_lower')
    ema200 = arr('ema200')
    adx = arr('adx'); dip = arr('dip'); dim = arr('dim'); rsi = arr('rsi')
    bb_w = arr('bb_w'); bb_w_avg = arr('bb_w_avg'); mom = arr('mom'); wpr = arr('wpr')
    srsi_k = arr('srsi_k')
    dpiv = arr('dpiv'); dr1 = arr('dr1'); dr2 = arr('dr2'); dr3 = arr('dr3')
    ds1 = arr('ds1'); ds2 = arr('ds2'); ds3 = arr('ds3')
    pdh = arr('pdh'); pdl = arr('pdl'); pwh = arr('pwh'); pwl = arr('pwl')

    # rolling: barre dall'ultimo break; sweep intraday di PDH/PDL
    bars_since_up = np.full(n, 99.0); bars_since_dn = np.full(n, 99.0)
    cnt_u = cnt_d = 99
    for i in range(n):
        cnt_u = 0 if tlb_up_s[i] else min(cnt_u + 1, 99)
        cnt_d = 0 if tlb_dn_s[i] else min(cnt_d + 1, 99)
        bars_since_up[i] = cnt_u; bars_since_dn[i] = cnt_d

    day_id = (T // 86400)
    pdh_swept = np.zeros(n); pdl_swept = np.zeros(n)
    cur_day = -1; hi_run = -1e18; lo_run = 1e18
    for i in range(n):
        if day_id[i] != cur_day:
            cur_day = day_id[i]; hi_run = H[i]; lo_run = L[i]
        else:
            hi_run = max(hi_run, H[i]); lo_run = min(lo_run, L[i])
        if np.isfinite(pdh[i]) and hi_run >= pdh[i]: pdh_swept[i] = 1.0
        if np.isfinite(pdl[i]) and lo_run <= pdl[i]: pdl_swept[i] = 1.0

    # percentile ATR rolling
    atr_pct = np.full(n, np.nan)
    for i in range(ATR_PCT_LB, n):
        w = atr[i - ATR_PCT_LB:i]
        w = w[np.isfinite(w)]
        if len(w) > 20 and np.isfinite(atr[i]):
            atr_pct[i] = (w < atr[i]).mean()

    # nearest level (pivot Fib + key level) e conteggio confluenza
    lvl_keys = [dpiv, dr1, dr2, dr3, ds1, ds2, ds3, pdh, pdl, pwh, pwl]
    nearest_signed = np.full(n, np.nan); n_within = np.full(n, np.nan)
    for i in range(n):
        if not np.isfinite(atr[i]):
            continue
        ds = [(C[i] - lv[i]) for lv in lvl_keys if np.isfinite(lv[i])]
        if not ds:
            continue
        a = np.array(ds)
        nearest_signed[i] = a[np.argmin(np.abs(a))] / atr[i]
        n_within[i] = float((np.abs(a) <= atr[i]).sum())

    def datr(level):
        return (C - level) / atr

    feats = {
        # ── Trendlines with Breaks [LuxAlgo] ──
        'tlb_upos_dist':   datr(tlb_upper),
        'tlb_dnos_dist':   datr(tlb_lower),
        'tlb_up_break':    tlb_up,
        'tlb_dn_break':    tlb_dn,
        'tlb_up_break_s':  tlb_up_s,
        'tlb_dn_break_s':  tlb_dn_s,
        'tlb_bars_since_up': np.minimum(bars_since_up, 50) / 50.0,
        'tlb_bars_since_dn': np.minimum(bars_since_dn, 50) / 50.0,
        # ── Pivot Points Standard (Fibonacci, daily) ──
        'dist_P':   datr(dpiv),
        'dist_R1':  datr(dr1), 'dist_S1': datr(ds1),
        'dist_R2':  datr(dr2), 'dist_S2': datr(ds2),
        'dist_R3':  datr(dr3), 'dist_S3': datr(ds3),
        'above_P':  (C > dpiv).astype(float),
        'nearest_lvl_signed': nearest_signed,
        'n_levels_within_atr': n_within,
        # ── Key Levels SpacemanBTC IDWM ──
        'dist_pdh': datr(pdh), 'dist_pdl': datr(pdl),
        'dist_pwh': datr(pwh), 'dist_pwl': datr(pwl),
        'pdh_swept': pdh_swept, 'pdl_swept': pdl_swept,
        # ── Moving Average Exponential 200 ──
        'ema200_dist': datr(ema200),
        'ema200_slope': (ema200 - np.roll(ema200, 10)) / atr,
        # ── Sessions [LuxAlgo] ──
        'sess_london': ((hours >= SESS_LONDON[0]) & (hours < SESS_LONDON[1])).astype(float),
        'sess_ny':     ((hours >= SESS_NY[0]) & (hours < SESS_NY[1])).astype(float),
        'sess_overlap':((hours >= SESS_OVERLAP[0]) & (hours < SESS_OVERLAP[1])).astype(float),
        'hour_sin': np.sin(2 * np.pi * hours / 24),
        'hour_cos': np.cos(2 * np.pi * hours / 24),
        'dow': dow.astype(float),
        # ── Contesto di regime ──
        'adx': adx, 'di_spread': (dip - dim),
        'rsi': rsi, 'srsi_k': srsi_k,
        'atr_pct': atr_pct,
        'bb_width_ratio': bb_w / np.where(bb_w_avg > 0, bb_w_avg, np.nan),
        'roc10': mom, 'wpr': wpr,
        'candle_body_atr': (C - O) / atr,
        'upper_wick_atr': (H - np.maximum(C, O)) / atr,
        'lower_wick_atr': (np.minimum(C, O) - L) / atr,
    }
    names = list(feats.keys())
    X = np.column_stack([feats[k] for k in names]).astype(float)
    X[np.isinf(X)] = np.nan
    X[:warmup] = np.nan
    return X, names, T, C


def forward_return_labels(close, atr, horizon, k_neutral=0.3):
    """Label direzione: +1 se ret forward > k·ATR, 0 se < -k·ATR, NaN nella zona neutra.
    `atr` in prezzo → soglia neutra scala con la volatilità (no drift secolare)."""
    n = len(close)
    fwd = np.full(n, np.nan)
    fwd[:n - horizon] = close[horizon:] / close[:n - horizon] - 1.0
    thr = k_neutral * atr / close
    y = np.full(n, np.nan)
    y[fwd > thr] = 1.0
    y[fwd < -thr] = 0.0
    return y, fwd


if __name__ == '__main__':
    import sys, os, importlib.util
    HERE = os.path.dirname(os.path.abspath(__file__))
    tf = sys.argv[1] if len(sys.argv) > 1 else 'H1'
    spec = importlib.util.spec_from_file_location('se2', os.path.join(HERE, 'strategy-engine-v2.py'))
    se2 = importlib.util.module_from_spec(spec); sys.argv = ['x']; spec.loader.exec_module(se2)
    path = os.path.join(HERE, '..', 'data', f'xauusd_{tf.lower()}_mt5.json')
    candles, _ = se2.load_from_file(path)
    ind = se2.compute_all(candles)
    X, names, T, C = build_features(candles, ind)
    atrp = np.array([ind['atr'][i] or np.nan for i in range(len(candles))])
    y, fwd = forward_return_labels(C, atrp, horizon={'M15': 16, 'M30': 12, 'H1': 10, 'H4': 6}.get(tf, 10))
    valid = np.isfinite(X).all(axis=1) & np.isfinite(y)
    print(f"{tf}: {len(candles)} bars, {X.shape[1]} feat, {valid.sum()} righe valide "
          f"({np.nanmean(y[valid])*100:.1f}% up)")
    print("features:", ", ".join(names))
