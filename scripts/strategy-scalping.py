"""
TradeFlow AI — Scalping Strategy Backtester
Timeframes: 5m (60gg) · 15m (60gg) · 30m (60gg)
8 strategie scalping su XAU/USD
"""
import sys, io, json, math, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

try:
    import yfinance as yf
except ImportError:
    print("Installa yfinance: pip install yfinance"); sys.exit(1)

SYMBOL   = 'GC=F'
PERIOD   = '60d'          # max per 5m/15m su yfinance
TF_CFGS  = {
    '5m':  {'tp': 3.0,  'sl': 2.0,  'lookahead': 12, 'label': '5  min'},
    '15m': {'tp': 5.0,  'sl': 3.0,  'lookahead': 8,  'label': '15 min'},
    '30m': {'tp': 8.0,  'sl': 4.5,  'lookahead': 6,  'label': '30 min'},
}

print("TradeFlow AI — Scalping Backtester")
print(f"Timeframes: 5m · 15m · 30m  |  Periodo: {PERIOD} XAU/USD")
print("="*65)

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
def download(interval):
    df = yf.download(SYMBOL, period=PERIOD, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty: raise RuntimeError(f"No data for {interval}")
    candles = []
    for ts, row in df.iterrows():
        try:
            t = int(ts.timestamp())
            o = float(row['Open'].iloc[0] if hasattr(row['Open'],'iloc') else row['Open'])
            h = float(row['High'].iloc[0] if hasattr(row['High'],'iloc') else row['High'])
            l = float(row['Low'].iloc[0]  if hasattr(row['Low'], 'iloc') else row['Low'])
            c = float(row['Close'].iloc[0] if hasattr(row['Close'],'iloc') else row['Close'])
            v = float(row['Volume'].iloc[0] if hasattr(row['Volume'],'iloc') else row['Volume'])
            if any(math.isnan(x) for x in [o,h,l,c]): continue
            candles.append({'t':t,'o':o,'h':h,'l':l,'c':c,'v':v})
        except: pass
    return candles

print("Download dati...")
candles = {}
for tf in TF_CFGS:
    c = download(tf)
    candles[tf] = c
    print(f"  {tf}: {len(c)} candele")

# ── INDICATOR MATH ────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for i in range(1,len(src)): v=src[i]*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1,len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def rsi(src, p=14):
    n=len(src); out=[None]*n
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    l=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    if len(g)<p: return out
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p, len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def atr(H,L,C,p=14):
    tr=[0]
    for i in range(1,len(C)):
        tr.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
    return sma(tr,p)

def bb(src, p=20, mult=2.0):
    mid=sma(src,p)
    upper=[None]*len(src); lower=[None]*len(src)
    for i in range(p-1,len(src)):
        sd=math.sqrt(sum((src[i-j]-mid[i])**2 for j in range(p))/p)
        upper[i]=mid[i]+mult*sd; lower[i]=mid[i]-mult*sd
    return mid, upper, lower

def macd(src, fast=12, slow=26, sig=9):
    ef=ema(src,fast); es=ema(src,slow)
    line=[ef[i]-es[i] for i in range(len(src))]
    signal=ema(line,sig)
    hist=[line[i]-signal[i] for i in range(len(src))]
    return line, signal, hist

def adx_calc(H,L,C,p=14):
    n=len(C); TR=[0]; DMP=[0]; DMM=[0]
    for i in range(1,n):
        TR.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
        up=H[i]-H[i-1]; dn=L[i-1]-L[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    sT=[0]; sP=[0]; sM=[0]
    for i in range(1,n):
        sT.append(sT[-1]-sT[-1]/p+TR[i])
        sP.append(sP[-1]-sP[-1]/p+DMP[i])
        sM.append(sM[-1]-sM[-1]/p+DMM[i])
    DIP=[sP[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DIM=[sM[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    dx=[(abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if DIP[i]+DIM[i]>0 else 0) for i in range(n)]
    adxv=sma(dx,p)
    return adxv, DIP, DIM

def stoch_rsi(src, p=14, k=3, d=3):
    r=rsi(src,p); n=len(r); sk=[None]*n
    for i in range(p-1,n):
        chunk=[x for x in r[i-p+1:i+1] if x is not None]
        if not chunk: continue
        lo=min(chunk); hi=max(chunk)
        sk[i]=(r[i]-lo)/(hi-lo)*100 if hi>lo and r[i] is not None else 50
    sk_ema=ema([x if x is not None else 50 for x in sk],k)
    sd_ema=ema(sk_ema,d)
    return sk_ema, sd_ema

def wpr(H,L,C,p=14):
    out=[None]*len(C)
    for i in range(p-1,len(C)):
        hh=max(H[i-p+1:i+1]); ll=min(L[i-p+1:i+1])
        out[i]=-100*(hh-C[i])/(hh-ll) if hh!=ll else -50
    return out

def keltner(H,L,C,p=20,mult=2.0):
    mid=ema(C,p); a=atr(H,L,C,p)
    upper=[mid[i]+mult*a[i] if a[i] is not None else None for i in range(len(C))]
    lower=[mid[i]-mult*a[i] if a[i] is not None else None for i in range(len(C))]
    return mid, upper, lower

def vwap_daily(candles):
    out=[None]*len(candles)
    cum_pv=0; cum_v=0; cur_date=None
    for i,c in enumerate(candles):
        dt=datetime.datetime.fromtimestamp(c['t'],tz=datetime.timezone.utc).date()
        if dt!=cur_date:
            cum_pv=0; cum_v=0; cur_date=dt
        tp=(c['h']+c['l']+c['c'])/3
        cum_pv+=tp*c['v']; cum_v+=c['v']
        out[i]=cum_pv/cum_v if cum_v>0 else c['c']
    return out

def supertrend(H,L,C,p=10,mult=3.0):
    a=atr(H,L,C,p); n=len(C)
    upper=[None]*n; lower=[None]*n; st=[None]*n; dir=[0]*n
    for i in range(p,n):
        if a[i] is None: continue
        mid=(H[i]+L[i])/2
        bu=mid+mult*a[i]; bl=mid-mult*a[i]
        upper[i]=bu if upper[i-1] is None or bu<upper[i-1] or C[i-1]>upper[i-1] else upper[i-1]
        lower[i]=bl if lower[i-1] is None or bl>lower[i-1] or C[i-1]<lower[i-1] else lower[i-1]
        if st[i-1] is None or st[i-1]==upper[i-1]:
            st[i]=upper[i] if C[i]<=upper[i] else lower[i]
            dir[i]=1 if C[i]<=upper[i] else -1
        else:
            st[i]=lower[i] if C[i]>=lower[i] else upper[i]
            dir[i]=-1 if C[i]>=lower[i] else 1
    return st, dir

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute_inds(cands):
    H=[c['h'] for c in cands]
    L=[c['l'] for c in cands]
    C=[c['c'] for c in cands]
    O=[c['o'] for c in cands]
    V=[c['v'] for c in cands]
    n=len(C)
    I={}
    I['C']=C; I['H']=H; I['L']=L; I['O']=O
    I['e5']=ema(C,5); I['e8']=ema(C,8)
    I['e13']=ema(C,13); I['e20']=ema(C,20)
    I['e50']=ema(C,50); I['e200']=ema(C,200)
    I['rsi']=rsi(C,14)
    I['rsi7']=rsi(C,7)
    I['atr']=atr(H,L,C,14)
    I['atr7']=atr(H,L,C,7)
    I['bb_mid'],I['bb_up'],I['bb_dn']=bb(C,20,2.0)
    I['ml'],I['ms'],I['mh']=macd(C,12,26,9)
    I['adx'],I['dip'],I['dim']=adx_calc(H,L,C,14)
    I['sk'],I['sd']=stoch_rsi(C,14,3,3)
    I['wpr']=wpr(H,L,C,14)
    I['km'],I['ku'],I['kl']=keltner(H,L,C,20,2.0)
    I['vwap']=vwap_daily(cands)
    I['st'],I['stdir']=supertrend(H,L,C,10,3.0)
    # ATR rolling avg (30 bars)
    I['atr_avg']=[None]*n
    for i in range(30,n):
        vals=[I['atr'][j] for j in range(i-30,i) if I['atr'][j] is not None]
        I['atr_avg'][i]=sum(vals)/len(vals) if vals else None
    # EMA slope
    I['slope_e20']=[None]*n
    for i in range(3,n):
        I['slope_e20'][i]=I['e20'][i]-I['e20'][i-3]
    return I

print("\nCalcolo indicatori...")
inds = {}
for tf, c in candles.items():
    inds[tf] = compute_inds(c)
    print(f"  {tf}: OK")

# ── STRATEGY FUNCTIONS ────────────────────────────────────────────────────────
# Each returns: (signal, direction) where signal=True/False, direction='buy'/'sell'

def s_ema_cross(I, i):
    """EMA5 x EMA8 cross con conferma EMA20 slope"""
    if i < 30: return False, None
    cross_up = I['e5'][i]>I['e8'][i] and I['e5'][i-1]<=I['e8'][i-1]
    cross_dn = I['e5'][i]<I['e8'][i] and I['e5'][i-1]>=I['e8'][i-1]
    slope = I['slope_e20'][i]
    if slope is None: return False, None
    if cross_up and slope > 0 and I['C'][i] > I['e20'][i]: return True, 'buy'
    if cross_dn and slope < 0 and I['C'][i] < I['e20'][i]: return True, 'sell'
    return False, None

def s_rsi_bounce(I, i):
    """RSI7 oversold/overbought bounce con BB conferma"""
    if i < 30: return False, None
    r=I['rsi7'][i]; rp=I['rsi7'][i-1]
    if r is None or rp is None: return False, None
    bu=I['bb_up'][i]; bd=I['bb_dn'][i]
    if bu is None or bd is None: return False, None
    if rp < 25 and r >= 25 and I['C'][i] <= bu:  return True, 'buy'
    if rp > 75 and r <= 75 and I['C'][i] >= bd:  return True, 'sell'
    return False, None

def s_bb_bounce(I, i):
    """BB band touch + RSI conferma (no-squeeze)"""
    if i < 30: return False, None
    bd=I['bb_dn'][i]; bu=I['bb_up'][i]; mid=I['bb_mid'][i]
    if bd is None: return False, None
    width = (bu-bd)/mid if mid>0 else 0
    if width < 0.003: return False, None   # in squeeze, skip
    r=I['rsi'][i]
    if r is None: return False, None
    if I['C'][i] <= bd and r < 45:  return True, 'buy'
    if I['C'][i] >= bu and r > 55:  return True, 'sell'
    return False, None

def s_vwap_bounce(I, i):
    """Price rimbalza su VWAP con momentum MACD"""
    if i < 30: return False, None
    v=I['vwap'][i]; h=I['mh'][i]
    if v is None or h is None: return False, None
    dist = abs(I['C'][i]-v)/v
    if dist > 0.003: return False, None   # troppo lontano da VWAP
    if I['C'][i] >= v and h > 0 and I['e5'][i] > I['e8'][i]: return True, 'buy'
    if I['C'][i] <= v and h < 0 and I['e5'][i] < I['e8'][i]: return True, 'sell'
    return False, None

def s_supertrend_cross(I, i):
    """Supertrend direction change con EMA20 filtro"""
    if i < 30: return False, None
    d=I['stdir'][i]; dp=I['stdir'][i-1]
    if d==0 or dp==0: return False, None
    if d==-1 and dp==1 and I['C'][i] < I['e20'][i]:  return True, 'sell'
    if d==1 and dp==-1 and I['C'][i] > I['e20'][i]:  return True, 'buy'
    return False, None

def s_stoch_rsi_cross(I, i):
    """StochRSI K/D cross in zona estrema"""
    if i < 30: return False, None
    k=I['sk'][i]; kp=I['sk'][i-1]; d=I['sd'][i]
    if None in (k,kp,d): return False, None
    cross_up = k > d and kp <= I['sd'][i-1]
    cross_dn = k < d and kp >= I['sd'][i-1]
    if cross_up and k < 30:  return True, 'buy'
    if cross_dn and k > 70:  return True, 'sell'
    return False, None

def s_macd_zero(I, i):
    """MACD hist cross zero con prezzo sopra/sotto EMA50"""
    if i < 30: return False, None
    h=I['mh'][i]; hp=I['mh'][i-1]
    if None in (h,hp): return False, None
    if hp < 0 and h >= 0 and I['C'][i] > I['e50'][i]: return True, 'buy'
    if hp > 0 and h <= 0 and I['C'][i] < I['e50'][i]: return True, 'sell'
    return False, None

def s_wpr_keltner(I, i):
    """W%R estremo + Keltner channel"""
    if i < 30: return False, None
    w=I['wpr'][i]; ku=I['ku'][i]; kl=I['kl'][i]
    if None in (w, ku, kl): return False, None
    if w < -80 and I['C'][i] < kl:  return True, 'buy'
    if w > -20 and I['C'][i] > ku:  return True, 'sell'
    return False, None

STRATEGIES = {
    'S_EMA_CROSS':      s_ema_cross,
    'S_RSI_BOUNCE':     s_rsi_bounce,
    'S_BB_BOUNCE':      s_bb_bounce,
    'S_VWAP_BOUNCE':    s_vwap_bounce,
    'S_SUPERTREND':     s_supertrend_cross,
    'S_STOCHRSI_CROSS': s_stoch_rsi_cross,
    'S_MACD_ZERO':      s_macd_zero,
    'S_WPR_KELTNER':    s_wpr_keltner,
}

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def backtest(cands, I, tp_amt, sl_amt, lookahead, fn):
    trades = []
    in_trade = False
    last_trade_bar = -999
    cooldown = max(2, lookahead // 3)   # cooldown in bars
    n = len(cands)

    # extreme filter: skip bars where ATR > 2.5x avg
    for i in range(50, n - lookahead):
        # cooldown
        if i - last_trade_bar < cooldown: continue
        # session filter (London+NY: 07-17 UTC)
        hour = datetime.datetime.fromtimestamp(cands[i]['t'], tz=datetime.timezone.utc).hour
        if hour < 7 or hour >= 17: continue
        # extreme ATR
        avg = I['atr_avg'][i]
        cur_atr = I['atr'][i]
        if avg and cur_atr and cur_atr > 2.5 * avg: continue

        sig, direction = fn(I, i)
        if not sig: continue

        entry = cands[i]['c']
        if direction == 'buy':
            tp_price = entry + tp_amt
            sl_price = entry - sl_amt
        else:
            tp_price = entry - tp_amt
            sl_price = entry + sl_amt

        # simulate next bars
        outcome = None
        for j in range(i+1, min(i+1+lookahead, n)):
            h = cands[j]['h']; l = cands[j]['l']
            if direction == 'buy':
                if l <= sl_price: outcome = -sl_amt; break
                if h >= tp_price: outcome = tp_amt;  break
            else:
                if h >= sl_price: outcome = -sl_amt; break
                if l <= tp_price: outcome = tp_amt;  break
        if outcome is None:
            outcome = cands[min(i+lookahead, n-1)]['c'] - entry if direction=='buy' else entry - cands[min(i+lookahead, n-1)]['c']

        trades.append({'i':i,'dir':direction,'pnl':outcome,'t':cands[i]['t']})
        last_trade_bar = i

    return trades

def analyze(trades, cands, tp_amt, sl_amt):
    if not trades:
        return {'n':0,'wr':0,'pnl':0,'pf':0,'dpd':0,'dd':0}
    n=len(trades)
    wins=[t for t in trades if t['pnl']>0]
    losses=[t for t in trades if t['pnl']<=0]
    wr=len(wins)/n*100
    pnl=sum(t['pnl'] for t in trades)
    gross_w=sum(t['pnl'] for t in wins)
    gross_l=abs(sum(t['pnl'] for t in losses))
    pf=gross_w/gross_l if gross_l>0 else 99.9
    # days
    days=set()
    for t in trades:
        days.add(datetime.datetime.fromtimestamp(t['t'],tz=datetime.timezone.utc).date())
    dpd=n/len(days) if days else 0
    # drawdown
    equity=0; peak=0; max_dd=0
    for t in trades:
        equity+=t['pnl']
        if equity>peak: peak=equity
        dd=peak-equity
        if dd>max_dd: max_dd=dd
    return {'n':n,'wr':round(wr,1),'pnl':round(pnl,1),'pf':round(pf,3),
            'dpd':round(dpd,2),'dd':round(max_dd,1),'days':len(days)}

# ── RUN ALL ───────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"BACKTEST: {len(STRATEGIES)} strategie × {len(TF_CFGS)} timeframe")
print(f"{'='*65}")

results = {}
table_rows = []

for sname, sfn in STRATEGIES.items():
    results[sname] = {}
    best_pf = -1; best_tf = None; best_stats = None

    for tf, cfg in TF_CFGS.items():
        c = candles[tf]; I = inds[tf]
        trades = backtest(c, I, cfg['tp'], cfg['sl'], cfg['lookahead'], sfn)
        stats = analyze(trades, c, cfg['tp'], cfg['sl'])
        results[sname][tf] = stats

        if stats['n'] >= 15 and stats['pf'] > best_pf:
            best_pf = stats['pf']; best_tf = tf; best_stats = stats

    results[sname]['best_tf'] = best_tf
    results[sname]['best_pf'] = best_pf

    # print per-strategy
    print(f"\n{sname}")
    hdr = f"  {'TF':5} {'N':>5} {'WR%':>7} {'P&L':>8} {'PF':>6} {'T/gg':>5} {'DD':>6}"
    print(hdr); print("  "+"-"*50)
    for tf, cfg in TF_CFGS.items():
        s = results[sname][tf]
        mark = ' *' if tf==best_tf else ''
        print(f"  {tf:5} {s['n']:>5} {s['wr']:>6.1f}% {s['pnl']:>8.1f} {s['pf']:>6.3f} {s['dpd']:>5.2f} {s['dd']:>6.1f}{mark}")
    if best_tf:
        print(f"  → BEST TF: {best_tf}  (PF={best_pf:.3f}, N={best_stats['n']}, WR={best_stats['wr']}%, {best_stats['dpd']} T/gg)")
    else:
        print(f"  → NESSUN TF valido (N<15)")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"RIEPILOGO — Migliori strategie scalping (PF ≥ 1.10, N ≥ 15)")
print(f"{'='*65}")
print(f"{'Strategia':<22} {'TF':>5} {'N':>5} {'WR%':>7} {'PF':>6} {'P&L':>8} {'T/gg':>5}")
print("-"*60)

valid = []
for sname, res in results.items():
    tf = res['best_tf']
    if tf is None: continue
    s = res[tf]
    if s['pf'] >= 1.10 and s['n'] >= 15:
        valid.append((sname, tf, s))

valid.sort(key=lambda x: x[2]['pf'], reverse=True)
for sname, tf, s in valid:
    print(f"{sname:<22} {tf:>5} {s['n']:>5} {s['wr']:>6.1f}% {s['pf']:>6.3f} {s['pnl']:>8.1f} {s['dpd']:>5.2f}")

if not valid:
    print("  Nessuna strategia scalping supera PF 1.10 con N≥15")

# ── DAILY PROFIT ANALYSIS ─────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("ANALISI €50/GIORNO — Position sizing necessario")
print(f"{'='*65}")

# H1 validated system: $3.01/day at 1 unit
h1_dpd = 3.01

# Scalping best
scal_dpd = max((s['dpd'] * TF_CFGS[tf]['tp'] * s['wr']/100 - s['dpd']*(1-s['wr']/100)*TF_CFGS[tf]['sl']
               for _,tf,s in valid), default=0)

print(f"\nH1 sistema attuale:        ~${h1_dpd:.2f}/giorno  (a 1x lot unitario)")
if scal_dpd > 0:
    best_s = valid[0] if valid else None
    tf_best = best_s[1] if best_s else '?'
    cfg_best = TF_CFGS[tf_best] if best_s else {'tp':5,'sl':3}
    s_best = best_s[2] if best_s else {}
    n_tpd = s_best.get('dpd',0)
    print(f"Scalping migliore ({tf_best}):  ~${scal_dpd:.2f}/giorno  (a 1x lot unitario)")
    print(f"  → {n_tpd:.1f} trade/gg · TP=${cfg_best['tp']}/SL=${cfg_best['sl']}")

print(f"\n--- Per raggiungere €50/giorno (~$55) ---")
systems = [('H1 solo', h1_dpd)]
if scal_dpd > 0: systems.append(('Scalping solo', scal_dpd))
combined = h1_dpd + scal_dpd
if scal_dpd > 0: systems.append(('H1 + Scalping', combined))

for name, dpd in systems:
    if dpd <= 0: continue
    mult = 55 / dpd
    print(f"\n  [{name}]")
    print(f"    Moltiplicatore lot necessario: {mult:.1f}x")
    print(f"    Es. se ora usi 0.1 lot → serve {0.1*mult:.2f} lot")
    print(f"    Es. se ora usi 0.5 lot → serve {0.5*mult:.2f} lot")

print(f"""
--- Strategia consigliata per €50/gg ---
1. H1 strategie validate (in produzione ora):  ~$3/gg a 1x
2. Scalping overlay (5m/15m) top strategie:    +$?/gg
3. Aumentare gradualmente il lot size fino a:  {55/combined:.1f}x (H1+Scalp)

ATTENZIONE: un moltiplicatore alto = drawdown proporzionale.
Con DD max H1 ≈ $120 → a {55/h1_dpd:.0f}x DD diventa ${ 120*55/h1_dpd:.0f}
Consigliato: aumentare lot gradualmente testando su demo prima.
""")

# ── SAVE JSON ─────────────────────────────────────────────────────────────────
output = {
    'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'symbol': SYMBOL,
    'period': PERIOD,
    'results': {
        sn: {
            tf: {k:v for k,v in sv.items() if k!='days'}
            for tf,sv in sr.items() if isinstance(sv,dict)
        }
        for sn, sr in results.items()
    },
    'valid_strategies': [
        {'name':sn,'tf':tf,'stats':s}
        for sn,tf,s in valid
    ]
}
with open('strategy_scalping_results.json','w',encoding='utf-8') as f:
    json.dump(output,f,indent=2)
print("Salvato: strategy_scalping_results.json")
print("="*65)
