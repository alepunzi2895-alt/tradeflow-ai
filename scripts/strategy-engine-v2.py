#!/usr/bin/env python3
"""
TradeFlow AI — Strategy Engine v2
Indicatori: OBV, Alligator, Supertrend, Order Blocks, BB, EMA 20/50/100/200,
            Momentum/ROC, RSI, StochRSI, MACD, ADX, ATR, Keltner, Williams%R, VWAP
Strategie: backtest su 730gg H1 XAU/USD
Output: strategy_engine_v2.json con rank, parametri, entry rules

USO:
  python scripts/strategy-engine-v2.py                         # yfinance GC=F (fallback)
  python scripts/strategy-engine-v2.py --file xauusd_h1_mt5.json  # dati reali MT5 ✅
  python scripts/strategy-engine-v2.py --file xauusd_h1_730d.json # dati storici salvati
"""
import sys, io, argparse, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json, datetime, math
from collections import defaultdict

# ── SIGNAL FUNCTIONS (single source of truth) ────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from signals import (
    signal_mfkk_intraday as s_mfkk_intraday,
    signal_golden_squeeze as s_golden_squeeze,
    signal_mfkk_scalping as s_mfkk_scalping,
    signal_ob_fvg_scalp as s_ob_fvg_scalp,
    signal_convergence_scalp as s_convergence_scalp,
    signal_mfkk_score as se_signal_mfkk_score,
    signal_range_reversal as s_range_reversal,
)
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

# ── ARGPARSE ──────────────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description='TradeFlow AI Backtester v2', add_help=False)
_parser.add_argument('--file', type=str, default=None,
    help='Carica candele da file JSON (prodotto da fetch_mt5_history.py). '
         'Se omesso usa yfinance GC=F.')
_parser.add_argument('--out',  type=str, default='strategy_engine_v2.json',
    help='File output risultati (default: strategy_engine_v2.json)')
_parser.add_argument('--rm',   action='store_true',
    help='Simula Risk Manager adattivo (AI Score da indicatori → lot/BE/TS)')
_args, _ = _parser.parse_known_args()

# ── CONFIG ────────────────────────────────────────────────────────────────────
import os
SYMBOL     = os.getenv('BT_SYMBOL', 'GC=F')
INTERVAL   = os.getenv('BT_INTERVAL', '1h')
PERIOD     = os.getenv('BT_PERIOD', '730d')
TP_USD     = 20.0
SL_USD     = 12.0
MAX_TRADES = 10
COOLDOWN_H = 0.5
SESSION_S  = 0
SESSION_E  = 24
EXTREME_K  = 3.5
OUT_FILE   = _args.out

# ── CARICAMENTO DATI ──────────────────────────────────────────────────────────
def load_from_file(path):
    """Carica candele da JSON prodotto da fetch_mt5_history.py o dati salvati."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    candles = data['candles'] if isinstance(data, dict) and 'candles' in data else data
    tf = data.get('timeframe', 'H1') if isinstance(data, dict) else 'H1'
    src = data.get('source', 'file') if isinstance(data, dict) else 'file'
    sym = data.get('symbol', path) if isinstance(data, dict) else path
    print(f"Caricato {len(candles)} candele da {path} (source={src}, TF={tf}, symbol={sym})")
    return candles, tf

def download():
    if not HAS_YF: raise RuntimeError("pip install yfinance")
    print(f"Downloading {SYMBOL} {INTERVAL} for {PERIOD}...")
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, progress=False)
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
def cci(src, p=50):
    n = len(src); out = [None] * n
    if n < p: return out
    for i in range(p - 1, n):
        sl = src[i - p + 1 : i + 1]
        mn = sum(sl) / p
        md = sum(abs(x - mn) for x in sl) / p
        out[i] = (src[i] - mn) / (0.015 * md) if md != 0 else 0
    return out

def stochastic(src, p=14):
    n = len(src); out = [None] * n
    for i in range(p - 1, n):
        sl = [x for x in src[i - p + 1 : i + 1] if x is not None]
        if len(sl) < p: continue
        lo = min(sl); hi = max(sl)
        out[i] = ((src[i] - lo) / (hi - lo) * 100) if hi > lo else 50
    return out

def stoch_rsi(src, rsi_p=14, stoch_p=14, k_p=3, d_p=3):
    """StochRSI = stoch of RSI"""
    r = rsi(src, rsi_p)
    n = len(r); stoch = [None]*n
    for i in range(rsi_p, n):
        sl = [x for x in r[i-rsi_p+1:i+1] if x is not None]
        if len(sl) < rsi_p or r[i] is None: continue
        lo = min(sl); hi = max(sl)
        stoch[i] = (r[i]-lo)/(hi-lo)*100 if hi>lo else 50
    sk = sma([x if x is not None else 50 for x in stoch], k_p)
    sd = sma([x if x is not None else 50 for x in sk], d_p)
    return sk, sd

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

def stdev_arr(src, p):
    """Standard deviation su finestra rolling p."""
    out=[None]*(p-1)
    for i in range(p-1,len(src)):
        sl=src[i-p+1:i+1]
        mn=sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def dema(src, p):
    """Double EMA — riduce lag rispetto a EMA standard."""
    ma1=ema(src,p); ma2=ema(ma1,p)
    return [2*ma1[i]-ma2[i] for i in range(len(src))]

def obv_macd_tchannel(H,L,C,V,
                      window_len=28,v_len=14,ma_len=9,slow_len=26):
    """
    OBV MACD Indicator — traduzione fedele Pine Script v4
    Ritorna (macd_line, b5, oc)
      macd_line : DEMA(9,obvOut) - EMA(26,close)
      b5        : livello T-Channel
      oc        : direzione (1=bull, -1=bear, 0=init)
    Segnali: oc[i] != oc[i-1] → cambio direzione
    """
    n=len(C)

    # 1. OBV normalizzato a price-scale
    obv_raw=[0.0]
    for i in range(1,n):
        s=1 if C[i]>C[i-1] else (-1 if C[i]<C[i-1] else 0)
        obv_raw.append(obv_raw[-1]+s*(V[i] or 0))

    hl=[H[i]-L[i] for i in range(n)]
    price_spread=stdev_arr(hl,window_len)
    smooth=sma(obv_raw,v_len)
    v_diff=[obv_raw[i]-(smooth[i] or 0) for i in range(n)]
    v_spread=stdev_arr(v_diff,window_len)

    out=[]
    for i in range(n):
        if smooth[i] is None or not v_spread[i] or not price_spread[i]:
            out.append(C[i]); continue
        shadow=(obv_raw[i]-smooth[i])/v_spread[i]*price_spread[i]
        out.append(H[i]+shadow if shadow>0 else L[i]+shadow)

    # 2. DEMA(9) + MACD
    dm=dema(out,ma_len)
    slow_ma=ema(C,slow_len)
    macd_line=[dm[i]-slow_ma[i] for i in range(n)]

    # 3. T-Channel (p=1)
    b5=[macd_line[0]]; oc_=[0]; cum_dev=0.0
    for i in range(1,n):
        cum_dev+=abs(macd_line[i]-b5[-1])
        a15=cum_dev/i
        if   macd_line[i]>b5[-1]+a15: b5.append(macd_line[i])
        elif macd_line[i]<b5[-1]-a15: b5.append(macd_line[i])
        else: b5.append(b5[-1])
        if   b5[-1]>b5[-2]: oc_.append(1)
        elif b5[-1]<b5[-2]: oc_.append(-1)
        else: oc_.append(oc_[-1])

    return macd_line,b5,oc_

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

def calc_fvg(o,h,l,c,std_len=100,displ_factor=2):
    """
    Fair Value Gap (ICT) — H1 approximation per backtester.
    Bullish FVG: L[i] > H[i-2]  (prezzo lascia un gap rialzista)
    Bearish FVG: H[i] < L[i-2]  (prezzo lascia un gap ribassista)
    Displacement: corpo candela intermedia > stdev(corpi, std_len) * displ_factor
    Ritorna:
      fvg_bull[i] = True se la barra i si trova in mitigazione di un Bullish FVG attivo
      fvg_bear[i] = True se la barra i si trova in mitigazione di un Bearish FVG attivo
    """
    n=len(c)
    body=[abs(o[i]-c[i]) for i in range(n)]
    body_std=stdev_arr(body, std_len)
    fvg_bull=[False]*n
    fvg_bear=[False]*n
    active_bull=[]  # list of {'lo': H[i-2], 'hi': L[i], 'bar': i, 'displaced': bool}
    active_bear=[]  # list of {'lo': H[i], 'hi': L[i-2], 'bar': i, 'displaced': bool}

    for i in range(2,n):
        displaced=(body_std[i-1] is not None and body_std[i-1]>0 and
                   body[i-1] > body_std[i-1]*displ_factor)
        # Create new FVGs
        if l[i] > h[i-2]:
            active_bull.append({'lo':h[i-2],'hi':l[i],'bar':i,'displaced':displaced})
        if h[i] < l[i-2]:
            active_bear.append({'lo':h[i],'hi':l[i-2],'bar':i,'displaced':displaced})
        # Check mitigations and invalidations for bull FVGs
        still_bull=[]
        for fvg in active_bull:
            if fvg['bar']==i: still_bull.append(fvg); continue
            if l[i] < fvg['lo']: continue  # invalidato (prezzo sceso sotto il gap)
            if c[i] <= fvg['hi'] and c[i] >= fvg['lo']:
                fvg_bull[i]=True  # mitigazione in corso
            still_bull.append(fvg)
        active_bull=still_bull[-20:]  # mantieni max 20 FVG attivi
        # Check mitigations and invalidations for bear FVGs
        still_bear=[]
        for fvg in active_bear:
            if fvg['bar']==i: still_bear.append(fvg); continue
            if h[i] > fvg['hi']: continue  # invalidato (prezzo salito sopra il gap)
            if c[i] >= fvg['lo'] and c[i] <= fvg['hi']:
                fvg_bear[i]=True  # mitigazione in corso
            still_bear.append(fvg)
        active_bear=still_bear[-20:]

    return fvg_bull, fvg_bear

# ── COMPUTE ALL ───────────────────────────────────────────────────────────────
def compute_all(candles):
    n=len(candles)
    H=[c['h'] for c in candles]; L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]; V=[c['v'] for c in candles]
    O=[c['o'] for c in candles]

    # EMAs
    e13=ema(C,13); e34=ema(C,34); e89=ema(C,89); e233=ema(C,233)
    e20=ema(C,20); e50=ema(C,50); e100=ema(C,100); e200=e233 # Alias

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
    srsi_k,srsi_d=stoch_rsi(C,14,3,3)

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

    # OBV (standard)
    obv_v=obv(C,V)
    obv_ema20=ema(obv_v,20)

    # OBV MACD T-Channel (Pine Script v4 indicator)
    obvm_ml,obvm_b5,obvm_oc=obv_macd_tchannel(H,L,C,V)

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

    # FVG (Fair Value Gap) — per S09_MFKK_SCALPING
    fvg_bull, fvg_bear = calc_fvg(O,H,L,C)

    # CCI_S: CCI(50) -> stochastic(50) -> SMA(8) -> SMA(8)
    cci50 = cci(C, 50)
    stk50 = stochastic(cci50, 50)
    stk_k = sma([x if x is not None else 50 for x in stk50], 8)
    stk_d = sma([x if x is not None else 50 for x in stk_k], 8)

    return {
        'n':n,'H':H,'L':L,'C':C,'V':V,'O':O,
        'e13':e13,'e34':e34,'e89':e89,'e233':e233,
        'e20':e20,'e50':e50,'e100':e100,'e200':e200,
        'macd':ml,'macd_sig':sg,'macd_hist':hist_m,
        'adx':adx_v,'dip':dip,'dim':dim,
        'atr':atr_v,'atr30':atr30,
        'rsi':rsi14,'srsi_k':srsi_k,'srsi_d':srsi_d,
        'bb_up':bb_up,'bb_mid':bb_mid,'bb_lo':bb_lo,'bb_w':bb_w,'bb_w_avg':bb_w_avg,
        'kc_up':kc_up,'kc_mid':kc_mid,'kc_lo':kc_lo,
        'st':st_dir,
        'jaw':jaw,'teeth':teeth,'lips':lips,
        'obv':obv_v,'obv_ema':obv_ema20,
        'obv_macd_ml':obvm_ml,'obv_macd_b5':obvm_b5,'obv_macd_oc':obvm_oc,
        'mom':mom,'wpr':wpr,'vwap':vwap,
        'ob_bull':ob_bull,'ob_bear':ob_bear,
        'fvg_bull':fvg_bull,'fvg_bear':fvg_bear,
        'cci':stk_d, # MFKK uses the smoothed stochastic of CCI
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
    if a>=26 and dm>dp and spread>=10 and diff>=0.5: return 'sell'   # era a>=30, spread>=15, diff>=1.0
    if a>=24 and dp>dm and spread>=10 and diff<=-0.5: return 'buy'   # era a>=28, spread>=15, diff<=-1.0
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

def s12_williams_rsi_keltner(ind,i,hour=None):
    """
    WILLIAMS %R + RSI + KELTNER CHANNEL
    Prezzo tocca Keltner Channel + Williams%R estremo + RSI conferma
    Forte mean-reversion con filtro volatilità
    """
    wpr=ind['wpr'][i]; r=ind['rsi'][i]; c=ind['c'][i] if 'c' in ind else ind['C'][i]
    ku=ind['kc_up'][i]; kl=ind['kc_lo'][i]
    adx=ind['adx'][i]
    if None in (wpr,r,ku,kl,adx): return None
    if adx>=30: return None  # solo ranging/weak
    # BUY: prezzo sotto Keltner lower + W%R<-80 + RSI<35
    if c<=kl*1.002 and wpr<-80 and r<35:
        return 'buy'
    # SELL: prezzo sopra Keltner upper + W%R>-20 + RSI>65
    if c>=ku*0.998 and wpr>-20 and r>65:
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

def s15_obv_macd(ind,i,hour=None):
    """
    OBV MACD T-Channel — Pine Script v4 (traduzione fedele)
    Segnale: T-Channel cambia direzione
      BUY  quando oc passa da -1/0 a  1 (momentum volume-based rialzista)
      SELL quando oc passa da  1/0 a -1 (momentum volume-based ribassista)
    """
    if i<1: return None
    oc=ind.get('obv_macd_oc')
    if oc is None: return None
    if oc[i]==1  and oc[i-1]!=1:  return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1: return 'sell'
    return None

# ── STRATEGY MAP ───────────────────────────────────────────────────────────────
STRATS = {
    'S05_MFKK_INTRADAY':      (s_mfkk_intraday,       ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN']),
    'S09_MFKK_SCALPING':      (s_mfkk_scalping,       ['VOLATILE','WEAK_UP','WEAK_DOWN','RANGE']),
    'S10_OB_FVG_SCALP':       (s_ob_fvg_scalp,        ['RANGE', 'VOLATILE', 'WEAK_UP', 'WEAK_DOWN']),
    'S16_GOLDEN_SQUEEZE':     (s_golden_squeeze,      ['TREND_UP', 'TREND_DOWN', 'WEAK_UP', 'WEAK_DOWN']),
    'S17_CONVERGENCE_SCALP':  (s_convergence_scalp,   ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN','VOLATILE','RANGE']),
    'S00_MFKK':               (se_signal_mfkk_score,  ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN','VOLATILE','RANGE']),
    'S18_RANGE_REVERSAL':     (s_range_reversal,      ['RANGE','WEAK_UP','WEAK_DOWN','UNKNOWN']),
}

# H4: S09/S10 hurt performance (PF 0.446/0.658) — use S16+S17+S00 only
REGIME_PRIORITY_H4 = {
    'TREND_UP':   ['S16_GOLDEN_SQUEEZE', 'S17_CONVERGENCE_SCALP', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    'TREND_DOWN': ['S16_GOLDEN_SQUEEZE', 'S17_CONVERGENCE_SCALP', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    'WEAK_UP':    ['S16_GOLDEN_SQUEEZE', 'S17_CONVERGENCE_SCALP', 'S00_MFKK'],
    'WEAK_DOWN':  ['S16_GOLDEN_SQUEEZE', 'S17_CONVERGENCE_SCALP', 'S00_MFKK'],
    'RANGE':      ['S17_CONVERGENCE_SCALP', 'S00_MFKK'],
    'VOLATILE':   ['S17_CONVERGENCE_SCALP', 'S00_MFKK'],
    'UNKNOWN':    ['S16_GOLDEN_SQUEEZE', 'S17_CONVERGENCE_SCALP'],
}

# M30: S05 rimosso da TREND (backtest 2026-05-08: WR 22.7% → drag). S10 resta (WR 49%, +$638 su M30).
REGIME_PRIORITY_M30 = {
    'TREND_UP':   ['S16_GOLDEN_SQUEEZE', 'S10_OB_FVG_SCALP', 'S00_MFKK'],
    'TREND_DOWN': ['S16_GOLDEN_SQUEEZE', 'S10_OB_FVG_SCALP', 'S00_MFKK'],
    'WEAK_UP':    ['S10_OB_FVG_SCALP', 'S18_RANGE_REVERSAL', 'S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK'],
    'WEAK_DOWN':  ['S10_OB_FVG_SCALP', 'S18_RANGE_REVERSAL', 'S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK'],
    'RANGE':      ['S18_RANGE_REVERSAL', 'S10_OB_FVG_SCALP', 'S09_MFKK_SCALPING', 'S17_CONVERGENCE_SCALP'],
    'VOLATILE':   ['S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'],
    'UNKNOWN':    ['S18_RANGE_REVERSAL', 'S10_OB_FVG_SCALP', 'S16_GOLDEN_SQUEEZE', 'S17_CONVERGENCE_SCALP'],
}

# H1: S10 rimosso da TREND/WEAK (backtest 2026-05-08: WR 27.1%, -$156 su H1).
#     S05 rimosso da TREND (WR 29.7% < soglia 35%). S16+S00 coprono i loro slot.
REGIME_PRIORITY_H1 = {
    'TREND_UP':   ['S16_GOLDEN_SQUEEZE', 'S00_MFKK'],
    'TREND_DOWN': ['S16_GOLDEN_SQUEEZE', 'S00_MFKK'],
    'WEAK_UP':    ['S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK'],
    'WEAK_DOWN':  ['S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK'],
    'RANGE':      ['S10_OB_FVG_SCALP', 'S09_MFKK_SCALPING', 'S17_CONVERGENCE_SCALP'],
    'VOLATILE':   ['S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'],
    'UNKNOWN':    ['S16_GOLDEN_SQUEEZE', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'],
}

# Fallback generico (M15 e altri TF) — invariato
REGIME_PRIORITY = REGIME_PRIORITY_M30

# ── BACKTEST SINGOLA STRATEGIA ────────────────────────────────────────────────
def run_one(candles, ind, name, fn, tf='H1', tp=TP_USD, sl=SL_USD):
    trades=[]; day_n=defaultdict(int); day_h=defaultdict(lambda:-99)
    n=len(candles)
    
    # Scala lookahead bars in base al TF (base 30 bar su H1)
    tf_mult = 1
    if tf == 'M30': tf_mult = 2
    elif tf == 'M15': tf_mult = 4
    elif tf == 'M5': tf_mult = 12
    lookahead = 30 * tf_mult
    if name == 'S17_CONVERGENCE_SCALP': lookahead = 150
    
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
        if name == 'S09_MFKK_SCALPING':
            curr_tp = round(av * 4.0, 2)
            curr_sl = round(av * 1.0, 2)
        elif name == 'S10_OB_FVG_SCALP':
            curr_tp = round(av * 3.5, 2)
            curr_sl = round(av * 1.2, 2)
        elif name == 'S16_GOLDEN_SQUEEZE':
            curr_tp = round(av * 3.5, 2)
            curr_sl = round(av * 2.0, 2)
        elif name == 'S05_MFKK_INTRADAY':
            curr_tp = round(av * 3.5, 2)
            curr_sl = round(av * 1.0, 2)
        elif name == 'S17_CONVERGENCE_SCALP':
            curr_tp = round(av * 4.0, 2)
            curr_sl = round(av * 1.0, 2)
        elif name == 'S00_MFKK':
            curr_tp = round(av * 3.5, 2)
            curr_sl = round(av * 1.0, 2)
        elif name == 'S18_RANGE_REVERSAL':
            curr_tp = round(av * 2.0, 2)
            curr_sl = round(av * 1.2, 2)

        # Route hour/h1_trend correctly per signal function signature
        if name == 'S00_MFKK':
            sig = fn(ind, i, hour=hour)
        elif name == 'S16_GOLDEN_SQUEEZE':
            h1t = ind['st'][i] if ind.get('st') else None
            sig = fn(ind, i, h1_trend=h1t, hour=hour)
        elif name == 'S18_RANGE_REVERSAL':
            sig = fn(ind, i, hour=hour)
        else:
            sig = fn(ind, i, hour)
        if sig is None: continue
        
        entry=c['c']
        tp_p=entry+curr_tp if sig=='buy' else entry-curr_tp
        sl_p=entry-curr_sl if sig=='buy' else entry+curr_sl
        
        outcome='open'; win=False; close_price=entry
        curr_sl_dyn = sl_p
        
        for j in range(i+1,min(i+lookahead,n)): # Scaled lookahead (base 30 H1)
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
        # BUGFIX (2026-07-16): pnl/outcome derivato dal movimento di prezzo firmato reale, non
        # dal ramo (tp_p vs curr_sl_dyn) che ha chiuso il trade. curr_sl_dyn può essere trailato
        # in profondo profitto (BE/trailing sopra); un'uscita lì è comunque una VINCITA se
        # close_price è oltre entry nella direzione del trade. Il vecchio codice etichettava
        # OGNI uscita non-TP come outcome='loss' con pnl=-abs(...) incondizionatamente — un trade
        # trailato a +$40 e chiuso a +$38 veniva registrato come una perdita di $38. Falsava ogni
        # classifica standalone Fase 1 (vedi research/mtf-confluence, 07_self_learning_log.md).
        pnl = (close_price - entry) if sig=='buy' else (entry - close_price)
        outcome = 'win' if pnl > 0 else 'loss'
        trades.append({'date':day,'hour':hour,'dir':sig,'entry':entry,
                        'outcome':outcome,'pnl':round(pnl,2),'strategy':name})
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
def run_adaptive(candles, ind, tf='H1'):
    trades=[]; day_n=defaultdict(int); day_h=defaultdict(lambda:-99)
    n=len(candles)
    if tf == 'H4':
        priority = REGIME_PRIORITY_H4
    elif tf == 'H1':
        priority = REGIME_PRIORITY_H1
    else:
        priority = REGIME_PRIORITY_M30

    tf_mult = 1
    if tf == 'M30': tf_mult = 2
    elif tf == 'M15': tf_mult = 4
    lookahead = 150

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
        pool=priority.get(r,['S16_GOLDEN_SQUEEZE'])
        sig=None; used=None
        h1t_st = ind['st'][i] if ind.get('st') else None
        for name in pool:
            if name not in STRATS: continue
            fn=STRATS[name][0]
            if name == 'S16_GOLDEN_SQUEEZE':
                s=fn(ind,i,h1_trend=h1t_st,hour=hour)
            elif name == 'S00_MFKK':
                s=fn(ind,i,hour=hour,tf=tf)
            elif name == 'S18_RANGE_REVERSAL':
                s=fn(ind,i,hour=hour)
            elif name in ('S05_MFKK_INTRADAY','S09_MFKK_SCALPING','S10_OB_FVG_SCALP','S17_CONVERGENCE_SCALP'):
                s=fn(ind,i,h1_trend=h1t_st,hour=hour)
            else:
                s=fn(ind,i,hour)
            if s: sig=s; used=name; break
        if not sig: continue
        entry=c['c']
        # Strategia con ATR-based TP/SL d'élite
        if used == 'S09_MFKK_SCALPING':
            tp_d = round(av*4.0, 2); sl_d = round(av*1.0, 2)
        elif used == 'S10_OB_FVG_SCALP':
            tp_d = round(av*3.5, 2); sl_d = round(av*1.2, 2)
        elif used == 'S16_GOLDEN_SQUEEZE':
            tp_d = round(av*3.5, 2); sl_d = round(av*2.0, 2)
        elif used == 'S05_MFKK_INTRADAY':
            tp_d = round(av*3.5, 2); sl_d = round(av*1.0, 2)
        elif used == 'S17_CONVERGENCE_SCALP':
            tp_d = round(av*4.0, 2); sl_d = round(av*1.0, 2)
        elif used == 'S00_MFKK':
            tp_d = round(av*3.5, 2); sl_d = round(av*1.0, 2)
        elif used == 'S18_RANGE_REVERSAL':
            tp_d = round(av*2.0, 2); sl_d = round(av*1.2, 2)
        else:
            tp_d = TP_USD; sl_d = SL_USD
        tp_p=entry+tp_d if sig=='buy' else entry-tp_d
        sl_p=entry-sl_d if sig=='buy' else entry+sl_d
        outcome='open'; win=False
        for j in range(i+1,min(i+lookahead,n)):
            jh=candles[j]['h']; jl=candles[j]['l']
            if sig=='buy':
                if jh>=tp_p: win=True; outcome='win'; break
                if jl<=sl_p: outcome='loss'; break
            else:
                if jl<=tp_p: win=True; outcome='win'; break
                if jh>=sl_p: outcome='loss'; break
        if outcome=='open': continue
        pnl=tp_d if win else -sl_d
        trades.append({'date':day,'hour':hour,'dir':sig,'entry':entry,
                        'outcome':outcome,'pnl':pnl,'strategy':used,'regime':r})
        day_n[day]+=1; day_h[day]=hour
    return trades

# ── AI SCORE SIMULATION (per backtest RM) ─────────────────────────────────────
def estimate_ai_score(ind, i):
    """Stima AI Confidence Score da indicatori — proxy per backtest Risk Manager."""
    adx = ind['adx'][i]; dip = ind['dip'][i]; dim = ind['dim'][i]
    mc  = ind['macd'][i]; sg  = ind['macd_sig'][i]; r = ind['rsi'][i]
    if None in (adx, dip, dim, mc, sg, r): return 50.0
    score = 50.0
    if adx >= 30:   score += 22
    elif adx >= 22: score += 10
    elif adx < 15:  score -= 15
    hist = mc - sg
    if abs(hist) > 1.0: score += 10
    elif abs(hist) > 0.4: score += 5
    if 45 <= r <= 65: score += 5
    elif r > 75 or r < 25: score -= 10
    di_spread = abs(dip - dim)
    if di_spread >= 15: score += 10
    elif di_spread >= 8: score += 5
    return max(0.0, min(100.0, score))

# AI Score tiers (mirrors risk_manager.py)
RM_TIERS = [
    {'score_max': 40,  'lot': 0.5, 'tp': 1.0, 'sl': 0.8, 'be_pct': 0.80, 'ts_pct': 0.50, 'label': 'CONSERVATIVE'},
    {'score_max': 60,  'lot': 0.8, 'tp': 1.0, 'sl': 1.0, 'be_pct': 0.70, 'ts_pct': 0.50, 'label': 'NORMAL'},
    {'score_max': 75,  'lot': 1.0, 'tp': 1.5, 'sl': 1.0, 'be_pct': 0.60, 'ts_pct': 0.40, 'label': 'AGGRESSIVE'},
    {'score_max': 85,  'lot': 1.2, 'tp': 1.8, 'sl': 1.2, 'be_pct': 0.50, 'ts_pct': 0.35, 'label': 'STRONG'},
    {'score_max': 100, 'lot': 1.5, 'tp': 2.0, 'sl': 1.5, 'be_pct': 0.50, 'ts_pct': 0.30, 'label': 'MAX'},
]

def get_rm_tier(score):
    for t in RM_TIERS:
        if score <= t['score_max']: return t
    return RM_TIERS[-1]

def run_adaptive_rm(candles, ind, tf='H1'):
    """
    Sistema adattivo con Risk Manager:
    AI Score → lot_mult applicato al P&L (stessa logica TP/SL della FASE 3).
    Misura l'impatto del position sizing adattivo senza distorcere le statistiche con BE/TS.
    """
    trades=[]; day_n=defaultdict(int); day_h=defaultdict(lambda:-99)
    n=len(candles)
    if tf == 'H4':
        priority = REGIME_PRIORITY_H4
    elif tf == 'H1':
        priority = REGIME_PRIORITY_H1
    else:
        priority = REGIME_PRIORITY_M30
    lookahead = 150

    for i in range(220, n):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')
        if not (SESSION_S<=hour<SESSION_E): continue
        av=ind['atr'][i]; aa=ind['atr30'][i]
        if av and aa and av>EXTREME_K*aa: continue
        if day_n[day]>=MAX_TRADES: continue
        if hour-day_h[day]<COOLDOWN_H: continue
        r=regime(ind,i)
        pool=priority.get(r,['S16_GOLDEN_SQUEEZE'])
        sig=None; used=None
        h1t_st = ind['st'][i] if ind.get('st') else None
        for name in pool:
            if name not in STRATS: continue
            fn=STRATS[name][0]
            if name == 'S16_GOLDEN_SQUEEZE':
                s=fn(ind,i,h1_trend=h1t_st,hour=hour)
            elif name == 'S00_MFKK':
                s=fn(ind,i,hour=hour,tf=tf)
            elif name == 'S18_RANGE_REVERSAL':
                s=fn(ind,i,hour=hour)
            elif name in ('S05_MFKK_INTRADAY','S09_MFKK_SCALPING','S10_OB_FVG_SCALP','S17_CONVERGENCE_SCALP'):
                s=fn(ind,i,h1_trend=h1t_st,hour=hour)
            else:
                s=fn(ind,i,hour)
            if s: sig=s; used=name; break
        if not sig: continue

        # ATR-based TP/SL identici a run_adaptive (coerenza confronto)
        if used == 'S09_MFKK_SCALPING':
            tp_d = round(av*4.0, 2); sl_d = round(av*1.0, 2)
        elif used == 'S10_OB_FVG_SCALP':
            tp_d = round(av*3.5, 2); sl_d = round(av*1.2, 2)
        elif used == 'S16_GOLDEN_SQUEEZE':
            tp_d = round(av*3.5, 2); sl_d = round(av*2.0, 2)
        elif used == 'S05_MFKK_INTRADAY':
            tp_d = round(av*3.5, 2); sl_d = round(av*1.0, 2)
        elif used == 'S17_CONVERGENCE_SCALP':
            tp_d = round(av*4.0, 2); sl_d = round(av*1.0, 2)
        elif used == 'S00_MFKK':
            tp_d = round(av*3.5, 2); sl_d = round(av*1.0, 2)
        elif used == 'S18_RANGE_REVERSAL':
            tp_d = round(av*2.0, 2); sl_d = round(av*1.2, 2)
        else:
            tp_d = TP_USD; sl_d = SL_USD

        # AI Score → lot multiplier
        ai_score = estimate_ai_score(ind, i)
        tier = get_rm_tier(ai_score)
        lot_mult = tier['lot']

        entry = c['c']
        tp_p  = entry + tp_d if sig=='buy' else entry - tp_d
        sl_p  = entry - sl_d if sig=='buy' else entry + sl_d
        outcome='open'; win=False

        for j in range(i+1, min(i+lookahead, n)):
            jh=candles[j]['h']; jl=candles[j]['l']
            if sig=='buy':
                if jh >= tp_p: win=True; outcome='win'; break
                if jl <= sl_p: outcome='loss'; break
            else:
                if jl <= tp_p: win=True; outcome='win'; break
                if jh >= sl_p: outcome='loss'; break

        if outcome=='open': continue
        # P&L scalato per lot_mult — misura impatto position sizing
        base_pnl = tp_d if win else -sl_d
        pnl_scaled = round(base_pnl * lot_mult, 2)
        trades.append({'date':day,'hour':hour,'dir':sig,'entry':entry,
                       'outcome':outcome,'pnl':pnl_scaled,'strategy':used,
                       'regime':r,'ai_score':round(ai_score,1),'tier':tier['label'],
                       'lot_mult':lot_mult,'base_pnl':round(base_pnl,2)})
        day_n[day]+=1; day_h[day]=hour
    return trades

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("TradeFlow AI — Strategy Engine v2")
    print("Indicatori: EMA20/50/100/200, MACD, ADX, RSI, StochRSI, BB, Keltner,")
    print("            Supertrend, Alligator, OBV, Momentum, Williams%R, VWAP, Order Blocks")
    print("="*72)

    print("Caricamento dati...")
    if _args.file:
        candles, tf = load_from_file(_args.file)
    else:
        print("  (nessun --file specificato, uso yfinance GC=F)")
        candles = download()
        tf = 'H1'
    print(f"  {len(candles)} candele {tf} | prima: {datetime.datetime.fromtimestamp(candles[0]['t']).strftime('%Y-%m-%d')} | ultima: {datetime.datetime.fromtimestamp(candles[-1]['t']).strftime('%Y-%m-%d')}")

    print("Calcolo 15 indicatori...")
    ind=compute_all(candles)
    print("  OK")

    # ── FASE 1: Backtest individuale ─────────────────────────────────────────
    print("\n" + "="*72)
    print(f"FASE 1: Backtest individuale 12 strategie su {tf}")
    print("="*72)
    hdr=f"{'Strategia':<22} {'N':>5} {'WR%':>6} {'P&L':>8} {'PF':>6} {'$/gg':>7} {'tr/gg':>5} {'Mesi+':>7} {'DD':>7}"
    print(hdr); print("-"*72)
    all_results={}
    for name,(fn,_) in STRATS.items():
        if name=='S10_ST_MACD_SESSION':
            trades=run_one(candles,ind,name,s10_supertrend_macd_session,tf=tf)
        else:
            trades=run_one(candles,ind,name,fn,tf=tf)
        s=stats(trades)
        all_results[name]={'stats':s,'trades':trades}
        print(f"{name:<22} {s['n']:>5} {s['wr']:>6.1f}% {s['pnl']:>8.1f} {s['pf']:>6.3f} {s['avg_day']:>7.2f} {s['tr_day']:>5.2f} {s['months']:>7} {s['dd']:>7.1f}")

    # ── FASE 2: Ranking per PF ────────────────────────────────────────────────
    ranked=sorted(all_results.items(), key=lambda x:-x[1]['stats']['pf'])
    print("\n" + "="*72)
    print(f"RANKING STRATEGIE (per Profit Factor su {tf})")
    print("="*72)
    for i,(name,res) in enumerate(ranked):
        s=res['stats']
        status="✅ USATA" if s['pf']>=1.10 and s['n']>=30 else ("⚠️ BORDELINE" if s['pf']>=1.0 else "❌ ESCLUSA")
        print(f"  {i+1:2}. {name:<22} PF={s['pf']:.3f} WR={s['wr']:.1f}% N={s['n']} {status}")

    # ── FASE 3: Sistema adattivo ──────────────────────────────────────────────
    print("\n" + "="*72)
    print(f"FASE 3: Sistema ADATTIVO (regime + strategia ottimale su {tf})")
    print("="*72)
    adap=run_adaptive(candles,ind,tf=tf)
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
            t2=run_one(candles,ind,name,fn,tf=tf,tp=tp,sl=sl)
            s2=stats(t2,tp,sl)
            rr=tp/sl
            print(f"  ${tp:>4} ${sl:>4} {rr:>5.2f} | {s2['n']:>5} {s2['wr']:>6.1f}% {s2['pnl']:>8.1f} {s2['pf']:>6.3f}")

    # ── FASE 5: Sistema adattivo + Risk Manager (--rm) ───────────────────────
    rm_trades = []; srm = {}; by_rm = defaultdict(list)
    if _args.rm:
        print("\n" + "="*72)
        print(f"FASE 5: Sistema ADATTIVO + RISK MANAGER (AI Score simulato · {tf})")
        print("="*72)
        rm_trades = run_adaptive_rm(candles, ind, tf=tf)
        srm = stats(rm_trades)
        print(f"\n  Trade totali:    {srm['n']}")
        print(f"  Win Rate:        {srm['wr']}%")
        print(f"  P&L totale:      ${srm['pnl']}")
        print(f"  Profit Factor:   {srm['pf']}")
        print(f"  Media $/giorno:  ${srm['avg_day']}")
        print(f"  Trade/giorno:    {srm['tr_day']}")
        print(f"  Mesi positivi:   {srm['months']}")
        print(f"  Max Drawdown:    ${srm['dd']}")

        by_rm = defaultdict(list)
        for t in rm_trades: by_rm[t['strategy']].append(t)
        print(f"\n  {'Strategia':<22} {'N':>5} {'WR%':>6} {'P&L':>8}")
        for name, tl in sorted(by_rm.items(), key=lambda x: -len(x[1])):
            s2 = stats(tl)
            print(f"  {name:<22} {s2['n']:>5} {s2['wr']:>6.1f}% {s2['pnl']:>8.1f}")

        # Distribuzione AI Score tier
        tier_dist = defaultdict(int)
        for t in rm_trades: tier_dist[t['tier']] += 1
        print(f"\n  Distribuzione tier:")
        for tier_name, cnt in sorted(tier_dist.items(), key=lambda x: -x[1]):
            print(f"    {tier_name:<14}: {cnt} trade ({cnt/srm['n']*100:.1f}%)")

        print(f"\n  Confronto Base vs RM:")
        print(f"    Base:   P&L ${sa['pnl']} | PF {sa['pf']} | WR {sa['wr']}%")
        print(f"    Con RM: P&L ${srm['pnl']} | PF {srm['pf']} | WR {srm['wr']}%")

    # ── FASE 6: S17_CONVERGENCE_SCALP ─────────────────────────────────────────
    print("\n" + "="*72)
    print("FASE 6: S17_CONVERGENCE_SCALP V2 — EMA34/89 + StochRSI + BB%B + EMA50")
    print("        (backtest su dati H1 come proxy; su M5/M15 frequenza ×12/×4)")
    print("="*72)
    s17_trades = run_one(candles, ind, 'S17_CONVERGENCE_SCALP', s_convergence_scalp, tf=tf, tp=25, sl=12) # Proxy para 2.5x TP / 0.8x SL
    ss17 = stats(s17_trades)
    print(f"\n  Trade totali:    {ss17['n']}")
    print(f"  Win Rate:        {ss17['wr']}%")
    print(f"  P&L totale:      ${ss17['pnl']}")
    print(f"  Profit Factor:   {ss17['pf']}")
    print(f"  Trade/giorno:    {ss17['tr_day']}")
    print(f"  Media $/giorno:  ${ss17['avg_day']}")
    print(f"  Mesi positivi:   {ss17['months']}")
    print(f"  Max Drawdown:    ${ss17['dd']}")
    print(f"\n  TP: ATR×2.5 | SL: ATR×0.8 | RR: 3.125")
    print(f"  Su M5 frequenza stimata: {ss17['tr_day']*12:.1f} trade/gg")
    if ss17['pf'] >= 1.10 and ss17['n'] >= 30:
        print(f"  → ✅ PROMETTENTE: PF {ss17['pf']:.3f} su dati proxy H1")
        print(f"     Raccomandazione: backtest dedicato su dati M5 prima dell'attivazione")
    elif ss17['pf'] >= 1.0:
        print(f"  → ⚠️  BORDELINE: PF {ss17['pf']:.3f} — ottimizzare soglie o cambiare TF")
    else:
        print(f"  → ❌ NON PROFICUA su questo dataset: PF {ss17['pf']:.3f}")

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
        'regime_priority':REGIME_PRIORITY_H4 if tf == 'H4' else REGIME_PRIORITY,
        'adaptive':{'stats':sa,'by_strategy':{n:stats(tl) for n,tl in by_s.items()}},
        'adaptive_rm':{'stats':srm,'by_strategy':{n:stats(tl) for n,tl in by_rm.items()}} if rm_trades else {},
        'last_signals':adap[-50:],
        'config':{'tp':TP_USD,'sl':SL_USD,'max_trades':MAX_TRADES,'cooldown_h':COOLDOWN_H,
                  'session_utc':[SESSION_S,SESSION_E],'extreme_mult':EXTREME_K}
    }
    with open(OUT_FILE,'w') as f:
        json.dump(output,f,indent=2,default=str)

    print("\n" + "="*72)
    print(f"SALVATO: {OUT_FILE}")
    print(f"SISTEMA ADATTIVO: {sa['wr']}% WR · ${sa['avg_day']}/gg · {sa['tr_day']:.1f} trade/gg")
    if _args.rm:
        print(f"ADATTIVO + RM:    {srm['wr']}% WR · ${srm['avg_day']}/gg · {srm['tr_day']:.1f} trade/gg")
    print("="*72)

if __name__=='__main__':
    main()
