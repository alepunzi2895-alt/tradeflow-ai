#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — S10_OB_FVG_SCALP Backtest
=========================================
Testa "ICT Order Block + FVG Confluence Scalping" su M5, M15, M30, H1.

Logica:
  LONG : EMA20 > EMA50 + price in Bullish OB zone + Bull FVG attivo + candle bullish
  SHORT: EMA20 < EMA50 + price in Bearish OB zone + Bear FVG attivo + candle bearish
  TP = 1.0 × ATR(14) | SL = 0.6 × ATR(14)

USO:
  python scripts/backtest_ob_fvg_scalp.py --mt5            # dati dal broker live
  python scripts/backtest_ob_fvg_scalp.py --m15-file f.json
  python scripts/backtest_ob_fvg_scalp.py --mt5 --relax    # versione OR (ob OR fvg)
"""
import sys, io, os, json, math, argparse, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── ARGS ──────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument('--mt5',   action='store_true', help='Fetch dati live da MT5')
ap.add_argument('--m5-file',  default='data/xauusd_m5_mt5.json')
ap.add_argument('--m15-file', default='data/xauusd_m15_mt5.json')
ap.add_argument('--m30-file', default='data/xauusd_m30_mt5.json')
ap.add_argument('--h1-file',  default='data/xauusd_h1_mt5.json')
ap.add_argument('--bars', type=int, default=5000, help='Barre da scaricare per TF')
ap.add_argument('--out',  default='backtest_ob_fvg_scalp.json')
ap.add_argument('--relax', action='store_true', help='Usa versione OR (ob OR fvg) invece di AND')
args = ap.parse_args()

TP_MULT   = 1.0
SL_MULT   = 0.6
WARMUP    = 200   # barre iniziali saltate
SESSION   = (7, 17)  # ore UTC operative
MAX_BARS_TRADE = 120  # max barre per risolvere un trade prima di timeout

# ── MATH ──────────────────────────────────────────────────────────────────────
def ema(src, p):
    k = 2/(p+1); v = src[0]; o = [v]
    for x in src[1:]:
        v = x*k + v*(1-k); o.append(v)
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

# ── ORDER BLOCK DETECTION ─────────────────────────────────────────────────────
def calc_order_blocks(O, H, L, C, lookback=20):
    """
    Bullish OB: ultima candela bearish (C<O) prima di un'impulso rialzista
                (almeno 2 barre bullish consecutive dopo), non ancora mitigato.
                Prezzo corrente torna nella zona del corpo dell'OB.
    Bearish OB: opposto.
    Returns: (ob_bull[i], ob_bear[i]) — bool lists
    """
    n = len(C)
    ob_bull = [False]*n
    ob_bear = [False]*n

    # Precomputa running min/max per verifica mitigazione efficiente
    # run_min_lo[j] = min(L[j:i]) - aggiornato per ogni i nel loop principale
    # Non precomputiamo per semplicità: uso slice diretto (OK per <=10k barre)

    for i in range(lookback + 4, n):
        c_now = C[i]; o_now = O[i]

        # ── Cerca OB Bullish ──────────────────────────────────────────────────
        for j in range(i - 3, max(i - lookback - 1, 2), -1):
            if C[j] >= O[j]: continue               # deve essere bearish
            ob_lo = min(O[j], C[j])
            ob_hi = max(O[j], C[j])
            # L'impulso dopo l'OB: almeno 2 barre bullish
            if not (j + 2 < n and C[j+1] > O[j+1] and C[j+2] > O[j+2]): continue
            # OB mitigato se prezzo è sceso sotto ob_lo nel frattempo
            if any(L[k] < ob_lo * 0.999 for k in range(j+1, i)): continue
            # Prezzo corrente deve rientrare nel corpo dell'OB
            if ob_lo * 0.999 <= c_now <= ob_hi * 1.002:
                ob_bull[i] = True
                break

        # ── Cerca OB Bearish ─────────────────────────────────────────────────
        for j in range(i - 3, max(i - lookback - 1, 2), -1):
            if C[j] <= O[j]: continue               # deve essere bullish
            ob_lo = min(O[j], C[j])
            ob_hi = max(O[j], C[j])
            # Impulso bearish dopo
            if not (j + 2 < n and C[j+1] < O[j+1] and C[j+2] < O[j+2]): continue
            # OB mitigato se prezzo ha bucato sopra ob_hi
            if any(H[k] > ob_hi * 1.001 for k in range(j+1, i)): continue
            # Prezzo corrente rientra nel corpo
            if ob_lo * 0.998 <= c_now <= ob_hi * 1.001:
                ob_bear[i] = True
                break

    return ob_bull, ob_bear

# ── FVG DETECTION ─────────────────────────────────────────────────────────────
def calc_fvg(O, H, L, C, std_len=100, df=2):
    """
    Bull FVG: L[i] > H[i-2] — gap rialzista non ancora riempito
    Bear FVG: H[i] < L[i-2] — gap ribassista non ancora riempito
    Identico a mt5-bot.py / backtest_combined.py
    """
    n = len(C)
    body = [abs(O[i]-C[i]) for i in range(n)]
    bs = stdev_arr(body, std_len)
    fb = [False]*n; fs = [False]*n
    ab = []; as_ = []

    for i in range(2, n):
        disp = (bs[i-1] is not None and bs[i-1] > 0 and body[i-1] > bs[i-1]*df)
        if L[i] > H[i-2]: ab.append({'lo': H[i-2], 'hi': L[i], 'bar': i, 'd': disp})
        if H[i] < L[i-2]: as_.append({'lo': H[i], 'hi': L[i-2], 'bar': i, 'd': disp})
        # Bull FVG: check se prezzo è in zona
        sb = []
        for fvg in ab:
            if fvg['bar'] == i: sb.append(fvg); continue
            if L[i] < fvg['lo']: continue  # FVG invalidato
            if fvg['lo'] <= C[i] <= fvg['hi']: fb[i] = True
            sb.append(fvg)
        ab = sb[-20:]
        # Bear FVG
        sb2 = []
        for fvg in as_:
            if fvg['bar'] == i: sb2.append(fvg); continue
            if H[i] > fvg['hi']: continue  # FVG invalidato
            if fvg['lo'] <= C[i] <= fvg['hi']: fs[i] = True
            sb2.append(fvg)
        as_ = sb2[-20:]

    return fb, fs

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute_ind(candles):
    O = [c['o'] for c in candles]; H = [c['h'] for c in candles]
    L = [c['l'] for c in candles]; C = [c['c'] for c in candles]
    V = [c.get('v', 0) for c in candles]
    n = len(C)
    I = {'O':O, 'H':H, 'L':L, 'C':C, 'V':V, 'n':n}
    I['e20']  = ema(C, 20)
    I['e50']  = ema(C, 50)
    I['atr']  = atr14(H, L, C)
    # ATR 30-bar average (per filtro extreme)
    I['atr30'] = [None]*n
    for i in range(30, n):
        vs = [I['atr'][j] for j in range(i-30, i) if I['atr'][j] is not None]
        I['atr30'][i] = sum(vs)/len(vs) if vs else None
    print("  Calcolo OB zones...")
    I['ob_bull'], I['ob_bear'] = calc_order_blocks(O, H, L, C)
    print("  Calcolo FVG zones...")
    I['fvg_bull'], I['fvg_bear'] = calc_fvg(O, H, L, C)
    return I

# ── SIGNAL ────────────────────────────────────────────────────────────────────
def s_ob_fvg_scalp(I, i, relax=False):
    """
    S10_OB_FVG_SCALP:
      STRICT (default): EMA trend + OB zone AND FVG attivo + candle confirm
      RELAX:            EMA trend + OB zone OR  FVG attivo + candle confirm
    """
    e20 = I['e20'][i]; e50 = I['e50'][i]
    if None in (e20, e50): return None

    ob_b  = I['ob_bull'][i];  ob_s  = I['ob_bear'][i]
    fvg_b = I['fvg_bull'][i]; fvg_s = I['fvg_bear'][i]
    C = I['C']; O = I['O']
    bull_candle = C[i] > O[i]
    bear_candle = C[i] < O[i]

    if relax:
        if e20 > e50 and (ob_b or fvg_b) and bull_candle: return 'buy'
        if e20 < e50 and (ob_s or fvg_s) and bear_candle: return 'sell'
    else:
        if e20 > e50 and ob_b and fvg_b and bull_candle: return 'buy'
        if e20 < e50 and ob_s and fvg_s and bear_candle: return 'sell'
    return None

# ── DATA LOADING ─────────────────────────────────────────────────────────────
def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        candles = d.get('candles', d) if isinstance(d, dict) else d
        for c in candles:
            if 'o' not in c:
                c['o'] = c.get('open', c.get('c', 0))
        return sorted(candles, key=lambda x: x['t'])
    except Exception as e:
        print(f"  Errore {path}: {e}")
        return []

def fetch_mt5(tf_str, n_bars):
    """Scarica N barre dal broker MT5 per il TF dato."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("  MetaTrader5 non disponibile")
        return []
    tf_map = {
        'M5':  mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        'H1':  mt5.TIMEFRAME_H1,
    }
    tf_enum = tf_map.get(tf_str, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos("GOLD", tf_enum, 0, min(n_bars, 99_999))
    if rates is None or len(rates) == 0:
        rates = mt5.copy_rates_from_pos("XAUUSD", tf_enum, 0, min(n_bars, 99_999))
    if rates is None or len(rates) == 0:
        print(f"  Nessun dato {tf_str}: {mt5.last_error()}")
        return []
    candles = []
    for r in rates:
        candles.append({
            't': int(r['time']),
            'o': float(r['open']),
            'h': float(r['high']),
            'l': float(r['low']),
            'c': float(r['close']),
            'v': float(r['tick_volume']),
        })
    return candles

def get_candles(tf_str, n_bars, json_file):
    if args.mt5:
        c = fetch_mt5(tf_str, n_bars)
        if c:
            # Salva per riuso
            out_file = f"xauusd_{tf_str.lower()}_mt5.json"
            with open(out_file, 'w', encoding='utf-8') as f:
                json.dump({'candles': c}, f)
            print(f"  {tf_str}: {len(c)} barre salvate in {out_file}")
            return c
    # Fallback JSON
    if os.path.exists(json_file):
        c = load_json(json_file)
        if c:
            print(f"  {tf_str}: {len(c)} barre da {json_file}")
            return c
    print(f"  {tf_str}: nessun dato disponibile")
    return []

# ── SINGLE-TF BACKTEST ────────────────────────────────────────────────────────
def backtest_tf(candles, tf_label, relax=False):
    """
    Simula S10_OB_FVG_SCALP su un singolo timeframe.
    1 trade alla volta, nessun cooldown, sessione UTC.
    """
    if len(candles) < WARMUP + 50:
        return None

    print(f"\n  Calcolo indicatori {tf_label} ({len(candles)} barre)...")
    I = compute_ind(candles)

    trades = []
    equity = 0.0
    max_equity = 0.0
    max_dd = 0.0
    in_trade = False
    trade_open_i = -1
    trade_dir = None
    trade_tp = trade_sl = 0.0
    trade_tp_pts = trade_sl_pts = 0.0
    trades_today = 0
    current_day = None

    for i in range(WARMUP, len(candles)-1):
        ts = candles[i]['t']
        dt = datetime.datetime.utcfromtimestamp(ts)
        day = dt.date(); hour = dt.hour

        if day != current_day:
            current_day = day; trades_today = 0

        # ── Risolvi trade aperto ──────────────────────────────────────────────
        if in_trade:
            bars_open = i - trade_open_i
            h = candles[i]['h']; l = candles[i]['l']
            hit = None
            if trade_dir == 'buy':
                if l <= trade_sl: hit = 'sl'
                elif h >= trade_tp: hit = 'tp'
            else:
                if h >= trade_sl: hit = 'sl'
                elif l <= trade_tp: hit = 'tp'
            if hit is None and bars_open >= MAX_BARS_TRADE:
                hit = 'timeout'
            if hit:
                pnl = trade_tp_pts if hit == 'tp' else (-trade_sl_pts if hit == 'sl' else 0)
                if hit == 'timeout':
                    pnl = candles[i]['c'] - candles[trade_open_i]['c']
                    if trade_dir == 'sell': pnl = -pnl
                equity += pnl
                trades[-1].update({'result': hit, 'pnl': round(pnl, 2), 'close_i': i, 'close_t': ts})
                if equity > max_equity: max_equity = equity
                dd = max_equity - equity
                if dd > max_dd: max_dd = dd
                in_trade = False
            continue  # trade in corso → non aprirne un altro

        # ── Filtri pre-segnale ────────────────────────────────────────────────
        if hour < SESSION[0] or hour >= SESSION[1]: continue
        atr_v = I['atr'][i]; atr30 = I['atr30'][i]
        if atr_v is None: continue
        if atr30 and atr_v > 3.5 * atr30: continue  # giorno estremo

        # ── Segnale ───────────────────────────────────────────────────────────
        sig = s_ob_fvg_scalp(I, i, relax=relax)
        if not sig: continue

        # ── Apri trade ────────────────────────────────────────────────────────
        entry = candles[i]['c']
        tp_pts = atr_v * TP_MULT
        sl_pts = atr_v * SL_MULT
        if sig == 'buy':
            tp_price = entry + tp_pts
            sl_price = entry - sl_pts
        else:
            tp_price = entry - tp_pts
            sl_price = entry + sl_pts

        in_trade      = True
        trade_open_i  = i
        trade_dir     = sig
        trade_tp      = tp_price
        trade_sl      = sl_price
        trade_tp_pts  = tp_pts
        trade_sl_pts  = sl_pts
        trades_today += 1
        trades.append({
            'tf': tf_label, 'dir': sig, 'open_t': ts, 'entry': round(entry, 2),
            'tp': round(tp_price, 2), 'sl': round(sl_price, 2),
            'atr': round(atr_v, 2), 'result': None, 'pnl': None,
        })

    # ── Statistiche ──────────────────────────────────────────────────────────
    closed = [t for t in trades if t['result'] is not None]
    if not closed:
        return {'tf': tf_label, 'trades': 0}

    wins = [t for t in closed if t['result'] == 'tp']
    losses = [t for t in closed if t['result'] in ('sl', 'timeout')]
    wr = len(wins)/len(closed)*100
    gross_win  = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0
    pf = gross_win / gross_loss if gross_loss > 0 else 999.0
    total_pnl  = sum(t['pnl'] for t in closed)

    # Equity curve P&L ($ equivalente, normalizzato a 0.01 lot su XAUUSD = $1/punto)
    # ATR-based → già in punti di prezzo. 1 punto XAUUSD ≈ $1 su 0.01 lot

    return {
        'tf':          tf_label,
        'trades':      len(closed),
        'wins':        len(wins),
        'losses':      len(losses),
        'wr':          round(wr, 1),
        'pf':          round(pf, 2),
        'pnl_total':   round(total_pnl, 2),
        'max_dd':      round(max_dd, 2),
        'avg_win':     round(gross_win/len(wins), 2) if wins else 0,
        'avg_loss':    round(gross_loss/len(losses), 2) if losses else 0,
        'tp_mult':     TP_MULT,
        'sl_mult':     SL_MULT,
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("="*60)
    print("TradeFlow AI — S10_OB_FVG_SCALP Backtest")
    mode = "RELAX (OB OR FVG)" if args.relax else "STRICT (OB AND FVG)"
    print(f"Versione: {mode} | TP×{TP_MULT} SL×{SL_MULT} ATR")
    print("="*60)

    if args.mt5:
        print("\nConnessione MT5...")
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                print(f"  MT5 initialize() fallito: {mt5.last_error()}")
                return
            print(f"  MT5 connesso")
        except ImportError:
            print("  MetaTrader5 non disponibile — uso file JSON")
            args.mt5 = False

    timeframes = [
        ('M5',  args.bars*4,   vars(args).get('m5_file',  'xauusd_m5_mt5.json')),
        ('M15', args.bars*2,   vars(args).get('m15_file', 'xauusd_m15_mt5.json')),
        ('M30', args.bars,     vars(args).get('m30_file', 'xauusd_m30_mt5.json')),
        ('H1',  args.bars//4,  vars(args).get('h1_file',  'xauusd_h1_mt5.json')),
    ]

    results = []
    for tf_str, n_bars, json_file in timeframes:
        print(f"\n{'─'*50}")
        print(f"Timeframe: {tf_str}")
        candles = get_candles(tf_str, n_bars, json_file)
        if not candles:
            print(f"  Salto {tf_str} — nessun dato")
            continue
        r = backtest_tf(candles, tf_str, relax=args.relax)
        if r and r.get('trades', 0) > 0:
            results.append(r)
            print(f"\n  ── Risultati {tf_str} ──────────────────────────────")
            print(f"  Trades : {r['trades']}  (W:{r['wins']} / L:{r['losses']})")
            print(f"  WR     : {r['wr']}%")
            print(f"  PF     : {r['pf']}")
            print(f"  P&L    : ${r['pnl_total']:+.2f}")
            print(f"  MaxDD  : ${r['max_dd']:.2f}")
            print(f"  AvgWin : ${r['avg_win']:.2f} | AvgLoss: ${r['avg_loss']:.2f}")
        else:
            print(f"  Nessun trade generato su {tf_str}")

    if not results:
        print("\nNessun risultato generato.")
        return

    # ── Riepilogo comparativo ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("RIEPILOGO COMPARATIVO")
    print(f"{'='*60}")
    print(f"{'TF':<6} {'Trades':<8} {'WR%':<8} {'PF':<7} {'P&L':>10} {'MaxDD':>9}")
    print("─"*52)
    best = None
    for r in results:
        star = ""
        if best is None or (r['pf'] > best['pf'] and r['trades'] >= 20):
            best = r; star = " ◄ BEST"
        print(f"  {r['tf']:<4} {r['trades']:<8} {r['wr']:<8} {r['pf']:<7} "
              f"${r['pnl_total']:>8.2f}  ${r['max_dd']:>7.2f}{star}")
    print()
    if best:
        print(f"Timeframe consigliato: {best['tf']} "
              f"(PF={best['pf']}, WR={best['wr']}%, {best['trades']} trades)")
        print(f"\n→ Per aggiungere al playbook:")
        print(f"  regime X: {{ strategy: 'S10_OB_FVG_SCALP', tf: '{best['tf']}' }}")

    # ── Salva JSON ────────────────────────────────────────────────────────────
    output = {
        'strategy': 'S10_OB_FVG_SCALP',
        'mode': 'relax' if args.relax else 'strict',
        'tp_mult': TP_MULT, 'sl_mult': SL_MULT,
        'results': results,
        'best_tf': best['tf'] if best else None,
        'generated': datetime.datetime.utcnow().isoformat(),
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nRisultati salvati in: {args.out}")

    if args.mt5:
        try:
            import MetaTrader5 as mt5
            mt5.shutdown()
        except Exception:
            pass

if __name__ == '__main__':
    main()
