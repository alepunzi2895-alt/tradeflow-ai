import json
from backtest_mfkk_intraday import compute, ema

def simulate_s05(candles, ind, rsi_thr, adx_thr, rsi_os):
    trades = []
    n = len(candles)
    # S05 Logic
    for i in range(100, n-1):
        # same logic as in backtest_mfkk_intraday.py for mfkk_intraday_v3
        macd = ind['macd'][i]; 
        hist = ind['macd'][i] # approximated hist
        rsi = ind['rsi'][i]; c = candles[i]['c']
        adx = ind['adx'][i]
        obv_oc = ind['obv_oc'][i]
        
        if rsi is None or adx is None: continue
        
        # V3 Sell Exhaustion logic
        is_sell = False
        is_buy = False
        
        if adx >= adx_thr:
            # Sell Exhaustion
            if macd > 0 and rsi < rsi_os:
                if obv_oc == -1:
                    is_sell = True
            
            # Buy Exhaustion
            if macd < 0 and rsi > rsi_thr:
                if obv_oc == 1:
                    is_buy = True

        if is_buy:
            trades.append({'d': 'buy', 'e': c, 'bar': i})
        elif is_sell:
            trades.append({'d': 'sell', 'e': c, 'bar': i})
            
    return trades

if __name__ == '__main__':
    print("Loading data...")
    with open('data/xauusd_h1_730d.json', 'r') as f:
        data = json.load(f)
        candles = data.get('candles', data) if isinstance(data, dict) else data

    # Calculate indicators
    print("Pre-calculating indicators...")
    ind = compute(candles)
    
    print("Starting Grid Search...")
    best_res = []
    for rsi_thr in range(50, 70, 5):
        for rsi_os in range(30, 50, 5):
            for adx_thr in range(15, 35, 5):
                trades = simulate_s05(candles, ind, rsi_thr, adx_thr, rsi_os)
                # simulate PNL with ATR TP/SL
                pnl = 0
                wins = 0
            losses = 0
            for t in trades:
                atr = ind['atr'][t['bar']]
                if atr is None: continue
                # TP ATRx1.5, SL ATRx1.0
                tp = atr * 1.5
                sl = atr * 1.0
                e = t['e']
                d = t['d']
                # Search future
                for j in range(t['bar']+1, min(t['bar']+50, len(candles))):
                    h, l = candles[j]['h'], candles[j]['l']
                    if d == 'buy':
                        if l <= e - sl:
                            pnl -= sl
                            losses += 1
                            break
                        if h >= e + tp:
                            pnl += tp
                            wins += 1
                            break
                    else:
                        if h >= e + sl:
                            pnl -= sl
                            losses += 1
                            break
                        if l <= e - tp:
                            pnl += tp
                            wins += 1
                            break
            
            n = wins + losses
            if n == 0: continue
            wr = wins / n * 100
            pf = (wins * 1.5) / losses if losses > 0 else 999
            
            best_res.append({'rsi': rsi_thr, 'adx': adx_thr, 'n': n, 'wr': wr, 'pf': pf, 'pnl': pnl})

    best_res.sort(key=lambda x: x['pf'], reverse=True)
    for r in best_res[:10]:
        print(f"RSI>{r['rsi']} ADX>{r['adx']} | N={r['n']} WR={r['wr']:.1f}% PF={r['pf']:.2f}")

