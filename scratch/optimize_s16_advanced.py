import json
import os
import datetime
import math

def ema(src, p):
    if not src: return []
    k = 2 / (p + 1)
    o = [src[0]]
    for i in range(1, len(src)):
        o.append(src[i] * k + o[-1] * (1 - k))
    return o

def atr(H, L, C, p=14):
    tr = [0]
    for i in range(1, len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    out = [None] * (p-1)
    for i in range(p-1, len(tr)):
        out.append(sum(tr[i-p+1:i+1])/p)
    return out

def obv(C, V):
    out = [0.0]
    for i in range(1, len(C)):
        s = 1 if C[i] > C[i-1] else (-1 if C[i] < C[i-1] else 0)
        out.append(out[-1] + s * V[i])
    return out

def supertrend(H, L, C, p=10, m=3.0):
    atr_v = atr(H, L, C, p)
    n = len(C)
    dir_ = [1] * n
    st = [0.0] * n
    ub = [(H[i]+L[i])/2 + m*(atr_v[i] or 0) for i in range(n)]
    lb = [(H[i]+L[i])/2 - m*(atr_v[i] or 0) for i in range(n)]
    f_ub = [0.0] * n
    f_lb = [0.0] * n
    for i in range(1, n):
        f_ub[i] = ub[i] if ub[i] < f_ub[i-1] or C[i-1] > f_ub[i-1] else f_ub[i-1]
        f_lb[i] = lb[i] if lb[i] > f_lb[i-1] or C[i-1] < f_lb[i-1] else f_lb[i-1]
        if st[i-1] == f_ub[i-1] and C[i] <= f_ub[i]: st[i] = f_ub[i]; dir_[i] = 1
        elif st[i-1] == f_ub[i-1] and C[i] > f_ub[i]: st[i] = f_lb[i]; dir_[i] = -1
        elif st[i-1] == f_lb[i-1] and C[i] >= f_lb[i]: st[i] = f_lb[i]; dir_[i] = -1
        elif st[i-1] == f_lb[i-1] and C[i] < f_lb[i]: st[i] = f_ub[i]; dir_[i] = 1
        else: st[i] = f_ub[i]; dir_[i] = 1
    return dir_

def run_advanced_test(m15_file, h1_file):
    print(f"Loading data: {m15_file} and {h1_file}...")
    with open(m15_file, 'r') as f: m15_raw = json.load(f).get('candles', [])
    with open(h1_file, 'r') as f: h1_raw = json.load(f).get('candles', [])
    
    C = [c['c'] for c in m15_raw]; H = [c['h'] for c in m15_raw]
    L = [c['l'] for c in m15_raw]; V = [c['v'] for c in m15_raw]
    n = len(C)

    print("Computing indicators...")
    a_v = atr(H, L, C, 14)
    obv_v = obv(C, V); obv_e20 = ema(obv_v, 20)
    e233 = ema(C, 233)
    
    # H1 Trend mapping
    h1_C = [c['c'] for c in h1_raw]; h1_H = [c['h'] for c in h1_raw]; h1_L = [c['l'] for c in h1_raw]
    h1_st = supertrend(h1_H, h1_L, h1_C, 10, 3.0)
    h1_trend_map = {}
    for i, c in enumerate(h1_raw):
        h1_trend_map[c['t'] // 3600 * 3600] = h1_st[i]

    tps = [2.0, 2.5, 3.0]
    sls = [1.0, 1.2, 1.5]
    be_filters = [True, False]
    session_filters = [True, False]

    results = []
    print("\nStarting Advanced Sweep (Session + BE + EMA 233)...")
    print(f"{'TP':>4} | {'SL':>4} | {'BE':>5} | {'Sess':>5} | {'N':>5} | {'WR':>6} | {'PF':>5} | {'PnL':>8}")
    print("-" * 65)

    for tp_m in tps:
        for sl_m in sls:
            for use_be in be_filters:
                for use_sess in session_filters:
                    trades = []
                    wins = 0; losses = 0; gross_win = 0; gross_loss = 0
                    
                    for i in range(250, n - 100):
                        if a_v[i] is None or e233[i] is None: continue
                        
                        ts = m15_raw[i]['t']
                        dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                        hour = dt.hour
                        
                        # Session Filter (7-17 UTC)
                        if use_sess and not (7 <= hour <= 17): continue
                        
                        # H1 Trend Alignment
                        h_ts = ts // 3600 * 3600
                        trend = h1_trend_map.get(h_ts, 0)
                        if trend == 0: continue
                        
                        # Golden Squeeze Logic
                        is_bull = trend == -1 and obv_v[i] > obv_e20[i] and C[i] > C[i-1] and C[i] > e233[i]
                        is_bear = trend == 1 and obv_v[i] < obv_e20[i] and C[i] < C[i-1] and C[i] < e233[i]
                        
                        sig = 'buy' if is_bull else ('sell' if is_bear else None)
                        if not sig: continue
                        
                        # Trade Management
                        entry = C[i]; atr_val = a_v[i]
                        tp_p = entry + tp_m * atr_val if sig == 'buy' else entry - tp_m * atr_val
                        sl_p = entry - sl_m * atr_val if sig == 'buy' else entry + sl_m * atr_val
                        be_p = entry + 1.0 * atr_val if sig == 'buy' else entry - 1.0 * atr_val
                        
                        has_be = False
                        outcome = None
                        for j in range(i+1, min(i+100, n)):
                            jh = m15_raw[j]['h']; jl = m15_raw[j]['l']
                            
                            # Check Breakeven trigger
                            if use_be and not has_be:
                                if (sig == 'buy' and jh >= be_p) or (sig == 'sell' and jl <= be_p):
                                    has_be = True
                                    sl_p = entry # Move to Breakeven
                            
                            if sig == 'buy':
                                if jh >= tp_p: outcome = 'win'; break
                                if jl <= sl_p: outcome = 'loss'; break
                            else:
                                if jl <= tp_p: outcome = 'win'; break
                                if jh >= sl_p: outcome = 'loss'; break
                        
                        if outcome == 'win':
                            wins += 1; gross_win += tp_m * atr_val; trades.append(1)
                        elif outcome == 'loss':
                            losses += 1; gross_loss += (sl_m * atr_val if not has_be else 0); trades.append(0)
                            
                    if not trades: continue
                    wr = wins / len(trades); pnl = gross_win - gross_loss
                    pf = gross_win / gross_loss if gross_loss > 0 else 9.99
                    
                    results.append({'tp':tp_m, 'sl':sl_m, 'be':use_be, 'sess':use_sess, 'n':len(trades), 'wr':wr, 'pf':pf, 'pnl':pnl})
                    
                    if pf > 1.35:
                        print(f"{tp_m:4.1f} | {sl_m:4.1f} | {str(use_be):>5} | {str(use_sess):>5} | {len(trades):5d} | {wr:5.1%}| {pf:5.2f} | {pnl:8.0f}")

    results.sort(key=lambda x: x['pf'], reverse=True)
    print("\nTOP 5 CONFIGS:")
    for r in results[:5]: print(r)

if __name__ == "__main__":
    print("\n--- TEST M15 ---")
    run_advanced_test('xauusd_m15_mt5.json', 'xauusd_h1_mt5.json')
    print("\n\n--- TEST M30 ---")
    run_advanced_test('xauusd_m30_mt5.json', 'xauusd_h1_mt5.json')
