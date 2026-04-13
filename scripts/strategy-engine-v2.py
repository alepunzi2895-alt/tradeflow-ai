#!/usr/bin/env python3
"""
TradeFlow AI — Strategy Engine v2
Indicatori: OBV, Alligator, Supertrend, Order Blocks, BB, EMA 20/50/100/200,
            Momentum/ROC, RSI, StochRSI, MACD, ADX, ATR, Keltner, Williams%R, VWAP
Strategie: 12 strategie composite backtestato su 730gg H1 XAU/USD
Output: strategy_engine_v2.json con rank, parametri, entry rules
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json, datetime, math
from collections import defaultdict
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOL     = 'GC=F'
TP_USD     = 20.0
SL_USD     = 12.0
MAX_TRADES = 10          # per giorno (aggiornato)
COOLDOWN_H = 0.5         # 30 min tra trade
SESSION_S  = 0           # 24h trading
SESSION_E  = 24
EXTREME_K  = 3.5        

# ── DOWNLOAD ─────────────────────────────────────────────────────────────────
def download():
    if not HAS_YF: raise RuntimeError("pip install yfinance")
    df = yf.download(SYMBOL, period='730d', interval='1h', progress=False)
    if df is None or len(df)==0: raise RuntimeError(f"No data for {SYMBOL}")
    if hasattr(df.columns,'levels'): df.columns = df.columns.get_level_values(0)
    out=[]
    for ts,row in df.iterrows():
        o=row.get('Open'); h=row.get('High'); l=row.get('Low')
        c=row.get('Close'); v=row.get('Volume',0)
        if None in (o,h,l,c) or math.isnan(float(c)): continue
        out.append({'t':int(ts.timestamp()),'o':float(o),'h':float(h),
                    'l':float(l),'c':float(c),'v':float(v or 0)})
    return out

# ── MATH HELPERS ──────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for x in src[1:]: v=x*k+v*(1-k); o.append(v)
    return o

def smma(src, p):
    """Smoothed MA (Wilder) — usata da Alligator"""
    o=[None]*(p-1)
    init=sum(src[:p])/p; o.append(init); v=init
    for x in src[p:]: v=(v*(p-1)+x)/p; o.append(v)
    return o

def sma(src, p):
    o=new=[None]*(p-1)
    for i in range(p-1,len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def rsi(src, p=14):
    n=len(src); out=[None]*n
    if n<=p: return out
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    l=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def stoch_rsi(src, rsi_p=14, stoch_p=14, k_p=3, d_p=3):
    """StochRSI = stoch of RSI"""
    r=rsi(src,rsi_p)
    n=len(r); raw=[None]*n
    for i in range(stoch_p-1,n):
        sl=[x for x in r[i-stoch_p+1:i+1] if x is not None]
        if len(sl)<stoch_p or r[i] is None: continue
        hi=max(sl); lo=min(sl)
        raw[i]=(r[i]-lo)/(hi-lo)*100 if hi>lo else 50
    sk=sma([x if x else 50 for x in raw],k_p)
    sd=sma([x if x else 50 for x in sk],d_p)
    return sk,sd

def bollinger(src, p=20, m=2.0):
    mid=sma(src,p); up=[]; lo=[]
    for i,v in enumerate(mid):
        if v is None: up.append(None);lo.append(None);continue
        sl=src[i-p+1:i+1]
        mn=sum(sl)/p
        std=math.sqrt(sum((x-mn)**2 for x in sl)/p)
        up.append(v+m*std); lo.append(v-m*std)
    bw=[(up[i]-lo[i])/mid[i] if (mid[i] and up[i] is not None) else None for i in range(len(src))]
    return up,mid,lo,bw

def keltner(h,l,c,p=20,m=2.0,atr_p=10):
    mid=ema(c,p)
    atr_v=atr(h,l,c,atr_p)
    up=[mid[i]+m*atr_v[i] if atr_v[i] else None for i in range(len(c))]
    lo=[mid[i]-m*atr_v[i] if atr_v[i] else None for i in range(len(c))]
    return up,mid,lo

def atr(h,l,c,p=14):
    tr=[0]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return sma(tr,p)

def adx_full(h,l,c,p=14):
    n=len(c); TR=[0];DMP=[0];DMM=[0]
    for i in range(1,n):
        TR.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    sT=[0];sP=[0];sM=[0]
    for i in range(1,n):
        sT.append(sT[-1]-sT[-1]/p+TR[i])
        sP.append(sP[-1]-sP[-1]/p+DMP[i])
        sM.append(sM[-1]-sM[-1]/p+DMM[i])
    DIP=[sP[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DIM=[sM[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    ADX=sma(DX,p)
    return ADX,DIP,DIM

def macd_full(c,f=12,sl=26,sig=9):
    e1=ema(c,f); e2=ema(c,sl)
    ml=[e1[i]-e2[i] for i in range(len(c))]
    sg=ema(ml,sig)
    hist=[ml[i]-sg[i] for i in range(len(c))]
    return ml,sg,hist

def supertrend(h,l,c,p=10,m=3.0):
    """Supertrend indicator"""
    atr_v=atr(h,l,c,p)
    n=len(c); dir_=[1]*n; st=[0.0]*n
    ub=[(h[i]+l[i])/2+m*(atr_v[i] or 0) for i in range(n)]
    lb=[(h[i]+l[i])/2-m*(atr_v[i] or 0) for i in range(n)]
    final_ub=[0.0]*n; final_lb=[0.0]*n
    for i in range(1,n):
        final_ub[i]=ub[i] if ub[i]<final_ub[i-1] or c[i-1]>final_ub[i-1] else final_ub[i-1]
        final_lb[i]=lb[i] if lb[i]>final_lb[i-1] or c[i-1]<final_lb[i-1] else final_lb[i-1]
        if st[i-1]==final_ub[i-1] and c[i]<=final_ub[i]: st[i]=final_ub[i]; dir_[i]=1
        elif st[i-1]==final_ub[i-1] and c[i]>final_ub[i]: st[i]=final_lb[i]; dir_[i]=-1
        elif st[i-1]==final_lb[i-1] and c[i]>=final_lb[i]: st[i]=final_lb[i]; dir_[i]=-1
        elif st[i-1]==final_lb[i-1] and c[i]<final_lb[i]: st[i]=final_ub[i]; dir_[i]=1
        else: st[i]=final_ub[i]; dir_[i]=1
    return dir_  # 1=bearish (price below), -1=bullish (price above)

def alligator(h,l):
    """Williams Alligator — SMMA di HL/2"""
    med=[(h[i]+l[i])/2 for i in range(len(h))]
    jaw=smma(med,13)    # 8 shift (non shiftiamo per semplicità — usiamo valore attuale)
    teeth=smma(med,8)   # 5 shift
    lips=smma(med,5)    # 3 shift
    return jaw,teeth,lips

def obv(c,v):
    out=[0.0]
    for i in range(1,len(c)):
        if c[i]>c[i-1]: out.append(out[-1]+v[i])
        elif c[i]<c[i-1]: out.append(out[-1]-v[i])
        else: out.append(out[-1])
    return out

def momentum(c,p=10):
    """Rate of Change (%)"""
    out=[None]*p
    for i in range(p,len(c)):
        out.append((c[i]-c[i-p])/c[i-p]*100 if c[i-p]!=0 else 0)
    return out

def williams_r(h,l,c,p=14):
    out=[None]*(p-1)
    for i in range(p-1,len(c)):
        hi=max(h[i-p+1:i+1]); lo=min(l[i-p+1:i+1])
        out.append((hi-c[i])/(hi-lo)*-100 if hi>lo else -50)
    return out

def vwap_daily(candles):
    """Calcola VWAP resettato ogni giorno UTC"""
    out=[0.0]*len(candles)
    cum_pv=0; cum_v=0; last_day=None
    for i,c in enumerate(candles):
        dt=datetime.datetime.utcfromtimestamp(c['t'])
        day=dt.date()
        if day!=last_day: cum_pv=0; cum_v=0; last_day=day
        tp=(c['h']+c['l']+c['c'])/3
        cum_pv+=tp*c['v']; cum_v+=c['v']
        out[i]=cum_pv/cum_v if cum_v>0 else tp
    return out

def order_blocks(h,l,c,lookback=5,threshold=0.5):
    """
    Bullish OB: ultima candela bearish prima di impulso rialzista forte
    Bearish OB: ultima candela bullish prima di impulso ribassista forte
    Ritorna lista di zone (tipo, high, low, indice)
    """
    n=len(c); obs=[]
    for i in range(lookback,n-3):
        # Impulso rialzista: next 3 candles gain > threshold%
        gain3=sum(max(0,c[i+j]-c[i+j-1]) for j in range(1,4))/c[i]*100
        if gain3>threshold and c[i]<c[i-1]:  # candela bearish prima del pump
            obs.append({'type':'bull_ob','hi':h[i],'lo':l[i],'idx':i})
        # Impulso ribassista
        drop3=sum(max(0,c[i+j-1]-c[i+j]) for j in range(1,4))/c[i]*100
        if drop3>threshold and c[i]>c[i-1]:  # candela bullish prima del dump
            obs.append({'type':'bear_ob','hi':h[i],'lo':l[i],'idx':i})
    return obs

# ── COMPUTE ALL ───────────────────────────────────────────────────────────────
def compute_all(candles):
    n=len(candles)
    H=[c['h'] for c in candles]; L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]; V=[c['v'] for c in candles]
    O=[c['o'] for c in candles]

    # EMAs
    e20=ema(C,20); e50=ema(C,50); e100=ema(C,100); e200=ema(C,200)

    # MACD
    ml,sg,hist_m=macd_full(C)

    # ADX
    adx_v,dip,dim=adx_full(H,L,C,14)

    # ATR
    atr_v=atr(H,L,C,14)
    atr30=sma([x if x else 0 for x in atr_v],30)

    # RSI
    rsi14=rsi(C,14)

    # StochRSI
    srsi_k,srsi_d=stoch_rsi(C,14,14,3,3)

    # Bollinger (20,2)
    bb_up,bb_mid,bb_lo,bb_w=bollinger(C,20,2.0)
    # BB width 20-period avg for squeeze detection
    bb_w_avg=sma([x if x else 0 for x in bb_w],20)

    # Keltner (20,2 ATR10)
    kc_up,kc_mid,kc_lo=keltner(H,L,C,20,2.0,10)

    # Supertrend(10,3)
    st_dir=supertrend(H,L,C,10,3.0)

    # Alligator
    jaw,teeth,lips=alligator(H,L)

    # OBV
    obv_v=obv(C,V)
    obv_ema20=ema(obv_v,20)

    # Momentum/ROC (10)
    mom=momentum(C,10)

    # Williams %R (14)
    wpr=williams_r(H,L,C,14)

    # VWAP
    vwap=vwap_daily(candles)

    # Order Blocks (pre-computed, used as zones)
    obs=order_blocks(H,L,C)
    # Crea array boolean: è il prezzo in un OB attivo?
    ob_bull=[False]*n; ob_bear=[False]*n
    for ob in obs:
        # OB è attivo se non è stato invalidato (prezzo non ci è passato oltre)
        for j in range(ob['idx']+1,min(ob['idx']+50,n)):
            if ob['type']=='bull_ob':
                if C[j]>=ob['lo'] and C[j]<=ob['hi']: ob_bull[j]=True
                if C[j]<ob['lo']: break  # invalidato
            else:
                if C[j]>=ob['lo'] and C[j]<=ob['hi']: ob_bear[j]=True
                if C[j]>ob['hi']: break

    return {
        'n':n,'H':H,'L':L,'C':C,'V':V,'O':O,
        'e20':e20,'e50':e50,'e100':e100,'e200':e200,
        'macd':ml,'macd_sig':sg,'macd_hist':hist_m,
        'adx':adx_v,'dip':dip,'dim':dim,
        'atr':atr_v,'atr30':atr30,
        'rsi':rsi14,'srsi_k':srsi_k,'srsi_d':srsi_d,
        'bb_up':bb_up,'bb_mid':bb_mid,'bb_lo':bb_lo,'bb_w':bb_w,'bb_w_avg':bb_w_avg,
        'kc_up':kc_up,'kc_mid':kc_mid,'kc_lo':kc_lo,
        'st':st_dir,
        'jaw':jaw,'teeth':teeth,'lips':lips,
        'obv':obv_v,'obv_e20':obv_ema20,
        'mom':mom,'wpr':wpr,'vwap':vwap,
        'ob_bull':ob_bull,'ob_bear':ob_bear,
    }

# ── REGIME DETECTION ─────────────────────────────────────────────────────────
def regime(ind,i):
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    av=ind['atr'][i]; aa=ind['atr30'][i]
    if None in (a,av,aa): return 'UNKNOWN'
    rv=av/aa if aa else 1
    if a>=30 and dp>dm: return 'TREND_UP'
    if a>=30 and dm>dp: return 'TREND_DOWN'
    if a>=22 and dp>dm: return 'WEAK_UP'
    if a>=22 and dm>dp: return 'WEAK_DOWN'
    if rv>1.4:           return 'VOLATILE'
    return 'RANGE'

# ── 12 STRATEGIE COMPOSITE ────────────────────────────────────────────────────

def s1_exhaustion(ind,i,hour=None):
    """
    EXHAUSTION (esistente, PF 2.29)
    ADX≥30 + DI dominante + MACD esteso contro-trend
    → segnale di esaurimento del trend corrente
    """
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; sg=ind['macd_sig'][i]
    if None in (a,dp,dm,m,sg): return None
    diff=m-sg; spread=abs(dp-dm)
    if a>=30 and dm>dp and spread>=15 and diff>=1.0: return 'sell'
    if a>=28 and dp>dm and spread>=15 and diff<=-1.0: return 'buy'
    return None

def s2_alligator_trend(ind,i,hour=None):
    """
    ALLIGATOR + EMA200 + OBV
    Alligator aperto in direzione (lips≠teeth≠jaw ordinati) +
    prezzo sopra/sotto EMA200 + OBV in trend
    WR atteso: 48-55% in TREND regime
    """
    jaw=ind['jaw'][i]; teeth=ind['teeth'][i]; lips=ind['lips'][i]
    e200=ind['e200'][i]; c=ind['C'][i]
    obv_v=ind['obv'][i]; obv_e=ind['obv_e20'][i]
    if None in (jaw,teeth,lips,e200,obv_e): return None
    # BUY: lips>teeth>jaw (alligatore aperto su) + sopra EMA200 + OBV crescente
    if lips>teeth>jaw and c>e200 and obv_v>obv_e:
        return 'buy'
    # SELL: lips<teeth<jaw + sotto EMA200 + OBV decrescente
    if lips<teeth<jaw and c<e200 and obv_v<obv_e:
        return 'sell'
    return None

def s3_supertrend_ema(ind,i,hour=None):
    """
    SUPERTREND + EMA 20>50>100 + RSI midline
    Tutti confermano stessa direzione = trend solido
    """
    st=ind['st'][i]; c=ind['C'][i]
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]
    r=ind['rsi'][i]
    if None in (e20,e50,e100,r): return None
    # BUY: supertrend bullish + EMA stack up + RSI sopra 50
    if st==-1 and e20>e50>e100 and r>=50:
        return 'buy'
    # SELL: supertrend bearish + EMA stack down + RSI sotto 50
    if st==1 and e20<e50<e100 and r<=50:
        return 'sell'
    return None

def s4_bb_squeeze_momentum(ind,i,hour=None):
    """
    BB SQUEEZE + MOMENTUM
    Bollinger width sotto media = compressione volatilità
    Breakout + momentum in stessa direzione + Keltner conferma
    """
    if i<1: return None
    bw=ind['bb_w'][i]; bwa=ind['bb_w_avg'][i]
    mom=ind['mom'][i]; c=ind['C'][i]
    bb_up=ind['bb_up'][i]; bb_lo=ind['bb_lo'][i]
    kc_up=ind['kc_up'][i]; kc_lo=ind['kc_lo'][i]
    if None in (bw,bwa,mom,bb_up,bb_lo,kc_up,kc_lo): return None
    # Squeeze: BB dentro Keltner (TTM Squeeze)
    in_squeeze = bb_lo[i] if False else (bb_up<kc_up and bb_lo>kc_lo)
    # Check previous squeeze and current break
    bw_prev=ind['bb_w'][i-1]
    was_squeeze=bw_prev and bw_prev<bwa
    # BUY: uscita da squeeze + momentum positivo + prezzo vicino a BB up
    if was_squeeze and mom>0 and c>=bb_lo*1.005:
        return 'buy'
    if was_squeeze and mom<0 and c<=bb_up*0.995:
        return 'sell'
    return None

def s5_rsi_divergence(ind,i,hour=None):
    """
    RSI DIVERGENCE + SUPERTREND FLIP
    Divergenza bearish/bullish RSI + Supertrend appena cambiato direzione
    Segnale di inversione affidabile
    """
    if i<5: return None
    r=ind['rsi']; c=ind['C']; st=ind['st']
    if None in (r[i],r[i-3],r[i-4],r[i-5]): return None
    # Supertrend flipped in last 2 bars?
    st_flip_bull=(st[i]==-1 and (st[i-1]==1 or st[i-2]==1))
    st_flip_bear=(st[i]==1 and (st[i-1]==-1 or st[i-2]==-1))
    # Bearish divergence: price higher high, RSI lower high
    price_hh=c[i]>c[i-3] and c[i]>c[i-4]
    rsi_lh=r[i]<r[i-3] and r[i]<r[i-4] and r[i]>60
    # Bullish divergence: price lower low, RSI higher low
    price_ll=c[i]<c[i-3] and c[i]<c[i-4]
    rsi_hl=r[i]>r[i-3] and r[i]>r[i-4] and r[i]<40
    if st_flip_bear and price_hh and rsi_lh: return 'sell'
    if st_flip_bull and price_ll and rsi_hl: return 'buy'
    return None

def s6_orderblock_bounce(ind,i,hour=None):
    """
    ORDER BLOCK + RSI + EMA Trend
    Prezzo ritesta una zona di Order Block istituzionale
    RSI non esaurito + EMA principale allineata
    """
    ob_b=ind['ob_bull'][i]; ob_s=ind['ob_bear'][i]
    r=ind['rsi'][i]; e50=ind['e50'][i]; c=ind['C'][i]
    if None in (r,e50): return None
    # Bounce su bullish OB (supporto istituzionale) + in uptrend
    if ob_b and r<=55 and c>e50*0.998:
        return 'buy'
    # Bounce su bearish OB (resistenza istituzionale) + in downtrend
    if ob_s and r>=45 and c<e50*1.002:
        return 'sell'
    return None

def s7_stochrsi_bb(ind,i,hour=None):
    """
    STOCHRSI + BOLLINGER BAND + ALLIGATOR
    StochRSI in zona estrema + prezzo a banda BB + alligatore aperto
    Mean reversion in trend
    """
    sk=ind['srsi_k'][i]; sd=ind['srsi_d'][i]
    bb_u=ind['bb_up'][i]; bb_l=ind['bb_lo'][i]; c=ind['C'][i]
    jaw=ind['jaw'][i]; teeth=ind['teeth'][i]; lips=ind['lips'][i]
    if None in (sk,sd,bb_u,bb_l,jaw,teeth): return None
    # BUY: StochRSI oversold (<20) + prezzo su BB lower + alligatore up
    if sk<20 and sd<20 and c<=bb_l*1.003 and lips>jaw:
        return 'buy'
    # SELL: StochRSI overbought (>80) + prezzo su BB upper + alligatore down
    if sk>80 and sd>80 and c>=bb_u*0.997 and lips<jaw:
        return 'sell'
    return None

def s8_obv_ema_momentum(ind,i,hour=None):
    """
    OBV TREND + EMA STACK + MOMENTUM
    Volume conferma il trend + tutte le EMA allineate + ROC positivo
    Trend-following ad alta convinzione
    """
    obv_v=ind['obv'][i]; obv_e=ind['obv_e20'][i]
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]; e200=ind['e200'][i]
    mom=ind['mom'][i]; adx=ind['adx'][i]; c=ind['C'][i]
    if None in (obv_e,e20,e50,e100,e200,mom,adx): return None
    if adx<18: return None  # serve un minimo di trend
    # BUY: EMA stack perfetto + OBV crescente + momentum positivo
    if e20>e50>e100>e200 and obv_v>obv_e and mom>0 and c>e20:
        return 'buy'
    # SELL: EMA stack ribassista + OBV decrescente + momentum negativo
    if e20<e50<e100<e200 and obv_v<obv_e and mom<0 and c<e20:
        return 'sell'
    return None

def s9_vwap_momentum(ind,i,hour=None):
    """
    VWAP BOUNCE + WILLIAMS %R + MOMENTUM
    Prezzo torna al VWAP dopo deviazione + Williams%R in zona di svolta + momentum
    Intraday mean-reversion vs VWAP
    """
    vwap=ind['vwap'][i]; c=ind['C'][i]
    wpr=ind['wpr'][i]; mom=ind['mom'][i]; r=ind['rsi'][i]
    if None in (vwap,wpr,mom,r): return None
    # BUY: prezzo appena sotto VWAP + W%R oversold + momentum girando
    vwap_diff=(c-vwap)/vwap*100
    if -0.3<=vwap_diff<=0.1 and wpr<-70 and mom>-0.1 and r>=40:
        return 'buy'
    # SELL: prezzo appena sopra VWAP + W%R overbought
    if -0.1<=vwap_diff<=0.3 and wpr>-30 and mom<0.1 and r<=60:
        return 'sell'
    return None

def s10_supertrend_macd_session(ind,i,hour=None):
    """
    SUPERTREND + MACD + SESSION (London/NY)
    Entra in direzione del trend principale (Supertrend) solo quando
    MACD conferma momentum, nelle ore migliori
    """
    if not (7<=hour<=13): return None  # London + prima NY
    st=ind['st'][i]; m=ind['macd'][i]; sg=ind['macd_sig'][i]
    r=ind['rsi'][i]; e50=ind['e50'][i]; c=ind['C'][i]
    if None in (m,sg,r,e50): return None
    diff=m-sg
    # BUY: supertrend bull + MACD bull + RSI ok + sopra EMA50
    if st==-1 and diff>0 and 45<=r<=70 and c>e50:
        return 'buy'
    # SELL: supertrend bear + MACD bear + RSI ok + sotto EMA50
    if st==1 and diff<0 and 30<=r<=55 and c<e50:
        return 'sell'
    return None

def s11_alligator_awakening(ind,i,hour=None):
    """
    ALLIGATOR AWAKENING + ADX RISING + MACD CROSS
    Alligatore che dorme (linee intrecciate) e si sveglia = inizio trend
    Combinato con ADX che sale e MACD che incrocia
    """
    if i<3: return None
    jaw=ind['jaw']; teeth=ind['teeth']; lips=ind['lips']
    adx=ind['adx']; ml=ind['macd']; hist=ind['macd_hist']
    if None in (jaw[i],teeth[i],lips[i],adx[i]): return None
    # Sleeping: linee molto vicine
    spread_now=abs(lips[i]-jaw[i])/jaw[i]*100 if jaw[i] else 0
    spread_prev=abs(lips[i-3]-jaw[i-3])/jaw[i-3]*100 if jaw[i-3] else 0
    was_sleeping=spread_prev<0.3
    # MACD hist cross
    hist_cross_up=hist[i]>0 and hist[i-1] is not None and hist[i-1]<0
    hist_cross_dn=hist[i]<0 and hist[i-1] is not None and hist[i-1]>0
    # BUY: dormiva, si sveglia verso l'alto
    if was_sleeping and spread_now>spread_prev and lips[i]>teeth[i] and hist_cross_up:
        return 'buy'
    # SELL
    if was_sleeping and spread_now>spread_prev and lips[i]<teeth[i] and hist_cross_dn:
        return 'sell'
    return None

def s13_struc_break(ind,i,hour=None):
    """S13: Structure Breakout + Retest"""
    if i < 60: return None
    H=ind['H']; L=ind['L']; C=ind['C']
    hh=max(H[i-40:i]); ll=min(L[i-40:i])
    c=C[i]; l=L[i]; h=H[i]
    if c > hh and l <= hh * 1.001 and l >= hh * 0.999: return 'buy'
    if c < ll and h >= ll * 0.999 and h <= ll * 1.001: return 'sell'
    return None

def s14_key_levels(ind,i,hour=None):
    """S14: Key Levels (Monthly/Weekly Pivots simulated)"""
    if i < 24: return None
    H=ind['H']; L=ind['L']; C=ind['C']
    high=max(H[i-24:i]); low=min(L[i-24:i]); close=C[i]
    pp=(high+low+close)/3
    s1=2*pp-high; r1=2*pp-low
    c=C[i]; r=ind['rsi'][i]
    if r is None: return None
    if c > s1 and L[i] <= s1 * 1.001 and r < 40: return 'buy'
    if c < r1 and H[i] >= r1 * 0.999 and r > 60: return 'sell'
    return None

# ── STRATEGY MAP ──────────────────────────────────────────────────────────────
STRATS = {
    'S01_EXHAUSTION':       (s1_exhaustion,        ['TREND_UP','TREND_DOWN']),
    'S02_ALLIGATOR_OBV':    (s2_alligator_trend,   ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN']),
    'S03_SUPERTREND_EMA':   (s3_supertrend_ema,    ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN']),
    'S04_BB_SQUEEZE':       (s4_bb_squeeze_momentum,['RANGE','VOLATILE','WEAK_UP','WEAK_DOWN']),
    'S05_RSI_DIV':          (s5_rsi_divergence,    ['TREND_UP','TREND_DOWN']),
    'S06_ORDERBLOCK':       (s6_orderblock_bounce, ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN']),
    'S07_STOCHRSI_BB':      (s7_stochrsi_bb,       ['RANGE','VOLATILE']),
    'S08_OBV_EMA_MOM':      (s8_obv_ema_momentum,  ['TREND_UP','TREND_DOWN']),
    'S09_VWAP_WPER':        (s9_vwap_momentum,     ['RANGE','VOLATILE','WEAK_UP','WEAK_DOWN']),
    'S10_ST_MACD_SESSION':  (s10_supertrend_macd_session, ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN']),
    'S11_ALLIGATOR_AWAKEN': (s11_alligator_awakening, ['RANGE','WEAK_UP','WEAK_DOWN']),
    'S12_WPR_RSI_KELT':     (s12_williams_rsi_keltner,['RANGE','VOLATILE']),
    'S13_STRUC_BREAK':      (s13_struc_break,      ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN']),
    'S14_KEY_LEVELS':       (s14_key_levels,       ['RANGE','WEAK_UP','WEAK_DOWN']),
}

REGIME_PRIORITY = {
    'TREND_UP':   ['S01_EXHAUSTION','S08_OBV_EMA_MOM','S03_SUPERTREND_EMA','S02_ALLIGATOR_OBV','S05_RSI_DIV','S10_ST_MACD_SESSION'],
    'TREND_DOWN': ['S01_EXHAUSTION','S08_OBV_EMA_MOM','S03_SUPERTREND_EMA','S02_ALLIGATOR_OBV','S05_RSI_DIV','S10_ST_MACD_SESSION'],
    'WEAK_UP':    ['S10_ST_MACD_SESSION','S02_ALLIGATOR_OBV','S06_ORDERBLOCK','S04_BB_SQUEEZE','S11_ALLIGATOR_AWAKEN'],
    'WEAK_DOWN':  ['S10_ST_MACD_SESSION','S02_ALLIGATOR_OBV','S06_ORDERBLOCK','S04_BB_SQUEEZE','S11_ALLIGATOR_AWAKEN'],
    'RANGE':      ['S12_WPR_RSI_KELT','S07_STOCHRSI_BB','S09_VWAP_WPER','S04_BB_SQUEEZE','S11_ALLIGATOR_AWAKEN'],
    'VOLATILE':   ['S07_STOCHRSI_BB','S12_WPR_RSI_KELT','S09_VWAP_WPER'],
    'UNKNOWN':    ['S10_ST_MACD_SESSION','S07_STOCHRSI_BB','S09_VWAP_WPER'],
}

# ── BACKTEST SINGOLA STRATEGIA ────────────────────────────────────────────────
def run_one(candles, ind, name, fn, tp=TP_USD, sl=SL_USD):
    trades=[]; day_n=defaultdict(int); day_h=defaultdict(lambda:-99)
    n=len(candles)
    for i in range(220,n):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')
        if not (SESSION_S<=hour<SESSION_E): continue
        av=ind['atr'][i]; aa=ind['atr30'][i]
        if av and aa and av>EXTREME_K*aa: continue
        if day_n[day]>=MAX_TRADES: continue
        if hour-day_h[day]<COOLDOWN_H: continue
        
        # Dynamic TP/SL mapping
        curr_tp = tp
        curr_sl = sl
        if name in ('S13_STRUC_BREAK','S14_KEY_LEVELS'):
            curr_tp = round(av * 2.0, 2)
            curr_sl = round(av * 1.0, 2)

        sig=fn(ind,i,hour)
        if sig is None: continue
        
        entry=c['c']
        tp_p=entry+curr_tp if sig=='buy' else entry-curr_tp
        sl_p=entry-curr_sl if sig=='buy' else entry+curr_sl
        
        outcome='open'; win=False; close_price=entry
        curr_sl_dyn = sl_p
        
        for j in range(i+1,min(i+30,n)): # max 30 bars (H1)
            jc=candles[j]['c']; jh=candles[j]['h']; jl=candles[j]['l']
            
            # --- SIMULA BE & TRAILING (nuovo richiesto) ---
            profit = (jc - entry) if sig=='buy' else (entry - jc)
            risk = curr_sl
            if profit >= risk * 0.8: # Break Even
                curr_sl_dyn = entry + 0.2 if sig=='buy' else entry - 0.2
            if profit >= risk * 1.2: # Trailing
                potential = jc - risk * 0.7 if sig=='buy' else jc + risk * 0.7
                if sig=='buy': curr_sl_dyn = max(curr_sl_dyn, potential)
                else: curr_sl_dyn = min(curr_sl_dyn, potential) if curr_sl_dyn else potential

            if sig=='buy':
                if jh>=tp_p: win=True; outcome='win'; close_price=tp_p; break
                if jl<=curr_sl_dyn: outcome='loss'; close_price=curr_sl_dyn; break
            else:
                if jl<=tp_p: win=True; outcome='win'; close_price=tp_p; break
                if jh>=curr_sl_dyn: outcome='loss'; close_price=curr_sl_dyn; break
        
        if outcome=='open': continue
        p_val = abs(close_price - entry)
        pnl = p_val if win else -abs(entry - close_price)
        trades.append({'date':day,'hour':hour,'dir':sig,'entry':entry,
                        'outcome':outcome,'pnl':pnl,'strategy':name})
        day_n[day]+=1; day_h[day]=hour
    return trades

def stats(trades, tp=TP_USD, sl=SL_USD):
    if not trades: return {'n':0,'wr':0,'pnl':0,'pf':0,'dd':0,'avg_day':0,'tr_day':0,'months':'0/0'}
    wins=[t for t in trades if t['outcome']=='win']
    loss=[t for t in trades if t['outcome']=='loss']
    n=len(trades); wr=len(wins)/n*100
    pnl=sum(t['pnl'] for t in trades)
    gw=sum(t['pnl'] for t in wins) if wins else 0
    gl=abs(sum(t['pnl'] for t in loss)) if loss else 0.001
    pf=round(gw/gl,3)
    days=set(t['date'] for t in trades)
    avg=pnl/len(days) if days else 0
    tpd=n/len(days) if days else 0
    mo=defaultdict(list)
    for t in trades: mo[t['date'][:7]].append(t['pnl'])
    pos=sum(1 for v in mo.values() if sum(v)>0)
    cum=0;peak=0;dd=0
    for t in sorted(trades,key=lambda x:x['date']+f"{x['hour']:02d}"):
        cum+=t['pnl']
        if cum>peak: peak=cum
        if peak-cum>dd: dd=peak-cum
    return {'n':n,'wr':round(wr,1),'pnl':round(pnl,1),'pf':pf,
            'dd':round(dd,1),'avg_day':round(avg,2),'tr_day':round(tpd,2),
            'months':f"{pos}/{len(mo)}"}

# ── ADAPTIVE BACKTEST ─────────────────────────────────────────────────────────
def run_adaptive(candles, ind):
    trades=[]; day_n=defaultdict(int); day_h=defaultdict(lambda:-99)
    n=len(candles)
    for i in range(220,n):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')
        if not (SESSION_S<=hour<SESSION_E): continue
        av=ind['atr'][i]; aa=ind['atr30'][i]
        if av and aa and av>EXTREME_K*aa: continue
        if day_n[day]>=MAX_TRADES: continue
        if hour-day_h[day]<COOLDOWN_H: continue
        r=regime(ind,i)
        pool=REGIME_PRIORITY.get(r,['S10_ST_MACD_SESSION'])
        sig=None; used=None
        for name in pool:
            fn=STRATS[name][0]
            s=fn(ind,i,hour) if name=='S10_ST_MACD_SESSION' else fn(ind,i)
            if s: sig=s; used=name; break
        if not sig: continue
        entry=c['c']
        tp_p=entry+TP_USD if sig=='buy' else entry-TP_USD
        sl_p=entry-SL_USD if sig=='buy' else entry+SL_USD
        outcome='open'; win=False
        for j in range(i+1,min(i+25,n)):
            jh=candles[j]['h']; jl=candles[j]['l']
            if sig=='buy':
                if jh>=tp_p: win=True; outcome='win'; break
                if jl<=sl_p: outcome='loss'; break
            else:
                if jl<=tp_p: win=True; outcome='win'; break
                if jh>=sl_p: outcome='loss'; break
        if outcome=='open': continue
        pnl=TP_USD if win else -SL_USD
        trades.append({'date':day,'hour':hour,'dir':sig,'entry':entry,
                        'outcome':outcome,'pnl':pnl,'strategy':used,'regime':r})
        day_n[day]+=1; day_h[day]=hour
    return trades

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("TradeFlow AI — Strategy Engine v2")
    print("Indicatori: EMA20/50/100/200, MACD, ADX, RSI, StochRSI, BB, Keltner,")
    print("            Supertrend, Alligator, OBV, Momentum, Williams%R, VWAP, Order Blocks")
    print("="*72)

    print("Download dati...")
    candles=download()
    print(f"  {len(candles)} candele H1 ({candles[0]['date'] if 'date' in candles[0] else datetime.datetime.utcfromtimestamp(candles[0]['t']).strftime('%Y-%m-%d')} → oggi)")

    print("Calcolo 15 indicatori...")
    ind=compute_all(candles)
    print("  OK")

    # ── FASE 1: Backtest individuale ─────────────────────────────────────────
    print("\n" + "="*72)
    print("FASE 1: Backtest individuale 12 strategie")
    print("="*72)
    hdr=f"{'Strategia':<22} {'N':>5} {'WR%':>6} {'P&L':>8} {'PF':>6} {'$/gg':>7} {'tr/gg':>5} {'Mesi+':>7} {'DD':>7}"
    print(hdr); print("-"*72)
    all_results={}
    for name,(fn,_) in STRATS.items():
        if name=='S10_ST_MACD_SESSION':
            trades=run_one(candles,ind,name,s10_supertrend_macd_session)
        else:
            trades=run_one(candles,ind,name,fn)
        s=stats(trades)
        all_results[name]={'stats':s,'trades':trades}
        print(f"{name:<22} {s['n']:>5} {s['wr']:>6.1f}% {s['pnl']:>8.1f} {s['pf']:>6.3f} {s['avg_day']:>7.2f} {s['tr_day']:>5.2f} {s['months']:>7} {s['dd']:>7.1f}")

    # ── FASE 2: Ranking per PF ────────────────────────────────────────────────
    ranked=sorted(all_results.items(), key=lambda x:-x[1]['stats']['pf'])
    print("\n" + "="*72)
    print("RANKING STRATEGIE (per Profit Factor)")
    print("="*72)
    for i,(name,res) in enumerate(ranked):
        s=res['stats']
        status="✅ USATA" if s['pf']>=1.10 and s['n']>=30 else ("⚠️ BORDELINE" if s['pf']>=1.0 else "❌ ESCLUSA")
        print(f"  {i+1:2}. {name:<22} PF={s['pf']:.3f} WR={s['wr']:.1f}% N={s['n']} {status}")

    # ── FASE 3: Sistema adattivo ──────────────────────────────────────────────
    print("\n" + "="*72)
    print("FASE 3: Sistema ADATTIVO (regime + strategia ottimale)")
    print("="*72)
    adap=run_adaptive(candles,ind)
    sa=stats(adap)
    print(f"\n  Trade totali:    {sa['n']}")
    print(f"  Win Rate:        {sa['wr']}%")
    print(f"  P&L totale:      ${sa['pnl']}")
    print(f"  Profit Factor:   {sa['pf']}")
    print(f"  Media $/giorno:  ${sa['avg_day']}")
    print(f"  Trade/giorno:    {sa['tr_day']}")
    print(f"  Mesi positivi:   {sa['months']}")
    print(f"  Max Drawdown:    ${sa['dd']}")

    by_s=defaultdict(list)
    for t in adap: by_s[t['strategy']].append(t)
    print(f"\n  {'Strategia':<22} {'N':>5} {'WR%':>6} {'P&L':>8}")
    for name,tl in sorted(by_s.items(),key=lambda x:-len(x[1])):
        s2=stats(tl)
        print(f"  {name:<22} {s2['n']:>5} {s2['wr']:>6.1f}% {s2['pnl']:>8.1f}")

    active_days=len(set(t['date'] for t in adap))
    print(f"\n  Giorni con trade: {active_days}/~730")

    # ── FASE 4: Best TP/SL per top 3 strategie ────────────────────────────────
    top3=[n for n,_ in ranked[:3] if ranked[0][1]['stats']['n']>=20][:3]
    print("\n" + "="*72)
    print("FASE 4: TP/SL sweep sulle top 3 strategie")
    print("="*72)
    tp_sl_configs=[(15,9),(18,10),(20,12),(22,12),(25,12),(25,15),(30,15),(30,18)]
    for name in top3:
        fn=STRATS[name][0]
        print(f"\n  {name}:")
        print(f"  {'TP':>5} {'SL':>5} {'R:R':>5} | {'N':>5} {'WR%':>6} {'P&L':>8} {'PF':>6}")
        for tp,sl in tp_sl_configs:
            if name=='S10_ST_MACD_SESSION': continue
            t2=run_one(candles,ind,name,fn,tp=tp,sl=sl)
            s2=stats(t2,tp,sl)
            rr=tp/sl
            print(f"  ${tp:>4} ${sl:>4} {rr:>5.2f} | {s2['n']:>5} {s2['wr']:>6.1f}% {s2['pnl']:>8.1f} {s2['pf']:>6.3f}")

    # ── OUTPUT JSON ───────────────────────────────────────────────────────────
    output={
        'generated_at':datetime.datetime.utcnow().isoformat(),
        'n_candles':len(candles),
        'indicators':['EMA20','EMA50','EMA100','EMA200','MACD','ADX+DI','RSI','StochRSI',
                       'BollingerBands','KeltnerChannels','Supertrend','Alligator',
                       'OBV','Momentum/ROC','Williams%R','VWAP','OrderBlocks','ATR'],
        'strategies':{n:{'stats':r['stats'],'regime_fit':STRATS[n][1]}
                      for n,r in all_results.items()},
        'ranking':[{'rank':i+1,'name':n,'pf':r['stats']['pf'],'wr':r['stats']['wr'],
                    'n':r['stats']['n'],'use':r['stats']['pf']>=1.10 and r['stats']['n']>=30}
                   for i,(n,r) in enumerate(ranked)],
        'regime_priority':REGIME_PRIORITY,
        'adaptive':{'stats':sa,'by_strategy':{n:stats(tl) for n,tl in by_s.items()}},
        'last_signals':adap[-50:],
        'config':{'tp':TP_USD,'sl':SL_USD,'max_trades':MAX_TRADES,'cooldown_h':COOLDOWN_H,
                  'session_utc':[SESSION_S,SESSION_E],'extreme_mult':EXTREME_K}
    }
    with open('strategy_engine_v2.json','w') as f:
        json.dump(output,f,indent=2,default=str)

    print("\n" + "="*72)
    print("SALVATO: strategy_engine_v2.json")
    print(f"SISTEMA ADATTIVO: {sa['wr']}% WR · ${sa['avg_day']}/gg · {sa['tr_day']:.1f} trade/gg")
    print("="*72)

if __name__=='__main__':
    main()
