#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Confidence score per i setup dei layout (S31/S32/S33/S34)  (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════════
Punteggio 0-100 per OGNI setup, costruito da fattori INDIPENDENTI dal trigger d'ingresso
(così che il gating aggiunga informazione vera, non ri-selezioni lo stesso combo overfit).
Pesi FISSI dalla teoria (curriculum ECABS / `directives/10_trading_education.md`) — NON
tunati: l'esperimento è "il sistema intelligente rende profittevoli S32/S33/S34?", non
"trova i pesi che le rendono profittevoli".

Fattori (± punti sul base 40):
  strat_quality   ± (score s3?_status − 50)·0.25      qualità confluenza propria del setup
  mtf_bias        +14 / −10   HTF (H4/H1) nel verso (§9 MTF) — per mean-reversion: +8 se HTF range
  structure       +14 / −12   BOS conferma (trend) · CHoCH nel verso (reversal) · penalità se CHoCH contro (§1 SMC)
  oscillator      +10         RSI/StochRSI estremo nel verso alla zona ("ricetta alta prob." §6)
  premium_disc    +8 / −6     long in discount / short in premium vs swing recente (§4 Fib)
  session         +7 / +3     overlap London+NY 13-16 UTC / sessione singola (§7)
  candle          +6          hammer/shooting-star (regola dei terzi) o engulfing nel verso (§6)
  regime_fit      +8          ADX coerente con l'intento (S33 trend ADX≥25 · S34 range ADX≤22)
  news_vol        −16 / −6    spike ATR (proxy news: no dataset storico) — §10

`setup_confidence(...)` → (score, factors_dict). `conf_tier(score)` → dict lot/label.
"""
import numpy as np

# tier di sizing (mirror RM_TIERS ma guidato dal confidence del setup, non da ADX/MACD generici)
CONF_TIERS = [
    {'max': 55, 'lot': 0.0, 'label': 'SKIP'},
    {'max': 65, 'lot': 0.7, 'label': 'LOW'},
    {'max': 75, 'lot': 1.0, 'label': 'NORMAL'},
    {'max': 85, 'lot': 1.3, 'label': 'HIGH'},
    {'max': 101, 'lot': 1.6, 'label': 'MAX'},
]


def conf_tier(score):
    for t in CONF_TIERS:
        if score < t['max']:
            return t
    return CONF_TIERS[-1]


def _hammer(o, h, l, c, d):
    """Regola dei terzi: corpo nel terzo (superiore per hammer / inferiore per star),
    mecca opposta >= 2/3 del range. d='buy' -> hammer, 'sell' -> shooting star."""
    rng = h - l
    if rng <= 0:
        return False
    body_lo = min(o, c); body_hi = max(o, c)
    if d == 'buy':
        lower_wick = body_lo - l
        return (body_lo >= l + rng * 2 / 3) and (lower_wick >= rng * 0.5)
    upper_wick = h - body_hi
    return (body_hi <= h - rng * 2 / 3) and (upper_wick >= rng * 0.5)


def _engulf(po, pc, o, c, d):
    if d == 'buy':
        return c > o and pc < po and c >= po and o <= pc
    return c < o and pc > po and c <= po and o >= pc


def setup_confidence(ind, i, d, strat, ms=None, htf_bias=None, status_score=None,
                     swing_hi=None, swing_lo=None):
    """
    ind        dict indicatori (rsi, srsi_k, atr, atr30, adx, O/H/L/C)
    d          'buy' / 'sell'
    strat      'S31' / 'S32' / 'S33' / 'S34'
    ms         dict da market_structure.structure_arrays (o None)
    htf_bias   array +1/-1/0 del bias HTF sulla barra i (o None)
    status_score  il .score di s3?_status a questa barra (o None -> 55)
    swing_hi/lo   array last swing high/low (per premium/discount) (o None)
    -> (score float 0-100, factors dict)
    """
    reversal = strat in ('S32', 'S34')
    f = {}
    score = 40.0
    C = ind['C']; O = ind['O']; H = ind['H']; L = ind['L']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    a30 = ind['atr30'][i] if (ind.get('atr30') and i < len(ind['atr30']) and ind['atr30'][i]) else None

    # 1) qualità del setup (confluenza propria)
    ss = 55.0 if status_score is None else float(status_score)
    f['strat_quality'] = round((ss - 50.0) * 0.25, 1)
    score += f['strat_quality']

    # 2) MTF bias (§9)
    hb = None
    if htf_bias is not None and i < len(htf_bias):
        hb = htf_bias[i]
    if hb is not None:
        want = 1 if d == 'buy' else -1
        if reversal:
            f['mtf_bias'] = 8.0 if hb == 0 else (4.0 if hb == want else -4.0)
        else:
            f['mtf_bias'] = 14.0 if hb == want else (-10.0 if hb == -want else 0.0)
        score += f['mtf_bias']

    # 3) struttura SMC (§1)
    if ms is not None:
        tr = ms['ms_trend'][i]
        b_since_bos = ms['ms_bars_since_bos'][i]
        b_since_choch = ms['ms_bars_since_choch'][i]
        choch_dir = 0
        # verso dell'ultimo CHoCH: cerchiamo indietro l'ultimo != 0
        if b_since_choch < 60:
            j = i - int(b_since_choch)
            if 0 <= j < len(ms['ms_choch']):
                choch_dir = ms['ms_choch'][j]
        want = 1 if d == 'buy' else -1
        if reversal:
            v = 0.0
            if choch_dir == want and b_since_choch <= 20:
                v += 12.0
            if tr == 0:
                v += 6.0
            if tr == -want:              # struttura ancora forte contro il fade -> rischio
                v -= 8.0
            f['structure'] = v
        else:
            v = 0.0
            if tr == want:
                v += 8.0
            if b_since_bos <= 12 and ms['ms_bos'][max(0, i - int(b_since_bos))] == want:
                v += 6.0
            if choch_dir == -want and b_since_choch <= 15:
                v -= 12.0
            f['structure'] = v
        score += f['structure']

    # 4) conferma oscillatore alla zona (§6, solo reversal)
    if reversal:
        r = ind['rsi'][i] if (ind.get('rsi') and ind['rsi'][i] is not None) else None
        sk = None
        for k in ('srsi_k', 'stoch_k'):
            a = ind.get(k)
            if a is not None and i < len(a) and a[i] is not None:
                sk = a[i]; break
        osc = 0.0
        if d == 'buy':
            if (r is not None and r < 35) or (sk is not None and sk < 25):
                osc = 10.0
        else:
            if (r is not None and r > 65) or (sk is not None and sk > 75):
                osc = 10.0
        f['oscillator'] = osc
        score += osc

    # 5) premium / discount vs swing recente (§4)
    sh = swing_hi[i] if (swing_hi is not None and i < len(swing_hi)) else None
    sl_ = swing_lo[i] if (swing_lo is not None and i < len(swing_lo)) else None
    if sh is not None and sl_ is not None and sh > sl_ and np.isfinite(sh) and np.isfinite(sl_):
        pos = (C[i] - sl_) / (sh - sl_)
        if d == 'buy':
            f['premium_disc'] = 8.0 if pos < 0.5 else -6.0
        else:
            f['premium_disc'] = 8.0 if pos > 0.5 else -6.0
        score += f['premium_disc']

    # 6) sessione (§7) — hour UTC deve essere passato via ind['_hour'] o dedotto
    hour = ind.get('_hour')
    if hour is not None:
        if 13 <= hour < 16:
            f['session'] = 7.0
        elif 8 <= hour < 21:
            f['session'] = 3.0
        else:
            f['session'] = 0.0
        score += f['session']

    # 7) candela reale nel verso (§6)
    cndl = 0.0
    if _hammer(O[i], H[i], L[i], C[i], d):
        cndl = 6.0
    elif i > 0 and _engulf(O[i - 1], C[i - 1], O[i], C[i], d):
        cndl = 6.0
    f['candle'] = cndl
    score += cndl

    # 8) regime fit
    ax = ind['adx'][i] if (ind.get('adx') and ind['adx'][i] is not None) else None
    if ax is not None:
        if strat == 'S33':
            f['regime_fit'] = 8.0 if ax >= 25 else (-6.0 if ax < 18 else 0.0)
        elif strat == 'S34':
            f['regime_fit'] = 8.0 if ax <= 22 else (-6.0 if ax > 28 else 0.0)
        elif strat == 'S31':
            f['regime_fit'] = 6.0 if ax >= 20 else 0.0
        else:
            f['regime_fit'] = 0.0
        score += f['regime_fit']

    # 9) news / volatilità (proxy: nessun dataset news storico) §10
    if atr and a30:
        rv = atr / a30
        if rv > 2.5:
            f['news_vol'] = -16.0
        elif rv > 1.6:
            f['news_vol'] = -6.0
        else:
            f['news_vol'] = 0.0
        score += f['news_vol']

    score = max(0.0, min(100.0, score))
    return score, f
