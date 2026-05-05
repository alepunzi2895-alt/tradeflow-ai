"""Analisi buy/sell breakdown S00_MFKK con filtri ADX/ST su M30."""
import json, sys, datetime
sys.path.insert(0, 'scripts')

from signals import signal_mfkk_score

# load data
with open('data/xauusd_m30_mt5.json') as f:
    raw = json.load(f)
candles = raw['candles']

# compute indicators via engine
import os

eng_source = open('scripts/strategy-engine-v2.py', encoding='utf-8').read()
eng_code   = compile(eng_source, 'scripts/strategy-engine-v2.py', 'exec')
eng_ns = {'__file__': 'scripts/strategy-engine-v2.py', '__name__': 'eng'}
exec(eng_code, eng_ns)
compute_indicators = eng_ns['compute_all']

ind = compute_indicators(candles)
N = len(candles)

TP_ATR = 3.5
SL_ATR = 1.5

results = {'buy': [], 'sell': []}

for i in range(100, N - 1):
    ts   = candles[i]['t']
    hour = datetime.datetime.utcfromtimestamp(ts).hour

    a  = ind['adx'][i]
    dp = ind['dip'][i]
    dm = ind['dim'][i]
    if None in (a, dp, dm):
        continue

    sig = signal_mfkk_score(ind, i, hour=hour, tf='M30')
    if sig is None:
        continue

    atr = (ind.get('atr') or [None] * N)[i]
    if not atr or atr <= 0:
        continue

    tp    = atr * TP_ATR
    sl    = atr * SL_ATR
    entry = candles[i + 1]['o']

    win = None
    for j in range(i + 1, min(i + 50, N)):
        h = candles[j]['h']
        l = candles[j]['l']
        if sig == 'buy':
            if l <= entry - sl: win = False; break
            if h >= entry + tp: win = True;  break
        else:
            if h >= entry + sl: win = False; break
            if l <= entry - tp: win = True;  break
    if win is None:
        continue

    pnl = tp if win else -sl
    st  = (ind.get('st') or [0] * N)[i]
    ema50 = (ind.get('ema50') or ind.get('ema_50') or [None] * N)[i]
    close = candles[i]['c']
    rsi   = (ind.get('rsi') or [None] * N)[i]

    results[sig].append({
        'win': win, 'pnl': pnl,
        'adx': a, 'dip': dp, 'dim': dm,
        'st': st,
        'above_ema50': (ema50 is not None and close > ema50),
        'rsi': rsi,
    })

# ── Report ──────────────────────────────────────────────────────────────────

def report(label, lst):
    if not lst:
        print(f'{label}: N=0')
        return
    wins = sum(1 for t in lst if t['win'])
    pnl  = sum(t['pnl'] for t in lst)
    wr   = wins / len(lst)
    print(f'{label}: N={len(lst):4d}  WR={wr:.1%}  P&L=${pnl:+.0f}')

for d in ['buy', 'sell']:
    lst = results[d]
    report(f'\n{d.upper()} TOTAL', lst)

    # ADX buckets
    for lo, hi in [(0, 20), (20, 25), (25, 30), (30, 40), (40, 100)]:
        report(f'  ADX {lo:2d}-{hi:3d}', [t for t in lst if lo <= t['adx'] < hi])

    # Supertrend
    report(f'  ST bullish (st=-1)', [t for t in lst if t['st'] == -1])
    report(f'  ST bearish (st=+1)', [t for t in lst if t['st'] ==  1])

    # ST aligned (buy+ST_bull, sell+ST_bear)
    if d == 'buy':
        report(f'  [filter] BUY + ST aligned', [t for t in lst if t['st'] == -1])
        report(f'  [filter] BUY + ST + ADX>=25',
               [t for t in lst if t['st'] == -1 and t['adx'] >= 25])
        report(f'  [filter] BUY + ST + ADX>=20',
               [t for t in lst if t['st'] == -1 and t['adx'] >= 20])
        report(f'  [filter] BUY + DI+>=20 AND ST',
               [t for t in lst if t['st'] == -1 and t['dip'] - t['dim'] >= 20])
    else:
        report(f'  [filter] SELL + ST aligned', [t for t in lst if t['st'] ==  1])
        report(f'  [filter] SELL + ST + ADX>=25',
               [t for t in lst if t['st'] ==  1 and t['adx'] >= 25])
        report(f'  [filter] SELL + DI- spread>=25 + ST',
               [t for t in lst if t['st'] ==  1 and t['dim'] - t['dip'] >= 25])

print()
