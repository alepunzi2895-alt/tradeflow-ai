"""
Scalping Hunt v3 — XAU/USD M5
Ottimizzazione S4 RSI Dip Trend (unica strategia positiva in v2).
Varianti testate:
  A) parametri base v2 (benchmark)
  B) ADX >= 25, RSI dip < 35, ATR 3.0/1.2
  C) ADX >= 25, RSI dip < 35, ATR 2.5/1.0  (SL più stretto)
  D) ADX >= 22, RSI dip < 40, ATR 3.0/1.5  (più permissivo)
  E) session 7-20, ADX >= 25, RSI < 35, ATR 3.0/1.2
  F) session 8-12 (London open only), ADX >= 22, RSI < 38, ATR 2.5/1.2
  G) EMA200 slope gate + ADX >= 22 + RSI < 35 + ATR 2.5/1.2
  H) long-only bull bias + ADX >= 25 + RSI < 35 + ATR 3.0/1.2
"""
import json, math
from datetime import datetime, timezone

DATA_FILE  = "data/xauusd_m5_mt5.json"
CAPITAL_0  = 1000.0
RISK_PCT   = 0.01
SPREAD     = 0.40
MIN_BARS   = 250
MAX_HOLD   = 48
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

    atr_w = wilder(trs)
    pdm_w = wilder(pdms)
    ndm_w = wilder(ndms)
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

# ─── Engine ────────────────────────────────────────────────────────────────────

def run_bt(candles, sig_fn, name, atr_tp_mult, atr_sl_mult, session=(7, 19), bias='both'):
    n = len(candles)
    times  = [c['t'] for c in candles]
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    closes = [c['c'] for c in candles]
    vols   = [c['v'] for c in candles]

    e21  = ema(closes, 21)
    e50  = ema(closes, 50)
    e200 = ema(closes, 200)
    r14  = rsi(closes, 14)
    atr_v = atr_series(highs, lows, closes, ATR_PERIOD)
    adx_v = adx_series(highs, lows, closes, 14)

    indic = dict(
        e21=e21, e50=e50, e200=e200,
        r14=r14, atr=atr_v, adx=adx_v,
        highs=highs, lows=lows, closes=closes, vols=vols,
    )

    capital = CAPITAL_0
    trades  = []
    pos     = None
    max_eq  = capital
    max_dd  = 0.0

    for i in range(MIN_BARS, n):
        ts   = times[i]
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        in_sess = session[0] <= hour < session[1]

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
                trades.append({'pnl': pnl, 'win': pnl > 0, 'exit': exit_reason, 'dir': pos['dir']})
                pos = None
                max_eq = max(max_eq, capital)
                dd = (max_eq - capital) / max_eq * 100
                max_dd = max(max_dd, dd)

        if not pos and in_sess:
            a = atr_v[i]
            if not a or a == 0:
                continue
            sig = sig_fn(i, indic)
            if not sig:
                continue
            if bias == 'long' and sig != 'BUY':
                continue
            if bias == 'short' and sig != 'SELL':
                continue

            entry  = closes[i]
            tp_pts = a * atr_tp_mult
            sl_pts = a * atr_sl_mult
            lots   = max(0.01, round(capital * RISK_PCT / sl_pts, 2))

            if sig == 'BUY':
                pos = dict(dir='BUY', entry=entry, tp=entry+tp_pts, sl=entry-sl_pts,
                           open_bar=i, lots=lots)
            else:
                pos = dict(dir='SELL', entry=entry, tp=entry-tp_pts, sl=entry+sl_pts,
                           open_bar=i, lots=lots)

    if pos:
        cl = closes[-1]
        pnl = (cl - pos['entry'] - SPREAD)*pos['lots'] if pos['dir'] == 'BUY' \
              else (pos['entry'] - cl - SPREAD)*pos['lots']
        capital += pnl
        trades.append({'pnl': pnl, 'win': pnl > 0, 'exit': 'END', 'dir': pos['dir']})

    total     = len(trades)
    wins_list = [t for t in trades if t['win']]
    loss_list = [t for t in trades if not t['win']]
    gw  = sum(t['pnl'] for t in wins_list)
    gl  = abs(sum(t['pnl'] for t in loss_list))
    pf  = gw / gl if gl > 0 else 999.0
    wr  = len(wins_list)/total*100 if total else 0
    net = capital - CAPITAL_0
    aw  = gw/len(wins_list) if wins_list else 0
    al  = gl/len(loss_list) if loss_list else 0
    exp = (wr/100*aw) - ((1-wr/100)*al)

    day_span = (times[-1] - times[MIN_BARS]) / 86400
    tpd = total / day_span * 5/7 if total > 1 else 0

    return dict(name=name, total=total, wr=wr, pf=pf, net=net,
                cap=capital, dd=max_dd, exp=exp, aw=aw, al=al,
                ret=net/CAPITAL_0*100, tpd=tpd, gross_win=gw, gross_loss=gl)

# ─── Segnali RSI Dip — varianti ────────────────────────────────────────────────

def make_rsi_dip(adx_min=20, rsi_dip_buy=38, rsi_dip_sell=62, ema200_slope=False):
    """Factory: ritorna sig_fn con parametri configurabili."""
    def sig(i, d):
        r14, e50, e200, adx_v, cl = d['r14'], d['e50'], d['e200'], d['adx'], d['closes']
        if not all([r14[i], r14[i-1], r14[i-2], e50[i], e200[i], adx_v[i]]):
            return None
        strong_up = e50[i] > e200[i] and cl[i] > e50[i] and adx_v[i] > adx_min
        strong_dn = e50[i] < e200[i] and cl[i] < e50[i] and adx_v[i] > adx_min

        if ema200_slope and i >= 20:
            slope_up = e200[i] > e200[i-20] if e200[i-20] else False
            slope_dn = e200[i] < e200[i-20] if e200[i-20] else False
            strong_up = strong_up and slope_up
            strong_dn = strong_dn and slope_dn

        if strong_up and r14[i-2] > r14[i-1] < r14[i] and r14[i-1] < rsi_dip_buy:
            return 'BUY'
        if strong_dn and r14[i-2] < r14[i-1] > r14[i] and r14[i-1] > rsi_dip_sell:
            return 'SELL'
        return None
    return sig

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 90)
    print("  SCALPING HUNT v3 — RSI Dip Trend Optimization — XAU/USD M5")
    print(f"  Capitale: ${CAPITAL_0:,.0f} | Risk/trade: {RISK_PCT*100:.0f}% | Spread: ${SPREAD}")
    print("=" * 90)

    with open(DATA_FILE) as f:
        raw = json.load(f)
    candles = raw['candles']
    first_ts = datetime.fromtimestamp(candles[MIN_BARS]['t'], tz=timezone.utc).strftime('%Y-%m-%d')
    last_ts  = datetime.fromtimestamp(candles[-1]['t'],      tz=timezone.utc).strftime('%Y-%m-%d')
    print(f"\n  Barre: {len(candles):,} | Periodo: {first_ts} → {last_ts}")
    print(f"  Prezzo: {candles[MIN_BARS]['c']:.2f} → {candles[-1]['c']:.2f} (+87.5%)\n")

    # (nome, sig_fn, atr_tp, atr_sl, session, bias)
    strategies = [
        # Baseline da v2
        ("A: baseline v2 [ADX20, RSI<38, ATR2.5/1.2, 8-17]",
         make_rsi_dip(20, 38, 62),            2.5, 1.2, (8, 17), 'both'),

        # Filtri più stretti
        ("B: ADX25 + RSI<35 + ATR3.0/1.2",
         make_rsi_dip(25, 35, 65),            3.0, 1.2, (8, 17), 'both'),

        # SL più stretto, TP invariato
        ("C: ADX25 + RSI<35 + ATR2.5/1.0",
         make_rsi_dip(25, 35, 65),            2.5, 1.0, (8, 17), 'both'),

        # Più permissivo, TP più largo
        ("D: ADX22 + RSI<40 + ATR3.0/1.5",
         make_rsi_dip(22, 40, 60),            3.0, 1.5, (8, 17), 'both'),

        # Sessione estesa
        ("E: ADX25 + RSI<35 + ATR3.0/1.2 + sess7-20",
         make_rsi_dip(25, 35, 65),            3.0, 1.2, (7, 20), 'both'),

        # Solo London open (8-12)
        ("F: ADX22 + RSI<38 + ATR2.5/1.2 + London only",
         make_rsi_dip(22, 38, 62),            2.5, 1.2, (8, 12), 'both'),

        # EMA200 slope gate
        ("G: ADX22 + RSI<35 + ATR2.5/1.2 + EMA200slope",
         make_rsi_dip(22, 35, 65, ema200_slope=True), 2.5, 1.2, (8, 17), 'both'),

        # Long-only bull bias, parametri ottimali
        ("H: LONG-ONLY + ADX25 + RSI<35 + ATR3.0/1.2",
         make_rsi_dip(25, 35, 65),            3.0, 1.2, (8, 17), 'long'),

        # RR aggressivo (molto largo TP)
        ("I: ADX20 + RSI<38 + ATR4.0/1.2 [RR 3.3:1]",
         make_rsi_dip(20, 38, 62),            4.0, 1.2, (8, 17), 'both'),

        # ATR equilibrato, tutto il giorno
        ("J: ADX18 + RSI<42 + ATR2.0/1.0 + sess7-20",
         make_rsi_dip(18, 42, 58),            2.0, 1.0, (7, 20), 'both'),

        # TP stretto, alta WR target
        ("K: ADX25 + RSI<35 + ATR1.5/1.0 [RR 1.5:1]",
         make_rsi_dip(25, 35, 65),            1.5, 1.0, (8, 17), 'both'),
    ]

    results = []
    for name, fn, tp_m, sl_m, sess, bias in strategies:
        r = run_bt(candles, fn, name, tp_m, sl_m, sess, bias)
        results.append(r)
        status = "✓" if r['pf'] > 1.0 else "✗"
        print(f"  {status} {name[:60]:<60} PF={r['pf']:.3f} WR={r['wr']:.1f}% N={r['total']:>4}")

    # Sort per PF
    results.sort(key=lambda x: x['pf'] if x['pf'] < 999 else 0, reverse=True)

    print("\n")
    hdr = f"{'Variante':<54} {'#Trd':>5} {'T/g':>5} {'WR%':>6} {'PF':>6} {'Net P&L':>9} {'Ret%':>7} {'MaxDD%':>7} {'Exp$':>7}"
    print(hdr)
    print("-" * 115)
    for r in results:
        pf_str = f"{r['pf']:.3f}" if r['pf'] < 99 else ">99"
        flag = "★" if r['pf'] > 1.15 and r['total'] >= 50 else " "
        print(f"{flag} {r['name']:<52} {r['total']:>5} {r['tpd']:>5.2f} {r['wr']:>5.1f}% {pf_str:>6} "
              f"${r['net']:>8.2f} {r['ret']:>6.1f}% {r['dd']:>6.1f}% ${r['exp']:>6.3f}")

    # Miglior candidato (PF + trade sufficienti)
    def score(r):
        if r['total'] < 30:
            return -999
        pf_cap = min(r['pf'], 3.0)
        return pf_cap * 0.40 + r['wr'] * 0.20 + r['ret'] * 0.20 - r['dd'] * 0.20

    best = max(results, key=score)

    print("\n" + "=" * 90)
    print(f"  MIGLIORE: {best['name']}")
    print("=" * 90)
    print(f"  Trades totali:       {best['total']}")
    print(f"  Trades/giorno:       {best['tpd']:.2f}")
    print(f"  Win Rate:            {best['wr']:.1f}%")
    print(f"  Profit Factor:       {best['pf']:.4f}")
    print(f"  Net P&L:             ${best['net']:+,.2f}")
    print(f"  Rendimento totale:   {best['ret']:+.1f}%")
    print(f"  Max Drawdown:        {best['dd']:.1f}%")
    print(f"  Avg Win:             ${best['aw']:.3f}/trade")
    print(f"  Avg Loss:            ${best['al']:.3f}/trade")
    rr = best['aw']/best['al'] if best['al'] > 0 else float('inf')
    print(f"  R:R netto:           {rr:.2f}:1")
    print(f"  Expectancy:          ${best['exp']:.4f}/trade")

    months = (candles[-1]['t'] - candles[MIN_BARS]['t']) / (30.5 * 86400)
    print(f"\n  P&L medio/mese:      ${best['net']/months:+,.2f}")
    print(f"  P&L medio/giorno:    ${best['net']/(months*22):+,.2f}")

    out = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {"capital": CAPITAL_0, "risk_pct": RISK_PCT, "spread": SPREAD},
        "results": results,
        "best": best
    }
    with open("backtests/results/bt_scalp_v3.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Risultati salvati in backtests/results/bt_scalp_v3.json")
    print("=" * 90)

if __name__ == "__main__":
    main()
