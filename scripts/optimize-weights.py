import urllib.request
import json
import time
import sys
import math

def fetch_candles(days):
    print("Fetching up to 730 days (Yahoo limit)...")
    all_candles = []
    now = int(time.time())
    start = now - days * 86400
    
    for from_t in range(start, now, 59 * 86400):
        to_t = min(from_t + 59 * 86400, now)
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1h&period1={from_t}&period2={to_t}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
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
            pass # Ignore the 422 errors past 730 days
            
    seen = set()
    unique = []
    for c in all_candles:
        if c['t'] not in seen:
            seen.add(c['t'])
            unique.append(c)
    unique.sort(key=lambda x: x['t'])
    print(f"Fetched {len(unique)} candles")
    return unique

def ema(src, p):
    k = 2 / (p + 1)
    v = src[0]
    out = [v]
    for i in range(1, len(src)): out.append(src[i] * k + out[-1] * (1 - k))
    return out

def sma(src, p):
    out = [None] * len(src)
    for i in range(p - 1, len(src)):
        sl = src[i - p + 1:i + 1]
        out[i] = None if None in sl else sum(sl) / p
    return out

def calc_indicators(candles):
    n = len(candles)
    H = [x['h'] for x in candles]; L = [x['l'] for x in candles]; C = [x['c'] for x in candles]

    # CCI_S
    CCI_P, STOCH_P, SK, SD = 50, 50, 8, 8
    cci = [0]*n
    for i in range(CCI_P - 1, n):
        sl = C[i - CCI_P + 1:i + 1]
        mn = sum(sl) / CCI_P
        md = sum((abs(x - mn) for x in sl)) / CCI_P
        cci[i] = 0 if md == 0 else (C[i] - mn) / (0.015 * md)
        
    stk = [50]*n
    for i in range(CCI_P + STOCH_P - 2, n):
        lv = min(cci[i-STOCH_P+1:i+1])
        hv = max(cci[i-STOCH_P+1:i+1])
        stk[i] = 50 if (hv-lv)==0 else ((cci[i]-lv)/(hv-lv))*100
        
    stk_k = sma(stk, SK)
    stk_d = sma(stk_k, SD)

    # MACD
    ema12 = ema(C, 12); ema26 = ema(C, 26)
    macd = [ema12[i] - ema26[i] for i in range(n)]
    signal = ema(macd, 9)
    histogram = [macd[i] - signal[i] for i in range(n)]

    # ADX
    AP = 10
    TR = [0]*n; DMP = [0]*n; DMM = [0]*n
    for i in range(1, n):
        TR[i] = max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1]))
        up = H[i] - H[i-1]; dn = L[i-1] - L[i]
        DMP[i] = up if up > dn and up > 0 else 0
        DMM[i] = dn if dn > up and dn > 0 else 0
        
    sTR = [0]*n; sDMP = [0]*n; sDMM = [0]*n
    for i in range(1, n):
        sTR[i] = sTR[i-1] - sTR[i-1]/AP + TR[i]
        sDMP[i] = sDMP[i-1] - sDMP[i-1]/AP + DMP[i]
        sDMM[i] = sDMM[i-1] - sDMM[i-1]/AP + DMM[i]
        
    DIP = [sDMP[i]/v*100 if v > 0 else 0 for i, v in enumerate(sTR)]
    DIM = [sDMM[i]/v*100 if v > 0 else 0 for i, v in enumerate(sTR)]
    DX = [abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    ADX = sma(DX, AP)

    return {'stk_d': stk_d, 'macd': macd, 'signal': signal, 'hist': histogram, 'ADX': list(ADX), 'DIP': DIP, 'DIM': DIM, 'C': C}

def val_mfkk(cciVal, macdLine, macdSignal, macdHist, adxVal, diPlus, diMinus, c_dir):
    isBuy = c_dir == 'buy'
    
    cciScore = 50
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
    diff = macdLine - macdSignal
    str_val = min(abs(diff) / 3, 1)
    histBonus = 10 if ((isBuy and macdHist > 0) or (not isBuy and macdHist < 0)) else 0
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
    diDiff = diPlus - diMinus
    spreadBonus = min(abs(diDiff) / 20, 1)
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

    return cciScore, macdScore, adxScore

def simulate(candles, inds, wCCI, wMACD, wADX, TP=25, SL=15, score_thr=75):
    C = inds['C']
    n = len(C)
    trades = 0
    wins = 0
    losses = 0
    pnl = 0
    ot = None
    
    for i in range(120, n):
        cci = inds['stk_d'][i]; macd = inds['macd'][i]; sig = inds['signal'][i]; hist = inds['hist'][i]
        adx = inds['ADX'][i]; diP = inds['DIP'][i]; diM = inds['DIM'][i]
        if cci is None or adx is None: continue
        
        if ot:
            H = candles[i]['h']; L = candles[i]['l']
            if ot['d'] == 'buy':
                if L <= ot['e'] - SL:
                    pnl -= SL; losses += 1; ot = None; trades += 1
                elif H >= ot['e'] + TP:
                    pnl += TP; wins += 1; ot = None; trades += 1
            else:
                if H >= ot['e'] + SL:
                    pnl -= SL; losses += 1; ot = None; trades += 1
                elif L <= ot['e'] - TP:
                    pnl += TP; wins += 1; ot = None; trades += 1
            continue

        bs_cci, bs_macd, bs_adx = val_mfkk(cci, macd, sig, hist, adx, diP, diM, 'buy')
        ss_cci, ss_macd, ss_adx = val_mfkk(cci, macd, sig, hist, adx, diP, diM, 'sell')
        
        bs = bs_cci * wCCI + bs_macd * wMACD + bs_adx * wADX
        ss = ss_cci * wCCI + ss_macd * wMACD + ss_adx * wADX
        
        if bs >= score_thr and bs > ss:
            ot = {'d': 'buy', 'e': C[i]}
        elif ss >= score_thr and ss > bs:
            ot = {'d': 'sell', 'e': C[i]}
            
    return {'wr': wins/trades if trades>0 else 0, 'trades': trades, 'pnl': pnl}

candles = fetch_candles(1800)
inds = calc_indicators(candles)

weights = []
for c in range(10, 85, 5):
    for m in range(10, 85, 5):
        a = 100 - c - m
        if a >= 10:
            weights.append((c/100, m/100, a/100))

print(f"Testing {len(weights)} weight combinations (TP 25, SL 15, Score >=75)...")

best = None
best_score = -9999
results = []

for idx, (wc, wm, wa) in enumerate(weights):
    if idx % 50 == 0: print(f"Progress: {idx}/{len(weights)}")
    res = simulate(candles, inds, wc, wm, wa, TP=25, SL=15, score_thr=75)
    score = res['wr'] * (res['pnl'] if res['trades'] > 100 else -9999) # maximize P&L with consistent WR
    if score > best_score and res['trades'] >= 200:
        best_score = score
        best = (wc, wm, wa, res)
    results.append((wc, wm, wa, res['trades'], res['wr'], res['pnl']))

results.sort(key=lambda x: x[5], reverse=True) # sort by PnL

print("\n🏆 TOP 5 COMBINATIONS (Score >= 75 | WIDE TP=25 SL=15):")
for r in results[:5]:
    print(f"CCI: {int(r[0]*100)}% | MACD: {int(r[1]*100)}% | ADX: {int(r[2]*100)}%  => Trades: {r[3]}, WR: {r[4]*100:.1f}%, PnL: ${r[5]:.1f}")
    
print("\n🔄 CURRENT BASELINE: CCI 35% | MACD 35% | ADX 30%")
base = next(r for r in results if int(r[0]*100)==35 and int(r[1]*100)==35 and int(r[2]*100)==30)
print(f"Trade: {base[3]}, WR: {base[4]*100:.1f}%, PnL: ${base[5]:.1f}")
