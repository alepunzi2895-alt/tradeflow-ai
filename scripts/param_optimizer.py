#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Parameter Optimizer
====================================
Random search sui parametri di S10_OB_FVG_SCALP (e opzionalmente sistema globale)
con vincolo di MaxDD ≤ MAX_DD_PCT% dell'equity di picco.

Score = PF × sqrt(trades) × (1 - dd_ratio/MAX_DD_PCT)
  - premia qualità (PF) × frequenza (sqrt trades) × bassa DD

USO:
  python scripts/param_optimizer.py --mt5               # dati live MT5
  python scripts/param_optimizer.py --m15-file f.json   # file locale
  python scripts/param_optimizer.py --mt5 --n-trials 500
  python scripts/param_optimizer.py --mt5 --global      # ottimizza anche soglie regime

Output:
  optimized_params.json — top config da caricare nel bot
"""
import sys, io, os, json, math, random, argparse, datetime, itertools

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── ARGS ──────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument('--mt5',      action='store_true')
ap.add_argument('--m15-file', default='data/xauusd_m15_mt5.json')
ap.add_argument('--h1-file',  default='data/xauusd_h1_mt5.json')
ap.add_argument('--n-trials', type=int, default=300, help='Iterazioni random search')
ap.add_argument('--max-dd',   type=float, default=0.40, help='Max DrawDown % (0.40 = 40%%)')
ap.add_argument('--global',   dest='global_opt', action='store_true', help='Ottimizza anche soglie globali')
ap.add_argument('--out',      default='optimized_params.json')
ap.add_argument('--seed',     type=int, default=42)
args = ap.parse_args()

random.seed(args.seed)
MAX_DD_PCT  = args.max_dd
N_TRIALS    = args.n_trials
WARMUP      = 200
SESSION_DEF = (7, 17)

# ── MATH ──────────────────────────────────────────────────────────────────────
def ema(src, p):
    k = 2/(p+1); v = src[0]; o = [v]
    for x in src[1:]: v = x*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    out = [None]*(p-1)
    for i in range(p-1, len(src)):
        out.append(sum(src[i-p+1:i+1])/p)
    return out

def atr14(H, L, C):
    tr = [0]
    for i in range(1, len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    return sma(tr, 14)

def stdev_arr(src, p):
    out = [None]*(p-1)
    for i in range(p-1, len(src)):
        sl = src[i-p+1:i+1]; mn = sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def adx_wilder(H, L, C, p=14):
    n = len(C); TR=[0]; DMP=[0]; DMM=[0]
    for i in range(1, n):
        TR.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
        up=H[i]-H[i-1]; dn=L[i-1]-L[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    sT=[0]; sP=[0]; sM=[0]
    for i in range(1, n):
        sT.append(sT[-1]-sT[-1]/p+TR[i])
        sP.append(sP[-1]-sP[-1]/p+DMP[i])
        sM.append(sM[-1]-sM[-1]/p+DMM[i])
    DIP=[sP[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DIM=[sM[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    dx=[(abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if DIP[i]+DIM[i]>0 else 0) for i in range(n)]
    return sma(dx, p), DIP, DIM

# ── OB + FVG (parametrizzabili) ───────────────────────────────────────────────
def calc_ob_fvg(O, H, L, C, ob_lookback=20, fvg_std=100, fvg_df=2):
    n = len(C)
    ob_bull = [False]*n; ob_bear = [False]*n
    for i in range(ob_lookback+4, n):
        c_now = C[i]
        for j in range(i-3, max(i-ob_lookback-1, 2), -1):
            if C[j] >= O[j]: continue
            lo = min(O[j],C[j]); hi = max(O[j],C[j])
            if not (j+2 < n and C[j+1]>O[j+1] and C[j+2]>O[j+2]): continue
            if any(L[k] < lo*0.999 for k in range(j+1, i)): continue
            if lo*0.999 <= c_now <= hi*1.002: ob_bull[i]=True; break
        for j in range(i-3, max(i-ob_lookback-1, 2), -1):
            if C[j] <= O[j]: continue
            lo = min(O[j],C[j]); hi = max(O[j],C[j])
            if not (j+2 < n and C[j+1]<O[j+1] and C[j+2]<O[j+2]): continue
            if any(H[k] > hi*1.001 for k in range(j+1, i)): continue
            if lo*0.998 <= c_now <= hi*1.001: ob_bear[i]=True; break
    body = [abs(O[i]-C[i]) for i in range(n)]
    bs = stdev_arr(body, min(fvg_std, n//2))
    fb=[False]*n; fs=[False]*n; ab=[]; as_=[]
    for i in range(2, n):
        disp = bs[i-1] is not None and bs[i-1]>0 and body[i-1]>bs[i-1]*fvg_df
        if L[i]>H[i-2]: ab.append({'lo':H[i-2],'hi':L[i],'bar':i})
        if H[i]<L[i-2]: as_.append({'lo':H[i],'hi':L[i-2],'bar':i})
        sb=[]
        for fvg in ab:
            if fvg['bar']==i: sb.append(fvg); continue
            if L[i]<fvg['lo']: continue
            if fvg['lo']<=C[i]<=fvg['hi']: fb[i]=True
            sb.append(fvg)
        ab=sb[-20:]
        sb2=[]
        for fvg in as_:
            if fvg['bar']==i: sb2.append(fvg); continue
            if H[i]>fvg['hi']: continue
            if fvg['lo']<=C[i]<=fvg['hi']: fs[i]=True
            sb2.append(fvg)
        as_=sb2[-20:]
    return ob_bull, ob_bear, fb, fs

# ── BACKTEST CORE (S10 parametrizzato) ───────────────────────────────────────
def run_backtest(candles, params, session=SESSION_DEF, extreme_mult=3.5):
    """
    Backtest veloce di S10_OB_FVG_SCALP con parametri variabili.
    Ritorna dict con WR, PF, pnl, maxdd, trades.
    """
    O=[c['o'] for c in candles]; H=[c['h'] for c in candles]
    L=[c['l'] for c in candles]; C=[c['c'] for c in candles]
    n = len(C)

    tp_mult    = params['tp_mult']
    sl_mult    = params['sl_mult']
    ob_lb      = params['ob_lookback']
    ema_fast   = params['ema_fast']
    ema_slow   = params['ema_slow']
    relax      = params.get('relax', False)  # True = OB OR FVG

    e20  = ema(C, ema_fast)
    e50  = ema(C, ema_slow)
    atr  = atr14(H, L, C)
    atr30 = [None]*n
    for i in range(30, n):
        vs = [atr[j] for j in range(i-30, i) if atr[j] is not None]
        atr30[i] = sum(vs)/len(vs) if vs else None

    ob_bull, ob_bear, fvg_b, fvg_s = calc_ob_fvg(O, H, L, C, ob_lookback=ob_lb)

    equity     = 0.0
    peak_eq    = 0.0
    max_dd     = 0.0
    in_trade   = False
    t_open_i   = -1
    t_dir      = None
    t_tp = t_sl = t_tp_pts = t_sl_pts = 0.0
    wins = losses = 0
    gross_win = gross_loss = 0.0
    max_open  = 100  # max barre per trade aperto

    for i in range(WARMUP, n-1):
        dt   = datetime.datetime.utcfromtimestamp(candles[i]['t'])
        hour = dt.hour
        # ── Risolvi trade aperto ──────────────────────────────────────────────
        if in_trade:
            h = H[i]; l = L[i]
            hit = None
            if t_dir=='buy':
                if l <= t_sl: hit='sl'
                elif h >= t_tp: hit='tp'
            else:
                if h >= t_sl: hit='sl'
                elif l <= t_tp: hit='tp'
            if hit is None and (i - t_open_i) >= max_open:
                hit = 'timeout'
            if hit:
                if hit == 'tp':
                    pnl = t_tp_pts; wins += 1; gross_win += pnl
                elif hit == 'sl':
                    pnl = -t_sl_pts; losses += 1; gross_loss += t_sl_pts
                else:
                    close_p = C[i]
                    entry_p = candles[t_open_i]['c']
                    pnl = (close_p - entry_p) if t_dir=='buy' else (entry_p - close_p)
                    if pnl > 0: wins += 1; gross_win += pnl
                    else: losses += 1; gross_loss += abs(pnl)
                equity += pnl
                if equity > peak_eq: peak_eq = equity
                dd = peak_eq - equity
                if dd > max_dd: max_dd = dd
                in_trade = False
            continue

        # ── Filtri ────────────────────────────────────────────────────────────
        if hour < session[0] or hour >= session[1]: continue
        av = atr[i]; a30 = atr30[i]
        if av is None: continue
        if a30 and av > extreme_mult * a30: continue
        if e20[i] is None or e50[i] is None: continue

        # ── Segnale ───────────────────────────────────────────────────────────
        bull_c = C[i] > O[i]; bear_c = C[i] < O[i]
        sig = None
        if relax:
            if e20[i]>e50[i] and (ob_bull[i] or fvg_b[i]) and bull_c: sig='buy'
            elif e20[i]<e50[i] and (ob_bear[i] or fvg_s[i]) and bear_c: sig='sell'
        else:
            if e20[i]>e50[i] and ob_bull[i] and fvg_b[i] and bull_c: sig='buy'
            elif e20[i]<e50[i] and ob_bear[i] and fvg_s[i] and bear_c: sig='sell'
        if not sig: continue

        # ── Apri trade ────────────────────────────────────────────────────────
        entry = C[i]; tp_pts = av*tp_mult; sl_pts = av*sl_mult
        if sig=='buy': tp_p=entry+tp_pts; sl_p=entry-sl_pts
        else:          tp_p=entry-tp_pts; sl_p=entry+sl_pts
        in_trade=True; t_open_i=i; t_dir=sig
        t_tp=tp_p; t_sl=sl_p; t_tp_pts=tp_pts; t_sl_pts=sl_pts

    total = wins + losses
    if total < 10: return None  # troppo pochi trade per essere significativi
    wr  = wins/total
    pf  = gross_win/gross_loss if gross_loss>0 else 999.0
    dd_ratio = (max_dd/peak_eq) if peak_eq>0 else 1.0
    score = pf * math.sqrt(total) * max(0, 1 - dd_ratio/MAX_DD_PCT)
    return {
        'trades': total, 'wins': wins, 'losses': losses,
        'wr': round(wr*100, 1), 'pf': round(pf, 3),
        'pnl': round(equity, 2), 'max_dd': round(max_dd, 2),
        'dd_pct': round(dd_ratio*100, 1),
        'score': round(score, 3),
        'peak_eq': round(peak_eq, 2),
    }

# ── PARAM SPACE ───────────────────────────────────────────────────────────────
PARAM_SPACE = {
    'tp_mult':    [0.7, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0],
    'sl_mult':    [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
    'ob_lookback':[10, 12, 15, 18, 20, 25],
    'ema_fast':   [10, 12, 15, 20, 25],
    'ema_slow':   [30, 40, 50, 60, 70],
    'relax':      [False, True],
}

GLOBAL_SPACE = {
    'session_start': [6, 7, 8],
    'session_end':   [16, 17, 18],
    'extreme_mult':  [2.5, 3.0, 3.5, 4.0],
}

def sample_params():
    return {k: random.choice(v) for k, v in PARAM_SPACE.items()}

def sample_global():
    return {k: random.choice(v) for k, v in GLOBAL_SPACE.items()}

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_json(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    candles = d.get('candles', d) if isinstance(d, dict) else d
    for c in candles:
        if 'o' not in c: c['o'] = c.get('open', c.get('c', 0))
    return sorted(candles, key=lambda x: x['t'])

def fetch_mt5(tf, n):
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return []
    tf_map = {'M15': mt5.TIMEFRAME_M15, 'H1': mt5.TIMEFRAME_H1}
    rates = mt5.copy_rates_from_pos("GOLD", tf_map[tf], 0, min(n, 99_999))
    if rates is None or len(rates)==0:
        rates = mt5.copy_rates_from_pos("XAUUSD", tf_map[tf], 0, min(n, 99_999))
    if rates is None or len(rates)==0: return []
    return [{'t':int(r['time']),'o':float(r['open']),'h':float(r['high']),'l':float(r['low']),'c':float(r['close']),'v':float(r['tick_volume'])} for r in rates]

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("="*65)
    print("TradeFlow AI — Parameter Optimizer")
    print(f"Trials: {N_TRIALS} | MaxDD vincolo: {MAX_DD_PCT*100:.0f}%")
    print(f"Score = PF × √trades × (1 - dd/MaxDD)")
    print("="*65)

    if args.mt5:
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                print(f"MT5 fallito: {mt5.last_error()}"); return
            print("MT5 connesso")
        except ImportError:
            print("MetaTrader5 non disponibile — uso JSON"); args.mt5=False

    print("\nCarico dati M15...")
    if args.mt5:
        candles = fetch_mt5('M15', 8000)
        if candles:
            with open('data/xauusd_m15_mt5.json','w') as f: json.dump({'candles':candles},f)
            print(f"  {len(candles)} barre scaricate e salvate")
        else:
            candles = load_json(args.m15_file) if os.path.exists(args.m15_file) else []
    else:
        candles = load_json(args.m15_file) if os.path.exists(args.m15_file) else []

    if len(candles) < 500:
        print("Dati insufficienti (< 500 barre M15)"); return
    print(f"  {len(candles)} barre M15 disponibili")

    # ── OTTIMIZZAZIONE S10 ────────────────────────────────────────────────────
    print(f"\nAvvio random search {N_TRIALS} trial su S10_OB_FVG_SCALP...")
    results = []
    valid   = 0
    skipped_dd = 0

    for trial in range(N_TRIALS):
        if trial % 50 == 0 and trial > 0:
            print(f"  Trial {trial}/{N_TRIALS} | validi: {valid} | skip DD: {skipped_dd}")
        params = sample_params()
        # Vincolo: tp_mult > sl_mult (garantisce RR > 1)
        if params['tp_mult'] <= params['sl_mult']: continue
        # Vincolo: ema_fast < ema_slow
        if params['ema_fast'] >= params['ema_slow']: continue

        session    = SESSION_DEF
        extr_mult  = 3.5
        if args.global_opt:
            g = sample_global()
            session   = (g['session_start'], g['session_end'])
            extr_mult = g['extreme_mult']
            params['session']       = list(session)
            params['extreme_mult']  = extr_mult

        r = run_backtest(candles, params, session=session, extreme_mult=extr_mult)
        if r is None: continue

        # Vincolo MaxDD
        if r['dd_pct'] > MAX_DD_PCT*100:
            skipped_dd += 1; continue

        valid += 1
        results.append({'params': dict(params), 'result': r})

    print(f"\n  Completati {N_TRIALS} trial")
    print(f"  Validi (DD≤{MAX_DD_PCT*100:.0f}%): {valid}")
    print(f"  Scartati per DD: {skipped_dd}")

    if not results:
        print("\nNessun risultato valido. Prova ad aumentare --max-dd o --n-trials.")
        return

    # ── RANKING ───────────────────────────────────────────────────────────────
    results.sort(key=lambda x: x['result']['score'], reverse=True)
    top10 = results[:10]

    print(f"\n{'='*65}")
    print("TOP 10 CONFIGURAZIONI (score = PF × √trade × dd_factor)")
    print(f"{'='*65}")
    header = f"{'#':<3} {'Score':<8} {'PF':<7} {'WR%':<7} {'Trade':<7} {'P&L':>8} {'DD%':<7} {'tp×':<5} {'sl×':<5} {'OBw':<5} {'EMA':<10} {'Mode'}"
    print(header)
    print("─"*90)
    for rank, r in enumerate(top10, 1):
        p = r['params']; s = r['result']
        ema_str = f"{p['ema_fast']}/{p['ema_slow']}"
        mode    = "OR" if p.get('relax') else "AND"
        sess    = f" {p['session'][0]}-{p['session'][1]}h" if 'session' in p else ""
        print(f"{rank:<3} {s['score']:<8.2f} {s['pf']:<7.3f} {s['wr']:<7} {s['trades']:<7} "
              f"${s['pnl']:>7.2f} {s['dd_pct']:<7.1f} {p['tp_mult']:<5} {p['sl_mult']:<5} "
              f"{p['ob_lookback']:<5} {ema_str:<10} {mode}{sess}")

    # ── BEST CONFIG ───────────────────────────────────────────────────────────
    best = top10[0]
    bp   = best['params']
    br   = best['result']
    print(f"\n{'='*65}")
    print("★ CONFIGURAZIONE OTTIMALE")
    print(f"{'='*65}")
    print(f"  tp_mult     : {bp['tp_mult']}")
    print(f"  sl_mult     : {bp['sl_mult']}")
    print(f"  ob_lookback : {bp['ob_lookback']}")
    print(f"  ema_fast    : {bp['ema_fast']}")
    print(f"  ema_slow    : {bp['ema_slow']}")
    print(f"  mode        : {'RELAX (OB OR FVG)' if bp.get('relax') else 'STRICT (OB AND FVG)'}")
    if 'session' in bp:
        print(f"  session     : {bp['session'][0]}:00 - {bp['session'][1]}:00 UTC")
    if 'extreme_mult' in bp:
        print(f"  extreme_mult: {bp['extreme_mult']}")
    print(f"\n  → Trade 12m (stima): {br['trades']}")
    print(f"  → WR             : {br['wr']}%")
    print(f"  → PF             : {br['pf']}")
    print(f"  → P&L stimato    : ${br['pnl']:+.2f}")
    print(f"  → Max DD         : {br['dd_pct']}% (vincolo: {MAX_DD_PCT*100:.0f}%)")
    print(f"  → Score          : {br['score']}")

    # ── RR e atteso ───────────────────────────────────────────────────────────
    rr = round(bp['tp_mult']/bp['sl_mult'], 2)
    min_wr_break = round(1/(1+rr)*100, 1)
    print(f"\n  RR = {rr}:1 → WR minima di break-even: {min_wr_break}%")
    print(f"  {'✅ WR>' if br['wr']>min_wr_break else '⚠️ WR<'} {min_wr_break}% break-even "
          f"({'profittevole' if br['wr']>min_wr_break else 'NON profittevole a lungo termine'})")

    # ── SALVA OUTPUT ──────────────────────────────────────────────────────────
    output = {
        'generated':    datetime.datetime.utcnow().isoformat(),
        'strategy':     'S10_OB_FVG_SCALP',
        'n_trials':     N_TRIALS,
        'max_dd_pct':   MAX_DD_PCT,
        'best':         best,
        'top10':        top10,
        'apply_to_bot': {
            'tp_mult':    bp['tp_mult'],
            'sl_mult':    bp['sl_mult'],
            'ob_lookback': bp['ob_lookback'],
            'ema_fast':   bp['ema_fast'],
            'ema_slow':   bp['ema_slow'],
            'relax':      bp.get('relax', False),
            'session':    bp.get('session', list(SESSION_DEF)),
            'extreme_mult': bp.get('extreme_mult', 3.5),
        }
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Risultati salvati in: {args.out}")
    print("\nProssimi passi:")
    print("  1. Verifica i parametri ottimali in optimized_params.json")
    print("  2. Aggiorna STRATEGY_PARAMS e calc_order_blocks in mt5-bot.py")
    print("  3. Riavvia il bot: python -X utf8 scripts/mt5-bot.py")
    print("  4. Dopo 2 settimane live, ri-ottimizza con dati freschi")

    if args.mt5:
        try:
            import MetaTrader5 as mt5; mt5.shutdown()
        except Exception: pass

if __name__ == '__main__':
    main()
