import json, datetime, math
from collections import defaultdict

def ema(src, p):
    if not src: return []
    k=2/(p+1); v=src[0]; o=[v]
    for x in src[1:]: v=x*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1,len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def rsi(src, p=14):
    n=len(src); out=[None]*n
    if n<=p: return out
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    l=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def atr(h,l,c,p=14):
    tr=[0]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return sma(tr,p)

def adx_full(h,l,c,p=14):
    n=len(c); TR=[0];DMP=[0];DMM=[0]
    for i in range(1,n):
        TR.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    sT=[0];sP=[0];sM=[0]
    for i in range(1,n):
        if i==1: sT.append(TR[1]); sP.append(DMP[1]); sM.append(DMM[1])
        else:
            sT.append(sT[-1]-(sT[-1]/p)+TR[i])
            sP.append(sP[-1]-(sP[-1]/p)+DMP[i])
            sM.append(sM[-1]-(sM[-1]/p)+DMM[i])
    dx=[]
    for i in range(n):
        if sT[i]==0: dx.append(0); continue
        diP=100*sP[i]/sT[i]; diM=100*sM[i]/sT[i]
        diff=abs(diP-diM); summ=diP+diM
        dx.append(100*diff/summ if summ!=0 else 0)
    return sma(dx,p)

def obv_t_channel(c, v, p=20):
    o = [0]
    for i in range(1, len(c)):
        if c[i] > c[i-1]: o.append(o[-1] + v[i])
        elif c[i] < c[i-1]: o.append(o[-1] - v[i])
        else: o.append(o[-1])
    e = ema(o, p)
    sig = []
    for i in range(len(o)):
        if o[i] > e[i]: sig.append(1)
        elif o[i] < e[i]: sig.append(-1)
        else: sig.append(0)
    return sig

def optimize_s05(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    candles = data['candles']
    C = [c['c'] for c in candles]
    H = [c['h'] for c in candles]
    L = [c['l'] for c in candles]
    V = [c['v'] for c in candles]
    
    # Pre-compute indicators
    r = rsi(C, 14)
    a = adx_full(H, L, C, 14)
    av = atr(H, L, C, 14)
    av_sma = sma([x if x else 0 for x in av], 30)
    e200 = ema(C, 200)
    oc = obv_t_channel(C, V, 20)
    
    # MACD Line (12, 26)
    e12 = ema(C, 12); e26 = ema(C, 26)
    ml = [e12[i] - e26[i] for i in range(len(C))]
    
    # Momentum (10)
    mom = [None]*10
    for i in range(10, len(C)): mom.append(C[i] - C[i-10])

    def run_backtest(rsi_th, use_trend, use_vol, tp_mult, sl_mult):
        trades = []
        n = len(candles)
        for i in range(250, n):
            # Baseline filters
            if r[i] is None or a[i] is None or ml[i] is None or mom[i] is None or av[i] is None: continue
            
            # S05 Logic
            is_buy = oc[i] == 1 and r[i] > rsi_th and mom[i] > 0 and ml[i] > 0 and a[i] >= 25
            is_sell = oc[i] == -1 and r[i] < (100 - rsi_th) and mom[i] < 0 and ml[i] < 0 and a[i] >= 25
            
            if use_trend:
                if is_buy and C[i] < e200[i]: is_buy = False
                if is_sell and C[i] > e200[i]: is_sell = False
            
            if use_vol:
                if av[i] < av_sma[i]: # Volatility must be above its average
                    is_buy = False; is_sell = False
            
            sig = 'buy' if is_buy else ('sell' if is_sell else None)
            if not sig: continue
            
            entry = C[i]
            tp_p = entry + av[i]*tp_mult if sig=='buy' else entry - av[i]*tp_mult
            sl_p = entry - av[i]*sl_mult if sig=='buy' else entry + av[i]*sl_mult
            
            win = False; outcome = 'open'
            for j in range(i+1, min(i+48, n)): # Max 48h
                jh = candles[j]['h']; jl = candles[j]['l']
                if sig=='buy':
                    if jh >= tp_p: win=True; outcome='win'; break
                    if jl <= sl_p: outcome='loss'; break
                else:
                    if jl <= tp_p: win=True; outcome='win'; break
                    if jh >= sl_p: outcome='loss'; break
            
            if outcome != 'open':
                trades.append(tp_mult if win else -sl_mult)
        
        if not trades: return 0, 0, 0
        wr = sum(1 for t in trades if t > 0) / len(trades)
        pnl = sum(trades)
        pf = sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0) or 0.001)
        return wr, pf, pnl, len(trades)

    print(f"{'RSI':<4} | {'Trd':<3} | {'Vol':<3} | {'TP':<4} | {'SL':<4} | {'WR%':>6} | {'PF':>6} | {'PnL':>8} | {'N':>5}")
    print("-" * 70)
    
    results = []
    for rsi_th in [52, 55]:
        for trend in [False, True]:
            for vol in [False, True]:
                for tp in [1.5, 2.0]:
                    for sl in [1.0, 1.2]:
                        wr, pf, pnl, n = run_backtest(rsi_th, trend, vol, tp, sl)
                        results.append({'rsi':rsi_th, 'trend':trend, 'vol':vol, 'tp':tp, 'sl':sl, 'wr':wr, 'pf':pf, 'pnl':pnl, 'n':n})
                        print(f"{rsi_th:<4} | {str(trend):<3} | {str(vol):<3} | {tp:<4.1f} | {sl:<4.1f} | {wr*100:>5.1f}% | {pf:>6.3f} | {pnl:>8.1f} | {n:>5}")

    best = max(results, key=lambda x: x['pf'] if x['n'] > 50 else 0)
    print("\nBEST CONFIGURATION:")
    print(best)

if __name__ == "__main__":
    optimize_s05('xauusd_h1_mt5.json')
