#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — "XAU Scalper Cloud v3" (Pine dell'utente) su M5.

Port fedele del Pine:
  ribbon EMA 20/28/35/43/50 (bull = EMA20 > EMA50), Bollinger 20/2, MACD 12/26/9,
  Donchian 55 con livelli Fib, ATR 14 (RMA).
  trendBuy  = bull and low <= EMA20 and close > EMA20 and close > open and MACD > signal
  revBuy    = low[1] < BBlo[1] and close > BBlo and close > open and low[1] <= Fib0.236[1]
  (mirror per SELL; buy ha precedenza come nel Pine)
  SL = Donchian low - 0.3×ATR (BUY) / Donchian high + 0.3×ATR (SELL), TP = 2R.

Esecuzione realistica (stessa di strategy-engine-v2.run_one): entry al next-bar-open,
cost model SE2.trade_cost, uscita via backtest_execution.simulate_exit (BE/trailing
come il resto del roster), max 10 trade/giorno. In più: UNA posizione alla volta
(il bot non apre due trade della stessa strategia).

Varianti fissate a priori per il miglioramento (5 trial):
  V0_PINE     port fedele
  V1_TREND    solo pullback sulla nuvola (senza reversal)
  V2_REV      solo reversal Bollinger/Donchian
  V3_SESSION  V0 + filtro sessione 8-20 (opzione già presente nel Pine)
  V4_SWING_SL V0 ma SL sullo swing delle ultime 10 barre (± 0.3 ATR) invece del Donchian 55
Selezione della migliore SOLO sul periodo di training (prima dell'holdout), poi
verifica sull'holdout.

USO: python -X utf8 scripts/research_scalper_cloud.py            # round 1
     python -X utf8 scripts/research_scalper_cloud.py --round2   # round 2 su V1_TREND
"""
import datetime
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import opt_harness as OH
import research_trials as RT
from backtest_execution import simulate_exit

SE2 = OH.SE2
TF = 'M5'
LOOKAHEAD = 360          # come run_one su M5 (30 × 12)
MAX_PER_DAY = 10


def ema(x, n):
    out = np.empty_like(x); a = 2 / (n + 1); out[0] = x[0]
    for k in range(1, len(x)):
        out[k] = a * x[k] + (1 - a) * out[k - 1]
    return out


def rma(x, n):
    out = np.full_like(x, np.nan); out[n - 1] = np.mean(x[:n]); a = 1 / n
    for k in range(n, len(x)):
        out[k] = a * x[k] + (1 - a) * out[k - 1]
    return out


def indicators(candles):
    o = np.array([c['o'] for c in candles], float); h = np.array([c['h'] for c in candles], float)
    l = np.array([c['l'] for c in candles], float); c = np.array([c['c'] for c in candles], float)
    step = (50 - 20) / 4.0
    e0 = ema(c, 20); e4 = ema(c, 50)
    s = np.lib.stride_tricks.sliding_window_view
    mid = np.full_like(c, np.nan); sd = np.full_like(c, np.nan)
    mid[19:] = s(c, 20).mean(1); sd[19:] = s(c, 20).std(1)      # ta.stdev = popolazione
    bbu, bbl = mid + 2 * sd, mid - 2 * sd
    macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9)
    hh = np.full_like(c, np.nan); ll = np.full_like(c, np.nan)
    hh[54:] = s(h, 55).max(1); ll[54:] = s(l, 55).min(1)
    sw_hi = np.full_like(c, np.nan); sw_lo = np.full_like(c, np.nan)
    sw_hi[9:] = s(h, 10).max(1); sw_lo[9:] = s(l, 10).min(1)
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); tr[0] = h[0] - l[0]
    atr = rma(tr, 14)
    up, dn = h - np.roll(h, 1), np.roll(l, 1) - l; up[0] = dn[0] = 0
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pdi = 100 * rma(pdm, 14) / atr; mdi = 100 * rma(mdm, 14) / atr
    adx = rma(np.nan_to_num(100 * abs(pdi - mdi) / np.where(pdi + mdi == 0, 1, pdi + mdi)), 14)
    return dict(htf_bull=ema(c, 600) > ema(c, 2400), adx=adx, o=o, h=h, l=l, c=c, e0=e0, e4=e4, bbu=bbu, bbl=bbl, macd=macd, sig=sig,
                hh=hh, ll=ll, sw_hi=sw_hi, sw_lo=sw_lo, atr=atr)


def signal(I, i, use_trend=True, use_rev=True):
    o, h, l, c = I['o'], I['h'], I['l'], I['c']
    e0, bull = I['e0'][i], I['e0'][i] > I['e4'][i]
    trend_buy = use_trend and bull and l[i] <= e0 < c[i] and c[i] > o[i] and I['macd'][i] > I['sig'][i]
    trend_sell = use_trend and not bull and h[i] >= e0 > c[i] and c[i] < o[i] and I['macd'][i] < I['sig'][i]
    rng1 = I['hh'][i - 1] - I['ll'][i - 1]
    rev_buy = use_rev and l[i - 1] < I['bbl'][i - 1] and c[i] > I['bbl'][i] and c[i] > o[i] \
        and l[i - 1] <= I['ll'][i - 1] + rng1 * 0.236
    rev_sell = use_rev and h[i - 1] > I['bbu'][i - 1] and c[i] < I['bbu'][i] and c[i] < o[i] \
        and h[i - 1] >= I['ll'][i - 1] + rng1 * 0.786
    if trend_buy or rev_buy: return 'buy'
    if trend_sell or rev_sell: return 'sell'
    return None


VARIANTS = {
    'V0_PINE':     dict(),
    'V1_TREND':    dict(use_rev=False),
    'V2_REV':      dict(use_trend=False),
    'V3_SESSION':  dict(session=(8, 20)),
    'V4_SWING_SL': dict(swing_sl=True),
}


def run(candles, I, use_trend=True, use_rev=True, session=None, swing_sl=False, htf=False, adx_min=None):
    trades = []; day_n = defaultdict(int); busy_until = -1; n = len(candles)
    for i in range(300, n - 1):
        if i <= busy_until: continue
        dt = datetime.datetime.fromtimestamp(candles[i]['t'], datetime.timezone.utc)
        day = dt.strftime('%Y-%m-%d')
        if day_n[day] >= MAX_PER_DAY: continue
        if session and not (session[0] <= dt.hour < session[1]): continue
        if np.isnan(I['atr'][i]) or np.isnan(I['hh'][i - 1]) or np.isnan(I['bbl'][i - 1]): continue
        d = signal(I, i, use_trend, use_rev)
        if not d: continue
        if htf and (d == 'buy') != bool(I['htf_bull'][i]): continue
        if adx_min is not None and not (I['adx'][i] >= adx_min): continue
        buy = d == 'buy'; atr = I['atr'][i]
        if swing_sl:
            sl = I['sw_lo'][i] - 0.3 * atr if buy else I['sw_hi'][i] + 0.3 * atr
        else:
            sl = I['ll'][i] - 0.3 * atr if buy else I['hh'][i] + 0.3 * atr
        entry = candles[i + 1]['o']
        risk = (entry - sl) if buy else (sl - entry)
        if risk <= 0: continue
        tp = entry + 2 * risk if buy else entry - 2 * risk
        fill = simulate_exit(candles, i + 1, min(i + LOOKAHEAD, n), entry, sl, tp, buy)
        if fill is None: continue
        pnl = (fill['price'] - entry) if buy else (entry - fill['price'])
        pnl -= SE2.trade_cost(fill['reason'] == 'sl')
        j = fill['index']
        trades.append({'date': day, 'hour': dt.hour, 'dir': d, 'entry': entry, 'risk': risk,
                       'outcome': 'win' if pnl > 0 else 'loss', 'pnl': round(pnl, 2),
                       'strategy': 'SCALPER_CLOUD', 'entry_idx': i, 'exit_idx': j,
                       'entry_ts': candles[i + 1]['t'], 'exit_ts': candles[j]['t']})
        day_n[day] += 1; busy_until = j
    return trades


# Round 2 (dopo aver visto il round 1: il reversal perde, il trend-only è in pareggio):
# 4 varianti fisse costruite su V1_TREND, stessa regola di selezione (solo TRAIN).
VARIANTS_R2 = {
    'R2_HTF':       dict(use_rev=False, htf=True),            # allineato al trend H1 (EMA50/200 H1 ≈ EMA600/2400 M5)
    'R2_ADX20':     dict(use_rev=False, adx_min=20),          # solo con trend M5 presente
    'R2_SESSION':   dict(use_rev=False, session=(8, 20)),
    'R2_HTF_SWING': dict(use_rev=False, htf=True, swing_sl=True),
}


def main():
    candles, _ = OH._data_for(TF)
    I = indicators(candles)
    round2 = '--round2' in sys.argv
    variants = VARIANTS_R2 if round2 else VARIANTS
    num_trials = RT.record_trials(len(variants), asset='XAU', strategy_id='SCALPER_CLOUD',
                                  note=('round2 su V1_TREND' if round2 else 'Pine utente XAU Scalper Cloud v3 su M5: port + 4 varianti fisse') + ' (2026-09-24)')
    print(f"M5: {len(candles)} candele · trial cumulativi {num_trials}\n")
    results = {}
    for name, kw in variants.items():
        tr = run(candles, I, **kw)
        wf = SE2.walk_forward_report(tr, folds=4, holdout_frac=0.2)
        train, hold = SE2.split_holdout(tr, 0.2)
        ev = {'trades': tr, 'full': wf['full'], 'folds': wf['folds'], 'holdout': wf['holdout'],
              'holdout_start': wf['holdout_start'], 'train': SE2.stats(train)}
        results[name] = ev
        days = len(set(t['date'] for t in tr)) or 1
        print(f"=== {name} ===  trade/giorno ≈ {len(tr)/days:.1f}  rischio medio ${np.mean([t['risk'] for t in tr]):.1f}")
        print(f"  TRAIN  : {OH.fmt(ev['train'])}")
        print(f"  HOLDOUT: {OH.fmt(ev['holdout'])}  (da {ev['holdout_start']})")
        print(f"  fold PF: {' / '.join(f'{f['pf']:.2f}' for f in ev['folds'])}")
    best = max(results, key=lambda k: results[k]['train']['pf'])
    print(f"\nMigliore sul TRAIN: {best}")
    dsr = OH.dsr_check(results[best], num_trials)
    print(f"  holdout: {OH.fmt(results[best]['holdout'])}")
    print(f"  DSR: {'n/d' if dsr is None else ('SIGNIFICATIVO' if dsr.is_significant else 'non significativo')}")
    try:
        print(f"PBO ({len(results)} varianti): {OH.pbo_check({k: v['trades'] for k, v in results.items()}).pbo:.2f}")
    except Exception as e:
        print(f"PBO n/d ({e})")


if __name__ == '__main__':
    main()
