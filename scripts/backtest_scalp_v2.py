"""
Scalping Strategy Hunt v2 — XAU/USD M5
Strategie ottimizzate per il contesto bull run 2024-2026
Bias long, pullback su EMA, VWAP, ATR-based TP/SL
Capitale: $1000, risk 1%/trade, spread $0.40
"""

import json, math
from datetime import datetime, timezone

DATA_FILE  = "data/xauusd_m5_mt5.json"
CAPITAL_0  = 1000.0
RISK_PCT   = 0.01
SPREAD     = 0.40
MIN_BARS   = 250
MAX_HOLD   = 48        # ~4h massimo per M5
ATR_PERIOD = 14

# ─── Indicatori ────────────────────────────────────────────────────────────────

def ema(arr, n):
    out = [None] * len(arr)
    k = 2 / (n + 1)
    started = False
    for i, v in enumerate(arr):
        if v is None:
            continue
        if not started:
            out[i] = v
            started = True
        else:
            prev = next((out[j] for j in range(i-1, -1, -1) if out[j] is not None), None)
            out[i] = v * k + prev * (1 - k) if prev else v
    return out

def sma(arr, n):
    out = [None] * len(arr)
    for i in range(n-1, len(arr)):
        w = [x for x in arr[i-n+1:i+1] if x is not None]
        if len(w) == n:
            out[i] = sum(w) / n
    return out

def rsi(closes, n=14):
    out = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    for i in range(n, len(closes)):
        ag = sum(gains[i-n:i]) / n
        al = sum(losses[i-n:i]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def stoch(highs, lows, closes, k=5, d=3, smooth=3):
    raw_k = [None] * len(closes)
    for i in range(k-1, len(closes)):
        lo = min(lows[i-k+1:i+1])
        hi = max(highs[i-k+1:i+1])
        raw_k[i] = 100.0 * (closes[i] - lo) / (hi - lo) if hi != lo else 50.0
    sk = sma(raw_k, smooth)
    sd = sma(sk, d)
    return sk, sd

def atr_series(highs, lows, closes, n=14):
    out = [None] * len(closes)
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    if len(trs) < n:
        return out
    val = sum(trs[:n]) / n
    out[n] = val
    for i in range(1, len(trs) - n + 1):
        val = (val * (n-1) + trs[n-1+i]) / n
        out[n+i] = val
    return out

def rolling_vwap(candles, n=78):
    """VWAP rolling su n barre (~6.5h su M5)"""
    out = [None] * len(candles)
    for i in range(n-1, len(candles)):
        pv_sum = sum(((c['h']+c['l']+c['c'])/3) * c['v'] for c in candles[i-n+1:i+1])
        v_sum  = sum(c['v'] for c in candles[i-n+1:i+1])
        out[i] = pv_sum / v_sum if v_sum > 0 else None
    return out

def adx_series(highs, lows, closes, n=14):
    out = [None] * len(closes)
    trs, pdms, ndms = [], [], []
    for i in range(1, len(closes)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        pdms.append(up if up > dn and up > 0 else 0)
        ndms.append(dn if dn > up and dn > 0 else 0)
    def wilder(arr):
        r = [None] * len(arr)
        r[n-1] = sum(arr[:n])
        for i in range(n, len(arr)):
            r[i] = r[i-1] - r[i-1]/n + arr[i]
        return r
    atr_w = wilder(trs); pdm_w = wilder(pdms); ndm_w = wilder(ndms)
    dx_list = []
    for i in range(n-1, len(trs)):
        pdi = 100*pdm_w[i]/atr_w[i] if atr_w[i] else 0
        ndi = 100*ndm_w[i]/atr_w[i] if atr_w[i] else 0
        dx_list.append(100*abs(pdi-ndi)/(pdi+ndi) if pdi+ndi else 0)
    if len(dx_list) >= n:
        v = sum(dx_list[:n]) / n
        out[2*n-1] = v
        for i in range(1, len(dx_list)-n+1):
            v = (v*(n-1) + dx_list[n-1+i]) / n
            out[2*n+i-1] = v
    return out

def macd(closes, fast=12, slow=26, sig=9):
    ef = ema(closes, fast)
    es = ema(closes, slow)
    ml = [ef[i] - es[i] if ef[i] and es[i] else None for i in range(len(closes))]
    sl = ema(ml, sig)
    hist = [ml[i] - sl[i] if ml[i] and sl[i] else None for i in range(len(closes))]
    return ml, sl, hist

# ─── Engine ────────────────────────────────────────────────────────────────────

def run_bt(candles, sig_fn, name, atr_tp_mult, atr_sl_mult, session=(7, 19),
           bias='both', min_atr=None, max_atr=None):
    n = len(candles)
    times  = [c['t'] for c in candles]
    opens  = [c['o'] for c in candles]
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    closes = [c['c'] for c in candles]
    vols   = [c['v'] for c in candles]

    e8   = ema(closes, 8)
    e13  = ema(closes, 13)
    e21  = ema(closes, 21)
    e50  = ema(closes, 50)
    e200 = ema(closes, 200)
    r7   = rsi(closes, 7)
    r14  = rsi(closes, 14)
    sk, sd = stoch(highs, lows, closes, 5, 3, 3)
    atr_v  = atr_series(highs, lows, closes, ATR_PERIOD)
    vwap   = rolling_vwap(candles, 78)
    adx_v  = adx_series(highs, lows, closes, 14)
    ml, sl_line, hist = macd(closes)

    indic = dict(
        e8=e8, e13=e13, e21=e21, e50=e50, e200=e200,
        r7=r7, r14=r14, sk=sk, sd=sd,
        atr=atr_v, vwap=vwap, adx=adx_v,
        macd=ml, macd_sig=sl_line, macd_hist=hist,
        opens=opens, highs=highs, lows=lows, closes=closes, vols=vols,
    )

    capital = CAPITAL_0
    trades  = []
    pos     = None
    max_eq  = capital
    max_dd  = 0.0
    wins_streak = 0
    loss_streak = 0
    cur_win  = 0
    cur_loss = 0

    for i in range(MIN_BARS, n):
        ts   = times[i]
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        in_sess = session[0] <= hour < session[1]

        # Chiudi posizione aperta
        if pos:
            h, l, cl = highs[i], lows[i], closes[i]
            bars_open = i - pos['open_bar']
            pnl = None
            exit_reason = None

            if pos['dir'] == 'BUY':
                if l <= pos['sl']:
                    pnl = (pos['sl'] - pos['entry'] - SPREAD) * pos['lots']
                    exit_reason = 'SL'
                elif h >= pos['tp']:
                    pnl = (pos['tp'] - pos['entry'] - SPREAD) * pos['lots']
                    exit_reason = 'TP'
                elif bars_open >= MAX_HOLD:
                    pnl = (cl - pos['entry'] - SPREAD) * pos['lots']
                    exit_reason = 'TIME'
            else:
                if h >= pos['sl']:
                    pnl = (pos['entry'] - pos['sl'] - SPREAD) * pos['lots']
                    exit_reason = 'SL'
                elif l <= pos['tp']:
                    pnl = (pos['entry'] - pos['tp'] - SPREAD) * pos['lots']
                    exit_reason = 'TP'
                elif bars_open >= MAX_HOLD:
                    pnl = (pos['entry'] - cl - SPREAD) * pos['lots']
                    exit_reason = 'TIME'

            if pnl is not None:
                capital += pnl
                w = pnl > 0
                trades.append({'pnl': pnl, 'win': w, 'exit': exit_reason,
                                'dir': pos['dir'], 'entry': pos['entry']})
                pos = None
                max_eq = max(max_eq, capital)
                dd = (max_eq - capital) / max_eq * 100
                max_dd = max(max_dd, dd)

        # Apri nuova posizione
        if not pos and in_sess:
            a = atr_v[i]
            if a is None or a == 0:
                continue
            if min_atr and a < min_atr:
                continue
            if max_atr and a > max_atr:
                continue

            sig = sig_fn(i, indic)
            if not sig:
                continue
            if bias == 'long' and sig != 'BUY':
                continue
            if bias == 'short' and sig != 'SELL':
                continue

            entry = closes[i]
            tp_pts = a * atr_tp_mult
            sl_pts = a * atr_sl_mult
            risk_amt = capital * RISK_PCT
            lots = max(0.01, round(risk_amt / (sl_pts if sl_pts > 0 else 1), 2))
            if sig == 'BUY':
                pos = dict(dir='BUY', entry=entry,
                           tp=entry+tp_pts, sl=entry-sl_pts,
                           open_bar=i, lots=lots)
            else:
                pos = dict(dir='SELL', entry=entry,
                           tp=entry-tp_pts, sl=entry+sl_pts,
                           open_bar=i, lots=lots)

    if pos:
        cl = closes[-1]
        pnl = (cl - pos['entry'] - SPREAD)*pos['lots'] if pos['dir'] == 'BUY' \
              else (pos['entry'] - cl - SPREAD)*pos['lots']
        capital += pnl
        trades.append({'pnl': pnl, 'win': pnl > 0, 'exit': 'END', 'dir': pos['dir'], 'entry': pos['entry']})

    total     = len(trades)
    wins_list = [t for t in trades if t['win']]
    loss_list = [t for t in trades if not t['win']]
    gw   = sum(t['pnl'] for t in wins_list)
    gl   = abs(sum(t['pnl'] for t in loss_list))
    pf   = gw / gl if gl > 0 else 999.0
    wr   = len(wins_list)/total*100 if total else 0
    net  = capital - CAPITAL_0
    aw   = gw/len(wins_list) if wins_list else 0
    al   = gl/len(loss_list) if loss_list else 0
    exp  = (wr/100*aw) - ((1-wr/100)*al)

    # Trades per giorno
    if total > 1:
        day_span = (times[-1] - times[MIN_BARS]) / 86400
        tpd = total / day_span * 5/7  # solo giorni trading
    else:
        tpd = 0

    return dict(
        name=name, total=total, wr=wr, pf=pf, net=net,
        cap=capital, dd=max_dd, exp=exp, aw=aw, al=al,
        ret=net/CAPITAL_0*100, tpd=tpd,
        gross_win=gw, gross_loss=gl
    )

# ─── Segnali v2 ────────────────────────────────────────────────────────────────

def sig_pullback_ema21(i, d):
    """Pullback verso EMA21 in uptrend EMA50/200 + RSI risale da 35-50"""
    e21, e50, e200, r14, cl = d['e21'], d['e50'], d['e200'], d['r14'], d['closes']
    if not all([e21[i], e50[i], e200[i], r14[i], e21[i-1], r14[i-1]]):
        return None
    # Macro uptrend
    if not (e50[i] > e200[i] and cl[i] > e50[i]):
        return None
    # Prezzo tocca EMA21 da sopra (low barra toca) e chiude sopra
    if d['lows'][i-1] <= e21[i-1] * 1.002 and cl[i] > e21[i] and r14[i-1] < 50 and r14[i] > r14[i-1]:
        return 'BUY'
    # Macro downtrend (per sell)
    if e50[i] < e200[i] and cl[i] < e50[i]:
        if d['highs'][i-1] >= e21[i-1] * 0.998 and cl[i] < e21[i] and r14[i-1] > 50 and r14[i] < r14[i-1]:
            return 'SELL'
    return None

def sig_vwap_bounce(i, d):
    """Prezzo rimbalza su VWAP (toccata + chiusura dall'altra parte)"""
    vwap, cl, r14, e200 = d['vwap'], d['closes'], d['r14'], d['e200']
    adx_v = d['adx']
    if not all([vwap[i], vwap[i-1], r14[i], e200[i], adx_v[i]]):
        return None
    if adx_v[i] < 15:
        return None
    trend_up = cl[i] > e200[i]
    trend_dn = cl[i] < e200[i]
    # Bounce da sotto VWAP verso sopra (BUY)
    if (d['lows'][i-1] <= vwap[i-1] and cl[i] > vwap[i] and trend_up and 38 < r14[i] < 58):
        return 'BUY'
    # Rimbalzo da sopra VWAP verso sotto (SELL)
    if (d['highs'][i-1] >= vwap[i-1] and cl[i] < vwap[i] and trend_dn and 42 < r14[i] < 62):
        return 'SELL'
    return None

def sig_stoch_ema_ribbon(i, d):
    """
    EMA ribbon (8<13<21<50) + Stochastic K cross + ADX > 22
    """
    e8, e13, e21, e50, e200 = d['e8'], d['e13'], d['e21'], d['e50'], d['e200']
    sk, sd = d['sk'], d['sd']
    r14 = d['r14']
    adx_v = d['adx']
    cl = d['closes']
    if not all([e8[i], e13[i], e21[i], e50[i], e200[i], sk[i], sd[i], sk[i-1], sd[i-1], adx_v[i]]):
        return None
    if adx_v[i] < 22:
        return None
    bull_ribbon = e8[i] > e13[i] > e21[i] > e50[i] > e200[i]
    bear_ribbon = e8[i] < e13[i] < e21[i] < e50[i] < e200[i]
    k_cross_up   = sk[i] > sd[i] and sk[i-1] <= sd[i-1] and sk[i] < 55
    k_cross_down = sk[i] < sd[i] and sk[i-1] >= sd[i-1] and sk[i] > 45
    if bull_ribbon and k_cross_up   and r14[i] > 45: return 'BUY'
    if bear_ribbon and k_cross_down and r14[i] < 55: return 'SELL'
    return None

def sig_rsi_dip_trend(i, d):
    """
    RSI dip sotto 38 in uptrend forte → buy il rimbalzo
    RSI sopra 62 in downtrend forte → sell il rimbalzo
    """
    r14, e50, e200, adx_v, cl = d['r14'], d['e50'], d['e200'], d['adx'], d['closes']
    if not all([r14[i], r14[i-1], r14[i-2], e50[i], e200[i], adx_v[i]]):
        return None
    strong_up = e50[i] > e200[i] and cl[i] > e50[i] and adx_v[i] > 20
    strong_dn = e50[i] < e200[i] and cl[i] < e50[i] and adx_v[i] > 20
    # RSI ha fatto un dip e ora rimbalza
    if strong_up and r14[i-2] > r14[i-1] < r14[i] and r14[i-1] < 38:
        return 'BUY'
    if strong_dn and r14[i-2] < r14[i-1] > r14[i] and r14[i-1] > 62:
        return 'SELL'
    return None

def sig_macd_zero_cross_trend(i, d):
    """
    MACD line attraversa lo zero + EMA50/200 trend + ADX > 20
    """
    ml = d['macd']
    e50, e200, adx_v, cl = d['e50'], d['e200'], d['adx'], d['closes']
    if not all([ml[i], ml[i-1], e50[i], e200[i], adx_v[i]]):
        return None
    if adx_v[i] < 20:
        return None
    trend_up = cl[i] > e200[i] and e50[i] > e200[i]
    trend_dn = cl[i] < e200[i] and e50[i] < e200[i]
    if ml[i-1] < 0 <= ml[i] and trend_up: return 'BUY'
    if ml[i-1] > 0 >= ml[i] and trend_dn: return 'SELL'
    return None

def sig_inside_bar_breakout(i, d):
    """
    Inside bar (range più stretto del precedente) → breakout direzionale
    con EMA200 trend + volume > media
    """
    hi, lo, cl, vols = d['highs'], d['lows'], d['closes'], d['vols']
    e200, r14 = d['e200'], d['r14']
    if not all([e200[i], r14[i]]):
        return None
    if i < 5:
        return None
    # Inside bar: range[i-1] è contenuto in range[i-2]
    inside = (hi[i-1] < hi[i-2] and lo[i-1] > lo[i-2])
    if not inside:
        return None
    avg_vol = sum(vols[i-10:i]) / 10
    high_vol = vols[i] > avg_vol * 1.3
    trend_up = cl[i] > e200[i]
    trend_dn = cl[i] < e200[i]
    # Breakout sopra inside bar high → BUY
    if cl[i] > hi[i-1] and trend_up and high_vol and r14[i] > 50:
        return 'BUY'
    # Breakout sotto inside bar low → SELL
    if cl[i] < lo[i-1] and trend_dn and high_vol and r14[i] < 50:
        return 'SELL'
    return None

def sig_composite_v2(i, d):
    """
    Composite: EMA ribbon + VWAP + Stochastic + RSI momentum
    Score >= 3/4 nella direzione del trend macro
    """
    e8, e13, e21, e50, e200 = d['e8'], d['e13'], d['e21'], d['e50'], d['e200']
    r14, sk, sd = d['r14'], d['sk'], d['sd']
    vwap, adx_v, cl = d['vwap'], d['adx'], d['closes']
    ml = d['macd']
    if not all([e8[i], e13[i], e21[i], e50[i], e200[i],
                r14[i], r14[i-1], sk[i], sd[i], sk[i-1], sd[i-1],
                vwap[i], adx_v[i], ml[i], ml[i-1]]):
        return None

    if adx_v[i] < 18:
        return None

    trend_up = e21[i] > e50[i] > e200[i]
    trend_dn = e21[i] < e50[i] < e200[i]

    sc_b = 0
    sc_s = 0

    # 1. EMA struttura
    if e8[i] > e21[i]:   sc_b += 1
    if e8[i] < e21[i]:   sc_s += 1

    # 2. Stochastic cross (< 60 per buy, > 40 per sell)
    if sk[i] > sd[i] and sk[i-1] <= sd[i-1] and sk[i] < 65: sc_b += 1
    if sk[i] < sd[i] and sk[i-1] >= sd[i-1] and sk[i] > 35: sc_s += 1

    # 3. RSI zona favorevole
    if 45 < r14[i] < 68 and r14[i] > r14[i-1]: sc_b += 1
    if 32 < r14[i] < 55 and r14[i] < r14[i-1]: sc_s += 1

    # 4. Prezzo sopra/sotto VWAP
    if cl[i] > vwap[i]: sc_b += 1
    if cl[i] < vwap[i]: sc_s += 1

    if sc_b >= 3 and trend_up: return 'BUY'
    if sc_s >= 3 and trend_dn: return 'SELL'
    return None

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  SCALPING HUNT v2 — XAU/USD M5 | Bias adattivo bull/bear | ATR TP/SL")
    print(f"  Capitale: ${CAPITAL_0:,.0f} | Risk/trade: {RISK_PCT*100:.0f}% | Spread: ${SPREAD}")
    print("=" * 80)

    with open(DATA_FILE) as f:
        raw = json.load(f)
    candles = raw['candles']
    first_ts = datetime.fromtimestamp(candles[MIN_BARS]['t'], tz=timezone.utc).strftime('%Y-%m-%d')
    last_ts  = datetime.fromtimestamp(candles[-1]['t'], tz=timezone.utc).strftime('%Y-%m-%d')
    print(f"\n  Barre: {len(candles):,} | Periodo: {first_ts} → {last_ts}")
    print(f"  Prezzo inizio: {candles[MIN_BARS]['c']:.2f} → Fine: {candles[-1]['c']:.2f}\n")

    # (nome, funzione segnale, ATR_TP_mult, ATR_SL_mult, sessione, bias)
    strategies = [
        ("S1: EMA21 Pullback (8-19 UTC)",    sig_pullback_ema21,      2.0, 1.0, (8, 19),  'both'),
        ("S2: VWAP Bounce (8-17 UTC)",       sig_vwap_bounce,         2.0, 1.0, (8, 17),  'both'),
        ("S3: EMA Ribbon + Stoch (8-17)",    sig_stoch_ema_ribbon,    1.8, 0.9, (8, 17),  'both'),
        ("S4: RSI Dip Trend (8-17)",         sig_rsi_dip_trend,       2.5, 1.2, (8, 17),  'both'),
        ("S5: MACD Zero Cross (8-17)",       sig_macd_zero_cross_trend,2.0, 1.0, (8, 17), 'both'),
        ("S6: Inside Bar Breakout (8-17)",   sig_inside_bar_breakout, 1.5, 0.8, (8, 17),  'both'),
        ("S7: Composite v2 (8-17)",          sig_composite_v2,        2.0, 1.0, (8, 17),  'both'),
        # Versioni long-only per exploit del bull run
        ("S1L: EMA21 Pullback LONG only",    sig_pullback_ema21,      2.0, 1.0, (8, 19),  'long'),
        ("S3L: EMA Ribbon+Stoch LONG only",  sig_stoch_ema_ribbon,    1.8, 0.9, (8, 17),  'long'),
        ("S4L: RSI Dip Trend LONG only",     sig_rsi_dip_trend,       2.5, 1.2, (8, 17),  'long'),
        ("S7L: Composite v2 LONG only",      sig_composite_v2,        2.0, 1.0, (8, 17),  'long'),
    ]

    results = []
    for name, fn, tp_m, sl_m, sess, bias in strategies:
        r = run_bt(candles, fn, name, tp_m, sl_m, sess, bias)
        results.append(r)

    # Sort per PF
    results.sort(key=lambda x: x['pf'] if x['pf'] < 999 else -1, reverse=True)

    hdr = f"{'Strategia':<42} {'#Trd':>5} {'T/g':>5} {'WR%':>6} {'PF':>6} {'Net P&L':>9} {'Ret%':>7} {'MaxDD%':>7} {'Exp$':>7}"
    print(hdr)
    print("-" * 105)
    for r in results:
        pf_str = f"{r['pf']:.2f}" if r['pf'] < 99 else ">99"
        print(f"{r['name']:<42} {r['total']:>5} {r['tpd']:>5.1f} {r['wr']:>5.1f}% {pf_str:>6} "
              f"${r['net']:>8.2f} {r['ret']:>6.1f}% {r['dd']:>6.1f}% ${r['exp']:>6.3f}")

    # Trova miglior strategia (punteggio composito)
    def score(r):
        if r['total'] < 20:  # troppo pochi trade → scarta
            return -999
        pf_cap = min(r['pf'], 3.0)
        return pf_cap * 0.35 + r['wr'] * 0.25 + r['ret'] * 0.20 - r['dd'] * 0.20

    best = max(results, key=score)

    print("\n" + "=" * 80)
    print(f"  MIGLIORE: {best['name']}")
    print("=" * 80)
    print(f"  Trades totali:       {best['total']}")
    print(f"  Trades/giorno (est): {best['tpd']:.1f}")
    print(f"  Win Rate:            {best['wr']:.1f}%")
    print(f"  Profit Factor:       {best['pf']:.3f}")
    print(f"  Net P&L:             ${best['net']:+,.2f}")
    print(f"  Capitale finale:     ${best['cap']:,.2f}")
    print(f"  Rendimento totale:   {best['ret']:+.1f}% su ${CAPITAL_0:,.0f}")
    print(f"  Max Drawdown:        {best['dd']:.1f}%")
    print(f"  Avg Win:             ${best['aw']:.3f}/trade")
    print(f"  Avg Loss:            ${best['al']:.3f}/trade")
    print(f"  R:R netto:           {best['aw']/best['al']:.2f}:1" if best['al'] > 0 else "  R:R netto:           ∞")
    print(f"  Expectancy:          ${best['exp']:.4f}/trade")

    months = (candles[-1]['t'] - candles[MIN_BARS]['t']) / (30.5 * 86400)
    print(f"\n  P&L medio/mese:      ${best['net']/months:+,.2f}")
    print(f"  P&L medio/giorno:    ${best['net']/(months*22):+,.2f}")
    print(f"\n  Gross Win:           ${best['gross_win']:,.2f}")
    print(f"  Gross Loss:          ${best['gross_loss']:,.2f}")
    print(f"\n  NOTE: Spread ${SPREAD} incluso | Risk {RISK_PCT*100:.0f}%/trade")
    print("=" * 80)

    out = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {"capital": CAPITAL_0, "risk_pct": RISK_PCT, "spread": SPREAD},
        "results": results,
        "best": best
    }
    with open("backtests/results/bt_scalp_v2.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\n  Risultati in backtests/results/bt_scalp_v2.json")

if __name__ == "__main__":
    main()
