#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — S20_FIB_CONFLUENCE v3, focus lato BUY (2026-08-28)

v2 ha mostrato: edge tutto sul lato SELL (regime bet oro 2025-26, walk-forward T1 PF 0.51),
lato BUY breakeven (PF 0.98). Ultimo tentativo su richiesta utente: si salva il BUY?

Base v2 (ingresso confermato + higher-low + SL strutturale con floor ATR + TP parziali 1R/2R).
Nuove leve BUY-specifiche:
  - trend_str : forza del trend HTF richiesta (ema200 sola / stack e20>e50>e200 / ADX>=20)
  - mom       : momentum intatto (nessuno / RSI in salita >40 / MACD hist in salita)
  - near_ma   : entry deve tappare una MA dinamica in salita (nessuna / EMA50 / EMA100)
  - tp1_r     : TP1 in multipli di R (0.75 / 1.0 / 1.5)
  - tp2_r     : runner (2.0 / 2.5)

Barra di accettazione (piu' severa di v2, dopo la lezione SELL):
  tutti e 3 i terzi cronologici PF > 1.10  AND  N totale >= 40  AND  DD/PnL < 1.0

Uso: python -X utf8 scripts/research_s20_fib_v3_buy.py
"""
import sys, os, itertools, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import research_s20_fib_v2 as v2

SIG_LB = v2.SIG_LB
SWING_LB = v2.SWING_LB
SESSION = v2.SESSION


def buy_setup(ind, i, P):
    """Ritorna (entry, sl, tp1, tp2) per un BUY valido al bar i, o None."""
    ts = v2.CANDLES_CUR[i]['t']
    hour = datetime.datetime.utcfromtimestamp(ts).hour
    if not (SESSION[0] <= hour < SESSION[1]):
        return None

    rc = v2.raw_conf(ind, i - 1, P)
    if rc is None or not rc[0]:
        return None
    C = ind['C']
    if not C[i] > C[i - 1]:
        return None
    if not v2.struct_ok(ind, i, 'buy'):
        return None

    c = C[i]
    e20, e50, e100, e200 = ind['e20'][i], ind['e50'][i], ind['e100'][i], ind['e200'][i]
    if None in (e50, e100, e200):
        return None

    # trend HTF
    if P['trend_str'] == 'ema200':
        if not c > e200:
            return None
    elif P['trend_str'] == 'stack':
        if not (e20 is not None and e20 > e50 > e200):
            return None
    elif P['trend_str'] == 'adx':
        a = ind['adx'][i]; dp = ind['dip'][i]; dm = ind['dim'][i]
        if None in (a, dp, dm) or a < 20 or dp <= dm or not c > e200:
            return None

    # momentum intatto
    if P['mom'] == 'rsi':
        r = ind['rsi'][i]; rp = ind['rsi'][i - 1]
        if None in (r, rp) or not (r > 40 and r > rp):
            return None
    elif P['mom'] == 'macd':
        mh = ind['macd_hist'][i]; mhp = ind['macd_hist'][i - 1]
        if None in (mh, mhp) or not mh > mhp:
            return None

    # tap di una MA dinamica in salita
    atr = ind['atr'][i] or 0.0
    if atr <= 0:
        return None
    if P['near_ma'] in ('e50', 'e100'):
        ma = e50 if P['near_ma'] == 'e50' else e100
        ma_prev = ind['e50'][i - 3] if P['near_ma'] == 'e50' else ind['e100'][i - 3]
        if ma_prev is None or ma <= ma_prev:      # MA deve salire
            return None
        if ind['L'][i] > ma + 0.5 * atr or c < ma - 1.0 * atr:  # low tappa la MA, close non troppo sotto
            return None

    entry = c
    buf = 0.15 * atr
    sl = min(ind['L'][i] - buf, entry - P['sl_atr_k'] * atr)
    risk = entry - sl
    if risk <= 0:
        return None
    tp1 = entry + risk * P['tp1_r']
    tp2 = entry + risk * P['tp2_r']
    return (entry, sl, tp1, tp2)


def sim_buy(ind, i, setup, la):
    entry, sl, tp1, tp2 = setup
    n = len(v2.CANDLES_CUR)
    filled = False; booked = 0.0; stop = sl
    for j in range(i + 1, min(i + la, n)):
        jh = v2.CANDLES_CUR[j]['h']; jl = v2.CANDLES_CUR[j]['l']
        if not filled and jh >= tp1:
            booked = 0.5 * (tp1 - entry); filled = True; stop = entry
        if filled and jh >= tp2:
            return booked + 0.5 * (tp2 - entry)
        if jl <= stop:
            return -(entry - stop) if not filled else booked + 0.5 * (stop - entry)
    return booked if filled else None


def backtest(tf, P):
    v2.CANDLES_CUR = v2.CANDLES[tf]
    ind = v2.IND[tf]
    n = len(v2.CANDLES_CUR)
    la = {'M5': 288, 'M15': 96, 'M30': 48}[tf]
    trades = []; day_h = defaultdict(lambda: -99)
    for i in range(260, n):
        dt = datetime.datetime.utcfromtimestamp(v2.CANDLES_CUR[i]['t'])
        day = dt.strftime('%Y-%m-%d')
        if dt.hour - day_h[day] < 2:
            continue
        s = buy_setup(ind, i, P)
        if s is None:
            continue
        pnl = sim_buy(ind, i, s, la)
        if pnl is None:
            continue
        trades.append({'date': day, 'pnl': round(pnl, 2)})
        day_h[day] = dt.hour
    return trades


def stats(tr):
    if not tr:
        return None
    n = len(tr); wins = [t for t in tr if t['pnl'] > 0]
    gw = sum(t['pnl'] for t in wins); gl = abs(sum(t['pnl'] for t in tr if t['pnl'] <= 0)) or 1e-9
    cum = peak = dd = 0.0
    for t in sorted(tr, key=lambda x: x['date']):
        cum += t['pnl']; peak = max(peak, cum); dd = max(dd, peak - cum)
    mo = defaultdict(float)
    for t in tr:
        mo[t['date'][:7]] += t['pnl']
    return dict(n=n, wr=round(100 * len(wins) / n, 1), pf=round(gw / gl, 3),
                pnl=round(sum(t['pnl'] for t in tr), 1), dd=round(dd, 1),
                months=f"{sum(1 for x in mo.values() if x > 0)}/{len(mo)}")


def thirds(tr):
    tr = sorted(tr, key=lambda x: x['date'])
    k = len(tr) // 3
    return tr[:k], tr[k:2 * k], tr[2 * k:]


GRID = {
    'band':      [0.20, 0.25],
    'trend_str': ['ema200', 'stack', 'adx'],
    'mom':       ['none', 'rsi', 'macd'],
    'near_ma':   ['none', 'e50', 'e100'],
    'sl_atr_k':  [1.5],
    'tp1_r':     [0.75, 1.0, 1.5],
    'tp2_r':     [2.0],
    'rr_min':    [1.0],
    'htf':       ['ema200'],   # usato solo da v2.raw_conf indirettamente; qui non applicato
}
def main():
    v2.load_data()
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    print(f"{len(combos)} combo BUY-only · M5\n")
    print(f"{'band':<5}{'trend':<8}{'mom':<6}{'nearMA':<7}{'tp1R':<6} | {'ALL n/wr/pf/pnl/dd':<32} | {'T1 pf':<7}{'T2 pf':<7}{'T3 pf':<7}")
    keepers = []
    for P in combos:
        tr = backtest('M5', P)
        st = stats(tr)
        if not st or st['n'] < 40:
            continue
        t1, t2, t3 = thirds(tr)
        s1, s2, s3 = stats(t1), stats(t2), stats(t3)
        p1 = s1['pf'] if s1 else 0; p2 = s2['pf'] if s2 else 0; p3 = s3['pf'] if s3 else 0
        print(f"{P['band']:<5}{P['trend_str']:<8}{P['mom']:<6}{P['near_ma']:<7}{P['tp1_r']:<6} | "
              f"{st['n']:>4}/{st['wr']:>5}/{st['pf']:>6}/{st['pnl']:>7}/{st['dd']:>6} | "
              f"{p1:<7}{p2:<7}{p3:<7}")
        if min(p1, p2, p3) >= 1.10 and st['pnl'] > 0 and (st['dd'] / max(st['pnl'], 1e-9)) < 1.0:
            keepers.append((dict(P), st, (p1, p2, p3)))

    print("\n=== BUY che passa tutti e 3 i terzi (PF>=1.10) ===")
    if not keepers:
        print("  nessuno")
    for P, st, ps in keepers:
        print(f"  {P} | {st} | terzi {ps}")


if __name__ == '__main__':
    main()
