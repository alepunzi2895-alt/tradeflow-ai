"""
MFKK Entry Condition Optimizer
================================
Analizza 2 anni di candele H1 XAU/USD e XAG/USD per trovare empiricamente
le migliori condizioni di entry basate sui 3 indicatori MFKK.

Metodo:
  Per ogni canzone calcola lo stato degli indicatori → misura il
  forward return effettivo (quanto si muove il prezzo nelle prossime N ore)
  → trova le combinazioni che portano ai movimenti più consistenti.

Output:
  - Matrice win-rate per zona CCI × MACD × ADX
  - Pesi ottimali per XAU e XAG
  - Soglie di score calibrate empiricamente
  - Report JSON dettagliato
"""

import urllib.request
import json
import time
import math
import sys
import os
from collections import defaultdict

# Fix Unicode output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── CONFIG ──────────────────────────────────────────────────────────────────
DAYS = 730           # 2 anni
TP_USD_XAU = 15.0   # TP in $ per XAU
SL_USD_XAU = 10.0   # SL in $ per XAU
TP_USD_XAG = 0.50   # TP in $ per XAG
SL_USD_XAG = 0.25   # SL in $ per XAG
FORWARD_BARS = 48   # ore per misurare forward return (max 48h)
MIN_TRADES = 30     # min trade per considerare una combinazione valida

ASSETS = [
    {'symbol': 'GC%3DF',  'name': 'XAU/USD', 'tp': TP_USD_XAU, 'sl': SL_USD_XAU},
    {'symbol': 'SI%3DF',  'name': 'XAG/USD', 'tp': TP_USD_XAG, 'sl': SL_USD_XAG},
]

# ─── DATA FETCH ──────────────────────────────────────────────────────────────
def fetch_candles(symbol, days):
    print(f"  Scarico {days} giorni di {symbol}...")
    all_candles = []
    now = int(time.time())
    start = now - days * 86400

    for from_t in range(start, now, 59 * 86400):
        to_t = min(from_t + 59 * 86400, now)
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&period1={from_t}&period2={to_t}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json'
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                d = json.loads(response.read().decode())
                rs = d.get('chart', {}).get('result', [None])[0]
                if not rs or not rs.get('timestamp'):
                    continue
                q = rs.get('indicators', {}).get('quote', [{}])[0]
                ts_list = rs['timestamp']
                for i in range(len(ts_list)):
                    o = q.get('open', []); h = q.get('high', [])
                    l = q.get('low', []);  c = q.get('close', [])
                    if (i < len(c) and c[i] is not None and
                        i < len(h) and h[i] is not None and
                        i < len(l) and l[i] is not None and
                        i < len(o) and o[i] is not None):
                        all_candles.append({
                            't': ts_list[i], 'o': o[i],
                            'h': h[i], 'l': l[i], 'c': c[i]
                        })
        except Exception as e:
            pass

    seen = set()
    unique = []
    for c in all_candles:
        if c['t'] not in seen:
            seen.add(c['t'])
            unique.append(c)
    unique.sort(key=lambda x: x['t'])
    print(f"    → {len(unique)} candele uniche")
    return unique

# ─── INDICATORI ──────────────────────────────────────────────────────────────
def ema(src, p):
    k = 2 / (p + 1)
    v = src[0]
    out = [v]
    for i in range(1, len(src)):
        v = src[i] * k + out[-1] * (1 - k)
        out.append(v)
    return out

def sma_series(src, p):
    out = [None] * len(src)
    for i in range(p - 1, len(src)):
        sl = src[i - p + 1:i + 1]
        out[i] = None if None in sl else sum(sl) / p
    return out

def calc_indicators(candles):
    n = len(candles)
    H = [x['h'] for x in candles]
    L = [x['l'] for x in candles]
    C = [x['c'] for x in candles]

    # ── CCI_S ────────────────────────────────────────────────────────────
    CCI_P, STOCH_P, SK, SD = 50, 50, 8, 8
    cci = [None] * n
    for i in range(CCI_P - 1, n):
        sl = C[i - CCI_P + 1:i + 1]
        mn = sum(sl) / CCI_P
        md = sum(abs(x - mn) for x in sl) / CCI_P
        cci[i] = 0.0 if md == 0 else (C[i] - mn) / (0.015 * md)

    stk = [None] * n
    for i in range(CCI_P + STOCH_P - 2, n):
        if cci[i] is None:
            continue
        window = [cci[j] for j in range(i - STOCH_P + 1, i + 1) if cci[j] is not None]
        if not window:
            continue
        lv = min(window)
        hv = max(window)
        stk[i] = 50.0 if (hv - lv) == 0 else ((cci[i] - lv) / (hv - lv)) * 100

    stk_k = sma_series(stk, SK)
    stk_d = sma_series(stk_k, SD)

    # ── MACD(12,26,9) ────────────────────────────────────────────────────
    ema12 = ema(C, 12)
    ema26 = ema(C, 26)
    macd = [ema12[i] - ema26[i] for i in range(n)]
    signal = ema(macd, 9)
    histogram = [macd[i] - signal[i] for i in range(n)]

    # ── ADX(10) ──────────────────────────────────────────────────────────
    AP = 10
    TR = [0.0] * n
    DMP = [0.0] * n
    DMM = [0.0] * n
    for i in range(1, n):
        TR[i] = max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1]))
        up = H[i] - H[i-1]
        dn = L[i-1] - L[i]
        DMP[i] = up if up > dn and up > 0 else 0.0
        DMM[i] = dn if dn > up and dn > 0 else 0.0

    sTR = [0.0] * n
    sDMP = [0.0] * n
    sDMM = [0.0] * n
    for i in range(1, n):
        sTR[i]  = sTR[i-1]  - sTR[i-1]  / AP + TR[i]
        sDMP[i] = sDMP[i-1] - sDMP[i-1] / AP + DMP[i]
        sDMM[i] = sDMM[i-1] - sDMM[i-1] / AP + DMM[i]

    DIP = [sDMP[i] / sTR[i] * 100 if sTR[i] > 0 else 0.0 for i in range(n)]
    DIM = [sDMM[i] / sTR[i] * 100 if sTR[i] > 0 else 0.0 for i in range(n)]
    DX  = [abs(DIP[i] - DIM[i]) / (DIP[i] + DIM[i]) * 100
           if (DIP[i] + DIM[i]) > 0 else 0.0 for i in range(n)]
    ADX = sma_series(DX, AP)

    return {
        'stk_d': stk_d, 'macd': macd, 'signal': signal,
        'histogram': histogram, 'ADX': ADX, 'DIP': DIP, 'DIM': DIM,
        'C': C, 'H': H, 'L': L
    }

# ─── CLASSIFICAZIONE ZONE INDICATORI ─────────────────────────────────────────
def cci_zone(v):
    """Restituisce la zona CCI_S per BUY e SELL."""
    if v is None:
        return None, None
    # BUY zones (oversold favorisce BUY)
    if v <= 25:   buy_z = 'OS_DEEP'       # oversold profondo
    elif v <= 35: buy_z = 'OS_EXIT'       # uscita oversold
    elif v <= 50: buy_z = 'NEUTRAL_LOW'   # neutro basso
    elif v <= 65: buy_z = 'NEUTRAL_HIGH'  # neutro alto
    elif v < 75:  buy_z = 'OB_APPROACH'   # avvicina overbought
    else:         buy_z = 'OB_DEEP'       # overbought profondo

    # SELL zones (overbought favorisce SELL)
    if v >= 75:   sell_z = 'OB_DEEP'
    elif v >= 65: sell_z = 'OB_EXIT'
    elif v >= 50: sell_z = 'NEUTRAL_HIGH'
    elif v >= 35: sell_z = 'NEUTRAL_LOW'
    elif v > 25:  sell_z = 'OS_APPROACH'
    else:         sell_z = 'OS_DEEP'

    return buy_z, sell_z

def macd_zone(macd_val, sig_val, hist_val, isBuy):
    """Zona MACD."""
    if macd_val is None or sig_val is None:
        return None
    diff = macd_val - sig_val
    hist_ok = (isBuy and hist_val > 0) or (not isBuy and hist_val < 0)
    if isBuy:
        if diff > 2.0:   return 'STRONG_BULL'
        elif diff > 0.5: return 'BULL' + ('_H' if hist_ok else '')
        elif diff > 0:   return 'CROSSOVER_UP'
        elif diff > -1:  return 'WEAK_BEAR'
        else:            return 'STRONG_BEAR'
    else:
        if diff < -2.0:  return 'STRONG_BEAR'
        elif diff < -0.5:return 'BEAR' + ('_H' if hist_ok else '')
        elif diff < 0:   return 'CROSSOVER_DN'
        elif diff < 1:   return 'WEAK_BULL'
        else:            return 'STRONG_BULL'

def adx_zone(adx_val, dip, dim, isBuy):
    """Zona ADX."""
    if adx_val is None:
        return None
    di_ok = (dip > dim) if isBuy else (dim > dip)
    spread = abs(dip - dim)
    if adx_val >= 35:   strength = 'VERY_STRONG'
    elif adx_val >= 27: strength = 'STRONG'
    elif adx_val >= 20: strength = 'MODERATE'
    elif adx_val >= 14: strength = 'WEAK'
    elif adx_val >= 10: strength = 'VERY_WEAK'
    else:               strength = 'FLAT'

    direction = 'ALIGNED' if di_ok else 'AGAINST'
    spread_tag = 'WIDE' if spread > 15 else ('MED' if spread > 7 else 'NARROW')
    return f'{direction}_{strength}_{spread_tag}'

# ─── FORWARD RETURN ───────────────────────────────────────────────────────────
def calc_forward_outcome(candles, inds, i, tp, sl, isBuy, max_bars=FORWARD_BARS):
    """
    Dato l'entry alla chiusura della candela i,
    ritorna: 'TP', 'SL', 'NEUTRAL', e il numero di barre per arrivarci.
    """
    entry = inds['C'][i]
    n = len(candles)
    for j in range(i + 1, min(i + max_bars + 1, n)):
        h = inds['H'][j]
        l = inds['L'][j]
        if isBuy:
            if l <= entry - sl:
                return 'SL', j - i
            if h >= entry + tp:
                return 'TP', j - i
        else:
            if h >= entry + sl:
                return 'SL', j - i
            if l <= entry - tp:
                return 'TP', j - i
    # max bars raggiunto senza hit
    last_close = inds['C'][min(i + max_bars, n - 1)]
    move = last_close - entry if isBuy else entry - last_close
    return 'NEUTRAL', max_bars

# ─── ANALISI PRINCIPALE ───────────────────────────────────────────────────────
def analyze_asset(asset, candles):
    name = asset['name']
    tp = asset['tp']
    sl = asset['sl']
    print(f"\n  Calcolo indicatori per {name}...")
    inds = calc_indicators(candles)
    n = len(candles)

    # Raccogli dati per ogni punto d'ingresso potenziale
    # Struttura: combo_key → {tp_count, sl_count, neutral_count, bars_list}
    combo_stats = {
        'buy':  defaultdict(lambda: {'tp': 0, 'sl': 0, 'neutral': 0, 'bars': []}),
        'sell': defaultdict(lambda: {'tp': 0, 'sl': 0, 'neutral': 0, 'bars': []})
    }

    # Statistiche per singola zona (analisi marginale)
    cci_stats  = {'buy': defaultdict(lambda: {'tp':0,'sl':0,'n':0}),
                  'sell': defaultdict(lambda: {'tp':0,'sl':0,'n':0})}
    macd_stats = {'buy': defaultdict(lambda: {'tp':0,'sl':0,'n':0}),
                  'sell': defaultdict(lambda: {'tp':0,'sl':0,'n':0})}
    adx_stats  = {'buy': defaultdict(lambda: {'tp':0,'sl':0,'n':0}),
                  'sell': defaultdict(lambda: {'tp':0,'sl':0,'n':0})}

    START = 130
    print(f"  Analisi forward return ({n - START} punti, max {FORWARD_BARS}h forward)...")

    processed = 0
    for i in range(START, n - FORWARD_BARS - 1):
        cci_v  = inds['stk_d'][i]
        macd_v = inds['macd'][i]
        sig_v  = inds['signal'][i]
        hist_v = inds['histogram'][i]
        adx_v  = inds['ADX'][i]
        dip    = inds['DIP'][i]
        dim    = inds['DIM'][i]

        if cci_v is None or adx_v is None or macd_v is None:
            continue

        for direction, isBuy in [('buy', True), ('sell', False)]:
            bz, sz  = cci_zone(cci_v)
            cz = bz if isBuy else sz
            mz = macd_zone(macd_v, sig_v, hist_v, isBuy)
            az = adx_zone(adx_v, dip, dim, isBuy)

            if cz is None or mz is None or az is None:
                continue

            outcome, bars = calc_forward_outcome(candles, inds, i, tp, sl, isBuy)

            # Combo key = 3 zone insieme
            combo_key = f"{cz}|{mz}|{az}"
            s = combo_stats[direction][combo_key]
            s[outcome.lower()] = s.get(outcome.lower(), 0) + 1
            if outcome != 'NEUTRAL':
                s['bars'].append(bars)

            # Analisi marginale singola zona
            cci_stats[direction][cz][outcome.lower() if outcome != 'NEUTRAL' else 'n'] += 1
            if outcome == 'TP': cci_stats[direction][cz]['tp'] += 1
            if outcome == 'SL': cci_stats[direction][cz]['sl'] += 1
            cci_stats[direction][cz]['n'] += 1

            macd_stats[direction][mz]['n'] += 1
            if outcome == 'TP': macd_stats[direction][mz]['tp'] += 1
            if outcome == 'SL': macd_stats[direction][mz]['sl'] += 1

            adx_stats[direction][az]['n'] += 1
            if outcome == 'TP': adx_stats[direction][az]['tp'] += 1
            if outcome == 'SL': adx_stats[direction][az]['sl'] += 1

        processed += 1
        if processed % 2000 == 0:
            pct = processed / (n - START - FORWARD_BARS - 1) * 100
            print(f"    {pct:.0f}% completato...")

    return {
        'combo': {d: dict(v) for d, v in combo_stats.items()},
        'cci':   {d: dict(v) for d, v in cci_stats.items()},
        'macd':  {d: dict(v) for d, v in macd_stats.items()},
        'adx':   {d: dict(v) for d, v in adx_stats.items()},
    }

# ─── CALCOLO WIN RATE ─────────────────────────────────────────────────────────
def win_rate(s):
    tp = s.get('tp', 0)
    sl = s.get('sl', 0)
    total = tp + sl
    return (tp / total * 100) if total > 0 else 0.0

def total_resolved(s):
    return s.get('tp', 0) + s.get('sl', 0)

# ─── OTTIMIZZAZIONE PESI ─────────────────────────────────────────────────────
def optimize_weights(candles, inds, tp, sl):
    """Grid search sui pesi CCI/MACD/ADX."""
    print("  Ottimizzazione pesi (grid search)...")
    best_results = []
    n = len(inds['C'])
    START = 130

    def score_entry(i, direction):
        cci_v  = inds['stk_d'][i]
        macd_v = inds['macd'][i]
        sig_v  = inds['signal'][i]
        hist_v = inds['histogram'][i]
        adx_v  = inds['ADX'][i]
        dip    = inds['DIP'][i]
        dim    = inds['DIM'][i]
        if cci_v is None or adx_v is None:
            return None

        isBuy = direction == 'buy'
        # CCI score raw
        if isBuy:
            if cci_v <= 25:   cs = 95
            elif cci_v <= 35: cs = 85
            elif cci_v <= 50: cs = 60
            elif cci_v <= 65: cs = 35
            elif cci_v < 75:  cs = 15
            else:             cs = 0
        else:
            if cci_v >= 75:   cs = 95
            elif cci_v >= 65: cs = 85
            elif cci_v >= 50: cs = 60
            elif cci_v >= 35: cs = 35
            elif cci_v > 25:  cs = 15
            else:             cs = 0

        # MACD score raw
        diff = macd_v - sig_v
        str_v = min(abs(diff) / 3, 1)
        hb = 10 if ((isBuy and hist_v > 0) or (not isBuy and hist_v < 0)) else 0
        if isBuy:
            if diff > 0.5:   ms = round(65 + str_v * 25) + hb
            elif diff > 0:   ms = 60 + hb
            elif diff > -1:  ms = 30
            else:            ms = 5
        else:
            if diff < -0.5:  ms = round(65 + str_v * 25) + hb
            elif diff < 0:   ms = 60 + hb
            elif diff < 1:   ms = 30
            else:            ms = 5
        ms = max(0, min(100, ms))

        # ADX score raw
        diDiff = dip - dim
        spread = min(abs(diDiff) / 20, 1)
        astr = (1.0 if adx_v >= 35 else 0.85 if adx_v >= 27 else
                0.65 if adx_v >= 20 else 0.4 if adx_v >= 14 else
                0.2 if adx_v >= 10 else 0.05)
        if isBuy:
            if diDiff > 0 and adx_v >= 25:  as_ = round(60 + astr * 25 + spread * 15)
            elif diDiff > 0 and adx_v >= 10: as_ = 50
            elif diDiff > 0:                 as_ = 30
            else:                            as_ = 5
        else:
            if diDiff < 0 and adx_v >= 25:  as_ = round(60 + astr * 25 + spread * 15)
            elif diDiff < 0 and adx_v >= 10: as_ = 50
            elif diDiff < 0:                 as_ = 30
            else:                            as_ = 5
        as_ = max(0, min(100, as_))

        return cs, ms, as_

    # Pre-calcola tutti i raw scores
    raw_scores = {}
    for i in range(START, n - FORWARD_BARS - 1):
        for d in ['buy', 'sell']:
            r = score_entry(i, d)
            if r:
                raw_scores[(i, d)] = r

    results = []
    tested = 0
    for wc in range(10, 85, 5):
        for wm in range(10, 85, 5):
            wa = 100 - wc - wm
            if wa < 10:
                continue
            wc_f = wc / 100; wm_f = wm / 100; wa_f = wa / 100

            trades = 0
            wins = 0
            open_trade = None

            for i in range(START, n - FORWARD_BARS - 1):
                if open_trade:
                    # check exit
                    h = inds['H'][i]; l = inds['L'][i]; entry = open_trade['e']
                    isBuy_t = open_trade['d'] == 'buy'
                    if isBuy_t:
                        if l <= entry - sl:
                            trades += 1; open_trade = None; continue
                        elif h >= entry + tp:
                            trades += 1; wins += 1; open_trade = None; continue
                    else:
                        if h >= entry + sl:
                            trades += 1; open_trade = None; continue
                        elif l <= entry - tp:
                            trades += 1; wins += 1; open_trade = None; continue
                    continue

                buy_r  = raw_scores.get((i, 'buy'))
                sell_r = raw_scores.get((i, 'sell'))
                if not buy_r or not sell_r:
                    continue

                bs = buy_r[0] * wc_f + buy_r[1] * wm_f + buy_r[2] * wa_f
                ss = sell_r[0] * wc_f + sell_r[1] * wm_f + sell_r[2] * wa_f

                THRESH = 70
                if bs >= THRESH and bs > ss:
                    open_trade = {'d': 'buy', 'e': inds['C'][i]}
                elif ss >= THRESH and ss > bs:
                    open_trade = {'d': 'sell', 'e': inds['C'][i]}

            wr = wins / trades if trades > 0 else 0
            pnl = wins * tp - (trades - wins) * sl
            # score composito
            metric = wr * pnl if trades >= MIN_TRADES else -9999
            results.append({
                'wc': wc, 'wm': wm, 'wa': wa,
                'trades': trades, 'wr': round(wr * 100, 1),
                'pnl': round(pnl, 2), 'metric': round(metric, 2)
            })
            tested += 1

    results.sort(key=lambda x: x['metric'], reverse=True)
    return results[:10]

# ─── CALIBRAZIONE SCORE THRESHOLDS ───────────────────────────────────────────
def calibrate_cci_thresholds(cci_data, direction):
    """
    Suggerisce nuove soglie score per CCI basate sui win rate empirici.
    """
    zones_order = {
        'buy': ['OS_DEEP', 'OS_EXIT', 'NEUTRAL_LOW', 'NEUTRAL_HIGH', 'OB_APPROACH', 'OB_DEEP'],
        'sell': ['OB_DEEP', 'OB_EXIT', 'NEUTRAL_HIGH', 'NEUTRAL_LOW', 'OS_APPROACH', 'OS_DEEP']
    }
    result = {}
    for zone in zones_order[direction]:
        s = cci_data[direction].get(zone, {})
        n = total_resolved(s)
        wr = win_rate(s)
        # Mappa win rate → score (calibrato: 80% WR → 100, 50% WR → 50, 20% → 0)
        suggested_score = max(0, min(100, round((wr - 20) / 60 * 100))) if n >= MIN_TRADES else None
        result[zone] = {
            'n': n, 'tp': s.get('tp', 0), 'sl': s.get('sl', 0),
            'win_rate': round(wr, 1), 'suggested_score': suggested_score
        }
    return result

# ─── BEST COMBOS ─────────────────────────────────────────────────────────────
def find_best_combos(combo_data, direction, top_n=20):
    """Trova le N migliori combinazioni CCI×MACD×ADX."""
    entries = []
    for key, s in combo_data[direction].items():
        n = total_resolved(s)
        if n < MIN_TRADES:
            continue
        wr = win_rate(s)
        bars = s.get('bars', [])
        avg_bars = sum(bars) / len(bars) if bars else 0
        parts = key.split('|')
        entries.append({
            'cci_zone': parts[0],
            'macd_zone': parts[1],
            'adx_zone': parts[2],
            'n': n, 'tp': s.get('tp', 0), 'sl': s.get('sl', 0),
            'win_rate': round(wr, 1),
            'avg_bars': round(avg_bars, 1),
            'profit_factor': round(s.get('tp', 0) * 1.5 / max(s.get('sl', 1), 1), 2)
        })
    entries.sort(key=lambda x: (x['win_rate'], x['n']), reverse=True)
    return entries[:top_n]

# ─── STAMPA RISULTATI ─────────────────────────────────────────────────────────
def print_section(title):
    w = 70
    print(f"\n{'═' * w}")
    print(f"  {title}")
    print(f"{'═' * w}")

def print_zone_table(title, data, direction):
    print(f"\n  ── {title} ({direction.upper()}) ──")
    print(f"  {'Zona':<22} {'N':>6} {'TP':>6} {'SL':>6} {'WR%':>7} {'Score':>7}")
    print(f"  {'-'*55}")
    for zone, v in data.items():
        sc = str(v['suggested_score']) if v['suggested_score'] is not None else 'N/D'
        print(f"  {zone:<22} {v['n']:>6} {v['tp']:>6} {v['sl']:>6} {v['win_rate']:>6.1f}% {sc:>7}")

def print_best_combos(combos, direction):
    print(f"\n  ── TOP COMBINAZIONI CCI×MACD×ADX ({direction.upper()}) ──")
    print(f"  {'#':<3} {'CCI':<16} {'MACD':<18} {'ADX (trunc)':<22} {'N':>5} {'WR%':>6} {'AvgBars':>8}")
    print(f"  {'-'*80}")
    for idx, c in enumerate(combos[:15], 1):
        adx_short = c['adx_zone'][:20]
        print(f"  {idx:<3} {c['cci_zone']:<16} {c['macd_zone']:<18} {adx_short:<22} "
              f"{c['n']:>5} {c['win_rate']:>5.1f}% {c['avg_bars']:>7.1f}h")

def print_weight_opts(opts, name):
    print(f"\n  ── PESI OTTIMALI {name} (top 5) ──")
    print(f"  {'CCI%':>6} {'MACD%':>6} {'ADX%':>6} {'Trades':>7} {'WR%':>6} {'P&L':>8} {'Metric':>8}")
    print(f"  {'-'*55}")
    for r in opts[:5]:
        print(f"  {r['wc']:>6} {r['wm']:>6} {r['wa']:>6} {r['trades']:>7} "
              f"{r['wr']:>5.1f}% {r['pnl']:>7.1f} {r['metric']:>8.1f}")

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  MFKK Entry Condition Optimizer - 2 anni XAU + XAG H1          ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"  Parametri: {DAYS} giorni, FORWARD {FORWARD_BARS}h, MIN_TRADES {MIN_TRADES}")
    print(f"  XAU: TP=${TP_USD_XAU} SL=${SL_USD_XAU}  |  XAG: TP=${TP_USD_XAG} SL=${SL_USD_XAG}")

    all_report = {}

    for asset in ASSETS:
        print_section(f"ANALISI {asset['name']}")
        candles = fetch_candles(asset['symbol'], DAYS)
        if len(candles) < 500:
            print(f"  ⚠ Dati insufficienti ({len(candles)} candele), skip.")
            continue

        stats = analyze_asset(asset, candles)

        # Calibrazione soglie CCI
        print_section(f"CALIBRAZIONE SOGLIE CCI — {asset['name']}")
        cci_buy  = calibrate_cci_thresholds(stats['cci'], 'buy')
        cci_sell = calibrate_cci_thresholds(stats['cci'], 'sell')
        print_zone_table('CCI_S', cci_buy, 'buy')
        print_zone_table('CCI_S', cci_sell, 'sell')

        # Top combo
        print_section(f"TOP COMBINAZIONI ENTRY — {asset['name']}")
        buy_combos  = find_best_combos(stats['combo'], 'buy')
        sell_combos = find_best_combos(stats['combo'], 'sell')
        print_best_combos(buy_combos,  'buy')
        print_best_combos(sell_combos, 'sell')

        # Ottimizzazione pesi
        print_section(f"OTTIMIZZAZIONE PESI — {asset['name']}")
        inds = calc_indicators(candles)
        weight_opts = optimize_weights(candles, inds, asset['tp'], asset['sl'])
        print_weight_opts(weight_opts, asset['name'])
        current_wc, current_wm, current_wa = 35, 35, 30
        current = next((r for r in weight_opts
                        if r['wc'] == current_wc and r['wm'] == current_wm and r['wa'] == current_wa), None)
        if current:
            print(f"\n  BASELINE ATTUALE (CCI35 MACD35 ADX30): "
                  f"Trades={current['trades']}, WR={current['wr']}%, P&L={current['pnl']}")

        all_report[asset['name']] = {
            'cci_calibration': {'buy': cci_buy, 'sell': cci_sell},
            'best_buy_combos': buy_combos,
            'best_sell_combos': sell_combos,
            'optimal_weights': weight_opts,
        }

    # Salva report JSON
    out_path = 'entry_analysis_report.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(all_report, f, indent=2, ensure_ascii=False)

    print_section("RIEPILOGO FINALE")
    for asset_name, rep in all_report.items():
        best_w = rep['optimal_weights'][0] if rep['optimal_weights'] else None
        if best_w:
            print(f"  {asset_name}: pesi ottimali CCI={best_w['wc']}% MACD={best_w['wm']}% ADX={best_w['wa']}%"
                  f"  (WR={best_w['wr']}%, P&L=${best_w['pnl']})")
        bbc = rep['best_buy_combos'][:3]
        if bbc:
            print(f"    Top BUY combos: " + " | ".join(
                f"{c['cci_zone']}+{c['macd_zone'][:8]} WR={c['win_rate']}%" for c in bbc))
        bsc = rep['best_sell_combos'][:3]
        if bsc:
            print(f"    Top SELL combos: " + " | ".join(
                f"{c['cci_zone']}+{c['macd_zone'][:8]} WR={c['win_rate']}%" for c in bsc))

    print(f"\n  📁 Report completo: {out_path}")
    print("  ✅ Analisi completata!\n")

if __name__ == '__main__':
    main()
