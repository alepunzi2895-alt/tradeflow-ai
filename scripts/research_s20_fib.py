#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Sprint di ricerca parametri S20_FIB_CONFLUENCE (2026-08-28)

Il port fedele del Pine ("Repro Overlay — M5") fallisce il backtest su M5/M15/M30
(WR 10-18%, PF 0.49-1.06 standalone). Diagnosi: SL ancorato a Fib 0.236 sotto un
pullback poco profondo e' troppo stretto su TF bassi -> stop-out da rumore prima
che il movimento verso TP1 (Fib 0.618) si sviluppi.

Questo script sweepa i parametri ad alta leva con split cronologico 80% IS / 20% OOS.
Un cambiamento e' adottabile solo se OOS PF > ~1.2 in modo robusto sulle celle vicine,
con N ragionevole.

Uso: python -X utf8 scripts/research_s20_fib.py
"""
import sys, os, importlib.util, itertools
from collections import defaultdict

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location("se2", os.path.join(HERE, "strategy-engine-v2.py"))
se2 = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]
spec.loader.exec_module(se2)

DATA = {
    'M5':  os.path.join(HERE, '..', 'data', 'xauusd_m5_mt5.json'),
    'M15': os.path.join(HERE, '..', 'data', 'xauusd_m15_mt5.json'),
    'M30': os.path.join(HERE, '..', 'data', 'xauusd_m30_mt5.json'),
}

SWING_LB = 50
SIG_LB   = 20
SESSION  = (7, 19)

print("Carico dati e calcolo indicatori...")
CANDLES, IND = {}, {}
for tf, path in DATA.items():
    c, _ = se2.load_from_file(path)
    CANDLES[tf] = c
    IND[tf] = se2.compute_all(c)
    print(f"  {tf}: {len(c)} barre")


def fib_levels(ind, i, swing=SWING_LB):
    if i < swing:
        return None
    H = ind['H']; L = ind['L']
    hi = max(H[i - swing + 1:i + 1]); lo = min(L[i - swing + 1:i + 1])
    rng = hi - lo
    if rng <= 0:
        return None
    return {'hi': hi, 'lo': lo, 'rng': rng,
            'l236': lo + rng * 0.236, 'l382': lo + rng * 0.382,
            'l500': lo + rng * 0.500, 'l618': lo + rng * 0.618,
            'l786': lo + rng * 0.786}


def conf_state(ind, j, P):
    if j < max(SWING_LB, SIG_LB):
        return (False, False)
    H = ind['H']; L = ind['L']; C = ind['C']; O = ind['O']
    c = C[j]; o = O[j]
    e20 = ind['e20'][j]; e50 = ind['e50'][j]
    if None in (c, o, e20, e50):
        return (False, False)
    lv = fib_levels(ind, j)
    if lv is None:
        return (False, False)
    rib_bull = e20 >= e50
    hi20 = max(H[j - SIG_LB + 1:j + 1]); lo20 = min(L[j - SIG_LB + 1:j + 1])
    rev_up = c > o
    rev_dn = c < o
    if P['fresh_extreme']:
        is_bot = L[j] <= lo20 and rev_up
        is_top = H[j] >= hi20 and rev_dn
    else:
        # entro il 25% inferiore/superiore del range 20-barre + candela di inversione
        band = (hi20 - lo20) * 0.25
        is_bot = L[j] <= lo20 + band and rev_up
        is_top = H[j] >= hi20 - band and rev_dn
    buy_conf  = is_bot and c < lv['l382'] and rib_bull
    sell_conf = is_top and c > lv['l618'] and not rib_bull
    return (buy_conf, sell_conf)


def sig_at(ind, i, P):
    dt_hour = None
    ts = CANDLES_CUR[i]['t']
    import datetime as _dt
    dt_hour = _dt.datetime.utcfromtimestamp(ts).hour
    if not (SESSION[0] <= dt_hour < SESSION[1]):
        return None
    a = ind['adx'][i]
    if P['adx_min'] and (a is None or a < P['adx_min']):
        return None
    cur = conf_state(ind, i, P)
    prev = conf_state(ind, i - 1, P)
    if cur[0] and not prev[0]:
        direction = 'buy'
    elif cur[1] and not prev[1]:
        direction = 'sell'
    else:
        return None
    lv = fib_levels(ind, i)
    if lv is None:
        return None
    entry = ind['C'][i]
    atr = ind['atr'][i] or 0.0
    if direction == 'buy':
        sl = lv['l236']
        if P['sl_mode'] == 'atr_floor':
            sl = min(sl, entry - P['sl_atr_k'] * atr)
        tp1 = lv['l618'] if P['tp1'] == 0.618 else lv['l500']
        tp2 = lv['l786']
        if not (sl < entry < tp1):
            return None
    else:
        sl = lv['l786']
        if P['sl_mode'] == 'atr_floor':
            sl = max(sl, entry + P['sl_atr_k'] * atr)
        tp1 = lv['l382'] if P['tp1'] == 0.618 else lv['l500']
        tp2 = lv['l236']
        if not (tp1 < entry < sl):
            return None
    risk = abs(entry - sl); reward = abs(tp1 - entry)
    if risk <= 0 or reward / risk < P['rr_min']:
        return None
    return (direction, entry, sl, tp1, tp2)


def sim(ind, i, setup, lookahead):
    direction, entry, sl, tp1, tp2 = setup
    n = len(CANDLES_CUR)
    filled = False; booked = 0.0; stop = sl
    for j in range(i + 1, min(i + lookahead, n)):
        jh = CANDLES_CUR[j]['h']; jl = CANDLES_CUR[j]['l']
        if direction == 'buy':
            if not filled and jh >= tp1:
                booked = 0.5 * (tp1 - entry); filled = True; stop = entry
            if filled and jh >= tp2:
                return booked + 0.5 * (tp2 - entry)
            if jl <= stop:
                return -(entry - stop) if not filled else booked + 0.5 * (stop - entry)
        else:
            if not filled and jl <= tp1:
                booked = 0.5 * (entry - tp1); filled = True; stop = entry
            if filled and jl <= tp2:
                return booked + 0.5 * (entry - tp2)
            if jh >= stop:
                return -(stop - entry) if not filled else booked + 0.5 * (entry - stop)
    return None


def backtest(tf, P):
    global CANDLES_CUR
    CANDLES_CUR = CANDLES[tf]
    ind = IND[tf]
    n = len(CANDLES_CUR)
    la = {'M5': 360, 'M15': 120, 'M30': 60}[tf]
    import datetime as _dt
    trades = []
    day_h = defaultdict(lambda: -99)
    for i in range(220, n):
        ts = CANDLES_CUR[i]['t']
        dt = _dt.datetime.utcfromtimestamp(ts)
        day = dt.strftime('%Y-%m-%d')
        if dt.hour - day_h[day] < 2:  # cooldown ~2h come il canonico
            continue
        setup = sig_at(ind, i, P)
        if setup is None:
            continue
        pnl = sim(ind, i, setup, la)
        if pnl is None:
            continue
        trades.append({'date': day, 'pnl': round(pnl, 2)})
        day_h[day] = dt.hour
    return trades


def pf_wr(trades):
    if not trades:
        return (0, 0.0, 0.0, 0.0)
    n = len(trades)
    gw = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in trades if t['pnl'] <= 0)) or 1e-9
    wr = 100.0 * sum(1 for t in trades if t['pnl'] > 0) / n
    return (n, round(wr, 1), round(gw / gl, 3), round(sum(t['pnl'] for t in trades), 1))


def split(trades):
    if not trades:
        return [], []
    dates = sorted(t['date'] for t in trades)
    cut = dates[int(len(dates) * 0.8)]
    return [t for t in trades if t['date'] < cut], [t for t in trades if t['date'] >= cut]


GRID = {
    'sl_mode':       ['fib', 'atr_floor'],
    'sl_atr_k':      [1.5, 2.5],
    'tp1':           [0.5, 0.618],
    'adx_min':       [0, 20, 25],
    'fresh_extreme': [True, False],
    'rr_min':        [1.5],
}

keys = list(GRID)
combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
# dedup: sl_atr_k irrilevante se sl_mode == 'fib'
seen = set(); uniq = []
for P in combos:
    sig_key = tuple(sorted((k, (v if not (k == 'sl_atr_k' and P['sl_mode'] == 'fib') else None))
                           for k, v in P.items()))
    if sig_key in seen:
        continue
    seen.add(sig_key); uniq.append(P)

print(f"\n{len(uniq)} combo x 3 TF\n")
hdr = f"{'TF':<4} {'slmode':<10} {'k':<4} {'tp1':<6} {'adx':<4} {'fresh':<6} | {'IS n/wr/pf/pnl':<24} | {'OOS n/wr/pf/pnl':<24}"
print(hdr); print('-' * len(hdr))
winners = []
for P in uniq:
    for tf in ['M5', 'M15', 'M30']:
        tr = backtest(tf, P)
        is_t, oos_t = split(tr)
        i_n, i_wr, i_pf, i_pnl = pf_wr(is_t)
        o_n, o_wr, o_pf, o_pnl = pf_wr(oos_t)
        k = P['sl_atr_k'] if P['sl_mode'] == 'atr_floor' else '-'
        line = (f"{tf:<4} {P['sl_mode']:<10} {str(k):<4} {str(P['tp1']):<6} "
                f"{str(P['adx_min']):<4} {str(P['fresh_extreme']):<6} | "
                f"{i_n:>4}/{i_wr:>4}/{i_pf:>6}/{i_pnl:>7} | "
                f"{o_n:>4}/{o_wr:>4}/{o_pf:>6}/{o_pnl:>7}")
        print(line)
        if i_pf >= 1.1 and o_pf >= 1.2 and o_n >= 8 and i_n >= 25:
            winners.append((tf, dict(P), (i_n, i_wr, i_pf, i_pnl), (o_n, o_wr, o_pf, o_pnl)))

print("\n=== CANDIDATI (IS PF>=1.1, OOS PF>=1.2, N sufficiente) ===")
if not winners:
    print("  nessuno")
for tf, P, isr, oosr in winners:
    print(f"  {tf} {P} | IS {isr} | OOS {oosr}")
