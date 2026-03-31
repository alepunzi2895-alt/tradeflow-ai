import urllib.request
import json
import time
import sys
import math
from datetime import datetime

TP_DEFAULT = 15
SL_DEFAULT = 10
PERIOD_DEFAULT = 365

def get_arg(name, default_val):
    try:
        idx = sys.argv.index('--' + name)
        if idx + 1 < len(sys.argv):
            return float(sys.argv[idx + 1])
    except ValueError:
        pass
    return default_val

TP = get_arg('tp', TP_DEFAULT)
SL = get_arg('sl', SL_DEFAULT)
PERIOD = int(get_arg('period', PERIOD_DEFAULT))

print("╔══════════════════════════════════════════╗")
print("║  MFKK Strategy Backtester (Python)       ║")
print(f"║  XAU/USD H1  TP=${TP} SL=${SL}  {PERIOD}d       ║")
print("╚══════════════════════════════════════════╝\n")

def fetch_candles(days):
    all_candles = []
    now = int(time.time())
    start = now - days * 86400
    
    for from_t in range(start, now, 59 * 86400):
        to_t = min(from_t + 59 * 86400, now)
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1h&period1={from_t}&period2={to_t}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        try:
            with urllib.request.urlopen(req) as response:
                d = json.loads(response.read().decode())
                rs = d.get('chart', {}).get('result', [{}])[0]
                timestamps = rs.get('timestamp')
                if not timestamps: continue
                q = rs.get('indicators', {}).get('quote', [{}])[0]
                for i in range(len(timestamps)):
                    if q.get('close') and q['close'][i] is not None:
                        all_candles.append({
                            't': timestamps[i], 'o': q['open'][i],
                            'h': q['high'][i], 'l': q['low'][i], 'c': q['close'][i]
                        })
        except Exception as e:
            print(f" Chunk error: {e}")
            
    seen = set()
    unique = []
    for c in all_candles:
        if c['t'] not in seen:
            seen.add(c['t'])
            unique.append(c)
    unique.sort(key=lambda x: x['t'])
    print(f"📊 Fetched {len(unique)} unique H1 candles")
    return unique

def ema(src, p):
    k = 2 / (p + 1)
    v = src[0]
    out = [v]
    for i in range(1, len(src)):
        v = src[i] * k + v * (1 - k)
        out.append(v)
    return out

def sma(src, p):
    out = [None] * len(src)
    for i in range(p - 1, len(src)):
        sl = src[i - p + 1:i + 1]
        if None in sl: out[i] = None
        else: out[i] = sum(sl) / p
    return out

def highest(arr, p, i):
    m = -float('inf')
    for j in range(max(0, i - p + 1), i + 1):
        if arr[j] is not None: m = max(m, arr[j])
    return m

def lowest(arr, p, i):
    m = float('inf')
    for j in range(max(0, i - p + 1), i + 1):
        if arr[j] is not None: m = min(m, arr[j])
    return m

def calc_indicators(candles):
    n = len(candles)
    H = [x['h'] for x in candles]
    L = [x['l'] for x in candles]
    C = [x['c'] for x in candles]

    # CCI_S
    CCI_P, STOCH_P, SK, SD = 50, 50, 8, 8
    cci = [None] * n
    for i in range(CCI_P - 1, n):
        sl = C[i - CCI_P + 1:i + 1]
        mn = sum(sl) / CCI_P
        md = sum((abs(x - mn) for x in sl)) / CCI_P
        if md == 0: cci[i] = 0
        else: cci[i] = (C[i] - mn) / (0.015 * md)
        
    stk = [None] * n
    for i in range(CCI_P + STOCH_P - 2, n):
        if cci[i] is None: continue
        lv = lowest(cci, STOCH_P, i)
        hv = highest(cci, STOCH_P, i)
        if (hv - lv) == 0: stk[i] = 50
        else: stk[i] = ((cci[i] - lv) / (hv - lv)) * 100
        
    stk_k = [None] * n
    for i in range(SK - 1, n):
        sl = stk[i - SK + 1:i + 1]
        if None in sl: continue
        stk_k[i] = sum(sl) / SK
        
    stk_d = [None] * n
    for i in range(SD - 1, n):
        sl = stk_k[i - SD + 1:i + 1]
        if None in sl: continue
        stk_d[i] = sum(sl) / SD

    # MACD
    ema12 = ema(C, 12)
    ema26 = ema(C, 26)
    macd = [ema12[i] - ema26[i] for i in range(n)]
    signal = ema(macd, 9)
    histogram = [macd[i] - signal[i] for i in range(n)]

    # ADX
    AP = 10
    TR = [0] * n; DMP = [0] * n; DMM = [0] * n
    for i in range(1, n):
        TR[i] = max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1]))
        up = H[i] - H[i-1]; dn = L[i-1] - L[i]
        DMP[i] = up if up > dn and up > 0 else 0
        DMM[i] = dn if dn > up and dn > 0 else 0
        
    sTR = [0] * n; sDMP = [0] * n; sDMM = [0] * n
    for i in range(1, n):
        sTR[i] = sTR[i-1] - sTR[i-1]/AP + TR[i]
        sDMP[i] = sDMP[i-1] - sDMP[i-1]/AP + DMP[i]
        sDMM[i] = sDMM[i-1] - sDMM[i-1]/AP + DMM[i]
        
    DIP = [sDMP[i]/v*100 if v > 0 else 0 for i, v in enumerate(sTR)]
    DIM = [sDMM[i]/v*100 if v > 0 else 0 for i, v in enumerate(sTR)]
    DX = [abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    ADX = sma(DX, AP)

    return {'stk_d': stk_d, 'macd': macd, 'signal': signal, 'histogram': histogram, 'ADX': list(ADX), 'DIP': DIP, 'DIM': DIM, 'C': C}

def score_mfkk(cciVal, macdLine, macdSignal, macdHist, adxVal, diPlus, diMinus, c_dir):
    isBuy = c_dir == 'buy'
    
    cciScore = 50
    if cciVal is not None:
        if isBuy:
            if cciVal <= 25: cciScore = 95
            elif cciVal <= 35: cciScore = 85
            elif cciVal <= 50: cciScore = 60
            elif cciVal <= 65: cciScore = 35
            elif cciVal < 75: cciScore = 15
            else: cciScore = 0
        else:
            if cciVal >= 75: cciScore = 95
            elif cciVal >= 65: cciScore = 85
            elif cciVal >= 50: cciScore = 60
            elif cciVal >= 35: cciScore = 35
            elif cciVal > 25: cciScore = 15
            else: cciScore = 0

    macdScore = 50
    if macdLine is not None and macdSignal is not None:
        diff = macdLine - macdSignal
        str_val = min(abs(diff) / 3, 1)
        histBonus = 10 if macdHist is not None and ((isBuy and macdHist > 0) or (not isBuy and macdHist < 0)) else 0
        if isBuy:
            if diff > 0.5: macdScore = round(65 + str_val * 25) + histBonus
            elif diff > 0: macdScore = 60 + histBonus
            elif diff > -1: macdScore = 30
            else: macdScore = 5
        else:
            if diff < -0.5: macdScore = round(65 + str_val * 25) + histBonus
            elif diff < 0: macdScore = 60 + histBonus
            elif diff < 1: macdScore = 30
            else: macdScore = 5
        macdScore = max(0, min(100, macdScore))

    adxScore = 50
    if adxVal is not None and diPlus is not None and diMinus is not None:
        diDiff = diPlus - diMinus
        diSpread = abs(diDiff)
        spreadBonus = min(diSpread / 20, 1)
        adxStr = 1.0 if adxVal >= 35 else 0.85 if adxVal >= 27 else 0.65 if adxVal >= 20 else 0.4 if adxVal >= 14 else 0.2 if adxVal >= 10 else 0.05
        if isBuy:
            if diDiff > 0 and adxVal >= 25: adxScore = round(60 + adxStr * 25 + spreadBonus * 15)
            elif diDiff > 0 and adxVal >= 10: adxScore = 50
            elif diDiff > 0: adxScore = 30
            else: adxScore = 5
        else:
            if diDiff < 0 and adxVal >= 25: adxScore = round(60 + adxStr * 25 + spreadBonus * 15)
            elif diDiff < 0 and adxVal >= 10: adxScore = 50
            elif diDiff < 0: adxScore = 30
            else: adxScore = 5
        adxScore = max(0, min(100, adxScore))

    tot = cciScore * 0.35 + macdScore * 0.35 + adxScore * 0.30
    return {'score': round(tot), 'cciScore': cciScore, 'macdScore': macdScore, 'adxScore': adxScore}

def run_backtest(candles, inds, config):
    tp, sl = config['tp'], config['sl']
    minScore, minScoreForte = config['minScore'], config['minScoreForte']
    C = inds['C']
    n = len(C)
    
    trades = []
    openTrade = None
    
    for i in range(120, n):
        cciVal, macdVal, sigVal = inds['stk_d'][i], inds['macd'][i], inds['signal'][i]
        histVal, adxVal = inds['histogram'][i], inds['ADX'][i]
        diP, diM = inds['DIP'][i], inds['DIM'][i]
        price = C[i]
        time_t = candles[i]['t']
        
        if cciVal is None or adxVal is None: continue
        
        if openTrade:
            high_price, low_price = candles[i]['h'], candles[i]['l']
            if openTrade['dir'] == 'buy':
                if low_price <= openTrade['entry'] - sl:
                    openTrade['exit'] = openTrade['entry'] - sl
                    openTrade['result'] = 'SL'
                    openTrade['pnl'] = -sl
                    trades.append(openTrade)
                    openTrade = None
                elif high_price >= openTrade['entry'] + tp:
                    openTrade['exit'] = openTrade['entry'] + tp
                    openTrade['result'] = 'TP'
                    openTrade['pnl'] = tp
                    trades.append(openTrade)
                    openTrade = None
            else:
                if high_price >= openTrade['entry'] + sl:
                    openTrade['exit'] = openTrade['entry'] + sl
                    openTrade['result'] = 'SL'
                    openTrade['pnl'] = -sl
                    trades.append(openTrade)
                    openTrade = None
                elif low_price <= openTrade['entry'] - tp:
                    openTrade['exit'] = openTrade['entry'] - tp
                    openTrade['result'] = 'TP'
                    openTrade['pnl'] = tp
                    trades.append(openTrade)
                    openTrade = None
            continue

        bs = score_mfkk(cciVal, macdVal, sigVal, histVal, adxVal, diP, diM, 'buy')
        ss = score_mfkk(cciVal, macdVal, sigVal, histVal, adxVal, diP, diM, 'sell')
        
        c_dir, bestScore = None, None
        if bs['score'] >= minScore and bs['score'] > ss['score']:
            c_dir = 'buy'; bestScore = bs
        elif ss['score'] >= minScore and ss['score'] > bs['score']:
            c_dir = 'sell'; bestScore = ss
            
        if c_dir and bestScore:
            isForte = bestScore['score'] >= minScoreForte and bestScore['cciScore'] >= 70 and bestScore['macdScore'] >= 70 and bestScore['adxScore'] >= 70
            openTrade = {
                'dir': c_dir, 'entry': price, 'entryTime': time_t, 'barIndex': i,
                'score': bestScore['score'], 'forte': isForte,
                'cciScore': bestScore['cciScore'], 'macdScore': bestScore['macdScore'], 'adxScore': bestScore['adxScore']
            }
            
    if openTrade:
        pnl = C[-1] - openTrade['entry'] if openTrade['dir'] == 'buy' else openTrade['entry'] - C[-1]
        openTrade['exit'] = C[-1]
        openTrade['result'] = 'OPEN'
        openTrade['pnl'] = pnl
        trades.append(openTrade)
        
    return trades

def analyze_results(trades, label):
    closed = [t for t in trades if t.get('result') != 'OPEN']
    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] < 0]
    
    totalPnL = sum(t['pnl'] for t in closed)
    winRate = (len(wins) / len(closed) * 100) if closed else 0
    grossPro = sum(t['pnl'] for t in wins)
    grossLos = abs(sum(t['pnl'] for t in losses))
    pf = grossPro / grossLos if grossLos > 0 else float('inf') if grossPro > 0 else 0
    
    print(f"{label[:25]:<25} | {len(closed):<4} trades | WR: {winRate:5.1f}% | PnL: ${totalPnL:6.1f} | PF: {pf:4.2f}")
    return {'winRate': winRate, 'profitFactor': pf, 'totalPnL': totalPnL}

def main():
    candles = fetch_candles(PERIOD)
    if len(candles) < 200:
        print("Not enough candles")
        return
        
    inds = calc_indicators(candles)
    configs = [
        {'label': f"BASE", 'tp': TP, 'sl': SL, 'minScore': 70, 'minScoreForte': 80},
        {'label': f"STRICT", 'tp': TP, 'sl': SL, 'minScore': 75, 'minScoreForte': 85},
        {'label': f"RISKY", 'tp': TP, 'sl': SL, 'minScore': 60, 'minScoreForte': 75},
        {'label': f"TIGHT (TP=10 SL=7)", 'tp': 10, 'sl': 7, 'minScore': 70, 'minScoreForte': 80},
        {'label': f"WIDE (TP=25 SL=15)", 'tp': 25, 'sl': 15, 'minScore': 70, 'minScoreForte': 80},
        {'label': f"FORTE ONLY", 'tp': TP, 'sl': SL, 'minScore': 80, 'minScoreForte': 80},
    ]
    
    print("\n")
    for cfg in configs:
        trades = run_backtest(candles, inds, cfg)
        analyze_results(trades, cfg['label'])

if __name__ == '__main__':
    main()
