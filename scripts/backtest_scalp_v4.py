"""
Scalping Hunt v4 — RSI Dip Trend su M5 vs M15
Confronto variante C (vincitrice v3) + varianti extra su M15.

Variante C v3: ADX>=25, RSI dip < 35, ATR 2.5 TP / 1.0 SL, sess 8-17, both

M15 extra:
  C-m15:     stessa config su M15
  C2-m15:    ADX22 + RSI<38 + ATR2.5/1.0     (leggermente più permissivo)
  C3-m15:    ADX25 + RSI<35 + ATR3.0/1.2     (TP più largo)
  C4-m15:    ADX25 + RSI<35 + ATR2.5/1.0 + sess7-20
  C5-m15:    ADX25 + RSI<35 + ATR2.5/1.0 + EMA200slope
  C6-m15:    ADX25 + RSI<35 + ATR2.0/0.8 [RR 2.5:1, SL strettissimo]
  C7-m15:    ADX22 + RSI<35 + ATR2.5/1.0 + vol filter
  C8-m15:    ADX25 + RSI<35 + ATR2.5/1.0 + DI spread>5
"""
import json, math
from datetime import datetime, timezone

CAPITAL_0 = 1000.0
RISK_PCT  = 0.01
SPREAD    = 0.40
ATR_P     = 14

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

def adx_di(highs, lows, closes, n=14):
    """Ritorna (adx, dip, dim) come liste parallele."""
    L = len(closes)
    adx_out = [None] * L
    dip_out  = [None] * L
    dim_out  = [None] * L
    trs, pdms, ndms = [], [], []
    for i in range(1, L):
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
    dip_list = []
    dim_list = []
    for i in range(n-1, len(trs)):
        pdi = 100*pdm_w[i]/atr_w[i] if atr_w[i] else 0
        ndi = 100*ndm_w[i]/atr_w[i] if atr_w[i] else 0
        dip_list.append(pdi)
        dim_list.append(ndi)
        dx_list.append(100*abs(pdi-ndi)/(pdi+ndi) if pdi+ndi else 0)

    if len(dx_list) >= n:
        v = sum(dx_list[:n]) / n
        adx_out[2*n-1] = v
        dip_out[2*n-1] = dip_list[n-1]
        dim_out[2*n-1] = dim_list[n-1]
        for i in range(1, len(dx_list)-n+1):
            v = (v*(n-1) + dx_list[n-1+i]) / n
            adx_out[2*n+i-1] = v
            dip_out[2*n+i-1] = dip_list[n-1+i]
            dim_out[2*n+i-1] = dim_list[n-1+i]
    return adx_out, dip_out, dim_out

# ─── Engine ────────────────────────────────────────────────────────────────────

def run_bt(candles, sig_fn, name, atr_tp_mult, atr_sl_mult,
           session=(8, 17), bias='both', min_bars=250, max_hold=48):
    n = len(candles)
    times  = [c['t'] for c in candles]
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    closes = [c['c'] for c in candles]
    vols   = [c['v'] for c in candles]

    e50  = ema(closes, 50)
    e200 = ema(closes, 200)
    r14  = rsi(closes, 14)
    atr_v = atr_series(highs, lows, closes, ATR_P)
    adx_v, dip_v, dim_v = adx_di(highs, lows, closes, ATR_P)

    indic = dict(
        e50=e50, e200=e200, r14=r14,
        atr=atr_v, adx=adx_v, dip=dip_v, dim=dim_v,
        highs=highs, lows=lows, closes=closes, vols=vols,
    )

    capital = CAPITAL_0
    trades  = []
    pos     = None
    max_eq  = capital
    max_dd  = 0.0

    for i in range(min_bars, n):
        ts   = times[i]
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        in_sess = session[0] <= hour < session[1]

        if pos:
            h, l, cl = highs[i], lows[i], closes[i]
            pnl = None
            if pos['dir'] == 'BUY':
                if l <= pos['sl']:
                    pnl = (pos['sl'] - pos['entry'] - SPREAD) * pos['lots']
                elif h >= pos['tp']:
                    pnl = (pos['tp'] - pos['entry'] - SPREAD) * pos['lots']
                elif i - pos['open_bar'] >= max_hold:
                    pnl = (cl - pos['entry'] - SPREAD) * pos['lots']
            else:
                if h >= pos['sl']:
                    pnl = (pos['entry'] - pos['sl'] - SPREAD) * pos['lots']
                elif l <= pos['tp']:
                    pnl = (pos['entry'] - pos['tp'] - SPREAD) * pos['lots']
                elif i - pos['open_bar'] >= max_hold:
                    pnl = (pos['entry'] - cl - SPREAD) * pos['lots']

            if pnl is not None:
                capital += pnl
                trades.append({'pnl': pnl, 'win': pnl > 0, 'dir': pos['dir']})
                pos = None
                max_eq = max(max_eq, capital)
                max_dd = max(max_dd, (max_eq - capital) / max_eq * 100)

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
            sl_pts = a * atr_sl_mult
            tp_pts = a * atr_tp_mult
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
        trades.append({'pnl': pnl, 'win': pnl > 0, 'dir': pos['dir']})

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
    day_span = (times[-1] - times[min_bars]) / 86400
    tpd = total / day_span * 5/7 if total > 1 else 0

    return dict(name=name, total=total, wr=wr, pf=pf, net=net,
                cap=capital, dd=max_dd, exp=exp, aw=aw, al=al,
                ret=net/CAPITAL_0*100, tpd=tpd, gross_win=gw, gross_loss=gl)

# ─── Segnali factory ───────────────────────────────────────────────────────────

def make_sig(adx_min=25, rsi_buy=35, rsi_sell=65,
             ema200_slope=False, vol_mult=None, di_spread=None):
    def sig(i, d):
        r14, e50, e200 = d['r14'], d['e50'], d['e200']
        adx_v, dip_v, dim_v = d['adx'], d['dip'], d['dim']
        cl, vols = d['closes'], d['vols']

        if not all([r14[i], r14[i-1], r14[i-2], e50[i], e200[i], adx_v[i]]):
            return None

        if adx_v[i] < adx_min:
            return None

        strong_up = e50[i] > e200[i] and cl[i] > e50[i]
        strong_dn = e50[i] < e200[i] and cl[i] < e50[i]

        # EMA200 slope: verifica che l'EMA200 stia salendo/scendendo
        if ema200_slope and i >= 20 and e200[i-20]:
            strong_up = strong_up and (e200[i] > e200[i-20])
            strong_dn = strong_dn and (e200[i] < e200[i-20])

        # Volume filter: volume barra > media 10 barre × vol_mult
        if vol_mult and i >= 10:
            avg_vol = sum(vols[i-10:i]) / 10
            if avg_vol > 0 and vols[i] < avg_vol * vol_mult:
                return None

        # DI spread filter: DI+ - DI- > di_spread per BUY (e viceversa per SELL)
        dip = dip_v[i] if dip_v[i] else None
        dim = dim_v[i] if dim_v[i] else None

        if strong_up and r14[i-2] > r14[i-1] < r14[i] and r14[i-1] < rsi_buy:
            if di_spread and (dip is None or dim is None or dip - dim < di_spread):
                return None
            return 'BUY'

        if strong_dn and r14[i-2] < r14[i-1] > r14[i] and r14[i-1] > rsi_sell:
            if di_spread and (dip is None or dim is None or dim - dip < di_spread):
                return None
            return 'SELL'

        return None
    return sig

# ─── Main ──────────────────────────────────────────────────────────────────────

def load(path):
    with open(path) as f:
        return json.load(f)['candles']

def main():
    print("=" * 100)
    print("  SCALPING HUNT v4 — RSI Dip Trend | M5 vs M15 | XAU/USD")
    print(f"  Capitale: ${CAPITAL_0:,.0f} | Risk/trade: {RISK_PCT*100:.0f}% | Spread: ${SPREAD}")
    print("=" * 100)

    c5  = load("data/xauusd_m5_mt5.json")
    c15 = load("data/xauusd_m15_mt5.json")

    # max_hold proporzionale al TF: M5=48 barre (~4h), M15=24 barre (~6h)
    # min_bars: M5=250, M15=200

    strategies = [
        # ─── M5 ───────────────────────────────────────────────────────────────
        ("M5  | C  baseline",          c5,  make_sig(25,35,65),             2.5,1.0,(8,17),'both',250,48),
        ("M5  | C+ vol1.2",            c5,  make_sig(25,35,65,vol_mult=1.2),2.5,1.0,(8,17),'both',250,48),
        ("M5  | C+ DI_spread5",        c5,  make_sig(25,35,65,di_spread=5), 2.5,1.0,(8,17),'both',250,48),
        ("M5  | C+ DI5+vol1.2",        c5,  make_sig(25,35,65,di_spread=5,vol_mult=1.2),2.5,1.0,(8,17),'both',250,48),
        ("M5  | C+ slope200",          c5,  make_sig(25,35,65,ema200_slope=True),2.5,1.0,(8,17),'both',250,48),

        # ─── M15 ──────────────────────────────────────────────────────────────
        ("M15 | C  same config",       c15, make_sig(25,35,65),             2.5,1.0,(8,17),'both',200,24),
        ("M15 | C2 ADX22+RSI38",       c15, make_sig(22,38,62),             2.5,1.0,(8,17),'both',200,24),
        ("M15 | C3 ATR3.0/1.2",        c15, make_sig(25,35,65),             3.0,1.2,(8,17),'both',200,24),
        ("M15 | C4 sess7-20",          c15, make_sig(25,35,65),             2.5,1.0,(7,20),'both',200,24),
        ("M15 | C5 slope200",          c15, make_sig(25,35,65,ema200_slope=True),2.5,1.0,(8,17),'both',200,24),
        ("M15 | C6 ATR2.0/0.8",        c15, make_sig(25,35,65),             2.0,0.8,(8,17),'both',200,24),
        ("M15 | C7 vol1.2",            c15, make_sig(25,35,65,vol_mult=1.2),2.5,1.0,(8,17),'both',200,24),
        ("M15 | C8 DI_spread5",        c15, make_sig(25,35,65,di_spread=5), 2.5,1.0,(8,17),'both',200,24),
        ("M15 | C9 ADX22+RSI38+slope", c15, make_sig(22,38,62,ema200_slope=True),2.5,1.0,(8,17),'both',200,24),
        ("M15 | C10 ADX25+DI5+slope",  c15, make_sig(25,35,65,di_spread=5,ema200_slope=True),2.5,1.0,(8,17),'both',200,24),
    ]

    results = []
    for name, candles, fn, tp_m, sl_m, sess, bias, mb, mh in strategies:
        r = run_bt(candles, fn, name, tp_m, sl_m, sess, bias, mb, mh)
        results.append(r)
        flag = "✓" if r['pf'] > 1.0 else "✗"
        print(f"  {flag} {name:<36} PF={r['pf']:.3f}  WR={r['wr']:.1f}%  N={r['total']:>4}  DD={r['dd']:.1f}%")

    # Separa M5 / M15
    m5_r  = [r for r in results if r['name'].startswith('M5')]
    m15_r = [r for r in results if r['name'].startswith('M15')]

    def print_table(label, rows):
        rows = sorted(rows, key=lambda x: x['pf'] if x['pf'] < 999 else 0, reverse=True)
        print(f"\n{'─'*105}")
        print(f"  {label}")
        print(f"{'─'*105}")
        hdr = f"  {'Variante':<38} {'#Trd':>5} {'T/g':>5} {'WR%':>6} {'PF':>6} {'Net P&L':>9} {'Ret%':>7} {'MaxDD%':>7} {'Exp$':>7} {'RR':>5}"
        print(hdr)
        print(f"  {'-'*100}")
        for r in rows:
            rr = r['aw']/r['al'] if r['al'] > 0 else 0
            flag = "★" if r['pf'] >= 1.30 and r['total'] >= 50 else " "
            print(f"  {flag} {r['name']:<37} {r['total']:>5} {r['tpd']:>5.2f} {r['wr']:>5.1f}% "
                  f"{r['pf']:>6.3f} ${r['net']:>8.2f} {r['ret']:>6.1f}% {r['dd']:>6.1f}% "
                  f"${r['exp']:>6.3f} {rr:>4.2f}")

    print_table("M5  RISULTATI", m5_r)
    print_table("M15 RISULTATI", m15_r)

    # Miglior candidato globale
    def score(r):
        if r['total'] < 40:
            return -999
        pf_cap = min(r['pf'], 4.0)
        return pf_cap * 0.40 + r['wr'] * 0.20 + r['ret'] * 0.20 - r['dd'] * 0.20

    best_m5  = max(m5_r,  key=score)
    best_m15 = max(m15_r, key=score)
    best_all = max(results, key=score)

    def summary(label, r):
        print(f"\n  {label}: {r['name']}")
        rr = r['aw']/r['al'] if r['al'] > 0 else 0
        months = 17  # circa 17 mesi dataset
        print(f"    Trades: {r['total']} ({r['tpd']:.2f}/g)  WR: {r['wr']:.1f}%  PF: {r['pf']:.4f}  "
              f"NetP&L: ${r['net']:+,.2f} ({r['ret']:+.1f}%)  DD: {r['dd']:.1f}%  "
              f"RR: {rr:.2f}:1  Exp: ${r['exp']:.3f}")
        print(f"    P&L/mese: ~${r['net']/months:+.0f}  P&L/gg: ~${r['net']/(months*22):+.2f}")

    print("\n" + "=" * 100)
    print("  SOMMARIO MIGLIORI")
    print("=" * 100)
    summary("Best M5 ", best_m5)
    summary("Best M15", best_m15)
    summary("Best ALL", best_all)

    out = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {"capital": CAPITAL_0, "risk_pct": RISK_PCT, "spread": SPREAD},
        "m5_results":  m5_r,
        "m15_results": m15_r,
        "best_m5":  best_m5,
        "best_m15": best_m15,
        "best_all": best_all,
    }
    with open("backtests/results/bt_scalp_v4.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Risultati salvati in backtests/results/bt_scalp_v4.json")
    print("=" * 100)

if __name__ == "__main__":
    main()
