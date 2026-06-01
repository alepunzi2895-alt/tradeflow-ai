import json
import os
import math

def ema(src, p):
    if not src: return []
    k = 2 / (p + 1)
    out = [src[0]]
    for i in range(1, len(src)):
        out.append(src[i] * k + out[-1] * (1 - k))
    return out

def stdev_arr(src, p):
    out = [None]*(p-1)
    for i in range(p-1, len(src)):
        sl = src[i-p+1:i+1]
        mn = sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def atr(h, l, c, p=14):
    tr = [0.0]
    for i in range(1, len(c)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    out = [sum(tr[:p])/p]
    k = 2/(p+1)
    for i in range(p, len(tr)):
        out.append(tr[i]*k + out[-1]*(1-k))
    return [None]*(p-1) + out

def calc_fvg(O, H, L, C, std_len=100, df=2):
    n = len(C)
    body = [abs(O[i]-C[i]) for i in range(n)]
    bs = stdev_arr(body, std_len)
    fb = [False]*n; fs = [False]*n
    ab = []; as_ = []
    for i in range(2, n):
        disp = bs[i-1] is not None and bs[i-1] > 0 and body[i-1] > bs[i-1]*df
        if L[i] > H[i-2]: ab.append({'lo': H[i-2], 'hi': L[i], 'bar': i, 'd': disp})
        if H[i] < L[i-2]: as_.append({'lo': H[i], 'hi': L[i-2], 'bar': i, 'd': disp})
        sb = []
        for fvg in ab:
            if fvg['bar'] == i: sb.append(fvg); continue
            if L[i] < fvg['lo']: continue
            if C[i] <= fvg['hi'] and C[i] >= fvg['lo']: fb[i] = True
            sb.append(fvg)
        ab = sb[-20:]
        sb2 = []
        for fvg in as_:
            if fvg['bar'] == i: sb2.append(fvg); continue
            if H[i] > fvg['hi']: continue
            if C[i] >= fvg['lo'] and C[i] <= fvg['hi']: fs[i] = True
            sb2.append(fvg)
        as_ = sb2[-20:]
    return fb, fs

def calc_order_blocks(O, H, L, C, lookback=30):
    n = len(C)
    ob_bull = [False]*n; ob_bear = [False]*n
    for i in range(lookback + 4, n):
        # Bullish OB
        for j in range(i - 2, max(i - lookback - 1, 2), -1):
            if C[j] >= O[j]: continue
            ob_lo = min(O[j], C[j]); ob_hi = max(O[j], C[j])
            if not (j+1 < n and C[j+1] > O[j+1]): continue
            if any(L[k] < ob_lo * 0.998 for k in range(j+1, i)): continue
            if ob_lo * 0.998 <= C[i] <= ob_hi * 1.003:
                ob_bull[i] = True; break
        # Bearish OB
        for j in range(i - 2, max(i - lookback - 1, 2), -1):
            if C[j] <= O[j]: continue
            ob_lo = min(O[j], C[j]); ob_hi = max(O[j], C[j])
            if not (j+1 < n and C[j+1] < O[j+1]): continue
            if any(H[k] > ob_hi * 1.002 for k in range(j+1, i)): continue
            if ob_lo * 0.997 <= C[i] <= ob_hi * 1.002:
                ob_bear[i] = True; break
    return ob_bull, ob_bear

def backtest(data, tp_mult, sl_mult, trend_filter):
    O, H, L, C = data['O'], data['H'], data['L'], data['C']
    n = len(C)
    
    # Pre-calc indicators
    e233 = ema(C, 233)
    a = atr(H, L, C, 14)
    fb, fs = calc_fvg(O, H, L, C)
    ob_bull, ob_bear = calc_order_blocks(O, H, L, C)
    
    trades = []
    for i in range(233, n - 50):
        sig = None
        # Entry logic
        if ob_bull[i] and fb[i]:
            if not trend_filter or C[i] > e233[i]:
                sig = 'buy'
        elif ob_bear[i] and fs[i]:
            if not trend_filter or C[i] < e233[i]:
                sig = 'sell'
        
        if sig:
            entry = C[i]
            av = a[i]
            if not av: continue
            tp = entry + (tp_mult * av) if sig == 'buy' else entry - (tp_mult * av)
            sl = entry - (sl_mult * av) if sig == 'buy' else entry + (sl_mult * av)
            
            for j in range(i+1, min(i+100, n)):
                if sig == 'buy':
                    if H[j] >= tp: trades.append(tp_mult * av); break
                    if L[j] <= sl: trades.append(-sl_mult * av); break
                else:
                    if L[j] <= tp: trades.append(tp_mult * av); break
                    if H[j] >= sl: trades.append(-sl_mult * av); break
    
    if not trades: return 0, 0, 0
    pnl = sum(trades)
    wr = len([t for t in trades if t > 0]) / len(trades)
    gw = sum([t for t in trades if t > 0])
    gl = abs(sum([t for t in trades if t < 0])) or 0.001
    pf = gw / gl
    return len(trades), wr, pf, pnl

def optimize_tf(filename):
    print(f"\n--- OTTIMIZZAZIONE SU {filename} ---", flush=True)
    with open(filename) as f:
        raw = json.load(f)
    
    if isinstance(raw, dict) and 'candles' in raw:
        candles = raw['candles']
        data = {
            'O': [c['o'] for c in candles],
            'H': [c['h'] for c in candles],
            'L': [c['l'] for c in candles],
            'C': [c['c'] for c in candles],
        }
    else:
        data = raw

    O, H, L, C = data['O'], data['H'], data['L'], data['C']
    print(f"Calcolo indicatori per {len(C)} candele...", flush=True)
    e233 = ema(C, 233)
    a_v = atr(H, L, C, 14)
    fb, fs = calc_fvg(O, H, L, C)
    ob_bull, ob_bear = calc_order_blocks(O, H, L, C)
    print("Inizio Sweep...", flush=True)

    results = []
    print(f"{'TP':>4} | {'SL':>4} | {'Trend':>5} | {'N':>5} | {'WR':>6} | {'PF':>5} | {'PnL':>8}")
    print("-" * 55)
    
    for tp in [1.0, 1.5, 2.0, 2.5]:
        for sl in [0.5, 0.8, 1.0, 1.2]:
            for flt in [True, False]:
                trades = []
                for i in range(233, len(C) - 50):
                    sig = None
                    if ob_bull[i] and fb[i]:
                        if not flt or C[i] > e233[i]: sig = 'buy'
                    elif ob_bear[i] and fs[i]:
                        if not flt or C[i] < e233[i]: sig = 'sell'
                    
                    if sig:
                        entry = C[i]; av = a_v[i]
                        if not av: continue
                        target = entry + (tp * av) if sig == 'buy' else entry - (tp * av)
                        stop = entry - (sl * av) if sig == 'buy' else entry + (sl * av)
                        for j in range(i+1, min(i+100, len(C))):
                            if sig == 'buy':
                                if H[j] >= target: trades.append(tp*av); break
                                if L[j] <= stop: trades.append(-sl*av); break
                            else:
                                if L[j] <= target: trades.append(tp*av); break
                                if H[j] >= stop: trades.append(-sl*av); break
                
                if trades:
                    wr = len([t for t in trades if t > 0]) / len(trades)
                    gw = sum([t for t in trades if t > 0])
                    gl = abs(sum([t for t in trades if t < 0])) or 0.001
                    pf = gw / gl
                    pnl = sum(trades)
                    results.append({'tp': tp, 'sl': sl, 'flt': flt, 'n': len(trades), 'wr': wr, 'pf': pf, 'pnl': pnl})
                    print(f"{tp:>4.1f} | {sl:>4.1f} | {str(flt):>5} | {len(trades):>5} | {wr:>5.1%} | {pf:>5.2f} | {pnl:>8.1f}", flush=True)
    
    if results:
        top = sorted(results, key=lambda x: x['pf'], reverse=True)[:3]
        print("\nTOP 3 CONFIGS:")
        for t in top: print(t)

if __name__ == "__main__":
    for tf_file in ['xauusd_m30_mt5.json', 'xauusd_m15_mt5.json', 'xauusd_m5_mt5.json']:
        if os.path.exists(tf_file):
            optimize_tf(tf_file)
