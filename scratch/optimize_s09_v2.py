import json, os, datetime
import numpy as np

def _ema(src, p):
    if len(src) < p: return [None]*len(src)
    alpha = 2 / (p + 1)
    out = [None] * len(src)
    valid_start = 0
    while valid_start < len(src) and src[valid_start] is None:
        valid_start += 1
    if valid_start >= len(src): return out
    
    ema_val = src[valid_start]
    out[valid_start] = ema_val
    for i in range(valid_start + 1, len(src)):
        ema_val = src[i] * alpha + ema_val * (1 - alpha)
        out[i] = ema_val
    return out

def _atr(H, L, C, p=14):
    n = len(C)
    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1]))
    atr_out = [None] * n
    if n < p: return atr_out
    curr_atr = sum(tr[1:p+1])/p
    atr_out[p] = curr_atr
    for i in range(p+1, n):
        curr_atr = (curr_atr * (p-1) + tr[i]) / p
        atr_out[i] = curr_atr
    return atr_out

def backtest_s09_v2(data, ema_conf, tp_mult, sl_mult, use_trend_filter=True):
    C = np.array(data['C'])
    H = np.array(data['H'])
    L = np.array(data['L'])
    n = len(C)
    
    e1 = _ema(C, ema_conf[0])
    e2 = _ema(C, ema_conf[1])
    e3 = _ema(C, ema_conf[2])
    e4 = _ema(C, ema_conf[3])
    e200 = _ema(C, 200) # trend filter
    atr_vals = _atr(H, L, C, 14)
    
    trades = []
    in_pos = None # 'buy', 'sell'
    entry_price = 0
    tp_price = 0
    sl_price = 0
    
    for i in range(250, n):
        if in_pos:
            # Check exit
            if in_pos == 'buy':
                if H[i] >= tp_price:
                    trades.append({'pnl': tp_price - entry_price, 'win': True})
                    in_pos = None
                elif L[i] <= sl_price:
                    trades.append({'pnl': sl_price - entry_price, 'win': False})
                    in_pos = None
            else:
                if L[i] <= tp_price:
                    trades.append({'pnl': entry_price - tp_price, 'win': True})
                    in_pos = None
                elif H[i] >= sl_price:
                    trades.append({'pnl': entry_price - sl_price, 'win': False})
                    in_pos = None
            continue
        
        # Signal
        if any(x[i] is None for x in [e1, e2, e3, e4, e200, atr_vals]): continue
        
        bull_stack = e1[i] > e2[i] > e3[i] > e4[i]
        bear_stack = e1[i] < e2[i] < e3[i] < e4[i]
        
        # V2 Idea: Trend Filter EMA 200
        trend_up = C[i] > e200[i] if use_trend_filter else True
        trend_dn = C[i] < e200[i] if use_trend_filter else True
        
        atr = atr_vals[i]
        
        if bull_stack and trend_up:
            in_pos = 'buy'
            entry_price = C[i]
            tp_price = entry_price + atr * tp_mult
            sl_price = entry_price - atr * sl_mult
        elif bear_stack and trend_dn:
            in_pos = 'sell'
            entry_price = C[i]
            tp_price = entry_price - atr * tp_mult
            sl_price = entry_price + atr * sl_mult
            
    if not trades: return 0, 0, 0, 0
    pnl = sum(t['pnl'] for t in trades)
    wr = sum(1 for t in trades if t['win']) / len(trades)
    wins = [t['pnl'] for t in trades if t['win']]
    losses = [abs(t['pnl']) for t in trades if not t['win']]
    pf = sum(wins)/sum(losses) if losses and sum(losses)>0 else 99
    return len(trades), wr, pnl, pf

def optimize():
    print("Caricamento dati M5...")
    with open('xauusd_m5_mt5.json') as f:
        raw_data = json.load(f)
    
    # Check if format is list of candles
    if isinstance(raw_data, dict) and 'candles' in raw_data:
        candles = raw_data['candles']
        data = {
            'O': [c['o'] for c in candles],
            'H': [c['h'] for c in candles],
            'L': [c['l'] for c in candles],
            'C': [c['c'] for c in candles],
        }
    else:
        data = raw_data
    
    emas = [
        (10, 20, 50, 100),
        (20, 50, 100, 200),
        (8, 21, 55, 144), # Fibonacci
        (13, 34, 89, 233)
    ]
    tps = [1.5, 2.0, 2.5, 3.0]
    sls = [1.0, 1.2, 1.5]
    filters = [True, False]
    
    results = []
    print(f"{'EMA':<15} | {'TP':<4} | {'SL':<4} | {'FLT':<4} | {'N':<5} | {'WR%':<6} | {'PF':<5} | {'PnL'}")
    print("-" * 70)
    
    for ema in emas:
        for tp in tps:
            for sl in sls:
                for flt in filters:
                    n, wr, pnl, pf = backtest_s09_v2(data, ema, tp, sl, flt)
                    if n > 50:
                        results.append({
                            'ema': ema, 'tp': tp, 'sl': sl, 'flt': flt,
                            'n': n, 'wr': wr, 'pnl': pnl, 'pf': pf
                        })
                        print(f"{str(ema):<15} | {tp:<4} | {sl:<4} | {str(flt):<4} | {n:<5} | {wr*100:>5.1f}% | {pf:>5.2f} | {pnl:>.1f}")

    results.sort(key=lambda x: x['pf'], reverse=True)
    print("\nTOP 3 CONFIGS:")
    for r in results[:3]:
        print(r)

if __name__ == "__main__":
    optimize()
