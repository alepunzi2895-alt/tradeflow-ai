#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — scalp intraday XAU basati sulla STRUTTURA delle sessioni (M5).

Idea: invece di trigger da indicatori (tutti bocciati, vedi 05_backtest.md), usare i
livelli dove si concentrano gli ordini: range asiatico, massimo/minimo di ieri, range
d'apertura di New York. Stop strutturale oltre il livello, non multipli di ATR.

Orari in ora BROKER (UTC+3 estate / UTC+2 inverno, si sposta con l'ora legale europea,
quindi Londra 08:00 = 10:00 broker e New York 09:30 = 16:30 broker tutto l'anno).

Ipotesi fissate A PRIORI (4 trial), una posizione alla volta per strategia, max 1 trade
per lato al giorno:
  A ASIA_SWEEP   range asiatico 02-10. Tra 10 e 14 una barra buca il massimo (minimo) e
                 chiude dentro → SELL (BUY). SL = estremo della caccia + 0.1 ATR,
                 TP = lato opposto del range asiatico; scarta se TP < 1.5R.
  B ASIA_BREAK   stesso range. Tra 10 e 14 chiusura oltre il range nella direzione D1
                 (chiusura di ieri vs EMA20 D1) → segue la rottura. SL = metà range, TP 2R.
  C PDH_SWEEP    massimo/minimo di ieri. Tra 10 e 19 una barra lo buca e chiude dentro
                 → contro la rottura. SL = estremo della caccia + 0.1 ATR, TP 2R.
  D NY_ORB       range 16:30-17:00. Tra 17:00 e 19:00 chiusura oltre → segue.
                 SL = lato opposto del range, TP 2R.

Esecuzione identica a research_scalper_cloud.py: entry next-open, SE2.trade_cost,
backtest_execution.simulate_exit, walk-forward + holdout, selezione sul solo TRAIN.

USO: python -X utf8 scripts/research_session_scalps.py
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
from research_scalper_cloud import ema, rma, d1_bias

SE2 = OH.SE2
TF = 'M5'
LOOKAHEAD = 288          # max 1 giorno di barre M5


def prepare(candles):
    h = np.array([c['h'] for c in candles]); l = np.array([c['l'] for c in candles])
    c = np.array([c['c'] for c in candles])
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); tr[0] = h[0] - l[0]
    atr = rma(tr, 14)
    dts = [datetime.datetime.fromtimestamp(x['t'], datetime.timezone.utc) for x in candles]
    day = [d.date() for d in dts]; mins = [d.hour * 60 + d.minute for d in dts]
    d1, _ = d1_bias(candles)
    # massimo/minimo del giorno precedente (giorno broker)
    order, dh, dl = [], {}, {}
    for k, d in enumerate(day):
        if d not in dh: order.append(d); dh[d] = h[k]; dl[d] = l[k]
        dh[d] = max(dh[d], h[k]); dl[d] = min(dl[d], l[k])
    prev = {order[k]: order[k - 1] for k in range(1, len(order))}
    pdh = np.array([dh[prev[d]] if d in prev else np.nan for d in day])
    pdl = np.array([dl[prev[d]] if d in prev else np.nan for d in day])
    # range asiatico 02:00-10:00 e range NY 16:30-17:00, noti solo DOPO la loro chiusura
    def window_range(t0, t1):
        hi, lo = defaultdict(lambda: -np.inf), defaultdict(lambda: np.inf)
        for k, (d, m) in enumerate(zip(day, mins)):
            if t0 <= m < t1: hi[d] = max(hi[d], h[k]); lo[d] = min(lo[d], l[k])
        return (np.array([hi[d] if (d in hi and m >= t1) else np.nan for d, m in zip(day, mins)]),
                np.array([lo[d] if (d in lo and m >= t1) else np.nan for d, m in zip(day, mins)]))
    ah, al = window_range(120, 600)
    nh, nl = window_range(990, 1020)
    return dict(h=h, l=l, c=c, atr=atr, day=day, mins=mins, d1=d1, pdh=pdh, pdl=pdl,
                ah=ah, al=al, nh=nh, nl=nl)


def setups(P, i, kind):
    """Ritorna (dir, sl, tp_or_None) oppure None. tp None = 2R."""
    h, l, c, a, m = P['h'][i], P['l'][i], P['c'][i], P['atr'][i], P['mins'][i]
    if np.isnan(a): return None
    if kind == 'ASIA_SWEEP' and 600 <= m < 840 and not np.isnan(P['ah'][i]):
        hi, lo = P['ah'][i], P['al'][i]
        if h > hi and c < hi: return 'sell', h + 0.1 * a, lo
        if l < lo and c > lo: return 'buy', l - 0.1 * a, hi
    if kind == 'ASIA_BREAK' and 600 <= m < 840 and not np.isnan(P['ah'][i]):
        hi, lo = P['ah'][i], P['al'][i]; mid = (hi + lo) / 2
        if c > hi and P['d1'][i] == 1: return 'buy', mid, None
        if c < lo and P['d1'][i] == -1: return 'sell', mid, None
    if kind == 'ASIA_BREAK_ALL' and 600 <= m < 840 and not np.isnan(P['ah'][i]):
        hi, lo = P['ah'][i], P['al'][i]; mid = (hi + lo) / 2      # come ASIA_BREAK ma senza filtro D1
        if c > hi: return 'buy', mid, None
        if c < lo: return 'sell', mid, None
    if kind == 'PDH_SWEEP' and 600 <= m < 1140 and not np.isnan(P['pdh'][i]):
        if h > P['pdh'][i] and c < P['pdh'][i]: return 'sell', h + 0.1 * a, None
        if l < P['pdl'][i] and c > P['pdl'][i]: return 'buy', l - 0.1 * a, None
    if kind == 'NY_ORB' and 1020 <= m < 1140 and not np.isnan(P['nh'][i]):
        if c > P['nh'][i]: return 'buy', P['nl'][i], None
        if c < P['nl'][i]: return 'sell', P['nh'][i], None
    return None


def simulate_partial(candles, start, end, entry, stop, buy, risk):
    """Metà posizione chiusa a 1R, stop del resto portato a pareggio, resto a 2R.
    Stesso ordine pessimistico di simulate_exit: in ogni barra lo stop viene controllato
    per primo; gap oltre lo stop = fill all'apertura peggiore."""
    sgn = 1 if buy else -1; t1 = entry + sgn * risk; t2 = entry + sgn * 2 * risk
    banked = None; end = min(end, len(candles))
    if start >= end: return None
    for k in range(start, end):
        c = candles[k]
        if (c['l'] <= stop if buy else c['h'] >= stop):
            px = min(c['o'], stop) if buy else max(c['o'], stop)
            leg = (px - entry) * sgn
            return {'pnl': leg if banked is None else 0.5 * banked + 0.5 * leg, 'index': k,
                    'reason': 'sl' if banked is None else 'be'}
        if banked is None and (c['h'] >= t1 if buy else c['l'] <= t1):
            banked = risk; stop = entry
        if banked is not None and (c['h'] >= t2 if buy else c['l'] <= t2):
            return {'pnl': 0.5 * risk + 0.5 * 2 * risk, 'index': k, 'reason': 'tp'}
    leg = (candles[end - 1]['c'] - entry) * sgn
    return {'pnl': leg if banked is None else 0.5 * banked + 0.5 * leg, 'index': end - 1, 'reason': 'time'}


def run(candles, P, kind, partial=False):
    trades, busy, used, n = [], -1, set(), len(candles)
    for i in range(300, n - 1):
        if i <= busy: continue
        s = setups(P, i, kind)
        if not s: continue
        d, sl, tp = s
        if (P['day'][i], d) in used: continue
        buy = d == 'buy'; entry = candles[i + 1]['o']
        risk = (entry - sl) if buy else (sl - entry)
        if risk <= 0: continue
        if tp is None:
            tp = entry + 2 * risk if buy else entry - 2 * risk
        elif ((tp - entry) if buy else (entry - tp)) < 1.5 * risk:
            continue
        if partial:
            fill = simulate_partial(candles, i + 1, i + LOOKAHEAD, entry, sl, buy, risk)
            if fill is None: continue
            pnl = fill['pnl'] - SE2.trade_cost(fill['reason'] == 'sl')
        else:
            fill = simulate_exit(candles, i + 1, min(i + LOOKAHEAD, n), entry, sl, tp, buy)
            if fill is None: continue
            pnl = ((fill['price'] - entry) if buy else (entry - fill['price'])) - SE2.trade_cost(fill['reason'] == 'sl')
        j = fill['index']; dt = datetime.datetime.fromtimestamp(candles[i]['t'], datetime.timezone.utc)
        trades.append({'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour, 'dir': d, 'risk': risk,
                       'outcome': 'win' if pnl > 0 else 'loss', 'pnl': round(pnl, 2), 'strategy': kind,
                       'entry_idx': i, 'exit_idx': j, 'entry_ts': candles[i + 1]['t'], 'exit_ts': candles[j]['t']})
        used.add((P['day'][i], d)); busy = j
    return trades


KINDS = ('ASIA_SWEEP', 'ASIA_BREAK', 'PDH_SWEEP', 'NY_ORB')


def main():
    candles, _ = OH._data_for(TF)
    P = prepare(candles)
    num_trials = RT.record_trials(len(KINDS), asset='XAU', strategy_id='SESSION_SCALPS',
                                  note='scalp struttura sessioni M5: ASIA_SWEEP/ASIA_BREAK/PDH_SWEEP/NY_ORB (2026-09-24)')
    print(f"M5: {len(candles)} candele · trial cumulativi {num_trials}\n")
    results = {}
    for k in KINDS:
        tr = run(candles, P, k)
        if not tr:
            print(f"=== {k} === nessun trade"); continue
        wf = SE2.walk_forward_report(tr, folds=4, holdout_frac=0.2)
        train, _ = SE2.split_holdout(tr, 0.2)
        ev = {'trades': tr, 'folds': wf['folds'], 'holdout': wf['holdout'], 'train': SE2.stats(train)}
        results[k] = ev
        days = len(set(t['date'] for t in tr))
        print(f"=== {k} ===  trade/giorno attivo ≈ {len(tr)/days:.1f}  rischio medio ${np.mean([t['risk'] for t in tr]):.1f}")
        print(f"  TRAIN  : {OH.fmt(ev['train'])}")
        print(f"  HOLDOUT: {OH.fmt(ev['holdout'])}  (da {wf['holdout_start']})")
        print(f"  fold PF: {' / '.join(f'{f['pf']:.2f}' for f in ev['folds'])}")
    best = max(results, key=lambda k: results[k]['train']['pf'])
    dsr = OH.dsr_check(results[best], num_trials)
    print(f"\nMigliore sul TRAIN: {best} · holdout {OH.fmt(results[best]['holdout'])}")
    print(f"  DSR: {'n/d' if dsr is None else ('SIGNIFICATIVO' if dsr.is_significant else 'non significativo')}")
    try:
        print(f"PBO ({len(results)} ipotesi): {OH.pbo_check({k: v['trades'] for k, v in results.items()}).pbo:.2f}")
    except Exception as e:
        print(f"PBO n/d ({e})")


if __name__ == '__main__' and not {'--robust', '--partial'} & set(sys.argv):
    main()


# ── Robustezza ASIA_BREAK (2026-09-24): nessun parametro cambiato ────────────────
# python -X utf8 scripts/research_session_scalps.py --robust
def robust():
    import research_session_scalps as me
    RT.record_trials(2, asset='XAU', strategy_id='ASIA_BREAK',
                     note='robustezza: stesso setup su M15 (24m) + variante senza filtro D1 (2026-09-24)')
    for tf in ('M5', 'M15'):
        candles, _ = OH._data_for(tf)
        P = prepare(candles)
        me.LOOKAHEAD = 288 if tf == 'M5' else 96
        tr = run(candles, P, 'ASIA_BREAK')
        first = datetime.datetime.fromtimestamp(candles[0]['t'], datetime.timezone.utc).date()
        print(f"\n##### ASIA_BREAK @ {tf} (dati da {first}) #####")
        print(f"  full    : {OH.fmt(SE2.stats(tr))}")
        print(f"  BUY     : {OH.fmt(SE2.stats([t for t in tr if t['dir'] == 'buy']))}")
        print(f"  SELL    : {OH.fmt(SE2.stats([t for t in tr if t['dir'] == 'sell']))}")
        if tf == 'M15':
            print(f"  prima del 2025-04-25 (mai visto su M5): {OH.fmt(SE2.stats([t for t in tr if t['date'] < '2025-04-25']))}")
        saved = SE2.HALF_SPREAD_USD, SE2.SLIP_ENTRY_USD, SE2.SLIP_SL_USD
        SE2.HALF_SPREAD_USD, SE2.SLIP_ENTRY_USD, SE2.SLIP_SL_USD = [2 * x for x in saved]
        print(f"  costi ×2: {OH.fmt(SE2.stats(run(candles, P, 'ASIA_BREAK')))}")
        SE2.HALF_SPREAD_USD, SE2.SLIP_ENTRY_USD, SE2.SLIP_SL_USD = saved
        no = []
        for d in (1, -1):
            P2 = dict(P, d1=np.full(len(candles), d)); no += [t for t in run(candles, P2, 'ASIA_BREAK') if (t['dir'] == 'buy') == (d == 1)]
        print(f"  senza filtro D1 (entrambi i lati): {OH.fmt(SE2.stats(sorted(no, key=lambda t: t['entry_ts'])))}")


# ── Gestione parziale (2026-09-24): 1R metà + pareggio, con e senza filtro D1 ──────
# python -X utf8 scripts/research_session_scalps.py --partial
def partial_study():
    import research_session_scalps as me
    RT.record_trials(2, asset='XAU', strategy_id='ASIA_BREAK',
                     note='gestione parziale 1R+BE su ASIA_BREAK e ASIA_BREAK_ALL (2026-09-24)')
    for tf in ('M5', 'M15'):
        candles, _ = OH._data_for(tf)
        P = prepare(candles)
        me.LOOKAHEAD = 288 if tf == 'M5' else 96
        print(f"\n##### {tf} #####")
        for kind in ('ASIA_BREAK', 'ASIA_BREAK_ALL'):
            for partial in (False, True):
                tr = run(candles, P, kind, partial=partial)
                wf = SE2.walk_forward_report(tr, folds=4, holdout_frac=0.2)
                print(f"  {kind:15s} {'parziale 1R+BE' if partial else 'standard 2R   '} full {OH.fmt(SE2.stats(tr))}")
                print(f"  {'':15s} {'':14s} hold {OH.fmt(wf['holdout'])}  fold {' / '.join(f'{f['pf']:.2f}' for f in wf['folds'])}")


if __name__ == '__main__' and '--robust' in sys.argv:
    robust()
if __name__ == '__main__' and '--partial' in sys.argv:
    partial_study()
