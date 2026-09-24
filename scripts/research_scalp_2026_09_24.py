#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — scalping XAU con più trade al giorno (richiesta utente).

Tre ipotesi strutturalmente diverse da quelle già bocciate (S09/S10/S20/S32, layout
TradingView, ORB Londra): parametri FISSATI a priori, nessuna griglia, così il numero
di trial resta onesto (3 ipotesi × 2 TF = 6).

  ASIA_FADE   — mean reversion nella sessione asiatica (0-6): candela che buca la
                Bollinger e richiude dentro, con ADX < 20. TP 1.2 / SL 1.2 ATR.
  RSI2_TREND  — pullback di breve nel trend (stile Connors): trend EMA50/EMA200,
                RSI(2) < 10 per BUY, > 90 per SELL, 7-20. TP 1.0 / SL 1.5 ATR.
  EXPANSION   — continuazione dopo candela di espansione in Londra/NY (7-17):
                range > 2×ATR precedente, chiusura nel 25% estremo, a favore del
                trend EMA50/EMA200. TP 1.5 / SL 1.0 ATR.

Motore: opt_harness.evaluate() (cost model ON, entry next-open, max 10 trade/giorno,
cooldown 30 min, walk-forward + holdout). M15 = 24 mesi, M5 ≈ 17 mesi (limite MT5).

USO: python -X utf8 scripts/research_scalp_2026_09_24.py
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opt_harness as OH
import research_trials as RT

_RSI2 = {}


def _rsi2(ind):
    key = id(ind)
    if key not in _RSI2:
        C = ind['C']; out = [None] * len(C); ag = al = None
        for k in range(1, len(C)):
            ch = C[k] - C[k - 1]; g, l = max(ch, 0), max(-ch, 0)
            if k == 2:
                ag, al = g, l
            elif k > 2:
                ag = (ag * 1 + g) / 2; al = (al * 1 + l) / 2
            if ag is not None:
                out[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
        _RSI2[key] = out
    return _RSI2[key]


def asia_fade(ind, i, hour=None, **_):
    if hour is None or not (0 <= hour < 7): return None
    a, lo, up = ind['adx'][i], ind['bb_lo'][i], ind['bb_up'][i]
    if None in (a, lo, up) or a >= 20: return None
    if ind['L'][i] < lo < ind['C'][i]: return 'buy'
    if ind['H'][i] > up > ind['C'][i]: return 'sell'
    return None


def rsi2_trend(ind, i, hour=None, **_):
    if hour is None or not (7 <= hour < 20): return None
    e50, e200, c = ind['e50'][i], ind['e200'][i], ind['C'][i]
    r = _rsi2(ind)[i]
    if None in (e50, e200, r): return None
    if c > e200 and e50 > e200 and r < 10: return 'buy'
    if c < e200 and e50 < e200 and r > 90: return 'sell'
    return None


def expansion(ind, i, hour=None, **_):
    if hour is None or not (7 <= hour < 17): return None
    atr_p, e50, e200 = ind['atr'][i - 1], ind['e50'][i], ind['e200'][i]
    if None in (atr_p, e50, e200): return None
    h, l, c = ind['H'][i], ind['L'][i], ind['C'][i]
    rng = h - l
    if rng <= 2 * atr_p: return None
    if e50 > e200 and c >= h - 0.25 * rng: return 'buy'
    if e50 < e200 and c <= l + 0.25 * rng: return 'sell'
    return None


HYPOTHESES = {
    'ASIA_FADE':  (asia_fade,  1.2, 1.2),
    'RSI2_TREND': (rsi2_trend, 1.0, 1.5),
    'EXPANSION':  (expansion,  1.5, 1.0),
}


def main():
    tfs = ('M15', 'M5')
    num_trials = RT.record_trials(len(HYPOTHESES) * len(tfs), asset='XAU', strategy_id='SCALP_NEW',
                                  note='scalping 2026-09-24: ASIA_FADE/RSI2_TREND/EXPANSION × M15/M5, param fissi')
    print(f"Trial cumulativi (per DSR): {num_trials}")
    for tf in tfs:
        for name, (fn, tp, sl) in HYPOTHESES.items():
            ev = OH.evaluate(f'SCALP_{name}', fn, tf=tf, tp_mult=tp, sl_mult=sl)
            OH.print_eval(f"{name} @ {tf} (TP {tp} / SL {sl} ATR)", ev, num_trials)
            f = ev['full']
            if f.get('n'):
                print(f"  trade/giorno (giorni con trade): {f['tr_day']:.2f}")


if __name__ == '__main__':
    main()
