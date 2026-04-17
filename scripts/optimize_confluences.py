import json
import os
import datetime
import pandas as pd
import numpy as np
from collections import defaultdict

# --- UTILS ---
def ema(s, n):
    if len(s) < n: return [None]*len(s)
    res = [None]*len(s)
    alpha = 2 / (n + 1)
    res[n-1] = sum(s[:n])/n
    for i in range(n, len(s)):
        res[i] = s[i]*alpha + res[i-1]*(1-alpha)
    return res

def compute_indicators(candles):
    C = np.array([c['c'] for c in candles])
    H = np.array([c['h'] for c in candles])
    L = np.array([c['l'] for c in candles])
    V = np.array([c['v'] for c in candles])
    n = len(C)
    def get_bb(c, n=20, std=2.0):
        s = pd.Series(c); m = s.rolling(n).mean().values; d = s.rolling(n).std().values
        return m + std*d, m - std*d
    up, lo = get_bb(C)
    obv = [0]*n
    for i in range(1, n):
        if C[i] > C[i-1]: obv[i] = obv[i-1] + V[i]
        elif C[i] < C[i-1]: obv[i] = obv[i-1] - V[i]
        else: obv[i] = obv[i-1]
    o_e = ema(obv, 20)
    st = [0]*n
    mid = (H + L) / 2
    for i in range(1, n):
        if C[i] > mid[i-1]: st[i] = -1
        elif C[i] < mid[i-1]: st[i] = 1
        else: st[i] = st[i-1]
    atr = [0]*n
    for i in range(1, n):
        atr[i] = max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1]))
    atr_e = ema(atr, 14)
    return {'C':C,'H':H,'L':L,'up':up,'lo':lo,'obv':obv,'obv_e':o_e,'st':st,'atr':atr_e}

def run_elite_backtest(m15_file, h1_file):
    with open(m15_file, 'r') as f: m15_raw = json.load(f).get('candles', [])
    with open(h1_file, 'r') as f: h1_raw = json.load(f).get('candles', [])
    
    ind_m15 = compute_indicators(m15_raw)
    ind_h1 = compute_indicators(h1_raw)
    
    # Map H1 ST trend to M15 timestamps
    h1_trend = {}
    for i, c in enumerate(h1_raw):
        h1_trend[c['t'] // 3600 * 3600] = ind_h1['st'][i]

    trades = []; day_n = defaultdict(int); last_sig = None
    n = len(m15_raw)
    
    for i in range(50, n-30):
        c = m15_raw[i]; ts = c['t']
        dt = datetime.datetime.fromtimestamp(ts)
        hour = dt.hour; day = dt.strftime('%Y-%m-%d')
        
        if not (8 <= hour <= 17): continue # SESSION FILTER
        
        # H1 Alignment
        h_ts = ts // 3600 * 3600
        trend = h1_trend.get(h_ts, 0)
        
        # Golden Squeeze Logic
        obv = ind_m15['obv'][i]; oe = ind_m15['obv_e'][i]
        price = c['c']; up = ind_m15['up'][i]; lo = ind_m15['lo'][i]
        
        sig = None
        if trend == -1 and obv > oe and price > ind_m15['C'][i-1]: sig = 'buy'
        elif trend == 1 and obv < oe and price < ind_m15['C'][i-1]: sig = 'sell'
        
        if not sig or sig == last_sig: continue # NO DOUBLE ENTRIES
        if day_n[day] >= 4: continue # LIMIT TO 4 TRADES/DAY
        
        last_sig = sig
        atr = ind_m15['atr'][i] if ind_m15['atr'][i] else 5.0
        tp_d = atr * 2.0; sl_d = atr * 1.5 # PREMIUM RR
        tp_p = price + tp_d if sig=='buy' else price-tp_d
        sl_p = price - sl_d if sig=='buy' else price+sl_d
        
        win = False; outcome = 'open'
        for j in range(i+1, min(i+40, n)):
            jh, jl = m15_raw[j]['h'], m15_raw[j]['l']
            if sig=='buy':
                if jh >= tp_p: win=True; outcome='win'; break
                if jl <= sl_p: outcome='loss'; break
            else:
                if jl <= tp_p: win=True; outcome='win'; break
                if jh >= sl_p: outcome='loss'; break
        
        if outcome != 'open':
            trades.append({'day':day, 'pnl': tp_d if win else -sl_d, 'win':win})
            day_n[day] += 1

    if not trades: return None
    days = len(set(t['day'] for t in trades))
    wr = sum(1 for t in trades if t['win'])/len(trades)*100
    pnl = sum(t['pnl'] for t in trades)
    return {'n':len(trades), 'wr':round(wr,1), 'pnl':round(pnl,1), 'tpd':round(len(trades)/days, 2)}

def main():
    print("Testing ELITE COMBO: Golden Squeeze (H1 Trend + M15 Momentum)")
    res = run_elite_backtest('data/xauusd_m15_mt5.json', 'data/xauusd_h1_mt5.json')
    if res:
        print("\n" + "="*40)
        print(f"RESULTS FOR GOLDEN SQUEEZE (CONFLUENCE)")
        print("="*40)
        print(f"Total Trades:    {res['n']}")
        print(f"Win Rate:        {res['wr']}%")
        print(f"Total P&L:       ${res['pnl']}")
        print(f"Trades/Day:      {res['tpd']}  <-- TARGET 3-4")
        print("="*40)
    else: print("No trades found.")

if __name__ == "__main__": main()
