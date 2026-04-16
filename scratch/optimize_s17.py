import json
import os
import math

# --- INDICATOR HELPERS ---
def ema(src, p):
    if not src: return []
    k = 2 / (p + 1)
    o = [src[0]]
    for i in range(1, len(src)):
        o.append(src[i] * k + o[-1] * (1 - k))
    return o

def bb(src, p=20, mult=2.0):
    n = len(src)
    mid = [None] * (p-1)
    for i in range(p-1, n):
        mid.append(sum(src[i-p+1:i+1])/p)
    up = [None] * n; dn = [None] * n
    for i in range(p-1, n):
        sd = math.sqrt(sum((src[i-j]-mid[i])**2 for j in range(p))/p)
        up[i] = mid[i] + mult * sd
        dn[i] = mid[i] - mult * sd
    return mid, up, dn

def atr(H, L, C, p=14):
    tr = [0]
    for i in range(1, len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    out = [None] * (p-1)
    for i in range(p-1, len(tr)):
        out.append(sum(tr[i-p+1:i+1])/p)
    return out

def stoch_rsi(C, p=14, k_p=3, d_p=3):
    # RSI
    g, l = [0], [0]
    for i in range(1, len(C)):
        d = C[i] - C[i-1]
        g.append(d if d > 0 else 0); l.append(-d if d < 0 else 0)
    rsi = [None] * len(C); ag, al = 0, 0
    for i in range(len(C)):
        if i < p: ag += g[i]/p; al += l[i]/p; continue
        ag = (ag * (p-1) + g[i]) / p; al = (al * (p-1) + l[i]) / p
        rsi[i] = 100 - 100 / (1 + ag/al) if al > 0 else 100
    # Stoch
    stoch = [None] * len(C)
    for i in range(len(rsi)):
        if rsi[i] is None or i < p * 2: continue
        low = min(rsi[i-p+1 : i+1]); high = max(rsi[i-p+1 : i+1])
        stoch[i] = (rsi[i] - low) / (high - low) * 100 if high > low else 50
    # K & D
    k = [None] * len(stoch)
    for i in range(len(stoch)):
        if stoch[i] is None or i < k_p: continue
        k[i] = sum(x for x in stoch[i-k_p+1:i+1] if x is not None) / k_p
    d = [None] * len(k)
    for i in range(len(k)):
        if k[i] is None or i < d_p: continue
        d[i] = sum(x for x in k[i-d_p+1:i+1] if x is not None) / d_p
    return k, d

def run_optimization(file_path):
    if not os.path.exists(file_path): return
    with open(file_path, 'r') as f: data = json.load(f)
    candles = data if isinstance(data, list) else data.get('candles', [])
    C = [c['c'] for c in candles]; H = [c['h'] for c in candles]; L = [c['l'] for c in candles]
    n = len(C)

    print(f"\n>>> OTTIMIZZAZIONE CONVERGENCE SCALP (S17) - {file_path}")
    
    # Precompute indicators
    a_v = atr(H, L, C, 14)
    # Testing different EMA pairs
    ema_pairs = [(13,34), (21,55), (8,21), (34,89)]
    trend_filter_lens = [50, 233, 0] # 0 = no filter
    
    # StochRSI
    sk_v, sd_v = stoch_rsi(C, 14, 3, 3)
    # BB (20,2)
    _, bb_up, bb_lo = bb(C, 20, 2.0)

    # TP/SL multiples
    tps = [1.5, 2.0, 2.5, 3.0]
    sls = [0.8, 1.0, 1.2, 1.5]

    results = []
    
    for pair in ema_pairs:
        e_fast = ema(C, pair[0])
        e_slow = ema(C, pair[1])
        for tf_len in trend_filter_lens:
            e_trend = ema(C, tf_len) if tf_len > 0 else None
            for tp_m in tps:
                for sl_m in sls:
                    trades = []; pnl = 0; wins = 0; losses = 0
                    
                    for i in range(250, n - 100):
                        if None in (e_fast[i], e_slow[i], sk_v[i], sd_v[i], bb_up[i], bb_lo[i], a_v[i]): continue
                        
                        # Logic
                        bb_range = bb_up[i] - bb_lo[i]
                        bb_pct = (C[i] - bb_lo[i]) / bb_range if bb_range > 0 else 0.5
                        
                        bull_prev = e_fast[i-1] > e_slow[i-1] and sk_v[i-1] > sd_v[i-1]
                        bear_prev = e_fast[i-1] < e_slow[i-1] and sk_v[i-1] < sd_v[i-1]
                        
                        bull = e_fast[i] > e_slow[i] and sk_v[i] > sd_v[i] and bb_pct > 0.5 and not bull_prev
                        bear = e_fast[i] < e_slow[i] and sk_v[i] < sd_v[i] and bb_pct < 0.5 and not bear_prev
                        
                        if e_trend:
                            if bull and C[i] < e_trend[i]: bull = False
                            if bear and C[i] > e_trend[i]: bear = False
                        
                        sig = 'buy' if bull else ('sell' if bear else None)
                        if not sig: continue
                        
                        tp_p = C[i] + tp_m * a_v[i] if sig == 'buy' else C[i] - tp_m * a_v[i]
                        sl_p = C[i] - sl_m * a_v[i] if sig == 'buy' else C[i] + sl_m * a_v[i]
                        
                        win = lost = False
                        for j in range(i+1, min(i+150, n)):
                            if sig == 'buy':
                                if H[j] >= tp_p: win = True; break
                                if L[j] <= sl_p: lost = True; break
                            else:
                                if L[j] <= tp_p: win = True; break
                                if H[j] >= sl_p: lost = True; break
                        
                        if win:
                            pnl += tp_m * a_v[i]; wins += 1; trades.append(tp_m * a_v[i])
                        elif lost:
                            pnl -= sl_m * a_v[i]; losses += 1; trades.append(-sl_m * a_v[i])
                    
                    if not trades: continue
                    wr = wins / len(trades)
                    gross_win = sum(t for t in trades if t > 0)
                    gross_loss = abs(sum(t for t in trades if t < 0))
                    pf = gross_win / gross_loss if gross_loss > 0 else 9.99
                    
                    results.append({
                        'pair': pair, 'tf': tf_len, 'tp': tp_m, 'sl': sl_m,
                        'n': len(trades), 'wr': wr, 'pf': pf, 'pnl': pnl
                    })

    results.sort(key=lambda x: (x['pf'], x['n']), reverse=True)
    print(f"{'PAIR':>8} | {'TREND':>5} | {'TP':>4} | {'SL':>4} | {'N':>4} | {'WR':>6} | {'PF':>5} | {'PnL':>8}")
    print("-" * 65)
    
    count = 0
    for r in results:
        if r['pf'] >= 1.2 and r['n'] >= 20:
            print(f"{str(r['pair']):>8} | {r['tf']:>5} | {r['tp']:4.1f} | {r['sl']:4.1f} | {r['n']:4d} | {r['wr']:5.1%} | {r['pf']:5.2f} | {r['pnl']:8.1f}")
            count += 1
            if count >= 10: break

if __name__ == "__main__":
    run_optimization('xauusd_m15_mt5.json')
    run_optimization('xauusd_m5_mt5.json')
    run_optimization('xauusd_m30_mt5.json')
