#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Indicatori extra per feature screening (2026-09-07)

18 indicatori standard del catalogo TradingView non presenti in strategy-engine-v2.py::
compute_all() (che resta l'unica source of truth per il bot LIVE — questo modulo è
SOLO per feature_screen.py, ricerca/hypothesis-generation, mai importato da signals.py
o mt5-bot.py). Formule standard pubbliche (non richiedono verifica via TradingView MCP —
riservata a casi con ambiguità di formula/parametri, es. tipo di smoothing non ovvio).

Tutte le funzioni prendono array numpy H,L,C,(V) e ritornano array numpy della stessa
lunghezza (NaN nel periodo di warmup). Nessuna guarda avanti nel tempo (causali).
"""
import numpy as np


def _sma(x: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[p - 1:] = (c[p:] - c[:-p]) / p
    return out


def _ema(x: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    k = 2.0 / (p + 1)
    v = x[0]
    out[0] = v
    for i in range(1, len(x)):
        v = x[i] * k + v * (1 - k)
        out[i] = v
    return out


def _wma(x: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    w = np.arange(1, p + 1, dtype=float)
    for i in range(p - 1, len(x)):
        out[i] = np.dot(x[i - p + 1:i + 1], w) / w.sum()
    return out


def _true_range(H, L, C):
    tr = np.full(len(C), np.nan)
    tr[0] = H[0] - L[0]
    tr[1:] = np.maximum.reduce([H[1:] - L[1:], np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])])
    return tr


def _rolling_max(x, p):
    out = np.full(len(x), np.nan)
    for i in range(p - 1, len(x)):
        out[i] = np.max(x[i - p + 1:i + 1])
    return out


def _rolling_min(x, p):
    out = np.full(len(x), np.nan)
    for i in range(p - 1, len(x)):
        out[i] = np.min(x[i - p + 1:i + 1])
    return out


def _roc(C, p):
    out = np.full(len(C), np.nan)
    out[p:] = (C[p:] - C[:-p]) / C[:-p] * 100.0
    return out


# ── 1. Ichimoku (9/26/52) — tenkan/kijun causali, cloud letta con lo shift standard ──
def ichimoku(H, L, C, tenkan_p=9, kijun_p=26, senkou_b_p=52, shift=26):
    tenkan = (_rolling_max(H, tenkan_p) + _rolling_min(L, tenkan_p)) / 2
    kijun = (_rolling_max(H, kijun_p) + _rolling_min(L, kijun_p)) / 2
    raw_senkou_a = (tenkan + kijun) / 2
    raw_senkou_b = (_rolling_max(H, senkou_b_p) + _rolling_min(L, senkou_b_p)) / 2
    # la "nuvola attiva" al bar i è quella calcolata `shift` barre fa (shiftata avanti sul chart)
    senkou_a = np.roll(raw_senkou_a, shift); senkou_a[:shift] = np.nan
    senkou_b = np.roll(raw_senkou_b, shift); senkou_b[:shift] = np.nan
    return tenkan, kijun, senkou_a, senkou_b


# ── 2. Parabolic SAR (af 0.02, step 0.02, max 0.2) ───────────────────────────────────
def parabolic_sar(H, L, af_step=0.02, af_max=0.2):
    n = len(H)
    sar = np.full(n, np.nan)
    if n < 2:
        return sar
    trend_up = True
    af = af_step
    ep = H[0]
    sar[0] = L[0]
    for i in range(1, n):
        prev_sar = sar[i - 1]
        new_sar = prev_sar + af * (ep - prev_sar)
        if trend_up:
            new_sar = min(new_sar, L[i - 1], L[i - 2] if i >= 2 else L[i - 1])
            if L[i] < new_sar:
                trend_up = False
                new_sar = ep
                ep = L[i]
                af = af_step
            else:
                if H[i] > ep:
                    ep = H[i]
                    af = min(af + af_step, af_max)
        else:
            new_sar = max(new_sar, H[i - 1], H[i - 2] if i >= 2 else H[i - 1])
            if H[i] > new_sar:
                trend_up = True
                new_sar = ep
                ep = H[i]
                af = af_step
            else:
                if L[i] < ep:
                    ep = L[i]
                    af = min(af + af_step, af_max)
        sar[i] = new_sar
    return sar


# ── 3. Awesome Oscillator ─────────────────────────────────────────────────────────
def awesome_oscillator(H, L, fast=5, slow=34):
    median_price = (H + L) / 2
    return _sma(median_price, fast) - _sma(median_price, slow)


# ── 4. Money Flow Index (volume-weighted RSI) ────────────────────────────────────
def mfi(H, L, C, V, p=14):
    tp = (H + L + C) / 3
    raw_mf = tp * V
    n = len(C)
    pos_mf = np.zeros(n); neg_mf = np.zeros(n)
    diff = np.diff(tp, prepend=tp[0])
    pos_mf[diff > 0] = raw_mf[diff > 0]
    neg_mf[diff < 0] = raw_mf[diff < 0]
    pos_sum = _sma(pos_mf, p) * p
    neg_sum = _sma(neg_mf, p) * p
    mfr = pos_sum / np.where(neg_sum == 0, np.nan, neg_sum)
    return 100 - (100 / (1 + mfr))


# ── 5. Chaikin Money Flow ─────────────────────────────────────────────────────────
def cmf(H, L, C, V, p=20):
    rng = np.where((H - L) == 0, np.nan, H - L)
    mfv = ((C - L) - (H - C)) / rng * V
    return _sma(mfv, p) * p / np.where(_sma(V, p) == 0, np.nan, _sma(V, p) * p)


# ── 6. Aroon (up/down, 14) ─────────────────────────────────────────────────────────
def aroon(H, L, p=14):
    n = len(H)
    up = np.full(n, np.nan); down = np.full(n, np.nan)
    for i in range(p, n):
        window_h = H[i - p:i + 1]; window_l = L[i - p:i + 1]
        bars_since_hh = p - np.argmax(window_h)
        bars_since_ll = p - np.argmin(window_l)
        up[i] = 100 * (p - bars_since_hh) / p
        down[i] = 100 * (p - bars_since_ll) / p
    return up, down


# ── 7. Vortex Indicator (14) ───────────────────────────────────────────────────────
def vortex(H, L, C, p=14):
    n = len(C)
    vm_plus = np.zeros(n); vm_minus = np.zeros(n)
    vm_plus[1:] = np.abs(H[1:] - L[:-1])
    vm_minus[1:] = np.abs(L[1:] - H[:-1])
    tr = _true_range(H, L, C)
    tr_sum = _sma(np.nan_to_num(tr), p) * p
    vip = (_sma(vm_plus, p) * p) / np.where(tr_sum == 0, np.nan, tr_sum)
    vim = (_sma(vm_minus, p) * p) / np.where(tr_sum == 0, np.nan, tr_sum)
    return vip, vim


# ── 8. TRIX (15) — rate of change della tripla EMA ────────────────────────────────
def trix(C, p=15):
    e1 = _ema(C, p)
    e2 = _ema(np.nan_to_num(e1, nan=C[0]), p)
    e3 = _ema(np.nan_to_num(e2, nan=C[0]), p)
    out = np.full(len(C), np.nan)
    out[1:] = (e3[1:] - e3[:-1]) / np.where(e3[:-1] == 0, np.nan, e3[:-1]) * 10000
    return out


# ── 9. Ultimate Oscillator (7/14/28) ───────────────────────────────────────────────
def ultimate_oscillator(H, L, C, p1=7, p2=14, p3=28):
    n = len(C)
    bp = np.zeros(n); tr = np.zeros(n)
    prev_c = np.roll(C, 1); prev_c[0] = C[0]
    low_or_close = np.minimum(L, prev_c)
    high_or_close = np.maximum(H, prev_c)
    bp = C - low_or_close
    tr = high_or_close - low_or_close
    avg1 = _sma(bp, p1) * p1 / np.where(_sma(tr, p1) == 0, np.nan, _sma(tr, p1) * p1)
    avg2 = _sma(bp, p2) * p2 / np.where(_sma(tr, p2) == 0, np.nan, _sma(tr, p2) * p2)
    avg3 = _sma(bp, p3) * p3 / np.where(_sma(tr, p3) == 0, np.nan, _sma(tr, p3) * p3)
    return 100 * (4 * avg1 + 2 * avg2 + avg3) / 7


# ── 10. Choppiness Index (14) ──────────────────────────────────────────────────────
def choppiness_index(H, L, C, p=14):
    tr = _true_range(H, L, C)
    tr_sum = _sma(np.nan_to_num(tr), p) * p
    hh = _rolling_max(H, p); ll = _rolling_min(L, p)
    rng = np.where((hh - ll) == 0, np.nan, hh - ll)
    return 100 * np.log10(tr_sum / rng) / np.log10(p)


# ── 11. Elder Ray (Bull/Bear Power, EMA13) ─────────────────────────────────────────
def elder_ray(H, L, C, p=13):
    e = _ema(C, p)
    return H - e, L - e  # bull_power, bear_power


# ── 12. Force Index (EMA13 di (C-C_prev)*V) ────────────────────────────────────────
def force_index(C, V, p=13):
    n = len(C)
    raw = np.zeros(n)
    raw[1:] = (C[1:] - C[:-1]) * V[1:]
    return _ema(raw, p)


# ── 13. Coppock Curve (WMA10 di ROC14+ROC11) ───────────────────────────────────────
def coppock_curve(C, roc1=14, roc2=11, wma_p=10):
    combined = np.nan_to_num(_roc(C, roc1)) + np.nan_to_num(_roc(C, roc2))
    return _wma(combined, wma_p)


# ── 14. Detrended Price Oscillator (20) ────────────────────────────────────────────
def dpo(C, p=20):
    sma_p = _sma(C, p)
    shift = p // 2 + 1
    out = np.full(len(C), np.nan)
    out[shift:] = C[shift:] - sma_p[:-shift]
    return out


# ── 15. Donchian Channels (20) ─────────────────────────────────────────────────────
def donchian(H, L, p=20):
    upper = _rolling_max(H, p)
    lower = _rolling_min(L, p)
    return upper, lower, (upper + lower) / 2


# ── 16. Chandelier Exit (22, mult 3) ───────────────────────────────────────────────
def chandelier_exit(H, L, C, p=22, mult=3.0):
    tr = _true_range(H, L, C)
    atr_p = _sma(np.nan_to_num(tr), p)
    hh = _rolling_max(H, p); ll = _rolling_min(L, p)
    long_stop = hh - mult * atr_p
    short_stop = ll + mult * atr_p
    return long_stop, short_stop


# ── 17. Historical Volatility (20, annualizzata) ───────────────────────────────────
def historical_volatility(C, p=20, ann_factor=252):
    n = len(C)
    log_ret = np.full(n, np.nan)
    log_ret[1:] = np.log(C[1:] / C[:-1])
    out = np.full(n, np.nan)
    for i in range(p, n):
        out[i] = np.nanstd(log_ret[i - p + 1:i + 1], ddof=1) * np.sqrt(ann_factor) * 100
    return out


# ── 18. Fisher Transform (9) ───────────────────────────────────────────────────────
def fisher_transform(H, L, p=9):
    n = len(H)
    med = (H + L) / 2
    hh = _rolling_max(med, p); ll = _rolling_min(med, p)
    rng = np.where((hh - ll) == 0, np.nan, hh - ll)
    raw = 2 * ((med - ll) / rng - 0.5)
    raw = np.clip(raw, -0.999, 0.999)
    val = np.full(n, np.nan)
    fish = np.full(n, np.nan)
    v_prev = 0.0; f_prev = 0.0
    for i in range(n):
        if np.isnan(raw[i]):
            continue
        v = 0.33 * raw[i] + 0.67 * v_prev
        v = np.clip(v, -0.999, 0.999)
        f = 0.5 * np.log((1 + v) / (1 - v)) + 0.5 * f_prev
        val[i] = v; fish[i] = f
        v_prev, f_prev = v, f
    return fish


ALL_EXTRA_INDICATORS = [
    'ichimoku', 'parabolic_sar', 'awesome_oscillator', 'mfi', 'cmf', 'aroon', 'vortex',
    'trix', 'ultimate_oscillator', 'choppiness_index', 'elder_ray', 'force_index',
    'coppock_curve', 'dpo', 'donchian', 'chandelier_exit', 'historical_volatility',
    'fisher_transform',
]
