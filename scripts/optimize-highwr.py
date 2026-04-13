"""
MFKK High-WR Optimizer
========================
Obiettivo: trovare le condizioni che portano a WR >= 75-80% su XAU H1.

Approccio: non uno score generico ma filtri HARD cumulativi:
  1. ADX molto forte (>=30, >=35) con DI spread ampio (>10, >15)
  2. MACD in exhaustion (opposto alla direzione) oppure confermante
  3. CCI zone specifica
  4. Filtro orario sessioni (London/NY = ore 7-17 UTC)
  5. Conferma candle: la candela corrente deve chiudere in direzione del trade
  6. Distanza da ultimo trade della stessa direzione

Metodologia: per ogni combinazione di filtri, calcola:
  - n. trade, WR, P&L, Profit Factor, Max DD
  - "quality score" = WR * PF (vuole sia WR alta che edge reale)
"""

import urllib.request, json, time, sys, io, datetime
from collections import defaultdict

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DAYS = 730
TP_USD = 20.0
SL_USD = 12.0

# ─── FETCH ───────────────────────────────────────────────────────────────────
def fetch_candles(symbol, days):
    all_candles = []
    now = int(time.time())
    start = now - days * 86400
    for from_t in range(start, now, 59 * 86400):
        to_t = min(from_t + 59 * 86400, now)
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&period1={from_t}&period2={to_t}"
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
                rs = d.get('chart',{}).get('result',[None])[0]
                if not rs or not rs.get('timestamp'): continue
                q = rs.get('indicators',{}).get('quote',[{}])[0]
                for i,t in enumerate(rs['timestamp']):
                    c=q.get('close',[]); h=q.get('high',[]); l=q.get('low',[]); o=q.get('open',[])
                    if i<len(c) and c[i] and i<len(h) and h[i] and i<len(l) and l[i]:
                        all_candles.append({'t':t,'o':o[i] if i<len(o) else c[i],'h':h[i],'l':l[i],'c':c[i]})
        except: pass
    seen=set(); unique=[]
    for c in all_candles:
        if c['t'] not in seen: seen.add(c['t']); unique.append(c)
    unique.sort(key=lambda x:x['t'])
    return unique

# ─── INDICATORI ───────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; out=[v]
    for x in src[1:]: v=x*k+out[-1]*(1-k); out.append(v)
    return out

def sma(src, p):
    out=[None]*len(src)
    for i in range(p-1,len(src)):
        sl=src[i-p+1:i+1]
        out[i]=None if None in sl else sum(sl)/p
    return out

def calc_indicators(candles):
    n=len(candles)
    H=[x['h'] for x in candles]; L=[x['l'] for x in candles]; C=[x['c'] for x in candles]

    # CCI_S
    CCI_P,STOCH_P,SK,SD=50,50,8,8
    cci=[None]*n
    for i in range(CCI_P-1,n):
        sl=C[i-CCI_P+1:i+1]; mn=sum(sl)/CCI_P
        md=sum(abs(x-mn) for x in sl)/CCI_P
        cci[i]=0.0 if md==0 else (C[i]-mn)/(0.015*md)
    stk=[None]*n
    for i in range(CCI_P+STOCH_P-2,n):
        if cci[i] is None: continue
        w=[cci[j] for j in range(i-STOCH_P+1,i+1) if cci[j] is not None]
        if not w: continue
        lv,hv=min(w),max(w)
        stk[i]=50.0 if hv==lv else ((cci[i]-lv)/(hv-lv))*100
    stk_k=sma(stk,SK); stk_d=sma(stk_k,SD)
    # Precedenti per crossover
    stk_d_prev=[None]+stk_d[:-1]

    # MACD
    e12=ema(C,12); e26=ema(C,26)
    macd=[e12[i]-e26[i] for i in range(n)]
    signal=ema(macd,9)
    hist=[macd[i]-signal[i] for i in range(n)]
    hist_prev=[0.0]+hist[:-1]

    # ADX
    AP=10
    TR=[0.0]*n; DMP=[0.0]*n; DMM=[0.0]*n
    for i in range(1,n):
        TR[i]=max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
        up=H[i]-H[i-1]; dn=L[i-1]-L[i]
        DMP[i]=up if up>dn and up>0 else 0.0
        DMM[i]=dn if dn>up and dn>0 else 0.0
    sTR=[0.0]*n; sDMP=[0.0]*n; sDMM=[0.0]*n
    for i in range(1,n):
        sTR[i]=sTR[i-1]-sTR[i-1]/AP+TR[i]
        sDMP[i]=sDMP[i-1]-sDMP[i-1]/AP+DMP[i]
        sDMM[i]=sDMM[i-1]-sDMM[i-1]/AP+DMM[i]
    DIP=[sDMP[i]/sTR[i]*100 if sTR[i]>0 else 0.0 for i in range(n)]
    DIM=[sDMM[i]/sTR[i]*100 if sTR[i]>0 else 0.0 for i in range(n)]
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0.0 for i in range(n)]
    ADX=sma(DX,AP)

    # ATR(14)
    TR14=[0.0]*n
    for i in range(1,n):
        TR14[i]=max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
    ATR=sma(TR14,14)

    # EMA200 per trend macro
    e200=ema(C,200)

    return {
        'stk_d':stk_d,'stk_d_prev':stk_d_prev,
        'macd':macd,'signal':signal,'hist':hist,'hist_prev':hist_prev,
        'ADX':ADX,'DIP':DIP,'DIM':DIM,'C':C,'H':H,'L':L,
        'ATR':ATR,'EMA200':e200, 'candles_ref': candles
    }

# ─── FILTRI SPECIFICI ─────────────────────────────────────────────────────────
def check_entry(inds, i, direction, filters):
    """
    Verifica tutti i filtri per un potenziale entry alla barra i.
    Ritorna True se tutti i filtri passano.
    """
    cci_v  = inds['stk_d'][i]
    macd_v = inds['macd'][i]
    sig_v  = inds['signal'][i]
    hist_v = inds['hist'][i]
    hist_p = inds['hist_prev'][i]
    adx_v  = inds['ADX'][i]
    dip    = inds['DIP'][i]
    dim    = inds['DIM'][i]
    price  = inds['C'][i]
    e200   = inds['EMA200'][i]
    atr_v  = inds['ATR'][i]
    t      = inds['candles_ref'][i]['t']

    if cci_v is None or adx_v is None or atr_v is None:
        return False

    is_sell = direction == 'sell'
    diff    = macd_v - sig_v
    di_spread = abs(dip - dim)
    di_aligned = (dim > dip) if is_sell else (dip > dim)

    # Ora UTC per filtro sessione
    hour = datetime.datetime.utcfromtimestamp(t).hour

    # ── Filtro 1: ADX minimo ──────────────────────────────────────────
    if adx_v < filters['adx_min']:
        return False

    # ── Filtro 2: DI spread minimo ───────────────────────────────────
    if di_spread < filters['di_spread_min']:
        return False

    # ── Filtro 3: DI allineato alla direzione ────────────────────────
    if not di_aligned:
        return False

    # ── Filtro 4: MACD mode ──────────────────────────────────────────
    macd_mode = filters.get('macd_mode', 'any')
    if macd_mode == 'exhaustion':
        # MACD opposto alla direzione del trade (il segnale più forte)
        if is_sell and diff <= 0: return False   # SELL richiede MACD bullish
        if not is_sell and diff >= 0: return False  # BUY richiede MACD bearish
        if abs(diff) < filters.get('macd_diff_min', 0.5): return False
    elif macd_mode == 'aligned':
        # MACD confermante (stesso senso del trade)
        if is_sell and diff >= 0: return False
        if not is_sell and diff <= 0: return False
    elif macd_mode == 'exhaustion_or_crossover':
        # Exhaustion OPPURE crossover in direzione
        exhaustion = (is_sell and diff > 0.5) or (not is_sell and diff < -0.5)
        crossover  = (is_sell and hist_v < 0 and hist_p >= 0) or \
                     (not is_sell and hist_v > 0 and hist_p <= 0)
        if not exhaustion and not crossover: return False
    # 'any' = nessun filtro MACD

    # ── Filtro 5: CCI zone ───────────────────────────────────────────
    cci_filter = filters.get('cci_filter', 'any')
    if cci_filter == 'ob_deep' and (not is_sell or cci_v < 65): return False
    if cci_filter == 'os_deep' and (is_sell or cci_v > 35): return False
    if cci_filter == 'ob_or_neutral' and is_sell and cci_v < 40: return False
    if cci_filter == 'extreme':
        if is_sell and cci_v < 65: return False
        if not is_sell and cci_v > 35: return False

    # ── Filtro 6: sessione oraria ────────────────────────────────────
    session = filters.get('session', 'all')
    if session == 'london_ny' and not (7 <= hour <= 16): return False
    if session == 'london'    and not (7 <= hour <= 12): return False
    if session == 'ny'        and not (13 <= hour <= 20): return False
    if session == 'no_asian'  and (22 <= hour or hour <= 6): return False

    # ── Filtro 7: EMA200 macro trend ────────────────────────────────
    ema_filter = filters.get('ema200_filter', 'off')
    if ema_filter == 'on':
        if is_sell and price > e200 * 1.02: return False  # non SELL in macro bull
        if not is_sell and price < e200 * 0.98: return False

    # ── Filtro 8: conferma candle (chiude nella direzione) ───────────
    candle_confirm = filters.get('candle_confirm', False)
    if candle_confirm:
        candle = inds['candles_ref'][i]
        bearish_close = candle['c'] < candle['o']
        bullish_close = candle['c'] > candle['o']
        if is_sell and not bearish_close: return False
        if not is_sell and not bullish_close: return False

    # ── Filtro 9: ATR minimo (evita mercato troppo calmo) ────────────
    atr_min = filters.get('atr_min', 0)
    if atr_v < atr_min: return False

    return True

# ─── BACKTEST CON FILTRI HARD ─────────────────────────────────────────────────
def run_filtered_backtest(inds, filters, direction='both', tp=TP_USD, sl=SL_USD):
    C=inds['C']; n=len(C)
    trades=[]; ot=None; START=210

    for i in range(START, n):
        price=C[i]
        if inds['ADX'][i] is None: continue

        # Gestione trade aperto
        if ot:
            h=inds['H'][i]; l=inds['L'][i]
            if ot['d']=='sell':
                if h >= ot['e']+sl:
                    trades.append({**ot,'pnl':-sl,'result':'SL','bar_exit':i})
                    ot=None
                elif l <= ot['e']-tp:
                    trades.append({**ot,'pnl':tp,'result':'TP','bar_exit':i})
                    ot=None
            else:
                if l <= ot['e']-sl:
                    trades.append({**ot,'pnl':-sl,'result':'SL','bar_exit':i})
                    ot=None
                elif h >= ot['e']+tp:
                    trades.append({**ot,'pnl':tp,'result':'TP','bar_exit':i})
                    ot=None
            continue

        # Valuta entry
        for d in (['sell','buy'] if direction=='both' else [direction]):
            if check_entry(inds, i, d, filters):
                ot={'d':d,'e':price,'bar':i}
                break  # una direzione alla volta

    return trades

def stats(trades, min_n=20):
    closed=[t for t in trades if t.get('result') in ('TP','SL')]
    if len(closed) < min_n: return None
    wins=[t for t in closed if t['pnl']>0]
    losses=[t for t in closed if t['pnl']<0]
    pnl=sum(t['pnl'] for t in closed)
    gp=sum(t['pnl'] for t in wins); gl=abs(sum(t['pnl'] for t in losses))
    pf=gp/gl if gl>0 else (999 if gp>0 else 0)
    wr=len(wins)/len(closed)*100
    eq=0; peak=0; maxdd=0
    for t in closed:
        eq+=t['pnl']; peak=max(peak,eq); maxdd=max(maxdd,peak-eq)
    sells=[t for t in closed if t['d']=='sell']
    buys=[t for t in closed if t['d']=='buy']
    swr=len([t for t in sells if t['pnl']>0])/len(sells)*100 if sells else 0
    bwr=len([t for t in buys if t['pnl']>0])/len(buys)*100 if buys else 0
    return {'n':len(closed),'wr':round(wr,1),'pnl':round(pnl,2),'pf':round(pf,3),
            'maxdd':round(maxdd,2),'sn':len(sells),'bn':len(buys),
            'swr':round(swr,1),'bwr':round(bwr,1)}

# ─── GRID SEARCH FILTRI ───────────────────────────────────────────────────────
def main():
    print("MFKK High-WR Optimizer — obiettivo WR >= 75%")
    print("="*60)
    print("Download candele...")
    candles=fetch_candles('GC%3DF', DAYS)
    print(f"  {len(candles)} candele")
    if len(candles)<500: print("ERRORE dati"); return

    print("Calcolo indicatori...\n")
    inds=calc_indicators(candles)

    # ── FASE 1: Solo SELL, filtri progressivi ────────────────────────────────
    print("FASE 1: SELL ONLY — grid search filtri progressivi")
    print("-"*60)

    results = []
    combos = [
        # ADX_min, DI_spread, MACD_mode, CCI_filter, session, candle_confirm, ema200
        (25, 8,  'any',                  'any',          'all',       False, 'off'),
        (25, 10, 'any',                  'any',          'all',       False, 'off'),
        (25, 12, 'exhaustion',           'any',          'all',       False, 'off'),
        (25, 15, 'exhaustion',           'any',          'all',       False, 'off'),
        (28, 10, 'exhaustion',           'any',          'all',       False, 'off'),
        (28, 12, 'exhaustion',           'any',          'no_asian',  False, 'off'),
        (28, 15, 'exhaustion',           'any',          'london_ny', False, 'off'),
        (28, 15, 'exhaustion',           'ob_or_neutral','london_ny', False, 'off'),
        (30, 10, 'exhaustion',           'any',          'all',       False, 'off'),
        (30, 12, 'exhaustion',           'any',          'no_asian',  False, 'off'),
        (30, 15, 'exhaustion',           'any',          'london_ny', False, 'off'),
        (30, 15, 'exhaustion',           'ob_or_neutral','london_ny', False, 'off'),
        (30, 15, 'exhaustion',           'ob_deep',      'london_ny', False, 'off'),
        (30, 20, 'exhaustion',           'any',          'all',       False, 'off'),
        (30, 20, 'exhaustion',           'ob_or_neutral','london_ny', False, 'off'),
        (32, 12, 'exhaustion',           'any',          'all',       False, 'off'),
        (32, 15, 'exhaustion',           'any',          'london_ny', False, 'off'),
        (32, 15, 'exhaustion',           'ob_or_neutral','london_ny', False, 'off'),
        (35, 10, 'exhaustion',           'any',          'all',       False, 'off'),
        (35, 12, 'exhaustion',           'any',          'all',       False, 'off'),
        (35, 12, 'exhaustion',           'any',          'no_asian',  False, 'off'),
        (35, 15, 'exhaustion',           'any',          'all',       False, 'off'),
        (35, 15, 'exhaustion',           'any',          'london_ny', False, 'off'),
        (35, 15, 'exhaustion',           'ob_or_neutral','london_ny', False, 'off'),
        (35, 15, 'exhaustion',           'ob_deep',      'all',       False, 'off'),
        (35, 15, 'exhaustion',           'ob_deep',      'london_ny', False, 'off'),
        (35, 20, 'exhaustion',           'any',          'all',       False, 'off'),
        (35, 20, 'exhaustion',           'ob_or_neutral','london_ny', False, 'off'),
        (35, 20, 'exhaustion',           'ob_deep',      'london_ny', False, 'off'),
        (35, 10, 'exhaustion_or_crossover','any',        'all',       False, 'off'),
        (35, 15, 'exhaustion_or_crossover','any',        'london_ny', False, 'off'),
        (35, 15, 'aligned',              'any',          'all',       False, 'off'),
        (35, 15, 'aligned',              'any',          'london_ny', False, 'off'),
        # Con candle confirm
        (30, 12, 'exhaustion',           'any',          'all',       True,  'off'),
        (30, 15, 'exhaustion',           'any',          'london_ny', True,  'off'),
        (35, 12, 'exhaustion',           'any',          'all',       True,  'off'),
        (35, 15, 'exhaustion',           'any',          'london_ny', True,  'off'),
        (35, 15, 'exhaustion',           'ob_or_neutral','london_ny', True,  'off'),
        (35, 20, 'exhaustion',           'ob_or_neutral','london_ny', True,  'off'),
        # MACD diff min più alto
        (30, 12, 'exhaustion',           'any',          'all',       False, 'off'),
        (35, 15, 'exhaustion',           'any',          'all',       False, 'off'),
    ]

    for adx_min,di_sp,macd_mode,cci_f,sess,cc,ema_f in combos:
        filters={
            'adx_min':adx_min,'di_spread_min':di_sp,'macd_mode':macd_mode,
            'cci_filter':cci_f,'session':sess,'candle_confirm':cc,
            'ema200_filter':ema_f,'macd_diff_min':0.5
        }
        trades=run_filtered_backtest(inds, filters, direction='sell', tp=TP_USD, sl=SL_USD)
        s=stats(trades, min_n=15)
        if s:
            quality=s['wr']*s['pf']
            results.append({**filters,'**s':s,'quality':quality,
                'label':f"ADX>={adx_min} DI>={di_sp} {macd_mode} CCI={cci_f} {sess} cc={'Y' if cc else 'N'}"})

    results.sort(key=lambda x:x['quality'],reverse=True)

    print(f"\nTOP 15 SELL (ordinati per WR x PF):")
    print(f"{'ADX':>4}{'DI':>4}{'MACD':<26}{'CCI':<16}{'Sess':<12}{'CC':>3} | {'N':>5}{'WR%':>7}{'PnL':>9}{'PF':>6}{'DD':>8}")
    print("-"*100)
    for r in results[:15]:
        s=r['**s']
        cc='Y' if r['candle_confirm'] else 'N'
        print(f"{r['adx_min']:>4}{r['di_spread_min']:>4}{r['macd_mode']:<26}{r['cci_filter']:<16}{r['session']:<12}{cc:>3} | "
              f"{s['n']:>5}{s['wr']:>6.1f}%{s['pnl']:>9.1f}{s['pf']:>6.3f}{s['maxdd']:>8.1f}")

    # ── FASE 2: Combo BUY + SELL con filtri stretti ──────────────────────────
    print("\n\nFASE 2: BUY + SELL separati con i migliori filtri")
    print("-"*60)

    best_sell_filters = results[0]  # miglior filtro SELL

    # Test BUY con filtri diversi (exhaustion bearish)
    buy_combos = [
        (30, 10, 'exhaustion', 'any',     'all',      False),
        (30, 12, 'exhaustion', 'any',     'london_ny',False),
        (35, 10, 'exhaustion', 'any',     'all',      False),
        (35, 12, 'exhaustion', 'any',     'london_ny',False),
        (35, 10, 'aligned',    'any',     'all',      False),
        (35, 12, 'aligned',    'any',     'london_ny',False),
        (35, 10, 'aligned',    'os_deep', 'all',      False),
        (35, 10, 'aligned',    'os_deep', 'london_ny',False),
    ]

    buy_results=[]
    for adx_min,di_sp,macd_mode,cci_f,sess,cc in buy_combos:
        filters={'adx_min':adx_min,'di_spread_min':di_sp,'macd_mode':macd_mode,
                 'cci_filter':cci_f,'session':sess,'candle_confirm':cc,
                 'ema200_filter':'off','macd_diff_min':0.5}
        trades=run_filtered_backtest(inds,filters,direction='buy',tp=TP_USD,sl=SL_USD)
        s=stats(trades,min_n=10)
        if s:
            buy_results.append({**filters,'**s':s,
                'label':f"ADX>={adx_min} DI>={di_sp} {macd_mode} CCI={cci_f} {sess}"})

    buy_results.sort(key=lambda x:x['**s']['wr'],reverse=True)
    print("\nTOP 5 BUY:")
    for r in buy_results[:5]:
        s=r['**s']
        print(f"  {r['label']}: N={s['n']} WR={s['wr']}% PnL={s['pnl']} PF={s['pf']}")

    # ── FASE 3: MACD diff_min sweep per massimizzare WR SELL ─────────────────
    print("\n\nFASE 3: Sweep MACD exhaustion min_diff (miglior ADX/DI config)")
    print("-"*60)
    best_f = results[0]
    diff_results=[]
    for diff_min in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0]:
        filters={**best_f,'macd_diff_min':diff_min}
        trades=run_filtered_backtest(inds,filters,direction='sell',tp=TP_USD,sl=SL_USD)
        s=stats(trades,min_n=10)
        if s:
            diff_results.append({'diff_min':diff_min,**s})
            print(f"  MACD diff>={diff_min:.1f}: N={s['n']:4} WR={s['wr']:5.1f}% PnL={s['pnl']:8.1f} PF={s['pf']:.3f}")

    # ── FASE 4: TP/SL ottimali per la best config High-WR ────────────────────
    print("\n\nFASE 4: TP/SL sweep sulla best config")
    print("-"*60)
    tp_sl_results=[]
    best_filters = results[0]
    for tp_v,sl_v in [(12,8),(15,9),(15,10),(18,10),(20,12),(25,12),(25,15),(30,15),(30,18)]:
        trades=run_filtered_backtest(inds,best_filters,direction='sell',tp=tp_v,sl=sl_v)
        s=stats(trades,min_n=15)
        if s:
            rr=tp_v/sl_v
            tp_sl_results.append({'tp':tp_v,'sl':sl_v,'rr':round(rr,2),**s})
            print(f"  TP={tp_v:3} SL={sl_v:2} R:R={rr:.2f}: N={s['n']:4} WR={s['wr']:5.1f}% PnL={s['pnl']:8.1f} PF={s['pf']:.3f}")

    # ── RIEPILOGO FINALE ─────────────────────────────────────────────────────
    print("\n\n" + "="*60)
    print("CONFIGURAZIONE HIGH-WR FINALE")
    print("="*60)

    # La migliore per WR
    best_wr = sorted(results, key=lambda x:x['**s']['wr'], reverse=True)[0]
    # La migliore per qualità (WR x PF)
    best_q  = results[0]

    for label, b in [("BEST WR", best_wr), ("BEST QUALITY (WR x PF)", best_q)]:
        s=b['**s']
        print(f"\n--- {label} ---")
        print(f"  ADX>={b['adx_min']}, DI spread>={b['di_spread_min']}, MACD={b['macd_mode']}")
        print(f"  CCI={b['cci_filter']}, Session={b['session']}, CandleConfirm={b['candle_confirm']}")
        print(f"  N={s['n']}, WR={s['wr']}%, PnL=${s['pnl']}, PF={s['pf']}, MaxDD=${s['maxdd']}")
        print(f"  SELL: {s['sn']} trades WR={s['swr']}% | BUY: {s['bn']} trades WR={s['bwr']}%")

    # Salva config
    out={'generated':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
         'best_quality':{'filters':{k:v for k,v in best_q.items() if k not in ('**s','quality','label')},
                         'results':best_q['**s']},
         'best_wr':{'filters':{k:v for k,v in best_wr.items() if k not in ('**s','quality','label')},
                    'results':best_wr['**s']},
         'all_top15':[{'filters':{k:v for k,v in r.items() if k not in ('**s','quality','label')},
                       'results':r['**s']} for r in results[:15]]}
    with open('highwr_config.json','w') as f: json.dump(out,f,indent=2)
    print("\n  Config salvata: highwr_config.json")
    print("  OTTIMIZZAZIONE HIGH-WR COMPLETATA!")

if __name__=='__main__':
    main()
