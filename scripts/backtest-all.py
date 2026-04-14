#!/usr/bin/env python3
"""
TradeFlow AI — Backtest Unificato TUTTE le Strategie
=====================================================
Dati:    GC=F (COMEX Gold Futures H1) via yfinance — proxy per OANDA XAU/USD spot
         Nota: futures GC=F tracciano spot con ~contango minimo, ottimo per backtest pattern
Spread:  Modello realistico OANDA — $0.30 base + scaling su ATR (news widening)
Periodo: 730 giorni H1 (default)

Strategie testate:
  MFKK variants   : S00_MFKK, S00_MFKK_HWR
  Esistenti       : S01_EXHAUSTION, S06_ORDERBLOCK, S09_VWAP_WPR, S12_WPR_KELTNER,
                    S13_STRUC_BREAK, S14_KEY_LEVELS
  Nuove / v2      : S02_ALLIGATOR_OBV, S03_SUPERTREND_EMA, S04_BB_SQUEEZE,
                    S05_RSI_DIVERGENCE, S07_STOCHRSI_BB, S08_OBV_EMA_MOM,
                    S10_ST_MACD_SESSION, S11_ALLIGATOR_AWAKEN
  Dynamic Selector: REGIME_ADAPTIVE (sceglie automaticamente la strategia migliore per regime)

Output: backtest_all_results.json + stampa tabella riepilogativa
"""
import sys, io, os, json, time, math, datetime
from collections import defaultdict

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ══════════════════════════════════════════════════════════════
# CONFIGURAZIONE
# ══════════════════════════════════════════════════════════════
SYMBOL      = 'GC=F'         # COMEX Gold Futures — proxy OANDA XAU/USD
DAYS        = 730             # 2 anni
TP_USD      = 20.0
SL_USD      = 12.0
MAX_TRADES  = 10
COOLDOWN_H  = 0.5             # 30 min tra trade
EXTREME_K   = 3.5             # ATR > 3.5x avg = skip
SESSION     = (0, 24)         # 24h

# Spread OANDA realistico
SPREAD_BASE = 0.30            # USD — spread tipico OANDA XAU/USD in condizioni normali
SPREAD_MAX  = 2.00            # USD — cap in giornate di news ad alto impatto
SPREAD_ATR_MULT = 1.5         # moltiplicatore: se ATR > N*avg, spread scala proporzionalmente

CACHE_FILE  = 'xauusd_h1_730d.json'  # cache locale per non ri-scaricare ogni run

# ══════════════════════════════════════════════════════════════
# DATA FETCH (yfinance GC=F, con cache locale)
# ══════════════════════════════════════════════════════════════
def fetch_candles(days=DAYS, force=False):
    if not force and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding='utf-8') as f:
            cached = json.load(f)
        age_days = (time.time() - cached.get('fetched_at', 0)) / 86400
        if age_days < 1:
            candles = cached['candles']
            print(f'📦 Cache locale: {len(candles)} candele H1 ({age_days*24:.1f}h fa)')
            return candles
        print(f'🔄 Cache scaduta ({age_days:.0f}gg) — ri-scarico...')

    try:
        import yfinance as yf
    except ImportError:
        print('❌ yfinance non installato. Esegui: pip install yfinance')
        return []

    print(f'⬇️  Download {SYMBOL} H1 (2y) via yfinance...')
    try:
        t = yf.Ticker(SYMBOL)
        df = t.history(period='2y', interval='1h')
        df = df.dropna(subset=['Close'])
    except Exception as e:
        print(f'❌ Download fallito: {e}')
        return []

    all_candles = []
    for ts, row in df.iterrows():
        try:
            epoch = int(ts.timestamp())
            all_candles.append({
                't': epoch,
                'o': float(row['Open']),
                'h': float(row['High']),
                'l': float(row['Low']),
                'c': float(row['Close']),
                'v': float(row.get('Volume', 0) or 0)
            })
        except Exception:
            continue

    all_candles.sort(key=lambda x: x['t'])
    print(f'📊 Scaricate {len(all_candles)} candele H1 ({days}gg)')
    if all_candles:
        print(f'   Da: {datetime.datetime.utcfromtimestamp(all_candles[0]["t"]).strftime("%Y-%m-%d")}')
        print(f'   A:  {datetime.datetime.utcfromtimestamp(all_candles[-1]["t"]).strftime("%Y-%m-%d")}')
        print(f'   Range prezzi: ${all_candles[0]["c"]:.0f} – ${all_candles[-1]["c"]:.0f}')

    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'candles': all_candles, 'fetched_at': time.time()}, f)
    return all_candles

# ══════════════════════════════════════════════════════════════
# MATH HELPERS
# ══════════════════════════════════════════════════════════════
def ema(src, p):
    k = 2/(p+1); v = src[0]; out = [v]
    for x in src[1:]: v = x*k + v*(1-k); out.append(v)
    return out

def sma(src, p):
    out = [None]*len(src)
    for i in range(p-1, len(src)):
        sl = src[i-p+1:i+1]
        if any(x is None for x in sl): continue
        out[i] = sum(sl)/p
    return out

def smma(src, p):  # Smoothed MA (Wilder)
    out = [None]*(p-1)
    valid = [x for x in src[:p] if x is not None]
    if len(valid) < p: return out + [None]*(len(src)-p+1)
    v = sum(valid)/p; out.append(v)
    for x in src[p:]: v = (v*(p-1)+x)/p; out.append(v)
    return out

def rsi_fn(src, p=14):
    n = len(src); out = [None]*n
    g = [max(0, src[i]-src[i-1]) for i in range(1,n)]
    l = [max(0, src[i-1]-src[i]) for i in range(1,n)]
    if len(g) < p: return out
    ag = sum(g[:p])/p; al = sum(l[:p])/p
    out[p] = 100 - 100/(1+(ag/al if al>0 else 100))
    for i in range(p, len(g)):
        ag = (ag*(p-1)+g[i])/p; al = (al*(p-1)+l[i])/p
        out[i+1] = 100 - 100/(1+(ag/al if al>0 else 100))
    return out

def atr_fn(H, L, C, p=14):
    tr = [0.0]
    for i in range(1, len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    return sma(tr, p)

def adx_fn(H, L, C, p=14):
    n = len(C); TR=[0.]; DMP=[0.]; DMM=[0.]
    for i in range(1,n):
        TR.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
        up=H[i]-H[i-1]; dn=L[i-1]-L[i]
        DMP.append(up if up>dn and up>0 else 0.)
        DMM.append(dn if dn>up and dn>0 else 0.)
    sT=[0.]; sP=[0.]; sM=[0.]
    for i in range(1,n):
        sT.append(sT[-1]-sT[-1]/p+TR[i])
        sP.append(sP[-1]-sP[-1]/p+DMP[i])
        sM.append(sM[-1]-sM[-1]/p+DMM[i])
    DIP=[sP[i]/sT[i]*100 if sT[i]>0 else 0. for i in range(n)]
    DIM=[sM[i]/sT[i]*100 if sT[i]>0 else 0. for i in range(n)]
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0. for i in range(n)]
    return sma(DX,p), DIP, DIM

def macd_fn(src, f=12, s=26, sig=9):
    e1=ema(src,f); e2=ema(src,s)
    ml=[e1[i]-e2[i] for i in range(len(src))]
    sg=ema(ml,sig)
    hist=[ml[i]-sg[i] for i in range(len(src))]
    return ml, sg, hist

def bollinger_fn(src, p=20, m=2.0):
    mid=sma(src,p); up=[None]*len(src); lo=[None]*len(src); bw=[None]*len(src)
    for i in range(p-1,len(src)):
        if mid[i] is None: continue
        sl=src[i-p+1:i+1]; mn=sum(sl)/p
        std=math.sqrt(sum((x-mn)**2 for x in sl)/p)
        up[i]=mid[i]+m*std; lo[i]=mid[i]-m*std
        bw[i]=(up[i]-lo[i])/mid[i] if mid[i] else None
    bw_avg=sma([x if x else 0 for x in bw],20)
    return up, mid, lo, bw, bw_avg

def keltner_fn(H, L, C, p=20, m=2.0):
    mid=ema(C,p); a=atr_fn(H,L,C,p)
    up=[mid[i]+m*a[i] if a[i] else None for i in range(len(C))]
    lo=[mid[i]-m*a[i] if a[i] else None for i in range(len(C))]
    return up, mid, lo

def supertrend_fn(H, L, C, p=10, m=3.0):
    a=atr_fn(H,L,C,p); n=len(C)
    ub=[(H[i]+L[i])/2+m*(a[i] or 0) for i in range(n)]
    lb=[(H[i]+L[i])/2-m*(a[i] or 0) for i in range(n)]
    fub=[0.]*n; flb=[0.]*n; st=[1]*n
    for i in range(1,n):
        fub[i]=ub[i] if ub[i]<fub[i-1] or C[i-1]>fub[i-1] else fub[i-1]
        flb[i]=lb[i] if lb[i]>flb[i-1] or C[i-1]<flb[i-1] else flb[i-1]
        if st[i-1]==1 and C[i]<=fub[i]: st[i]=1
        elif st[i-1]==1 and C[i]>fub[i]: st[i]=-1
        elif st[i-1]==-1 and C[i]>=flb[i]: st[i]=-1
        elif st[i-1]==-1 and C[i]<flb[i]: st[i]=1
        else: st[i]=st[i-1]
    return st  # -1=bullish, 1=bearish

def alligator_fn(H, L):
    med=[(H[i]+L[i])/2 for i in range(len(H))]
    jaw=smma(med,13); teeth=smma(med,8); lips=smma(med,5)
    return jaw, teeth, lips

def obv_fn(C, V):
    out=[0.]
    for i in range(1,len(C)):
        out.append(out[-1]+(V[i] if C[i]>C[i-1] else -V[i] if C[i]<C[i-1] else 0))
    return out

def wpr_fn(H, L, C, p=14):
    out=[None]*(p-1)
    for i in range(p-1,len(C)):
        hi=max(H[i-p+1:i+1]); lo=min(L[i-p+1:i+1])
        out.append((hi-C[i])/(hi-lo)*-100 if hi>lo else -50)
    return out

def stochrsi_fn(C, rsi_p=14, stoch_p=14, k=3, d=3):
    r=rsi_fn(C,rsi_p); n=len(r); raw=[None]*n
    for i in range(stoch_p-1,n):
        sl=[x for x in r[i-stoch_p+1:i+1] if x is not None]
        if len(sl)<stoch_p or r[i] is None: continue
        hi=max(sl); lo=min(sl)
        raw[i]=(r[i]-lo)/(hi-lo)*100 if hi>lo else 50
    sk=sma([x if x else 50 for x in raw],k)
    sd=sma([x if x else 50 for x in sk],d)
    return sk, sd

def vwap_fn(candles):
    out=[]; cum_pv=0; cum_v=0; last_day=None
    for c in candles:
        dt=datetime.datetime.utcfromtimestamp(c['t']); day=dt.date()
        if day!=last_day: cum_pv=0; cum_v=0; last_day=day
        tp=(c['h']+c['l']+c['c'])/3
        cum_pv+=tp*c['v']; cum_v+=c['v']
        out.append(cum_pv/cum_v if cum_v>0 else tp)
    return out

def momentum_fn(C, p=10):
    out=[None]*p
    for i in range(p,len(C)):
        out.append((C[i]-C[i-p])/C[i-p]*100 if C[i-p]!=0 else 0)
    return out

# CCI_S (MFKK indicator)
def cci_s_fn(C, cci_p=50, stoch_p=50, sk_p=8, sd_p=8):
    n=len(C); cci=[None]*n
    for i in range(cci_p-1,n):
        sl=C[i-cci_p+1:i+1]; mn=sum(sl)/cci_p
        md=sum(abs(x-mn) for x in sl)/cci_p
        cci[i]=0. if md==0 else (C[i]-mn)/(0.015*md)
    stk=[None]*n
    for i in range(cci_p+stoch_p-2,n):
        if cci[i] is None: continue
        w=[cci[j] for j in range(i-stoch_p+1,i+1) if cci[j] is not None]
        if not w: continue
        lv,hv=min(w),max(w)
        stk[i]=50. if hv==lv else (cci[i]-lv)/(hv-lv)*100
    stk_k=sma([x if x else 0 for x in stk],sk_p)
    stk_d=sma([x if x else 0 for x in stk_k],sd_p)
    return stk_d

# ══════════════════════════════════════════════════════════════
# CALCOLO TUTTI GLI INDICATORI
# ══════════════════════════════════════════════════════════════
def compute_all(candles):
    n=len(candles)
    H=[c['h'] for c in candles]; L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]; V=[c['v'] for c in candles]

    atr14=atr_fn(H,L,C,14)
    atr30=sma([x if x else 0 for x in atr14],30)
    adx14,dip14,dim14=adx_fn(H,L,C,14)
    adx10,dip10,dim10=adx_fn(H,L,C,10)  # MFKK usa ADX(10)
    ml,sg,hist=macd_fn(C)
    e20=ema(C,20); e50=ema(C,50); e100=ema(C,100); e200=ema(C,200)
    rsi14=rsi_fn(C,14)
    bb_up,bb_mid,bb_lo,bb_w,bb_w_avg=bollinger_fn(C)
    kc_up,kc_mid,kc_lo=keltner_fn(H,L,C)
    st=supertrend_fn(H,L,C)
    jaw,teeth,lips=alligator_fn(H,L)
    obv_v=obv_fn(C,V); obv_e20=ema(obv_v,20)
    wpr=wpr_fn(H,L,C,14)
    srsi_k,srsi_d=stochrsi_fn(C)
    vwap=vwap_fn(candles)
    mom=momentum_fn(C,10)
    cci_s=cci_s_fn(C)          # CCI_S per MFKK (CCI+Stoch, ADX10)

    return {
        'n':n,'H':H,'L':L,'C':C,'V':V,
        'atr':atr14,'atr30':atr30,
        'adx':adx14,'dip':dip14,'dim':dim14,
        'adx10':adx10,'dip10':dip10,'dim10':dim10,
        'macd':ml,'macd_sig':sg,'macd_hist':hist,
        'e20':e20,'e50':e50,'e100':e100,'e200':e200,
        'rsi':rsi14,
        'bb_up':bb_up,'bb_lo':bb_lo,'bb_w':bb_w,'bb_w_avg':bb_w_avg,
        'kc_up':kc_up,'kc_lo':kc_lo,
        'st':st,'jaw':jaw,'teeth':teeth,'lips':lips,
        'obv':obv_v,'obv_e20':obv_e20,
        'wpr':wpr,'srsi_k':srsi_k,'srsi_d':srsi_d,
        'vwap':vwap,'mom':mom,'cci_s':cci_s,
    }

# ══════════════════════════════════════════════════════════════
# SPREAD MODEL OANDA REALISTICO
# ══════════════════════════════════════════════════════════════
def calc_spread(ind, i):
    """
    Spread OANDA XAU/USD: base $0.30 + scaling ATR per giornate volatili (news).
    OANDA spread tipico: 0.20-0.40 normali, 0.80-2.00 su NFP/FOMC/CPI.
    """
    atr = ind['atr'][i]
    atr_avg = ind['atr30'][i]
    if atr and atr_avg and atr_avg > 0:
        ratio = atr / atr_avg
        if ratio > SPREAD_ATR_MULT:
            spread = SPREAD_BASE * ratio
        else:
            spread = SPREAD_BASE
    else:
        spread = SPREAD_BASE
    return min(spread, SPREAD_MAX)

# ══════════════════════════════════════════════════════════════
# REGIME DETECTION
# ══════════════════════════════════════════════════════════════
def detect_regime(ind, i):
    adx=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    atr=ind['atr'][i]; atr30=ind['atr30'][i]
    if adx is None: return 'UNKNOWN'
    if atr and atr30 and atr > EXTREME_K * atr30: return 'EXTREME'
    if adx>=30: return 'TREND_UP' if dp>dm else 'TREND_DOWN'
    if adx>=22: return 'WEAK_UP' if dp>dm else 'WEAK_DOWN'
    if atr and atr30 and atr30>0 and atr>1.4*atr30: return 'VOLATILE'
    return 'RANGE'

# ══════════════════════════════════════════════════════════════
# MFKK SCORER (calibrato da backtest 730gg)
# ══════════════════════════════════════════════════════════════
def mfkk_score(cci_v, macd_v, sig_v, hist_v, adx_v, dip, dim, is_buy):
    # CCI score (trend-continuation, non mean-reversion)
    cs=50
    if cci_v is not None:
        if is_buy:
            if cci_v>=75: cs=60
            elif cci_v>=65: cs=52
            elif cci_v>=50: cs=45
            elif cci_v>=35: cs=38
            elif cci_v>=25: cs=28
            else: cs=18
        else:
            if cci_v<=25: cs=65
            elif cci_v<=35: cs=58
            elif cci_v<=50: cs=50
            elif cci_v<=65: cs=44
            else: cs=40

    # MACD score + exhaustion pattern
    diff=macd_v-sig_v if (macd_v is not None and sig_v is not None) else 0
    str_v=min(abs(diff)/3,1)
    hb=10 if ((is_buy and hist_v and hist_v>0) or (not is_buy and hist_v and hist_v<0)) else 0
    ms=50
    if is_buy:
        if diff>0.5: ms=round(65+str_v*25)+hb
        elif diff>0: ms=60+hb
        elif diff>-1: ms=30
        elif diff>-3: ms=40
        else: ms=15
    else:
        if diff<-0.5: ms=round(65+str_v*25)+hb
        elif diff<0: ms=60+hb
        elif diff<1: ms=30
        elif diff<3: ms=45
        else: ms=48
    ms=max(0,min(100,ms))

    # ADX score (peso maggiore)
    di_diff=dip-dim if (dip is not None and dim is not None) else 0
    spread_b=min(abs(di_diff)/20,1)
    astr=(1.0 if adx_v>=35 else 0.85 if adx_v>=27 else 0.65 if adx_v>=20
          else 0.4 if adx_v>=14 else 0.2 if adx_v>=10 else 0.05)
    ads=50
    if is_buy:
        if di_diff>0 and adx_v>=25: ads=round(60+astr*25+spread_b*15)
        elif di_diff>0 and adx_v>=10: ads=50
        elif di_diff>0: ads=30
        else: ads=5
    else:
        if di_diff<0 and adx_v>=25: ads=round(60+astr*25+spread_b*15)
        elif di_diff<0 and adx_v>=10: ads=50
        elif di_diff<0: ads=30
        else: ads=5
    ads=max(0,min(100,ads))

    # Pesi ottimali da backtest 730gg: CCI10%, MACD10%, ADX80%
    W_CCI=0.10; W_MACD=0.10; W_ADX=0.80
    score=round(cs*W_CCI + ms*W_MACD + ads*W_ADX)
    return score, cs, ms, ads

# ══════════════════════════════════════════════════════════════
# DEFINIZIONE STRATEGIE
# ══════════════════════════════════════════════════════════════
def sig_mfkk(ind, i, _h=None):
    cci_v=ind['cci_s'][i]; adx_v=ind['adx10'][i]
    dip=ind['dip10'][i]; dim=ind['dim10'][i]
    macd_v=ind['macd'][i]; sig_v=ind['macd_sig'][i]; hist_v=ind['macd_hist'][i]
    if any(x is None for x in [adx_v,dip,dim,macd_v,sig_v]): return None
    sc_sell,_,_,_ = mfkk_score(cci_v,macd_v,sig_v,hist_v,adx_v,dip,dim,False)
    sc_buy,_,_,_  = mfkk_score(cci_v,macd_v,sig_v,hist_v,adx_v,dip,dim,True)
    if sc_sell>=75 and sc_sell>sc_buy: return 'sell'
    if sc_buy>=90  and sc_buy>sc_sell: return 'buy'
    return None

def sig_mfkk_hwr(ind, i, _h=None):
    """HIGH WIN RATE SELL ONLY: ADX≥35 + DI spread≥20 + MACD diff≥0.5 + CCI non OS"""
    adx_v=ind['adx10'][i]; dip=ind['dip10'][i]; dim=ind['dim10'][i]
    macd_v=ind['macd'][i]; sig_v=ind['macd_sig'][i]; cci_v=ind['cci_s'][i]
    if any(x is None for x in [adx_v,dip,dim,macd_v,sig_v]): return None
    if adx_v<35: return None
    spread=abs(dip-dim)
    if spread<20: return None
    diff=macd_v-sig_v
    if dim>dip and diff>=0.5 and (cci_v is None or cci_v>=25):
        return 'sell'
    return None

def sig_exhaustion(ind, i, _h=None):
    adx=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; sg=ind['macd_sig'][i]
    if any(x is None for x in [adx,dp,dm,m,sg]): return None
    diff=m-sg; spread=abs(dp-dm)
    if adx>=30 and dm>dp and spread>=15 and diff>=1.0: return 'sell'
    if adx>=28 and dp>dm and spread>=15 and diff<=-1.0: return 'buy'
    return None

def sig_alligator_obv(ind, i, _h=None):
    jaw=ind['jaw'][i]; teeth=ind['teeth'][i]; lips=ind['lips'][i]
    e200=ind['e200'][i]; c=ind['C'][i]; obv=ind['obv'][i]; obv_e=ind['obv_e20'][i]
    if any(x is None for x in [jaw,teeth,lips,e200,obv_e]): return None
    if lips>teeth>jaw and c>e200 and obv>obv_e: return 'buy'
    if lips<teeth<jaw and c<e200 and obv<obv_e: return 'sell'
    return None

def sig_supertrend_ema(ind, i, _h=None):
    st=ind['st'][i]; c=ind['C'][i]
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]; r=ind['rsi'][i]
    if any(x is None for x in [e20,e50,e100,r]): return None
    if st==-1 and e20>e50>e100 and r>=50: return 'buy'
    if st==1 and e20<e50<e100 and r<=50: return 'sell'
    return None

def sig_bb_squeeze(ind, i, _h=None):
    if i<1: return None
    bw=ind['bb_w'][i]; bwa=ind['bb_w_avg'][i]; bw_p=ind['bb_w'][i-1]
    mom=ind['mom'][i]; c=ind['C'][i]; bb_up=ind['bb_up'][i]; bb_lo=ind['bb_lo'][i]
    if any(x is None for x in [bw,bwa,bw_p,mom,bb_up,bb_lo]): return None
    was_squeeze=bw_p<bwa
    if was_squeeze and mom>0.2 and c>bb_lo*1.003: return 'buy'
    if was_squeeze and mom<-0.2 and c<bb_up*0.997: return 'sell'
    return None

def sig_rsi_divergence(ind, i, _h=None):
    if i<6: return None
    r=ind['rsi']; c=ind['C']; st=ind['st']
    if any(x is None for x in [r[i],r[i-3],r[i-4]]): return None
    flip_bull=(st[i]==-1 and (st[i-1]==1 or st[i-2]==1))
    flip_bear=(st[i]==1  and (st[i-1]==-1 or st[i-2]==-1))
    p_hh=c[i]>c[i-3] and c[i]>c[i-4]; r_lh=r[i]<r[i-3] and r[i]<r[i-4] and r[i]>60
    p_ll=c[i]<c[i-3] and c[i]<c[i-4]; r_hl=r[i]>r[i-3] and r[i]>r[i-4] and r[i]<40
    if flip_bear and p_hh and r_lh: return 'sell'
    if flip_bull and p_ll and r_hl: return 'buy'
    return None

def sig_orderblock(ind, i, _h=None):
    """Order block: rimbalzo su swing H/L recente + EMA20 + RSI + MACD"""
    if i<15: return None
    c=ind['C'][i]; H=ind['H']; L=ind['L']
    e20=ind['e20'][i]; r=ind['rsi'][i]; m=ind['macd'][i]
    if any(x is None for x in [e20,r,m]): return None
    sw_lo=min(L[i-10:i]); sw_hi=max(H[i-10:i])
    dist_lo=(c-sw_lo)/c; dist_hi=(sw_hi-c)/c
    if dist_lo<0.0015 and c>e20*0.998 and r<52 and m>0: return 'buy'
    if dist_hi<0.0015 and c<e20*1.002 and r>48 and m<0: return 'sell'
    return None

def sig_stochrsi_bb(ind, i, _h=None):
    sk=ind['srsi_k'][i]; sd=ind['srsi_d'][i]
    bb_u=ind['bb_up'][i]; bb_l=ind['bb_lo'][i]; c=ind['C'][i]
    jaw=ind['jaw'][i]; lips=ind['lips'][i]
    if any(x is None for x in [sk,sd,bb_u,bb_l,jaw,lips]): return None
    if sk<20 and sd<20 and c<=bb_l*1.003 and lips>jaw: return 'buy'
    if sk>80 and sd>80 and c>=bb_u*0.997 and lips<jaw: return 'sell'
    return None

def sig_obv_ema_mom(ind, i, _h=None):
    obv=ind['obv'][i]; obv_e=ind['obv_e20'][i]
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]; e200=ind['e200'][i]
    mom=ind['mom'][i]; adx=ind['adx'][i]; c=ind['C'][i]
    if any(x is None for x in [obv_e,e20,e50,e100,e200,mom,adx]): return None
    if adx<20: return None
    if e20>e50>e100>e200 and obv>obv_e and mom>0 and c>e20: return 'buy'
    if e20<e50<e100<e200 and obv<obv_e and mom<0 and c<e20: return 'sell'
    return None

def sig_vwap_wpr(ind, i, _h=None):
    vwap=ind['vwap'][i]; c=ind['C'][i]; wpr=ind['wpr'][i]; m=ind['macd'][i]
    if any(x is None for x in [vwap,wpr,m]): return None
    if c>vwap and wpr<-80 and m>0: return 'buy'
    if c<vwap and wpr>-20 and m<0: return 'sell'
    return None

def sig_st_macd_session(ind, i, hour=None):
    if hour is None or not (7<=hour<=13): return None
    st=ind['st'][i]; m=ind['macd'][i]; sg=ind['macd_sig'][i]
    r=ind['rsi'][i]; e50=ind['e50'][i]; c=ind['C'][i]
    if any(x is None for x in [m,sg,r,e50]): return None
    diff=m-sg
    if st==-1 and diff>0 and 45<=r<=70 and c>e50: return 'buy'
    if st==1  and diff<0 and 30<=r<=55 and c<e50: return 'sell'
    return None

def sig_alligator_awaken(ind, i, _h=None):
    if i<4: return None
    jaw=ind['jaw']; teeth=ind['teeth']; lips=ind['lips']
    hist=ind['macd_hist']
    if any(x is None for x in [jaw[i],teeth[i],lips[i]]): return None
    sp_now=abs(lips[i]-jaw[i])/jaw[i]*100 if jaw[i] else 0
    sp_prev=abs(lips[i-3]-jaw[i-3])/jaw[i-3]*100 if jaw[i-3] else 0
    was_sleep=sp_prev<0.3
    hcup=hist[i] is not None and hist[i]>0 and hist[i-1] is not None and hist[i-1]<0
    hcdn=hist[i] is not None and hist[i]<0 and hist[i-1] is not None and hist[i-1]>0
    if was_sleep and sp_now>sp_prev and lips[i]>teeth[i] and hcup: return 'buy'
    if was_sleep and sp_now>sp_prev and lips[i]<teeth[i] and hcdn: return 'sell'
    return None

def sig_wpr_keltner(ind, i, _h=None):
    wpr=ind['wpr'][i]; r=ind['rsi'][i]; c=ind['C'][i]
    ku=ind['kc_up'][i]; kl=ind['kc_lo'][i]; adx=ind['adx'][i]
    if any(x is None for x in [wpr,r,ku,kl,adx]): return None
    if adx>=30: return None  # solo in ranging/weak
    if c<=kl*1.002 and wpr<-80 and r<35: return 'buy'
    if c>=ku*0.998 and wpr>-20 and r>65: return 'sell'
    return None

def sig_struc_break(ind, i, _h=None):
    if i<45: return None
    H=ind['H']; L=ind['L']; C=ind['C']
    hh=max(H[i-40:i]); ll=min(L[i-40:i]); c=C[i]
    if c>hh and L[i]<=hh*1.001: return 'buy'
    if c<ll and H[i]>=ll*0.999: return 'sell'
    return None

def sig_key_levels(ind, i, _h=None):
    if i<25: return None
    H=ind['H']; L=ind['L']; C=ind['C']
    hi=max(H[i-24:i]); lo=min(L[i-24:i]); close=C[i]
    pp=(hi+lo+close)/3; s1=2*pp-hi; r1=2*pp-lo
    c=C[i]; r=ind['rsi'][i]
    if r is None: return None
    if c>s1 and L[i]<=s1*1.001 and r<40: return 'buy'
    if c<r1 and H[i]>=r1*0.999 and r>60: return 'sell'
    return None

# ══════════════════════════════════════════════════════════════
# STRATEGY MAP + REGIME PRIORITY
# ══════════════════════════════════════════════════════════════
STRATS = {
    'S00_MFKK':           sig_mfkk,
    'S00_MFKK_HWR':       sig_mfkk_hwr,
    'S01_EXHAUSTION':      sig_exhaustion,
    'S02_ALLIGATOR_OBV':  sig_alligator_obv,
    'S03_SUPERTREND_EMA': sig_supertrend_ema,
    'S04_BB_SQUEEZE':     sig_bb_squeeze,
    'S05_RSI_DIVERGENCE': sig_rsi_divergence,
    'S06_ORDERBLOCK':     sig_orderblock,
    'S07_STOCHRSI_BB':    sig_stochrsi_bb,
    'S08_OBV_EMA_MOM':    sig_obv_ema_mom,
    'S09_VWAP_WPR':       sig_vwap_wpr,
    'S10_ST_MACD_SESSION':sig_st_macd_session,
    'S11_ALLIGATOR_AWAKEN':sig_alligator_awaken,
    'S12_WPR_KELTNER':    sig_wpr_keltner,
    'S13_STRUC_BREAK':    sig_struc_break,
    'S14_KEY_LEVELS':     sig_key_levels,
}

# Priority per regime — aggiornata dopo risultati backtest
REGIME_PRIORITY = {
    'TREND_UP':   ['S00_MFKK_HWR','S00_MFKK','S01_EXHAUSTION','S03_SUPERTREND_EMA',
                   'S08_OBV_EMA_MOM','S02_ALLIGATOR_OBV','S05_RSI_DIVERGENCE'],
    'TREND_DOWN': ['S00_MFKK_HWR','S00_MFKK','S01_EXHAUSTION','S03_SUPERTREND_EMA',
                   'S08_OBV_EMA_MOM','S02_ALLIGATOR_OBV','S05_RSI_DIVERGENCE'],
    'WEAK_UP':    ['S00_MFKK','S06_ORDERBLOCK','S10_ST_MACD_SESSION',
                   'S04_BB_SQUEEZE','S02_ALLIGATOR_OBV','S11_ALLIGATOR_AWAKEN'],
    'WEAK_DOWN':  ['S00_MFKK','S06_ORDERBLOCK','S10_ST_MACD_SESSION',
                   'S04_BB_SQUEEZE','S02_ALLIGATOR_OBV'],
    'RANGE':      ['S07_STOCHRSI_BB','S12_WPR_KELTNER','S09_VWAP_WPR',
                   'S04_BB_SQUEEZE','S14_KEY_LEVELS','S00_MFKK'],
    'VOLATILE':   ['S00_MFKK_HWR','S07_STOCHRSI_BB','S12_WPR_KELTNER'],
    'UNKNOWN':    ['S00_MFKK','S09_VWAP_WPR'],
}

# ══════════════════════════════════════════════════════════════
# BACKTEST ENGINE (con spread realistico)
# ══════════════════════════════════════════════════════════════
def run_backtest(candles, ind, sig_fn, tp=TP_USD, sl=SL_USD, name='?'):
    n=len(candles); trades=[]
    day_count=defaultdict(int); last_trade_ts=defaultdict(lambda: -9999)
    WARMUP=250  # barre di warmup per indicatori

    for i in range(WARMUP, n):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')

        # Sessione + limiti
        if not (SESSION[0]<=hour<SESSION[1]): continue
        atr=ind['atr'][i]; atr30=ind['atr30'][i]
        if atr and atr30 and atr>EXTREME_K*atr30: continue
        if day_count[day]>=MAX_TRADES: continue
        elapsed=(ts-last_trade_ts[day])/3600
        if elapsed<COOLDOWN_H: continue

        # Spread realistico
        spread=calc_spread(ind,i)

        # Dynamic TP/SL per strategie ATR-based
        curr_tp=tp; curr_sl=sl
        if name in ('S13_STRUC_BREAK','S14_KEY_LEVELS') and atr:
            curr_tp=round(atr*2.0,2); curr_sl=round(atr*1.0,2)
        if name in ('S00_MFKK','S00_MFKK_HWR'):
            curr_tp=20.0; curr_sl=12.0

        sig=sig_fn(ind,i,hour)
        if sig is None: continue

        entry=c['c']
        # Applica spread: BUY compra ad ASK (entry+spread/2), SELL vende a BID (entry-spread/2)
        if sig=='buy':
            entry_with_spread=entry+spread/2
            tp_p=entry_with_spread+curr_tp; sl_p=entry_with_spread-curr_sl
        else:
            entry_with_spread=entry-spread/2
            tp_p=entry_with_spread-curr_tp; sl_p=entry_with_spread+curr_sl

        # Simula esito sulle barre successive (max 48 barre = 2 giorni)
        outcome='timeout'; pnl=0
        for j in range(i+1, min(i+49,n)):
            fc=candles[j]
            if sig=='buy':
                if fc['l']<=sl_p: outcome='sl'; pnl=-curr_sl-spread/2; break
                if fc['h']>=tp_p: outcome='tp'; pnl=curr_tp-spread/2; break
            else:
                if fc['h']>=sl_p: outcome='sl'; pnl=-curr_sl-spread/2; break
                if fc['l']<=tp_p: outcome='tp'; pnl=curr_tp-spread/2; break
        if outcome=='timeout':
            # Chiudi a mercato (con spread/2 di costo aggiuntivo)
            pnl=(candles[min(i+48,n-1)]['c']-entry_with_spread)*(1 if sig=='buy' else -1)-spread/2
            pnl=round(pnl,2)

        regime=detect_regime(ind,i)
        trades.append({
            'time':dt.isoformat(),'dir':sig,'entry':round(entry_with_spread,2),
            'pnl':round(pnl,2),'outcome':outcome,'spread':round(spread,2),
            'regime':regime,'strategy':name,'hour':hour
        })
        day_count[day]+=1; last_trade_ts[day]=ts

    return trades

def run_regime_adaptive(candles, ind, tp=TP_USD, sl=SL_USD):
    """
    Dynamic regime-adaptive selector.
    Ad ogni barra rileva il regime e usa la strategia con priorità più alta.
    Max 1 segnale per barra (la prima strategia che spara wins).
    """
    n=len(candles); trades=[]
    day_count=defaultdict(int); last_trade_ts=defaultdict(lambda: -9999)
    WARMUP=250

    for i in range(WARMUP, n):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')

        if not (SESSION[0]<=hour<SESSION[1]): continue
        atr=ind['atr'][i]; atr30=ind['atr30'][i]
        if atr and atr30 and atr>EXTREME_K*atr30: continue
        if day_count[day]>=MAX_TRADES: continue
        elapsed=(ts-last_trade_ts[day])/3600
        if elapsed<COOLDOWN_H: continue

        regime=detect_regime(ind,i)
        if regime=='EXTREME': continue

        spread=calc_spread(ind,i)
        priority=REGIME_PRIORITY.get(regime, ['S00_MFKK'])

        sig=None; chosen=None
        for sname in priority:
            fn=STRATS.get(sname)
            if fn is None: continue
            s=fn(ind,i,hour)
            if s is not None:
                sig=s; chosen=sname; break

        if sig is None: continue

        curr_tp=tp; curr_sl=sl
        if chosen in ('S00_MFKK','S00_MFKK_HWR'): curr_tp=20.0; curr_sl=12.0
        elif chosen in ('S13_STRUC_BREAK','S14_KEY_LEVELS') and atr:
            curr_tp=round(atr*2.0,2); curr_sl=round(atr*1.0,2)

        if sig=='buy':
            e=c['c']+spread/2; tp_p=e+curr_tp; sl_p=e-curr_sl
        else:
            e=c['c']-spread/2; tp_p=e-curr_tp; sl_p=e+curr_sl

        outcome='timeout'; pnl=0
        for j in range(i+1, min(i+49,n)):
            fc=candles[j]
            if sig=='buy':
                if fc['l']<=sl_p: outcome='sl'; pnl=-curr_sl-spread/2; break
                if fc['h']>=tp_p: outcome='tp'; pnl=curr_tp-spread/2; break
            else:
                if fc['h']>=sl_p: outcome='sl'; pnl=-curr_sl-spread/2; break
                if fc['l']<=tp_p: outcome='tp'; pnl=curr_tp-spread/2; break
        if outcome=='timeout':
            pnl=(candles[min(i+48,n-1)]['c']-e)*(1 if sig=='buy' else -1)-spread/2
            pnl=round(pnl,2)

        trades.append({
            'time':dt.isoformat(),'dir':sig,'entry':round(e,2),'pnl':round(pnl,2),
            'outcome':outcome,'spread':round(spread,2),'regime':regime,
            'strategy':chosen,'hour':hour
        })
        day_count[day]+=1; last_trade_ts[day]=ts

    return trades

# ══════════════════════════════════════════════════════════════
# STATISTICHE
# ══════════════════════════════════════════════════════════════
def stats(trades, name=''):
    if not trades:
        return {'name':name,'n':0,'wr':0,'pnl':0,'pf':0,'maxdd':0,'sharpe':0,
                'avg_spread':0,'pnl_buy':0,'pnl_sell':0,'by_regime':{}}
    n=len(trades)
    wins=[t for t in trades if t['pnl']>0]
    losses=[t for t in trades if t['pnl']<=0]
    total_pnl=round(sum(t['pnl'] for t in trades),2)
    wr=round(len(wins)/n*100,1)
    gross_win=sum(t['pnl'] for t in wins)
    gross_loss=abs(sum(t['pnl'] for t in losses))
    pf=round(gross_win/gross_loss,2) if gross_loss>0 else 99.0
    avg_spread=round(sum(t['spread'] for t in trades)/n,3)

    # Max Drawdown
    equity=0; peak=0; maxdd=0
    for t in trades:
        equity+=t['pnl']
        if equity>peak: peak=equity
        dd=peak-equity
        if dd>maxdd: maxdd=dd
    maxdd=round(maxdd,2)

    # Sharpe semplificato (annualizzato su H1, ~6500 barre/anno)
    pnls=[t['pnl'] for t in trades]
    if len(pnls)>1:
        mean=sum(pnls)/len(pnls)
        std=math.sqrt(sum((x-mean)**2 for x in pnls)/len(pnls))
        sharpe=round((mean/std)*math.sqrt(len(pnls)/2),2) if std>0 else 0
    else: sharpe=0

    # P&L buy vs sell
    pnl_b=round(sum(t['pnl'] for t in trades if t['dir']=='buy'),2)
    pnl_s=round(sum(t['pnl'] for t in trades if t['dir']=='sell'),2)
    n_b=len([t for t in trades if t['dir']=='buy'])
    n_s=len([t for t in trades if t['dir']=='sell'])
    wr_b=round(len([t for t in trades if t['dir']=='buy' and t['pnl']>0])/n_b*100,1) if n_b>0 else 0
    wr_s=round(len([t for t in trades if t['dir']=='sell' and t['pnl']>0])/n_s*100,1) if n_s>0 else 0

    # P&L per mese
    by_month=defaultdict(float)
    for t in trades:
        mo=t['time'][:7]; by_month[mo]+=t['pnl']
    by_month={k:round(v,2) for k,v in sorted(by_month.items())}

    # P&L per regime
    by_regime=defaultdict(lambda:{'n':0,'pnl':0,'wins':0})
    for t in trades:
        r=t['regime']; by_regime[r]['n']+=1; by_regime[r]['pnl']+=t['pnl']
        if t['pnl']>0: by_regime[r]['wins']+=1
    by_regime={k:{'n':v['n'],'pnl':round(v['pnl'],2),'wr':round(v['wins']/v['n']*100,1) if v['n']>0 else 0}
               for k,v in by_regime.items()}

    # Mesi positivi/negativi
    pos_mo=len([v for v in by_month.values() if v>0])
    neg_mo=len([v for v in by_month.values() if v<=0])

    return {
        'name':name,'n':n,'wr':wr,'pnl':total_pnl,'pf':pf,'maxdd':maxdd,'sharpe':sharpe,
        'avg_spread':avg_spread,'pnl_buy':pnl_b,'pnl_sell':pnl_s,
        'n_buy':n_b,'n_sell':n_s,'wr_buy':wr_b,'wr_sell':wr_s,
        'pos_months':pos_mo,'neg_months':neg_mo,'total_months':len(by_month),
        'by_month':by_month,'by_regime':by_regime,
        'pnl_1m': round(total_pnl/max(1,len(by_month)),2),
        'pnl_12m':round(total_pnl/(max(1,len(by_month))/12),2),
        'pnl_24m':total_pnl,
    }

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    print('\n╔══════════════════════════════════════════════════════╗')
    print('║  TradeFlow AI — Backtest Unificato Tutte le Strategie ║')
    print(f'║  Dati: XAUUSD=X (spot OANDA-equiv) · {DAYS}gg H1       ║')
    print(f'║  Spread: ${SPREAD_BASE} base + ATR scaling (OANDA model)   ║')
    print('╚══════════════════════════════════════════════════════╝\n')

    # 1. Scarica dati
    candles = fetch_candles(DAYS)
    if len(candles) < 500:
        print('❌ Dati insufficienti. Verifica connessione internet.')
        return

    # 2. Calcola indicatori
    print('\nCalcolo indicatori...')
    ind = compute_all(candles)
    print(f'✅ Indicatori calcolati su {ind["n"]} barre.')

    # Spread medio atteso
    spreads=[calc_spread(ind,i) for i in range(250,ind['n'])]
    print(f'📊 Spread medio simulato: ${sum(spreads)/len(spreads):.3f} (OANDA model)')
    print(f'   Max spread giornata volatile: ${max(spreads):.3f}')

    # 3. Backtest tutte le strategie
    all_results = {}
    print('\n──────────────────────────────────────────────────────────')
    print('BACKTEST SINGOLE STRATEGIE (con spread realistico)')
    print('──────────────────────────────────────────────────────────')

    for name, fn in STRATS.items():
        try:
            trades = run_backtest(candles, ind, fn, TP_USD, SL_USD, name)
            s = stats(trades, name)
        except Exception as e:
            print(f"  {name:<26} ❌ Errore: {e}")
            all_results[name] = {'name':name,'n':0,'wr':0,'pnl':0,'pf':0,'maxdd':0,'sharpe':0,
                                  'pos_months':0,'total_months':0,'by_month':{},'by_regime':{},
                                  'pnl_1m':0,'pnl_12m':0,'pnl_24m':0,'avg_spread':0,
                                  'pnl_buy':0,'pnl_sell':0,'n_buy':0,'n_sell':0,'wr_buy':0,'wr_sell':0,
                                  'neg_months':0}
            continue
        all_results[name] = s
        wr_str  = f"{s['wr']:>5.1f}%"
        pnl_str = f"${s['pnl']:>8.0f}"
        pf_str  = f"{s['pf']:>5.2f}"
        dd_str  = f"-${s['maxdd']:>6.0f}"
        n_str   = f"{s['n']:>5}"
        sh_str  = f"{s['sharpe']:>5.2f}"
        pm_str  = f"{s.get('pos_months',0)}/{s.get('total_months',0)}"
        print(f"  {name:<26} N={n_str}  WR={wr_str}  P&L={pnl_str}  PF={pf_str}  DD={dd_str}  Sharpe={sh_str}  +Mesi={pm_str}")

    # 4. Dynamic regime-adaptive selector
    print('\n──────────────────────────────────────────────────────────')
    print('BACKTEST REGIME-ADAPTIVE (selezione automatica per regime)')
    print('──────────────────────────────────────────────────────────')
    adaptive_trades = run_regime_adaptive(candles, ind, TP_USD, SL_USD)
    s_adaptive = stats(adaptive_trades, 'REGIME_ADAPTIVE')
    all_results['REGIME_ADAPTIVE'] = s_adaptive
    print(f"  {'REGIME_ADAPTIVE':<26} N={s_adaptive['n']:>5}  WR={s_adaptive['wr']:>5.1f}%  "
          f"P&L=${s_adaptive['pnl']:>8.0f}  PF={s_adaptive['pf']:>5.2f}  "
          f"DD=-${s_adaptive['maxdd']:>6.0f}  Sharpe={s_adaptive['sharpe']:>5.2f}")

    # 5. Ranking per P&L
    print('\n══════════════════════════════════════════════════════════')
    print('RANKING PER P&L (con spread realistico OANDA)')
    print('══════════════════════════════════════════════════════════')
    ranked = sorted(all_results.items(), key=lambda x: x[1]['pnl'], reverse=True)
    print(f"  {'Rank':<5} {'Strategy':<26} {'P&L':>10} {'WR':>7} {'PF':>6} {'MaxDD':>8} {'Sharpe':>8}")
    print(f"  {'────':<5} {'────────────────────────':<26} {'───':>10} {'──':>7} {'──':>6} {'─────':>8} {'──────':>8}")
    for rank, (name, s) in enumerate(ranked, 1):
        if s['n'] < 10: continue  # skip se troppo pochi trade
        print(f"  {rank:<5} {name:<26} ${s['pnl']:>9.0f}  {s['wr']:>5.1f}%  {s['pf']:>5.2f}  -${s['maxdd']:>5.0f}  {s['sharpe']:>6.2f}")

    # 6. Best strategy per regime
    print('\n══════════════════════════════════════════════════════════')
    print('STRATEGIA MIGLIORE PER REGIME (P&L da by_regime)')
    print('══════════════════════════════════════════════════════════')
    regimes = ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN','RANGE','VOLATILE']
    for reg in regimes:
        best_name=None; best_pnl=-99999; best_n=0
        for name,s in all_results.items():
            if name=='REGIME_ADAPTIVE': continue
            r=s['by_regime'].get(reg,{})
            if r.get('n',0)>=5 and r.get('pnl',0)>best_pnl:
                best_pnl=r['pnl']; best_name=name; best_n=r['n']
        if best_name:
            print(f"  {reg:<14} → {best_name:<26} P&L=${best_pnl:.0f} N={best_n}")

    # 7. Monthly breakdown per top strategy
    print('\n══════════════════════════════════════════════════════════')
    print('ANALISI MENSILE — TOP 3 STRATEGIE')
    print('══════════════════════════════════════════════════════════')
    top3 = [name for name,_ in ranked[:4] if all_results[name]['n']>=10][:3]
    for name in top3:
        s=all_results[name]
        print(f"\n  {name} (WR {s['wr']}% | PF {s['pf']} | P&L totale ${s['pnl']})")
        for mo,pnl in s['by_month'].items():
            bar='█'*max(0,int(abs(pnl)/20)) if pnl>0 else '▒'*max(0,int(abs(pnl)/20))
            print(f"    {mo}  {'+' if pnl>=0 else ''}{pnl:>8.0f}  {bar}")

    # 8. Insights automatici
    print('\n══════════════════════════════════════════════════════════')
    print('INSIGHTS AUTOMATICI (per aggiornare directives)')
    print('══════════════════════════════════════════════════════════')

    best_overall = ranked[0]
    worst_overall = sorted(all_results.items(), key=lambda x: x[1]['pnl'])[0]
    best_wr = max((s for s in all_results.values() if s['n']>=10), key=lambda x: x['wr'])
    best_pf = max((s for s in all_results.values() if s['n']>=10), key=lambda x: x['pf'])

    print(f"\n  ✅ Strategia con P&L più alto:  {best_overall[0]} (${best_overall[1]['pnl']})")
    print(f"  ✅ Strategia con WR più alto:   {best_wr['name']} ({best_wr['wr']}%)")
    print(f"  ✅ Strategia con PF più alto:   {best_pf['name']} ({best_pf['pf']})")
    print(f"  ❌ Strategia meno performante:  {worst_overall[0]} (${worst_overall[1]['pnl']})")
    print(f"\n  📊 Spread medio applicato: ${sum(spreads)/len(spreads):.3f}/trade")
    print(f"  📊 REGIME_ADAPTIVE vs best single: ${s_adaptive['pnl']} vs ${best_overall[1]['pnl']}")
    adaptive_is_better = s_adaptive['pnl'] > best_overall[1]['pnl']
    print(f"  {'✅ Il selettore dinamico BATTE la singola migliore strategia!' if adaptive_is_better else '⚠️ La singola strategia batte il selettore dinamico — rifinire le priority'}")

    print(f"\n  🔑 REGOLE DA AGGIORNARE IN DIRECTIVES:")
    for name, s in ranked[:5]:
        if s['n']<10: continue
        buy_better = s['pnl_buy'] > s['pnl_sell'] if s['n_buy']>5 and s['n_sell']>5 else None
        dir_note = f"BUY più redditizio (${s['pnl_buy']})" if buy_better==True else f"SELL più redditizio (${s['pnl_sell']})" if buy_better==False else ""
        print(f"    {name}: P&L ${s['pnl']} | WR {s['wr']}% | PF {s['pf']} | DD -${s['maxdd']} | {dir_note}")

    # 9. Salva report JSON
    report = {
        'generated_at': datetime.datetime.utcnow().isoformat(),
        'symbol': 'XAUUSD=X',
        'period_days': DAYS,
        'candles': len(candles),
        'spread_base': SPREAD_BASE,
        'avg_spread': round(sum(spreads)/len(spreads),3),
        'strategies': all_results,
        'ranking': [{'name':n,'pnl':s['pnl'],'wr':s['wr'],'pf':s['pf'],'maxdd':s['maxdd'],'sharpe':s['sharpe']}
                    for n,s in ranked if s['n']>=10],
        'best_per_regime': {}
    }
    for reg in regimes:
        best_name=None; best_pnl=-99999
        for name,s in all_results.items():
            if name=='REGIME_ADAPTIVE': continue
            r=s['by_regime'].get(reg,{})
            if r.get('n',0)>=5 and r.get('pnl',0)>best_pnl:
                best_pnl=r['pnl']; best_name=name
        if best_name: report['best_per_regime'][reg]=best_name

    out_file='backtest_all_results.json'
    with open(out_file,'w',encoding='utf-8') as f:
        json.dump(report,f,indent=2,ensure_ascii=False)
    print(f'\n📁 Report completo salvato: {out_file}')
    print('\n✅ Backtest completato!')

if __name__=='__main__':
    main()
