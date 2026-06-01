import json
import os
import math

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

def keltner(H, L, C, p=20, mult=1.5):
    mid = ema(C, p)
    a = atr(H, L, C, p)
    up = [mid[i] + mult * a[i] if a[i] else None for i in range(len(C))]
    dn = [mid[i] - mult * a[i] if a[i] else None for i in range(len(C))]
    return mid, up, dn

def atr(H, L, C, p=14):
    tr = [0]
    for i in range(1, len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    # Simple SMA of TR
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

def run_test(file_path):
    if not os.path.exists(file_path):
        print(f"File {file_path} non trovato.")
        return
    
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    candles = data if isinstance(data, list) else data.get('candles', [])
    if not candles:
        print("Dati vuoti.")
        return

    C = [c['c'] for c in candles]
    H = [c['h'] for c in candles]
    L = [c['l'] for c in candles]
    V = [c['v'] for c in candles]
    n = len(C)

    print(f"--- OTTIMIZZAZIONE S16 SU {os.path.basename(file_path)} ---")
    print(f"Calcolo indicatori per {n} candele...")
    
    a_v = atr(H, L, C, 14)
    obv_v = obv(C, V)
    # Calcoliamo ST (proxy trend)
    st_v = supertrend(H, L, C, 10, 3.0)
    # Calcoliamo EMA 233 (istituzionale)
    e233 = ema(C, 233)
    # Calcoliamo BB (20,2) e KC (20,1.5) per Squeeze
    _, b_up, b_dn = bb(C, 20, 2.0)
    _, k_up, k_dn = keltner(H, L, C, 20, 1.5)
    is_sqz = [(b_up[i] < k_up[i] and b_dn[i] > k_dn[i]) if b_up[i] and k_up[i] else False for i in range(n)]
    
    # Pre-calcoliamo OBV EMA 20
    obv_e20 = ema(obv_v, 20)

    tps = [2.0, 2.5, 3.0]
    sls = [1.0, 1.2, 1.5]
    filters = [True] 
    squeezes = [True, False]

    results = []
    
    print("Inizio Sweep...")
    print(f"{'TP':>4} | {'SL':>4} | {'EMA':>5} | {'N':>6} | {'WR':>6} | {'PF':>5} | {'PnL':>10}")
    print("-" * 55)

    for tp_m in tps:
        for sl_m in sls:
            for use_ema in filters:
                for use_sqz in squeezes:
                    trades = []
                    pnl = 0
                    wins = 0
                    for i in range(250, n - 50):
                        if a_v[i] is None or e233[i] is None: continue
                        
                        # Logica S16 Base
                        is_bull = obv_v[i] > obv_e20[i] and C[i] > C[i-1] and st_v[i] == -1
                        is_bear = obv_v[i] < obv_e20[i] and C[i] < C[i-1] and st_v[i] == 1
                        
                        if use_ema:
                            if is_bull and C[i] < e233[i]: is_bull = False
                            if is_bear and C[i] > e233[i]: is_bear = False
                        
                        if use_sqz:
                            if not is_sqz[i]:
                                is_bull = False; is_bear = False
                    
                    sig = 'buy' if is_bull else ('sell' if is_bear else None)
                    if not sig: continue
                    
                    tp_p = C[i] + tp_m * a_v[i] if sig == 'buy' else C[i] - tp_m * a_v[i]
                    sl_p = C[i] - sl_m * a_v[i] if sig == 'buy' else C[i] + sl_m * a_v[i]
                    
                    win = lost = False
                    for j in range(i+1, min(i+48, n)):
                        if sig == 'buy':
                            if H[j] >= tp_p: win = True; break
                            if L[j] <= sl_p: lost = True; break
                        else:
                            if L[j] <= tp_p: win = True; break
                            if H[j] >= sl_p: lost = True; break
                    
                    if win:
                        pnl += tp_m * a_v[i]
                        wins += 1
                        trades.append({'res': 1, 'val': tp_m * a_v[i]})
                    elif lost:
                        pnl -= sl_m * a_v[i]
                        trades.append({'res': 0, 'val': sl_m * a_v[i]})
                        
                if not trades: continue
                wr = wins / len(trades)
                gross_win = sum([t['val'] for t in trades if t['res'] == 1])
                gross_loss = sum([t['val'] for t in trades if t['res'] == 0])
                pf = gross_win / gross_loss if gross_loss > 0 else 9.99
                
                results.append({'tp': tp_m, 'sl': sl_m, 'flt': use_ema, 'sqz': use_sqz, 'n': len(trades), 'wr': wr, 'pf': pf, 'pnl': pnl})
                
                if pf > 1.3: # Mostra solo configurazioni degne
                    print(f"{tp_m:4.1f} | {sl_m:4.1f} | {str(use_sqz):>5} | {len(trades):6d} | {wr:5.1%} | {pf:5.2f} | {pnl:10.1f}")

    results.sort(key=lambda x: x['pf'], reverse=True)
    print("\nTOP 3 CONFIGS:")
    for r in results[:3]:
        print(r)

if __name__ == "__main__":
    run_test('xauusd_m15_mt5.json')
    run_test('xauusd_m30_mt5.json')
    run_test('xauusd_m5_mt5.json')
