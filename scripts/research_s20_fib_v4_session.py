#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — S20_FIB_CONFLUENCE v4: filtro sessione + circuit breaker giornaliero (2026-08-28)

Diagnosi orari (v2 combined, M5, 20 mesi):
  h16 UTC = outlier fortissimo: n=13, WR 85%, +$137 — e STABILE per terzi (T1 +10 / T2 +15 / T3 +112),
  cioe' l'effetto e' piu' forte nel periodo recente (NY afternoon liquidity/momentum su gold).
  h8 (London open) e h15 anche positivi stabili. h7/h9/h17/h18 negativi. Lunedi' negativo.

v4 prova:
  1. Whitelist di ore d'ingresso (solo le finestre buone).
  2. Filtro weekday (salta lunedi').
  3. Circuit breaker giornaliero: dopo +daily_stop_r R realizzati nel giorno -> stop nuovi ingressi
     ("non continuare ad aprire trade dopo aver fatto profitto"). Anche loss-stop a -daily_loss_r R.

Base: v2 combined (buy+sell) e v3 BUY. Walk-forward: tutti e 3 i terzi di calendario PF > 1.1.

Uso: python -X utf8 scripts/research_s20_fib_v4_session.py
"""
import sys, os, itertools, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import research_s20_fib_v2 as v2
import research_s20_fib_v3_buy as v3


def backtest(mode, tf, P):
    v2.CANDLES_CUR = v2.CANDLES[tf]
    ind = v2.IND[tf]
    n = len(v2.CANDLES_CUR)
    la = {'M5': 288, 'M15': 96, 'M30': 48}[tf]
    trades = []
    day_h = defaultdict(lambda: -99)
    day_r = defaultdict(float)          # R realizzati per giorno di calendario
    hours = P.get('hours')
    for i in range(260, n):
        dt = datetime.datetime.utcfromtimestamp(v2.CANDLES_CUR[i]['t'])
        day = dt.strftime('%Y-%m-%d')
        if dt.hour - day_h[day] < 2:
            continue
        if hours is not None and dt.hour not in hours:
            continue
        if P.get('no_mon') and dt.weekday() == 0:
            continue
        # circuit breaker giornaliero
        ds = P.get('daily_stop_r')
        dl = P.get('daily_loss_r')
        if ds is not None and day_r[day] >= ds:
            continue
        if dl is not None and day_r[day] <= -dl:
            continue

        if mode == 'v2':
            s = v2.sig_at(ind, i, P)
            if s is None:
                continue
            direction, entry, sl, tp1, tp2 = s
            risk = abs(entry - sl)
            pnl = v2.sim(ind, i, s, la)
        else:
            s = v3.buy_setup(ind, i, P)
            if s is None:
                continue
            entry, sl, tp1, tp2 = s
            direction = 'buy'
            risk = entry - sl
            pnl = v3.sim_buy(ind, i, s, la)
        if pnl is None or risk <= 0:
            continue
        day_r[day] += pnl / risk
        day_h[day] = dt.hour
        trades.append({'date': day, 'pnl': round(pnl, 2), 'dir': direction})
    return trades


def stats(tr):
    if not tr:
        return None
    n = len(tr); wins = [t for t in tr if t['pnl'] > 0]
    gw = sum(t['pnl'] for t in wins); gl = abs(sum(t['pnl'] for t in tr if t['pnl'] <= 0)) or 1e-9
    cum = peak = dd = 0.0; maxcl = cl = 0
    for t in sorted(tr, key=lambda x: x['date']):
        cum += t['pnl']; peak = max(peak, cum); dd = max(dd, peak - cum)
        if t['pnl'] <= 0:
            cl += 1; maxcl = max(maxcl, cl)
        else:
            cl = 0
    mo = defaultdict(float)
    for t in tr:
        mo[t['date'][:7]] += t['pnl']
    return dict(n=n, wr=round(100 * len(wins) / n, 1), pf=round(gw / gl, 3),
                pnl=round(sum(t['pnl'] for t in tr), 1), dd=round(dd, 1), maxcl=maxcl,
                months=f"{sum(1 for x in mo.values() if x > 0)}/{len(mo)}")


def cal_thirds(tr):
    tr = sorted(tr, key=lambda x: x['date'])
    a = datetime.date.fromisoformat(tr[0]['date'])
    b = datetime.date.fromisoformat(tr[-1]['date'])
    span = (b - a).days
    c1 = (a + datetime.timedelta(days=span // 3)).isoformat()
    c2 = (a + datetime.timedelta(days=2 * span // 3)).isoformat()
    return ([t for t in tr if t['date'] < c1],
            [t for t in tr if c1 <= t['date'] < c2],
            [t for t in tr if t['date'] >= c2])


P2 = dict(band=0.25, htf='ema200', sl_atr_k=1.5, tp1='r1', tp2_r=2.0, rr_min=1.0)
P3 = dict(band=0.20, trend_str='stack', mom='macd', near_ma='none', sl_atr_k=1.5,
          tp1_r=1.5, tp2_r=2.0, rr_min=1.0, htf='ema200')

HOUR_SETS = {
    'all':        None,
    '15-16':      {15, 16},
    '8+15-16':    {8, 15, 16},
    '8+14-16':    {8, 14, 15, 16},
    '10+14-16':   {10, 14, 15, 16},
    '8+10+14-17': {8, 10, 14, 15, 16, 17},
}


def main():
    v2.load_data()
    print("mode          hours        no_mon dstop | ALL n/wr/pf/pnl/dd/mCL/mesi+          | T1pf  T2pf  T3pf")
    print("-" * 118)
    keepers = []
    for mode, base in [('v2', P2), ('buy', P3)]:
        for hkey, hset in HOUR_SETS.items():
            for no_mon in [False, True]:
                for dstop in [None, 2.0, 3.0]:
                    P = dict(base); P['hours'] = hset; P['no_mon'] = no_mon
                    P['daily_stop_r'] = dstop; P['daily_loss_r'] = 2.0
                    tr = backtest(mode, 'M5', P)
                    st = stats(tr)
                    if not st or st['n'] < 25:
                        continue
                    t1, t2, t3 = cal_thirds(tr)
                    s1, s2, s3 = stats(t1), stats(t2), stats(t3)
                    p1 = s1['pf'] if s1 else 0; p2 = s2['pf'] if s2 else 0; p3 = s3['pf'] if s3 else 0
                    print(f"{mode:<6}{hkey:>12}   {str(no_mon):<6} {str(dstop):<5} | "
                          f"{st['n']:>3}/{st['wr']:>5}/{st['pf']:>6}/{st['pnl']:>7}/{st['dd']:>6}/{st['maxcl']:>2}/{st['months']:>6}  | "
                          f"{p1:<5} {p2:<5} {p3:<5}")
                    if min(p1, p2, p3) >= 1.10 and st['n'] >= 30 and st['dd'] / max(st['pnl'], 1e-9) < 0.9:
                        keepers.append((mode, dict(hkey=hkey, no_mon=no_mon, dstop=dstop), st, (p1, p2, p3)))

    print("\n=== PASSA tutti e 3 i terzi (PF>=1.10, n>=30, DD/PnL<0.9) ===")
    if not keepers:
        print("  nessuno")
    for mode, tag, st, ps in keepers:
        print(f"  [{mode}] {tag} | {st} | terzi {ps}")


if __name__ == '__main__':
    main()
