"""
Scalping Strategy Hunt — XAU/USD M5
Testa 6 strategie scalp su ~100k candele M5 (~2 anni)
Capitale iniziale: $1000, risk 1% per trade, spread $0.40
"""

import json, math
from datetime import datetime, timezone

# ─── Config ────────────────────────────────────────────────────────────────────
DATA_FILE   = "data/xauusd_m5_mt5.json"
CAPITAL_0   = 1000.0      # USD
RISK_PCT    = 0.01        # 1% per trade
SPREAD      = 0.40        # USD/oz round-trip spread equivalente
MIN_BARS    = 100         # warm-up indicatori
SESSION_UTC = (7, 19)     # solo ora 07-19 UTC (London+NY)
MAX_HOLD    = 60          # barre massime prima di forzare chiusura (~5h)

# ─── Helpers indicatori ────────────────────────────────────────────────────────

def ema(arr, n):
    out = [None] * len(arr)
    k = 2 / (n + 1)
    for i, v in enumerate(arr):
        if v is None:
            continue
        if out[i-1] is None:
            out[i] = v
        else:
            out[i] = v * k + out[i-1] * (1 - k)
    return out

def sma(arr, n):
    out = [None] * len(arr)
    for i in range(n-1, len(arr)):
        window = [x for x in arr[i-n+1:i+1] if x is not None]
        if len(window) == n:
            out[i] = sum(window) / n
    return out

def rsi(closes, n=14):
    out = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    for i in range(n, len(closes)):
        ag = sum(gains[i-n:i]) / n
        al = sum(losses[i-n:i]) / n
        if al == 0:
            out[i] = 100.0
        else:
            out[i] = 100 - 100 / (1 + ag / al)
    return out

def macd(closes, fast=12, slow=26, sig=9):
    ef = ema(closes, fast)
    es = ema(closes, slow)
    ml = [ef[i] - es[i] if ef[i] and es[i] else None for i in range(len(closes))]
    sl = ema(ml, sig)
    hist = [ml[i] - sl[i] if ml[i] and sl[i] else None for i in range(len(closes))]
    return ml, sl, hist

def bollinger(closes, n=20, mult=2.0):
    mid = sma(closes, n)
    upper, lower = [None]*len(closes), [None]*len(closes)
    for i in range(n-1, len(closes)):
        s = math.sqrt(sum((closes[i-n+1+j] - mid[i])**2 for j in range(n)) / n)
        upper[i] = mid[i] + mult * s
        lower[i] = mid[i] - mult * s
    return upper, mid, lower

def stoch(highs, lows, closes, k=5, d=3):
    raw_k = [None]*len(closes)
    for i in range(k-1, len(closes)):
        lo = min(lows[i-k+1:i+1])
        hi = max(highs[i-k+1:i+1])
        raw_k[i] = 100*(closes[i]-lo)/(hi-lo) if hi != lo else 50.0
    smooth_k = sma(raw_k, d)
    smooth_d = sma(smooth_k, d)
    return smooth_k, smooth_d

def adx(highs, lows, closes, n=14):
    tr_arr, pdm, ndm = [], [], []
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i-1])
        lpc = abs(lows[i] - closes[i-1])
        tr_arr.append(max(hl, hpc, lpc))
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        pdm.append(up if up > dn and up > 0 else 0)
        ndm.append(dn if dn > up and dn > 0 else 0)

    def wilder(arr):
        out = [None]*len(arr)
        out[n-1] = sum(arr[:n])
        for i in range(n, len(arr)):
            out[i] = out[i-1] - out[i-1]/n + arr[i]
        return out

    atr_w = wilder(tr_arr)
    pdm_w = wilder(pdm)
    ndm_w = wilder(ndm)

    adx_out = [None]*(len(closes))
    dx_arr = []
    for i in range(n-1, len(tr_arr)):
        pdi = 100*pdm_w[i]/atr_w[i] if atr_w[i] else 0
        ndi = 100*ndm_w[i]/atr_w[i] if atr_w[i] else 0
        dx = 100*abs(pdi-ndi)/(pdi+ndi) if (pdi+ndi) else 0
        dx_arr.append(dx)

    adx_smooth = [None]*(len(closes))
    if len(dx_arr) >= n:
        adx_smooth[2*n-1] = sum(dx_arr[:n])/n
        for i in range(1, len(dx_arr)-n+1):
            prev = adx_smooth[2*n-2+i]
            if prev:
                adx_smooth[2*n-1+i] = (prev*(n-1) + dx_arr[n-1+i])/n

    return adx_smooth

def atr(highs, lows, closes, n=14):
    tr_arr = []
    for i in range(1, len(closes)):
        tr_arr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    atr_out = [None]*len(closes)
    if len(tr_arr) >= n:
        atr_out[n] = sum(tr_arr[:n])/n
        for i in range(1, len(tr_arr)-n+1):
            atr_out[n+i] = (atr_out[n+i-1]*(n-1) + tr_arr[n-1+i])/n
    return atr_out

# ─── Engine backtest ────────────────────────────────────────────────────────────

def run_backtest(candles, signals_fn, name, tp_pts, sl_pts):
    """
    signals_fn(i, indicators) → 'BUY' | 'SELL' | None
    Ritorna dizionario con metriche.
    """
    n = len(candles)
    times  = [c['t'] for c in candles]
    opens  = [c['o'] for c in candles]
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    closes = [c['c'] for c in candles]
    vols   = [c['v'] for c in candles]

    # Pre-computa indicatori
    ema5   = ema(closes, 5)
    ema13  = ema(closes, 13)
    ema21  = ema(closes, 21)
    ema50  = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi7   = rsi(closes, 7)
    rsi14  = rsi(closes, 14)
    ml, sl_line, hist = macd(closes)
    bup, bmid, blow   = bollinger(closes, 20, 2.0)
    sk, sd            = stoch(highs, lows, closes, 5, 3)
    adx_v             = adx(highs, lows, closes, 14)
    atr_v             = atr(highs, lows, closes, 14)

    indic = dict(
        ema5=ema5, ema13=ema13, ema21=ema21, ema50=ema50, ema200=ema200,
        rsi7=rsi7, rsi14=rsi14,
        macd=ml, macd_sig=sl_line, macd_hist=hist,
        bup=bup, bmid=bmid, blow=blow,
        stoch_k=sk, stoch_d=sd,
        adx=adx_v, atr=atr_v,
        opens=opens, highs=highs, lows=lows, closes=closes, vols=vols,
    )

    capital = CAPITAL_0
    equity_curve = [capital]
    trades = []
    position = None   # dict: {dir, entry, sl, tp, open_bar, lots}
    max_eq = capital
    max_dd = 0.0

    for i in range(MIN_BARS, n):
        ts = times[i]
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        in_session = SESSION_UTC[0] <= hour < SESSION_UTC[1]

        # Gestisci posizione aperta
        if position:
            h_bar = highs[i]
            l_bar = lows[i]
            cl = closes[i]
            bars_open = i - position['open_bar']
            pnl = None

            if position['dir'] == 'BUY':
                if l_bar <= position['sl']:
                    pnl = (position['sl'] - position['entry'] - SPREAD) * position['lots']
                elif h_bar >= position['tp']:
                    pnl = (position['tp'] - position['entry'] - SPREAD) * position['lots']
                elif bars_open >= MAX_HOLD:
                    pnl = (cl - position['entry'] - SPREAD) * position['lots']
            else:  # SELL
                if h_bar >= position['sl']:
                    pnl = (position['entry'] - position['sl'] - SPREAD) * position['lots']
                elif l_bar <= position['tp']:
                    pnl = (position['entry'] - position['tp'] - SPREAD) * position['lots']
                elif bars_open >= MAX_HOLD:
                    pnl = (position['entry'] - cl - SPREAD) * position['lots']

            if pnl is not None:
                capital += pnl
                trades.append({
                    'entry_bar': position['open_bar'],
                    'exit_bar': i,
                    'dir': position['dir'],
                    'entry': position['entry'],
                    'pnl': pnl,
                    'win': pnl > 0,
                })
                position = None
                equity_curve.append(capital)
                max_eq = max(max_eq, capital)
                dd = (max_eq - capital) / max_eq * 100
                max_dd = max(max_dd, dd)

        # Apri nuova posizione se in sessione e nessuna aperta
        if not position and in_session:
            sig = signals_fn(i, indic)
            if sig:
                entry = closes[i]
                risk_amt = capital * RISK_PCT
                lots = risk_amt / sl_pts  # oz (0.01 lot MT5 = 1 oz)
                lots = max(0.01, round(lots, 2))
                if sig == 'BUY':
                    position = dict(
                        dir='BUY', entry=entry,
                        sl=entry - sl_pts, tp=entry + tp_pts,
                        open_bar=i, lots=lots
                    )
                elif sig == 'SELL':
                    position = dict(
                        dir='SELL', entry=entry,
                        sl=entry + sl_pts, tp=entry - tp_pts,
                        open_bar=i, lots=lots
                    )

    # Chiudi posizione aperta
    if position:
        cl = closes[-1]
        pnl = (cl - position['entry'] - SPREAD) * position['lots'] if position['dir'] == 'BUY' \
              else (position['entry'] - cl - SPREAD) * position['lots']
        capital += pnl
        trades.append({'pnl': pnl, 'win': pnl > 0, 'dir': position['dir'], 'entry': position['entry'], 'exit_bar': n-1, 'entry_bar': position['open_bar']})

    # Metriche
    total = len(trades)
    wins  = [t for t in trades if t['win']]
    loss  = [t for t in trades if not t['win']]
    gross_win  = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in loss))
    pf  = gross_win / gross_loss if gross_loss > 0 else float('inf')
    wr  = len(wins)/total*100 if total > 0 else 0
    net = capital - CAPITAL_0

    avg_win  = gross_win/len(wins) if wins else 0
    avg_loss = gross_loss/len(loss) if loss else 0
    expectancy = (wr/100 * avg_win) - ((1-wr/100) * avg_loss)

    return {
        'name': name,
        'total_trades': total,
        'win_rate': wr,
        'profit_factor': pf,
        'net_pnl': net,
        'final_capital': capital,
        'max_drawdown': max_dd,
        'expectancy': expectancy,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'gross_win': gross_win,
        'gross_loss': gross_loss,
        'return_pct': net / CAPITAL_0 * 100,
    }

# ─── Definizione strategie ──────────────────────────────────────────────────────

def sig_ema_cross_rsi(i, d):
    """EMA 5/21 crossover + RSI 40-60 + EMA200 trend filter"""
    e5, e21, e200 = d['ema5'], d['ema21'], d['ema200']
    r14 = d['rsi14']
    if not all([e5[i], e5[i-1], e21[i], e21[i-1], e200[i], r14[i]]):
        return None
    cross_up   = e5[i] > e21[i] and e5[i-1] <= e21[i-1]
    cross_down = e5[i] < e21[i] and e5[i-1] >= e21[i-1]
    trend_up   = d['closes'][i] > e200[i]
    trend_dn   = d['closes'][i] < e200[i]
    if cross_up   and trend_up  and 42 < r14[i] < 65:  return 'BUY'
    if cross_down and trend_dn  and 35 < r14[i] < 58:  return 'SELL'
    return None

def sig_rsi_bounce(i, d):
    """RSI7 estremo + EMA21 direzione + ADX > 18"""
    r7, e21, adx_v = d['rsi7'], d['ema21'], d['adx']
    cl = d['closes']
    if not all(x for x in [r7[i], r7[i-1], e21[i], adx_v[i]]):
        return None
    strong = adx_v[i] > 18
    # RSI risale da sotto 28 → BUY
    if r7[i-1] < 28 and r7[i] > r7[i-1] and cl[i] > e21[i] and strong:  return 'BUY'
    # RSI scende da sopra 72 → SELL
    if r7[i-1] > 72 and r7[i] < r7[i-1] and cl[i] < e21[i] and strong:  return 'SELL'
    return None

def sig_bb_reversion(i, d):
    """Bollinger Band toccata + RSI recupero + EMA50 direzione"""
    bup, bmid, blow = d['bup'], d['bmid'], d['blow']
    r14 = d['rsi14']
    cl, lo, hi = d['closes'], d['lows'], d['highs']
    e50 = d['ema50']
    if not all(x for x in [bup[i], blow[i], r14[i], e50[i]]):
        return None
    # Tocca lower band + RSI risale da <35
    if hi[i-1] <= blow[i-1] and cl[i] > blow[i] and r14[i-1] < 35 and r14[i] > r14[i-1]:
        return 'BUY'
    # Tocca upper band + RSI scende da >65
    if lo[i-1] >= bup[i-1] and cl[i] < bup[i] and r14[i-1] > 65 and r14[i] < r14[i-1]:
        return 'SELL'
    return None

def sig_macd_ema(i, d):
    """MACD histogram inversione + EMA50 trend + ADX > 20"""
    hist  = d['macd_hist']
    e50   = d['ema50']
    adx_v = d['adx']
    cl    = d['closes']
    if not all(x for x in [hist[i], hist[i-1], hist[i-2], e50[i], adx_v[i]]):
        return None
    trending = adx_v[i] > 20
    # Histogram gira da negativo a positivo (2 barre consecutive salenti)
    if hist[i-2] < hist[i-1] < hist[i] and hist[i-1] < 0 and cl[i] > e50[i] and trending:
        return 'BUY'
    if hist[i-2] > hist[i-1] > hist[i] and hist[i-1] > 0 and cl[i] < e50[i] and trending:
        return 'SELL'
    return None

def sig_stoch_ema(i, d):
    """Stochastic 5,3,3 crossover in direzione EMA13/50 + RSI non estremo"""
    sk, sdd = d['stoch_k'], d['stoch_d']
    e13, e50 = d['ema13'], d['ema50']
    r14 = d['rsi14']
    cl = d['closes']
    if not all(x for x in [sk[i], sdd[i], sk[i-1], sdd[i-1], e13[i], e50[i], r14[i]]):
        return None
    trend_up = e13[i] > e50[i]
    trend_dn = e13[i] < e50[i]
    k_cross_up   = sk[i] > sdd[i] and sk[i-1] <= sdd[i-1] and sk[i] < 55
    k_cross_down = sk[i] < sdd[i] and sk[i-1] >= sdd[i-1] and sk[i] > 45
    if k_cross_up   and trend_up and r14[i] < 65: return 'BUY'
    if k_cross_down and trend_dn and r14[i] > 35: return 'SELL'
    return None

def sig_atr_momentum(i, d):
    """
    ATR Momentum Breakout:
    Prezzo rompe il max/min delle ultime 8 barre + ATR in espansione
    + EMA200 trend + RSI 45-65 zona momentum
    """
    cl, hi, lo = d['closes'], d['highs'], d['lows']
    atr_v = d['atr']
    e200  = d['ema200']
    r14   = d['rsi14']
    if not all(x for x in [atr_v[i], atr_v[i-1], e200[i], r14[i]]):
        return None
    lookback = 8
    if i < lookback + 2:
        return None
    recent_hi = max(hi[i-lookback:i])
    recent_lo = min(lo[i-lookback:i])
    atr_expand = atr_v[i] > atr_v[i-1] * 1.05   # ATR cresce
    trend_up   = cl[i] > e200[i]
    trend_dn   = cl[i] < e200[i]
    if cl[i] > recent_hi and atr_expand and trend_up and 45 < r14[i] < 68:
        return 'BUY'
    if cl[i] < recent_lo and atr_expand and trend_dn and 32 < r14[i] < 55:
        return 'SELL'
    return None

# ─── Strategia composita (miglior combo trovata) ───────────────────────────────

def sig_composite_best(i, d):
    """
    Confluenza: almeno 2/3 segnali concordi tra
    (1) EMA cross, (2) Stoch cross, (3) RSI momentum
    + EMA200 macro trend + ADX > 20
    """
    e5, e13, e21, e50, e200 = d['ema5'], d['ema13'], d['ema21'], d['ema50'], d['ema200']
    r14   = d['rsi14']
    sk, sdd  = d['stoch_k'], d['stoch_d']
    adx_v = d['adx']
    atr_v = d['atr']
    cl    = d['closes']

    if not all(x for x in [e5[i], e13[i], e21[i], e50[i], e200[i],
                             r14[i], sk[i], sdd[i], adx_v[i], atr_v[i],
                             e5[i-1], e13[i-1], sk[i-1], sdd[i-1]]):
        return None

    if adx_v[i] < 20:
        return None

    trend_up = cl[i] > e200[i] and e50[i] > e200[i]
    trend_dn = cl[i] < e200[i] and e50[i] < e200[i]

    score_buy  = 0
    score_sell = 0

    # Segnale 1: EMA5/EMA13 cross
    if e5[i] > e13[i] and e5[i-1] <= e13[i-1]:  score_buy  += 1
    if e5[i] < e13[i] and e5[i-1] >= e13[i-1]:  score_sell += 1

    # Segnale 2: Stochastic cross in zona favorevole
    if sk[i] > sdd[i] and sk[i-1] <= sdd[i-1] and sk[i] < 60: score_buy  += 1
    if sk[i] < sdd[i] and sk[i-1] >= sdd[i-1] and sk[i] > 40: score_sell += 1

    # Segnale 3: RSI momentum
    if 48 < r14[i] < 68 and r14[i] > r14[i-1]: score_buy  += 1
    if 32 < r14[i] < 52 and r14[i] < r14[i-1]: score_sell += 1

    if score_buy >= 2 and trend_up:   return 'BUY'
    if score_sell >= 2 and trend_dn:  return 'SELL'
    return None

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  SCALPING STRATEGY HUNT — XAU/USD M5")
    print(f"  Capitale: ${CAPITAL_0:,.0f} | Risk/trade: {RISK_PCT*100:.0f}% | Spread: ${SPREAD}")
    print("=" * 70)

    with open(DATA_FILE) as f:
        raw = json.load(f)
    candles = raw['candles']
    first_ts = datetime.fromtimestamp(candles[MIN_BARS]['t'], tz=timezone.utc).strftime('%Y-%m-%d')
    last_ts  = datetime.fromtimestamp(candles[-1]['t'], tz=timezone.utc).strftime('%Y-%m-%d')
    print(f"\n  Barre: {len(candles):,} ({first_ts} → {last_ts})\n")

    # Configurazione strategie (name, fn, TP, SL in punti XAU)
    strategies = [
        ("S1: EMA5/21 Cross + RSI + EMA200",   sig_ema_cross_rsi,   4.0, 2.0),
        ("S2: RSI7 Bounce + EMA21 + ADX",       sig_rsi_bounce,      3.0, 1.5),
        ("S3: Bollinger Reversion",              sig_bb_reversion,    3.5, 2.0),
        ("S4: MACD Hist Turn + EMA50",           sig_macd_ema,        5.0, 2.5),
        ("S5: Stochastic 5,3,3 + EMA13/50",     sig_stoch_ema,       3.5, 2.0),
        ("S6: ATR Momentum Breakout + EMA200",   sig_atr_momentum,    5.0, 2.5),
        ("S7: Composite Score (≥2/3 confluence)",sig_composite_best,  4.0, 2.0),
    ]

    results = []
    for name, fn, tp, sl in strategies:
        r = run_backtest(candles, fn, name, tp, sl)
        results.append(r)

    # Sort per Profit Factor
    results.sort(key=lambda x: x['profit_factor'] if x['profit_factor'] != float('inf') else 0, reverse=True)

    # Print tabella
    print(f"{'Strategia':<44} {'#Trd':>5} {'WR%':>6} {'PF':>6} {'NetP&L':>9} {'Ret%':>7} {'MaxDD%':>7} {'Expect':>8}")
    print("-" * 100)
    for r in results:
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else " ∞"
        print(f"{r['name']:<44} {r['total_trades']:>5} {r['win_rate']:>5.1f}% {pf_str:>6} "
              f"${r['net_pnl']:>8.2f} {r['return_pct']:>6.1f}% {r['max_drawdown']:>6.1f}% "
              f"${r['expectancy']:>7.3f}")

    # Dettaglio miglior strategia
    best = max(results, key=lambda x: (
        (x['profit_factor'] if x['profit_factor'] != float('inf') else 0) * 0.35 +
        x['win_rate'] * 0.25 +
        x['return_pct'] * 0.25 +
        (-x['max_drawdown']) * 0.15
    ))

    print("\n" + "=" * 70)
    print(f"  MIGLIOR STRATEGIA: {best['name']}")
    print("=" * 70)
    print(f"  Trades totali:      {best['total_trades']}")
    print(f"  Win Rate:           {best['win_rate']:.1f}%")
    print(f"  Profit Factor:      {best['profit_factor']:.3f}")
    print(f"  Net P&L:            ${best['net_pnl']:+.2f}")
    print(f"  Capitale finale:    ${best['final_capital']:,.2f}")
    print(f"  Rendimento:         {best['return_pct']:+.1f}%")
    print(f"  Max Drawdown:       {best['max_drawdown']:.1f}%")
    print(f"  Avg Win:            ${best['avg_win']:.3f}/trade")
    print(f"  Avg Loss:           ${best['avg_loss']:.3f}/trade")
    print(f"  Expectancy:         ${best['expectancy']:.4f}/trade")
    print(f"  Gross Win:          ${best['gross_win']:.2f}")
    print(f"  Gross Loss:         ${best['gross_loss']:.2f}")

    # Analisi mensile miglior strategia
    print(f"\n  --- P&L mensile (stima annualizzata) ---")
    months_approx = (candles[-1]['t'] - candles[MIN_BARS]['t']) / (30.5 * 86400)
    tpd = best['total_trades'] / (months_approx * 22)  # trading days
    print(f"  Trades/giorno (stima): {tpd:.1f}")
    print(f"  P&L medio/mese:        ${best['net_pnl']/months_approx:+.2f}")
    print(f"  P&L medio/giorno:      ${best['net_pnl']/(months_approx*22):+.2f}")

    print("\n  NOTA: Spread $0.40 incluso | Risk 1%/trade | Long+Short | 07-19 UTC")
    print("=" * 70)

    # Salva JSON risultati
    out = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {"capital": CAPITAL_0, "risk_pct": RISK_PCT, "spread": SPREAD, "session": SESSION_UTC},
        "results": results,
        "best": best
    }
    with open("backtests/results/bt_scalp_hunt.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\n  Risultati salvati in backtests/results/bt_scalp_hunt.json")

if __name__ == "__main__":
    main()
