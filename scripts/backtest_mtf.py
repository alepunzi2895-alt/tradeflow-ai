#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Multi-Timeframe Backtest
Gira TUTTE le strategie su M5 / M15 / M30 / H1 e mostra la tabella comparativa.
Per ogni strategia indica il TF migliore (per PF e P&L).

USO:
  python scripts/backtest_mtf.py
  python scripts/backtest_mtf.py --out mtf_results.json

FILE RICHIESTI (generati da fetch_mt5_history.py):
  xauusd_m5_mt5.json   xauusd_m15_mt5.json
  xauusd_m30_mt5.json  xauusd_h1_mt5.json
"""
import sys, io, json, math, datetime, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument('--out',      default='backtest_mtf_results.json')
ap.add_argument('--playbook', default='regime_playbook.json')
args = ap.parse_args()

# ── DATI TF ───────────────────────────────────────────────────────────────────
TF_FILES = {
    'M5':  'xauusd_m5_mt5.json',
    'M15': 'xauusd_m15_mt5.json',
    'M30': 'xauusd_m30_mt5.json',
    'H1':  'xauusd_h1_mt5.json',
}
# bars_per_hour, warmup, max_lookahead_bars, cooldown_bars, max_trades/day
TF_CFG = {
    'M5':  {'bph': 12, 'warmup': 350, 'look': 72,  'cd': 6,  'max_td': 15},
    'M15': {'bph':  4, 'warmup': 300, 'look': 48,  'cd': 2,  'max_td': 12},
    'M30': {'bph':  2, 'warmup': 250, 'look': 36,  'cd': 1,  'max_td': 10},
    'H1':  {'bph':  1, 'warmup': 220, 'look': 30,  'cd': 1,  'max_td': 10},
}
EXTREME_K = 3.5  # salta barre con ATR > K × media30
TP_MULT   = 1.5  # ATR × 1.5 per TP (valido per tutti)
SL_MULT   = 1.0  # ATR × 1.0 per SL

# ── MATH ──────────────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for x in src[1:]: v=x*k+v*(1-k); o.append(v)
    return o

def smma(src, p):
    o=[None]*(p-1); init=sum(src[:p])/p; o.append(init); v=init
    for x in src[p:]: v=(v*(p-1)+x)/p; o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1, len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def rsi(src, p=14):
    n=len(src); out=[None]*n
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    lo=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    if len(g)<p: return out
    ag=sum(g[:p])/p; al=sum(lo[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+lo[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def stoch_rsi(src, rp=14, sp=14, kp=3, dp=3):
    r=rsi(src,rp); n=len(r); raw=[None]*n
    for i in range(sp-1,n):
        sl=[x for x in r[i-sp+1:i+1] if x is not None]
        if len(sl)<sp or r[i] is None: continue
        hi=max(sl); lo=min(sl)
        raw[i]=(r[i]-lo)/(hi-lo)*100 if hi>lo else 50
    sk=sma([x if x else 50 for x in raw],kp)
    sd=sma([x if x else 50 for x in sk],dp)
    return sk,sd

def bollinger(src, p=20, m=2.0):
    mid=sma(src,p); up=[]; lo=[]
    for i,v in enumerate(mid):
        if v is None: up.append(None); lo.append(None); continue
        sl=src[i-p+1:i+1]; mn=sum(sl)/p
        std=math.sqrt(sum((x-mn)**2 for x in sl)/p)
        up.append(v+m*std); lo.append(v-m*std)
    bw=[(up[i]-lo[i])/mid[i] if (mid[i] and up[i] is not None) else None for i in range(len(src))]
    return up,mid,lo,bw

def keltner(h,l,c,p=20,m=2.0,ap=10):
    mid=ema(c,p); av=atr(h,l,c,ap)
    up=[mid[i]+m*av[i] if av[i] else None for i in range(len(c))]
    lo=[mid[i]-m*av[i] if av[i] else None for i in range(len(c))]
    return up,mid,lo

def atr(h,l,c,p=14):
    tr=[0]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return sma(tr,p)

def adx_full(h,l,c,p=14):
    n=len(c); TR=[0]; DMP=[0]; DMM=[0]
    for i in range(1,n):
        TR.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    sT=[0]; sP=[0]; sM=[0]
    for i in range(1,n):
        sT.append(sT[-1]-sT[-1]/p+TR[i])
        sP.append(sP[-1]-sP[-1]/p+DMP[i])
        sM.append(sM[-1]-sM[-1]/p+DMM[i])
    DIP=[sP[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DIM=[sM[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    return sma(DX,p),DIP,DIM

def macd_full(c,f=12,sl=26,sig=9):
    e1=ema(c,f); e2=ema(c,sl); ml=[e1[i]-e2[i] for i in range(len(c))]
    sg=ema(ml,sig); hist=[ml[i]-sg[i] for i in range(len(c))]
    return ml,sg,hist

def supertrend(h,l,c,p=10,m=3.0):
    av=atr(h,l,c,p); n=len(c); dir_=[1]*n; st=[0.0]*n
    ub=[(h[i]+l[i])/2+m*(av[i] or 0) for i in range(n)]
    lb=[(h[i]+l[i])/2-m*(av[i] or 0) for i in range(n)]
    fub=[0.0]*n; flb=[0.0]*n
    for i in range(1,n):
        fub[i]=ub[i] if ub[i]<fub[i-1] or c[i-1]>fub[i-1] else fub[i-1]
        flb[i]=lb[i] if lb[i]>flb[i-1] or c[i-1]<flb[i-1] else flb[i-1]
        if st[i-1]==fub[i-1] and c[i]<=fub[i]: st[i]=fub[i]; dir_[i]=1
        elif st[i-1]==fub[i-1] and c[i]>fub[i]: st[i]=flb[i]; dir_[i]=-1
        elif st[i-1]==flb[i-1] and c[i]>=flb[i]: st[i]=flb[i]; dir_[i]=-1
        else: st[i]=fub[i]; dir_[i]=1
    return dir_

def alligator(h,l):
    med=[(h[i]+l[i])/2 for i in range(len(h))]
    return smma(med,13),smma(med,8),smma(med,5)

def obv(c,v):
    out=[0.0]
    for i in range(1,len(c)):
        if c[i]>c[i-1]: out.append(out[-1]+v[i])
        elif c[i]<c[i-1]: out.append(out[-1]-v[i])
        else: out.append(out[-1])
    return out

def stdev_arr(src,p):
    out=[None]*(p-1)
    for i in range(p-1,len(src)):
        sl=src[i-p+1:i+1]; mn=sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def dema(src,p):
    m1=ema(src,p); m2=ema(m1,p)
    return [2*m1[i]-m2[i] for i in range(len(src))]

def momentum(c,p=10):
    out=[None]*p
    for i in range(p,len(c)):
        out.append(c[i]-c[i-p])
    return out

def williams_r(h,l,c,p=14):
    out=[None]*(p-1)
    for i in range(p-1,len(c)):
        hi=max(h[i-p+1:i+1]); lo=min(l[i-p+1:i+1])
        out.append((hi-c[i])/(hi-lo)*-100 if hi>lo else -50)
    return out

def vwap_daily(candles):
    out=[0.0]*len(candles); cum_pv=0; cum_v=0; last_day=None
    for i,c in enumerate(candles):
        dt=datetime.datetime.utcfromtimestamp(c['t']); day=dt.date()
        if day!=last_day: cum_pv=0; cum_v=0; last_day=day
        tp=(c['h']+c['l']+c['c'])/3; cum_pv+=tp*c['v']; cum_v+=c['v']
        out[i]=cum_pv/cum_v if cum_v>0 else tp
    return out

def obv_macd_tchannel(H,L,C,V,wl=28,vl=14,ml=9,sl=26):
    n=len(C); o=[0.0]
    for i in range(1,n): s=1 if C[i]>C[i-1] else(-1 if C[i]<C[i-1] else 0); o.append(o[-1]+s*(V[i] or 0))
    hl=[H[i]-L[i] for i in range(n)]; ps=stdev_arr(hl,wl); sm=sma(o,vl)
    vd=[o[i]-(sm[i] or 0) for i in range(n)]; vs=stdev_arr(vd,wl); out=[]
    for i in range(n):
        if sm[i] is None or not vs[i] or not ps[i]: out.append(C[i]); continue
        sh=(o[i]-sm[i])/vs[i]*ps[i]; out.append(H[i]+sh if sh>0 else L[i]+sh)
    dm=dema(out,ml); slw=ema(C,sl); mll=[dm[i]-slw[i] for i in range(n)]
    b5=[mll[0]]; oc=[0]; cd=0.0
    for i in range(1,n):
        cd+=abs(mll[i]-b5[-1]); a=cd/i
        if mll[i]>b5[-1]+a: b5.append(mll[i])
        elif mll[i]<b5[-1]-a: b5.append(mll[i])
        else: b5.append(b5[-1])
        oc.append(1 if b5[-1]>b5[-2] else(-1 if b5[-1]<b5[-2] else oc[-1]))
    return mll,b5,oc

def order_blocks(h,l,c,lb=5,thr=0.5):
    n=len(c); obs=[]
    for i in range(lb,n-3):
        g3=sum(max(0,c[i+j]-c[i+j-1]) for j in range(1,4))/c[i]*100
        if g3>thr and c[i]<c[i-1]: obs.append({'type':'bull','hi':h[i],'lo':l[i],'idx':i})
        d3=sum(max(0,c[i+j-1]-c[i+j]) for j in range(1,4))/c[i]*100
        if d3>thr and c[i]>c[i-1]: obs.append({'type':'bear','hi':h[i],'lo':l[i],'idx':i})
    return obs

def calc_fvg(o,h,l,c,std_len=100,df=2):
    n=len(c); body=[abs(o[i]-c[i]) for i in range(n)]; bs=stdev_arr(body,std_len)
    fb=[False]*n; fs=[False]*n; ab=[]; as_=[];
    for i in range(2,n):
        disp=bs[i-1] is not None and bs[i-1]>0 and body[i-1]>bs[i-1]*df
        if l[i]>h[i-2]: ab.append({'lo':h[i-2],'hi':l[i],'bar':i,'d':disp})
        if h[i]<l[i-2]: as_.append({'lo':h[i],'hi':l[i-2],'bar':i,'d':disp})
        sb=[];
        for fvg in ab:
            if fvg['bar']==i: sb.append(fvg); continue
            if l[i]<fvg['lo']: continue
            if c[i]<=fvg['hi'] and c[i]>=fvg['lo']: fb[i]=True
            sb.append(fvg)
        ab=sb[-20:]
        sb2=[]
        for fvg in as_:
            if fvg['bar']==i: sb2.append(fvg); continue
            if h[i]>fvg['hi']: continue
            if c[i]>=fvg['lo'] and c[i]<=fvg['hi']: fs[i]=True
            sb2.append(fvg)
        as_=sb2[-20:]
    return fb,fs

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute_all(candles):
    n=len(candles)
    H=[c['h'] for c in candles]; L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]; V=[c['v'] for c in candles]
    O=[c['o'] for c in candles]
    e20=ema(C,20); e50=ema(C,50); e100=ema(C,100); e200=ema(C,200)
    ml,sg,hist=macd_full(C)
    adx_v,dip,dim=adx_full(H,L,C,14)
    atr_v=atr(H,L,C,14); atr30=sma([x if x else 0 for x in atr_v],30)
    rsi14=rsi(C,14); srsi_k,srsi_d=stoch_rsi(C,14,14,3,3)
    bb_up,bb_mid,bb_lo,bb_w=bollinger(C,20,2.0); bb_wa=sma([x if x else 0 for x in bb_w],20)
    kc_up,kc_mid,kc_lo=keltner(H,L,C,20,2.0,10)
    st_dir=supertrend(H,L,C,10,3.0)
    jaw,teeth,lips=alligator(H,L)
    obv_v=obv(C,V); obv_e20=ema(obv_v,20)
    obvm_ml,obvm_b5,obvm_oc=obv_macd_tchannel(H,L,C,V)
    mom=momentum(C,10); wpr=williams_r(H,L,C,14); vwap=vwap_daily(candles)
    obs=order_blocks(H,L,C)
    ob_bull=[False]*n; ob_bear=[False]*n
    for ob in obs:
        for j in range(ob['idx']+1,min(ob['idx']+50,n)):
            if ob['type']=='bull':
                if C[j]>=ob['lo'] and C[j]<=ob['hi']: ob_bull[j]=True
                if C[j]<ob['lo']: break
            else:
                if C[j]>=ob['lo'] and C[j]<=ob['hi']: ob_bear[j]=True
                if C[j]>ob['hi']: break
    fvg_bull,fvg_bear=calc_fvg(O,H,L,C)
    cci50=[None]*49
    for i in range(49,n):
        sl=C[i-49:i+1]; mn=sum(sl)/50; md=sum(abs(x-mn) for x in sl)/50
        cci50.append((C[i]-mn)/(0.015*md) if md>0 else 0)
    return {
        'n':n,'H':H,'L':L,'C':C,'V':V,'O':O,
        'e20':e20,'e50':e50,'e100':e100,'e200':e200,
        'macd':ml,'macd_sig':sg,'macd_hist':hist,
        'adx':adx_v,'dip':dip,'dim':dim,'atr':atr_v,'atr30':atr30,
        'rsi':rsi14,'srsi_k':srsi_k,'srsi_d':srsi_d,
        'bb_up':bb_up,'bb_mid':bb_mid,'bb_lo':bb_lo,'bb_w':bb_w,'bb_wa':bb_wa,
        'kc_up':kc_up,'kc_mid':kc_mid,'kc_lo':kc_lo,'st':st_dir,
        'jaw':jaw,'teeth':teeth,'lips':lips,
        'obv':obv_v,'obv_e20':obv_e20,
        'obv_macd_ml':obvm_ml,'obv_macd_b5':obvm_b5,'obv_macd_oc':obvm_oc,
        'mom':mom,'wpr':wpr,'vwap':vwap,
        'ob_bull':ob_bull,'ob_bear':ob_bear,'fvg_bull':fvg_bull,'fvg_bear':fvg_bear,
        'cci':cci50,
    }

# ── REGIME ────────────────────────────────────────────────────────────────────
def regime(ind,i):
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    av=ind['atr'][i]; aa=ind['atr30'][i]
    if None in (a,av,aa): return 'UNKNOWN'
    rv=av/aa if aa else 1
    if a>=30 and dp>dm: return 'TREND_UP'
    if a>=30 and dm>dp: return 'TREND_DOWN'
    if a>=22 and dp>dm: return 'WEAK_UP'
    if a>=22 and dm>dp: return 'WEAK_DOWN'
    if rv>1.4: return 'VOLATILE'
    return 'RANGE'

# ── STRATEGIE ─────────────────────────────────────────────────────────────────
def s_mfkk_score(ind,i,h=None):
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; c=ind['cci'][i]
    if None in (a,dp,dm,m,c): return None
    sb=sc=0.0
    ac=min(a/40*100,100)
    if dm>dp: sc+=ac*0.80
    else:     sb+=ac*0.80
    ms=min(abs(m)/0.5*100,100)
    if m>=0: sb+=ms*0.10
    else:    sc+=ms*0.10
    cs=min(abs(c)/100*100,100)
    if c>=0: sb+=cs*0.10
    else:    sc+=cs*0.10
    if sb>=90 and sb>sc: return 'buy'
    if sc>=75 and sc>sb: return 'sell'
    return None

def s_mfkk_hwr(ind,i,h=None):
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; c=ind['cci'][i]
    if None in (a,dp,dm,m,c): return None
    if a>=35 and dm-dp>=20 and m>=0.5 and c>-100: return 'sell'
    return None

def s_intraday_v1(ind,i,h=None):
    if i<1: return None
    oc=ind['obv_macd_oc']; r=ind['rsi'][i]; m=ind['mom'][i]; a=ind['adx'][i]
    if None in (r,m,a): return None
    if oc[i]==1  and oc[i-1]!=1  and r<62 and m>0 and a>=18: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>38 and m<0 and a>=18: return 'sell'
    return None

def s_intraday_v2(ind,i,h=None):
    if i<2: return None
    oc=ind['obv_macd_oc']; r=ind['rsi'][i]; m=ind['mom'][i]
    a=ind['adx'][i]; mc=ind['macd'][i]
    if None in (r,m,a,mc): return None
    if a<20: return None
    if oc[i]==1  and r>50 and m>0 and mc>0: return 'buy'
    if oc[i]==-1 and r<50 and m<0 and mc<0: return 'sell'
    return None

def s_intraday_v3(ind,i,h=None):
    if i<1: return None
    oc=ind['obv_macd_oc']; r=ind['rsi'][i]; a=ind['adx'][i]; m=ind['mom'][i]
    if None in (r,a,m): return None
    if oc[i]==-1 and r>65 and a>=30 and m<0: return 'sell'
    return None

def s_intraday_v4(ind,i,h=None):
    if i<2: return None
    oc=ind['obv_macd_oc']; r=ind['rsi'][i]; a=ind['adx'][i]
    mc=ind['macd']; m=ind['mom'][i]; c=ind['C'][i]; e50=ind['e50'][i]
    if None in (r,a,mc[i],mc[i-1],m,e50): return None
    if oc[i]==1  and oc[i-1]!=1  and r<58 and a>=25 and mc[i]>0 and m>0 and c>e50: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>42 and a>=25 and mc[i]<0 and m<0 and c<e50: return 'sell'
    return None

def s_exhaustion(ind,i,h=None):
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; sg=ind['macd_sig'][i]
    if None in (a,dp,dm,m,sg): return None
    diff=m-sg; spread=abs(dp-dm)
    if a>=30 and dm>dp and spread>=15 and diff>=1.0: return 'sell'
    if a>=28 and dp>dm and spread>=15 and diff<=-1.0: return 'buy'
    return None

def s_alligator_obv(ind,i,h=None):
    jaw=ind['jaw'][i]; teeth=ind['teeth'][i]; lips=ind['lips'][i]
    e200=ind['e200'][i]; c=ind['C'][i]; obv_v=ind['obv'][i]; obv_e=ind['obv_e20'][i]
    if None in (jaw,teeth,lips,e200,obv_e): return None
    if lips>teeth>jaw and c>e200 and obv_v>obv_e: return 'buy'
    if lips<teeth<jaw and c<e200 and obv_v<obv_e: return 'sell'
    return None

def s_supertrend_ema(ind,i,h=None):
    st=ind['st'][i]; c=ind['C'][i]
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]; r=ind['rsi'][i]
    if None in (e20,e50,e100,r): return None
    if st==-1 and e20>e50>e100 and r>=50: return 'buy'
    if st==1  and e20<e50<e100 and r<=50: return 'sell'
    return None

def s_bb_squeeze(ind,i,h=None):
    if i<1: return None
    bw=ind['bb_w'][i]; bwa=ind['bb_wa'][i]; mom=ind['mom'][i]
    bb_up=ind['bb_up'][i]; bb_lo=ind['bb_lo'][i]
    kc_up=ind['kc_up'][i]; kc_lo=ind['kc_lo'][i]
    if None in (bw,bwa,mom,bb_up,bb_lo,kc_up,kc_lo): return None
    bwp=ind['bb_w'][i-1]; was_sq=bwp and bwp<bwa
    if was_sq and mom>0 and ind['C'][i]>=bb_lo*1.005: return 'buy'
    if was_sq and mom<0 and ind['C'][i]<=bb_up*0.995: return 'sell'
    return None

def s_rsi_div(ind,i,h=None):
    if i<5: return None
    r=ind['rsi']; c=ind['C']; st=ind['st']
    if None in (r[i],r[i-3],r[i-4]): return None
    flip_b=(st[i]==-1 and (st[i-1]==1 or st[i-2]==1))
    flip_s=(st[i]==1  and (st[i-1]==-1 or st[i-2]==-1))
    if flip_s and c[i]>c[i-3] and r[i]<r[i-3] and r[i]>60: return 'sell'
    if flip_b and c[i]<c[i-3] and r[i]>r[i-3] and r[i]<40: return 'buy'
    return None

def s_orderblock(ind,i,h=None):
    ob_b=ind['ob_bull'][i]; ob_s=ind['ob_bear'][i]
    r=ind['rsi'][i]; e50=ind['e50'][i]; c=ind['C'][i]
    if None in (r,e50): return None
    if ob_b and r<=55 and c>e50*0.998: return 'buy'
    if ob_s and r>=45 and c<e50*1.002: return 'sell'
    return None

def s_stochrsi_bb(ind,i,h=None):
    sk=ind['srsi_k'][i]; sd=ind['srsi_d'][i]
    bb_u=ind['bb_up'][i]; bb_l=ind['bb_lo'][i]; c=ind['C'][i]
    jaw=ind['jaw'][i]; lips=ind['lips'][i]
    if None in (sk,sd,bb_u,bb_l,jaw): return None
    if sk<20 and sd<20 and c<=bb_l*1.003 and lips>jaw: return 'buy'
    if sk>80 and sd>80 and c>=bb_u*0.997 and lips<jaw: return 'sell'
    return None

def s_obv_ema_mom(ind,i,h=None):
    obv_v=ind['obv'][i]; obv_e=ind['obv_e20'][i]
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]; e200=ind['e200'][i]
    mom=ind['mom'][i]; adx=ind['adx'][i]; c=ind['C'][i]
    if None in (obv_e,e20,e50,e100,e200,mom,adx): return None
    if adx<18: return None
    if e20>e50>e100>e200 and obv_v>obv_e and mom>0 and c>e20: return 'buy'
    if e20<e50<e100<e200 and obv_v<obv_e and mom<0 and c<e20: return 'sell'
    return None

def s_vwap_mom(ind,i,h=None):
    vwap=ind['vwap'][i]; c=ind['C'][i]
    wpr=ind['wpr'][i]; mom=ind['mom'][i]; r=ind['rsi'][i]
    if None in (vwap,wpr,mom,r): return None
    d=(c-vwap)/vwap*100
    if -0.3<=d<=0.1 and wpr<-70 and mom>-0.1 and r>=40: return 'buy'
    if -0.1<=d<=0.3 and wpr>-30 and mom<0.1  and r<=60: return 'sell'
    return None

def s_st_macd_session(ind,i,hour=None):
    if hour is None or not (7<=hour<=13): return None
    st=ind['st'][i]; m=ind['macd'][i]; sg=ind['macd_sig'][i]
    r=ind['rsi'][i]; e50=ind['e50'][i]; c=ind['C'][i]
    if None in (m,sg,r,e50): return None
    diff=m-sg
    if st==-1 and diff>0 and 45<=r<=70 and c>e50: return 'buy'
    if st==1  and diff<0 and 30<=r<=55 and c<e50: return 'sell'
    return None

def s_alligator_awaken(ind,i,h=None):
    if i<3: return None
    jaw=ind['jaw']; teeth=ind['teeth']; lips=ind['lips']
    hist=ind['macd_hist']
    if None in (jaw[i],teeth[i],lips[i]): return None
    sp_now=abs(lips[i]-jaw[i])/jaw[i]*100 if jaw[i] else 0
    sp_prev=abs(lips[i-3]-jaw[i-3])/jaw[i-3]*100 if jaw[i-3] else 0
    was_sl=sp_prev<0.3
    hcu=hist[i]>0 and hist[i-1] is not None and hist[i-1]<0
    hcd=hist[i]<0 and hist[i-1] is not None and hist[i-1]>0
    if was_sl and sp_now>sp_prev and lips[i]>teeth[i] and hcu: return 'buy'
    if was_sl and sp_now>sp_prev and lips[i]<teeth[i] and hcd: return 'sell'
    return None

def s_wpr_kelt(ind,i,h=None):
    wpr=ind['wpr'][i]; r=ind['rsi'][i]; c=ind['C'][i]
    ku=ind['kc_up'][i]; kl=ind['kc_lo'][i]; adx=ind['adx'][i]
    if None in (wpr,r,ku,kl,adx): return None
    if adx>=30: return None
    if c<=kl*1.002 and wpr<-80 and r<35: return 'buy'
    if c>=ku*0.998 and wpr>-20 and r>65: return 'sell'
    return None

def s_obv_macd(ind,i,h=None):
    if i<1: return None
    oc=ind.get('obv_macd_oc')
    if oc is None: return None
    if oc[i]==1  and oc[i-1]!=1:  return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1: return 'sell'
    return None

def s_mfkk_scalping(ind,i,h=None):
    e20=ind['e20'][i]; e50=ind['e50'][i]; e100=ind['e100'][i]; e200=ind['e200'][i]
    fb=ind.get('fvg_bull'); fs=ind.get('fvg_bear')
    if None in (e20,e50,e100,e200) or fb is None: return None
    if e20>e50>e100>e200 and fb[i]: return 'buy'
    if e20<e50<e100<e200 and fs[i]: return 'sell'
    return None

def s_struc_break(ind,i,h=None):
    if i<60: return None
    H=ind['H']; L=ind['L']; C=ind['C']
    hh=max(H[i-40:i]); ll=min(L[i-40:i]); c=C[i]
    if c>hh and L[i]<=hh*1.001 and L[i]>=hh*0.999: return 'buy'
    if c<ll and H[i]>=ll*0.999 and H[i]<=ll*1.001: return 'sell'
    return None

def s_key_levels(ind,i,h=None):
    if i<24: return None
    H=ind['H']; L=ind['L']; C=ind['C']
    hi=max(H[i-24:i]); lo=min(L[i-24:i]); cl=C[i]
    pp=(hi+lo+cl)/3; s1=2*pp-hi; r1=2*pp-lo
    r=ind['rsi'][i]
    if r is None: return None
    if cl>s1 and L[i]<=s1*1.001 and r<40: return 'buy'
    if cl<r1 and H[i]>=r1*0.999 and r>60: return 'sell'
    return None

STRATEGIES = {
    'S00_MFKK_SCORE':     s_mfkk_score,
    'S00_MFKK_HWR':       s_mfkk_hwr,
    'S05_V1_OBV_RSI_MOM': s_intraday_v1,
    'S05_V2_Triple_MACD': s_intraday_v2,
    'S05_V3_Sell_Exhaust': s_intraday_v3,
    'S05_V4_Strong_5cond': s_intraday_v4,
    'S01_EXHAUSTION':     s_exhaustion,
    'S02_ALLIGATOR_OBV':  s_alligator_obv,
    'S03_SUPERTREND_EMA': s_supertrend_ema,
    'S04_BB_SQUEEZE':     s_bb_squeeze,
    'S05_RSI_DIV':        s_rsi_div,
    'S06_ORDERBLOCK':     s_orderblock,
    'S07_STOCHRSI_BB':    s_stochrsi_bb,
    'S08_OBV_EMA_MOM':    s_obv_ema_mom,
    'S09_VWAP_MOM':       s_vwap_mom,
    'S10_ST_MACD_SESSION':s_st_macd_session,
    'S11_ALLIG_AWAKEN':   s_alligator_awaken,
    'S12_WPR_KELT':       s_wpr_kelt,
    'S13_STRUC_BREAK':    s_struc_break,
    'S14_KEY_LEVELS':     s_key_levels,
    'S15_OBV_MACD':       s_obv_macd,
    'S09_MFKK_SCALPING':  s_mfkk_scalping,
}

# ── BACKTEST RUNNER ───────────────────────────────────────────────────────────
def run(candles, ind, fn, cfg):
    warmup=cfg['warmup']; look=cfg['look']; cd=cfg['cd']; max_td=cfg['max_td']
    n=len(candles); trades=[]; day_n=defaultdict(int); last_bar=defaultdict(lambda: -9999)
    for i in range(warmup, n-1):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')
        av=ind['atr'][i]; aa=ind['atr30'][i]
        if not av or not aa or av>EXTREME_K*aa: continue
        if day_n[day]>=max_td: continue
        if i-last_bar[day]<cd: continue
        reg=regime(ind,i)
        sig=fn(ind,i,hour)
        if sig is None: continue
        entry=c['c']
        tp_d=round(av*TP_MULT,2); sl_d=round(av*SL_MULT,2)
        if tp_d<=0 or sl_d<=0: continue
        tp_p=entry+tp_d if sig=='buy' else entry-tp_d
        sl_p=entry-sl_d if sig=='buy' else entry+sl_d
        outcome='open'; win=False; close_price=entry; sl_dyn=sl_p
        for j in range(i+1, min(i+look, n)):
            jh=candles[j]['h']; jl=candles[j]['l']; jc=candles[j]['c']
            profit=(jc-entry) if sig=='buy' else (entry-jc)
            # Break-even a 80% del SL in guadagno
            if profit>=sl_d*0.8:
                sl_dyn=entry+0.1 if sig=='buy' else entry-0.1
            if sig=='buy':
                if jh>=tp_p: win=True; outcome='win'; close_price=tp_p; break
                if jl<=sl_dyn: outcome='loss'; close_price=sl_dyn; break
            else:
                if jl<=tp_p: win=True; outcome='win'; close_price=tp_p; break
                if jh>=sl_dyn: outcome='loss'; close_price=sl_dyn; break
        if outcome=='open': continue
        pnl=tp_d if win else -abs(entry-close_price)
        trades.append({'date':day,'dir':sig,'pnl':pnl,'outcome':outcome,'regime':reg})
        day_n[day]+=1; last_bar[day]=i
    return trades

def stats(trades):
    if not trades:
        return {'n':0,'wr':0.0,'pnl':0.0,'pf':0.0,'dd':0.0,'tpd':0.0,'score':0.0}
    wins=[t for t in trades if t['outcome']=='win']
    loss=[t for t in trades if t['outcome']=='loss']
    n=len(trades); wr=len(wins)/n*100
    pnl=sum(t['pnl'] for t in trades)
    gw=sum(t['pnl'] for t in wins) if wins else 0
    gl=abs(sum(t['pnl'] for t in loss)) if loss else 0.001
    pf=round(gw/gl,3)
    days=set(t['date'] for t in trades)
    tpd=round(n/len(days),2) if days else 0
    cum=0;peak=0;dd=0
    for t in sorted(trades,key=lambda x:x['date']):
        cum+=t['pnl']
        if cum>peak: peak=cum
        if peak-cum>dd: dd=peak-cum
    # Score composito: PF pesato + WR bonus + profittabilità
    score = pf*50 + (wr/100)*30 + (20 if pnl>0 else 0)
    return {'n':n,'wr':round(wr,1),'pnl':round(pnl,1),'pf':pf,'dd':round(dd,1),'tpd':tpd,'score':round(score,2)}

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    # Carica tutti i TF disponibili
    tf_data = {}
    for tf, fpath in TF_FILES.items():
        import os
        if not os.path.exists(fpath):
            print(f"  {tf}: file non trovato ({fpath}), skip.")
            continue
        with open(fpath,'r',encoding='utf-8') as f:
            raw=json.load(f)
        candles = raw['candles'] if isinstance(raw,dict) and 'candles' in raw else raw
        print(f"  {tf}: {len(candles)} candele — calcolo indicatori...", end=' ', flush=True)
        ind = compute_all(candles)
        tf_data[tf] = (candles, ind)
        print("ok")

    if not tf_data:
        print("Nessun file trovato. Esegui fetch_mt5_history.py prima.")
        return

    tfs = list(tf_data.keys())
    results = {}   # strat → {tf → stats_dict}

    total = len(STRATEGIES) * len(tfs)
    done  = 0

    print(f"\nBacktest: {len(STRATEGIES)} strategie × {len(tfs)} TF = {total} run\n")

    all_trades = {}  # (sname, tf) → lista trade grezzi (con regime)

    for sname, fn in STRATEGIES.items():
        results[sname] = {}
        for tf in tfs:
            candles, ind = tf_data[tf]
            cfg = TF_CFG[tf]
            trades = run(candles, ind, fn, cfg)
            all_trades[(sname, tf)] = trades
            results[sname][tf] = stats(trades)
            done += 1
            pf  = results[sname][tf]['pf']
            pnl = results[sname][tf]['pnl']
            wr  = results[sname][tf]['wr']
            n   = results[sname][tf]['n']
            print(f"  [{done:3d}/{total}] {sname:<22} {tf:<4}  n={n:5d}  WR={wr:5.1f}%  PF={pf:.3f}  PnL=${pnl:+.1f}")

    # ── TABELLA RIEPILOGATIVA ─────────────────────────────────────────────────
    print("\n" + "="*110)
    print(f"{'STRATEGIA':<22}  {'BEST TF':<6}", end='')
    for tf in tfs:
        print(f"  {tf:^20}", end='')
    print()
    print(f"{'':22}  {'':6}", end='')
    for tf in tfs:
        print(f"  {'WR%  PF   PnL':^20}", end='')
    print()
    print("-"*110)

    best_tf_map = {}  # strat → best_tf
    for sname in STRATEGIES:
        row = results[sname]
        best_tf = max((tf for tf in tfs if row[tf]['n']>5), key=lambda t: row[t]['score'], default=tfs[-1])
        best_tf_map[sname] = best_tf
        print(f"{sname:<22}  {best_tf:<6}", end='')
        for tf in tfs:
            s = row[tf]
            mark = '*' if tf==best_tf else ' '
            if s['n']>5:
                print(f"  {s['wr']:5.1f}% {s['pf']:.2f} ${s['pnl']:+7.0f}{mark}", end='')
            else:
                print(f"  {'—':^20}", end='')
        print()

    print("="*110)
    print("* = miglior TF per quella strategia (score = PF×50 + WR×0.3 + bonus PnL>0)\n")

    # Best TF per ogni strategia
    print("\n── RACCOMANDAZIONI ──────────────────────────────────────────────────────────")
    for sname,btf in best_tf_map.items():
        s=results[sname][btf]
        if s['n']>5:
            print(f"  {sname:<22} → {btf}  WR={s['wr']}%  PF={s['pf']}  PnL=${s['pnl']:+.0f}  Trades={s['n']}")

    # Salva JSON risultati
    out = {
        'generated_at': datetime.datetime.utcnow().isoformat(),
        'timeframes': tfs,
        'tp_mult': TP_MULT, 'sl_mult': SL_MULT,
        'results': results,
        'best_tf': best_tf_map,
    }
    with open(args.out,'w',encoding='utf-8') as f:
        json.dump(out,f,indent=2)
    print(f"\nSalvato: {args.out}")

    # ── ANALISI REGIME ────────────────────────────────────────────────────────
    REGIMES = ['TREND_UP','TREND_DOWN','WEAK_UP','WEAK_DOWN','VOLATILE','RANGE']
    MIN_TRADES = 15  # soglia minima per considerare un dato attendibile

    # Costruisce matrice: regime → tf → strategia → stats
    regime_matrix = {r: {tf: {} for tf in tfs} for r in REGIMES}
    for (sname, tf), trades in all_trades.items():
        for reg in REGIMES:
            subset = [t for t in trades if t.get('regime')==reg]
            s = stats(subset)
            if s['n'] >= MIN_TRADES:
                regime_matrix[reg][tf][sname] = s

    # Stampa tabella regime
    print("\n" + "="*100)
    print("ANALISI PER REGIME — top 3 strategie per ogni (regime × TF)")
    print("="*100)
    for reg in REGIMES:
        print(f"\n  {reg}")
        for tf in tfs:
            combos = regime_matrix[reg][tf]
            if not combos: continue
            top3 = sorted(combos.items(), key=lambda x: x[1]['score'], reverse=True)[:3]
            for sname, s in top3:
                print(f"    {tf}  {sname:<22}  WR={s['wr']:5.1f}%  PF={s['pf']:.3f}  PnL=${s['pnl']:+7.0f}  n={s['n']}")

    # Costruisce playbook: regime → best (strategy, TF)
    playbook = {}
    for reg in REGIMES:
        best_score = -1; best_combo = None
        for tf in tfs:
            for sname, s in regime_matrix[reg][tf].items():
                if s['pf'] >= 1.0 and s['score'] > best_score:
                    best_score = s['score']
                    best_combo = {'strategy': sname, 'tf': tf, **s}
        playbook[reg] = best_combo

    print("\n" + "="*80)
    print("PLAYBOOK OTTIMALE — cosa fare in ogni regime")
    print("="*80)
    for reg, combo in playbook.items():
        if combo:
            print(f"  {reg:<15} → {combo['strategy']:<22} su {combo['tf']}  "
                  f"WR={combo['wr']}%  PF={combo['pf']}  PnL=${combo['pnl']:+.0f}")
        else:
            print(f"  {reg:<15} → NESSUNA strategia profittevole — stai fuori")
    print("="*80)

    # Salva playbook JSON
    playbook_out = {
        'generated_at': datetime.datetime.utcnow().isoformat(),
        'tp_mult': TP_MULT, 'sl_mult': SL_MULT,
        'min_trades_threshold': MIN_TRADES,
        'playbook': playbook,
        'regime_matrix': {
            reg: {
                tf: {
                    sname: s for sname, s in regime_matrix[reg][tf].items()
                }
                for tf in tfs
            }
            for reg in REGIMES
        }
    }
    with open(args.playbook,'w',encoding='utf-8') as f:
        json.dump(playbook_out,f,indent=2)
    print(f"\nPlaybook salvato: {args.playbook}")

if __name__ == '__main__':
    main()
