#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Key level features per reverse-engineering segnali (2026-09-07)

Feature "livello chiave" (S/R, pivot, round number, swing, Fibonacci) — nessuna di queste
è in compute_all()/extra_indicators.py, che sono tutte indicator-shape (oscillatori/medie).
Ipotesi: i trader discrezionali (es. il provider Telegram studiato) spesso reagiscono a
livelli di prezzo piuttosto che a indicatori — questo modulo li rende testabili con lo
stesso framework (Cohen's d + classificatore) usato oggi.

SOLO research (telegram_signal_study.py) — non importato da signals.py/mt5-bot.py.
Tutte le feature sono distanze in unità ATR (stesso principio anti-drift-secolare di
extra_indicators.py) o già scala-invariante (es. posizione Fibonacci 0-1).
"""
import bisect
import datetime

import numpy as np


def _to_date(ts):
    return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).date()


def daily_prior_levels(intraday_times: np.ndarray, d1_candles: list):
    """Per ogni bar intraday, high/low del giorno precedente COMPLETO (PDH/PDL) e della
    settimana precedente COMPLETA (PWH/PWL) — causale, nessun lookahead."""
    d1_dates = [_to_date(c['t']) for c in d1_candles]
    d1_h = np.array([c['h'] for c in d1_candles])
    d1_l = np.array([c['l'] for c in d1_candles])
    d1_c = np.array([c['c'] for c in d1_candles])

    # Settimana ISO -> (week_high, week_low) aggregati sui bar D1 di quella settimana
    week_keys = [d.isocalendar()[:2] for d in d1_dates]  # (iso_year, iso_week)
    week_hl = {}
    for wk, h, l in zip(week_keys, d1_h, d1_l):
        if wk not in week_hl:
            week_hl[wk] = [h, l]
        else:
            week_hl[wk][0] = max(week_hl[wk][0], h)
            week_hl[wk][1] = min(week_hl[wk][1], l)

    n = len(intraday_times)
    pdh = np.full(n, np.nan); pdl = np.full(n, np.nan)
    pwh = np.full(n, np.nan); pwl = np.full(n, np.nan)
    piv = np.full(n, np.nan); r1 = np.full(n, np.nan); s1 = np.full(n, np.nan)
    r2 = np.full(n, np.nan); s2 = np.full(n, np.nan)

    sorted_weeks = sorted(week_hl.keys())

    for i, t in enumerate(intraday_times):
        d = _to_date(t)
        # ultimo indice D1 con data < d (giorno precedente completo) — binary search O(log n)
        idx = bisect.bisect_left(d1_dates, d) - 1
        if idx < 0:
            continue
        pdh[i], pdl[i] = d1_h[idx], d1_l[idx]
        ph, pl, pc = d1_h[idx], d1_l[idx], d1_c[idx]
        p = (ph + pl + pc) / 3.0
        piv[i] = p
        r1[i] = 2 * p - pl; s1[i] = 2 * p - ph
        r2[i] = p + (ph - pl); s2[i] = p - (ph - pl)

        wk = d.isocalendar()[:2]
        wpos = bisect.bisect_left(sorted_weeks, wk) - 1
        if wpos >= 0:
            pwh[i], pwl[i] = week_hl[sorted_weeks[wpos]]

    return {'pdh': pdh, 'pdl': pdl, 'pwh': pwh, 'pwl': pwl,
            'pivot': piv, 'r1': r1, 's1': s1, 'r2': r2, 's2': s2}


def round_number_distance(C: np.ndarray, step: float = 10.0):
    """Distanza dal livello psicologico (multiplo di `step`) più vicino."""
    nearest = np.round(C / step) * step
    return C - nearest


def swing_points(H: np.ndarray, L: np.ndarray, wing: int = 2):
    """Swing high/low a 5 barre (fractal, `wing` barre per lato) — CAUSALE: uno swing a
    bar k è "noto" solo da bar k+wing in poi (serve conferma dal lato destro)."""
    n = len(H)
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    for k in range(wing, n - wing):
        if H[k] == max(H[k - wing:k + wing + 1]):
            is_sh[k] = True
        if L[k] == min(L[k - wing:k + wing + 1]):
            is_sl[k] = True
    # Valore dell'ultimo swing NOTO al bar i (shift di `wing` barre per causalità)
    last_sh = np.full(n, np.nan); last_sl = np.full(n, np.nan)
    last_sh_v, last_sl_v = np.nan, np.nan
    for i in range(n):
        k = i - wing
        if k >= 0:
            if is_sh[k]:
                last_sh_v = H[k]
            if is_sl[k]:
                last_sl_v = L[k]
        last_sh[i] = last_sh_v
        last_sl[i] = last_sl_v
    return last_sh, last_sl


def fib_distance(C: np.ndarray, last_swing_high: np.ndarray, last_swing_low: np.ndarray):
    """Posizione del prezzo nel range [ultimo swing low, ultimo swing high] normalizzata
    0-1 (0=swing low, 1=swing high) + distanza dal livello Fib più vicino (38.2/50/61.8%)."""
    rng = last_swing_high - last_swing_low
    rng_safe = np.where(rng == 0, np.nan, rng)
    pos = (C - last_swing_low) / rng_safe
    fib_levels = np.array([0.236, 0.382, 0.5, 0.618, 0.786])
    dist_to_nearest_fib = np.full(len(C), np.nan)
    for i in range(len(C)):
        if np.isnan(pos[i]):
            continue
        dist_to_nearest_fib[i] = np.min(np.abs(fib_levels - pos[i]))
    return pos, dist_to_nearest_fib


def build_key_level_features(H, L, C, times, atr, d1_candles):
    """Ritorna dict di feature pronte per essere aggiunte a una feature matrix (distanze
    in unità ATR o già normalizzate 0-1)."""
    H, L, C = np.asarray(H, float), np.asarray(L, float), np.asarray(C, float)
    atr = np.asarray(atr, float)
    times = np.asarray(times)

    lv = daily_prior_levels(times, d1_candles)
    sh, sl = swing_points(H, L, wing=2)
    fib_pos, fib_dist = fib_distance(C, sh, sl)

    feats = {}
    for name in ['pdh', 'pdl', 'pwh', 'pwl', 'pivot', 'r1', 's1', 'r2', 's2']:
        feats[f'{name}_atr_dist'] = (C - lv[name]) / atr
    feats['round10_atr_dist'] = round_number_distance(C, 10.0) / atr
    feats['round25_atr_dist'] = round_number_distance(C, 25.0) / atr
    feats['swing_high_atr_dist'] = (C - sh) / atr
    feats['swing_low_atr_dist'] = (C - sl) / atr
    feats['fib_position'] = fib_pos
    feats['fib_dist_nearest'] = fib_dist
    return feats
