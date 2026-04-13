#!/usr/bin/env python3
"""
TradeFlow AI — Multi-Timeframe Strategy Backtester
Testa ogni strategia su 1h, 4h, 1d e trova il timeframe ottimale per ciascuna.
Output: strategy_mtf_results.json
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json, datetime, math
from collections import defaultdict

try:
    import yfinance as yf
except ImportError:
    print("pip install yfinance"); sys.exit(1)

# ── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOL   = 'GC=F'
TP_CFGS  = {'1h':{'tp':20,'sl':12},'4h':{'tp':40,'sl':24},'1d':{'tp':80,'sl':45}}
MAX_TRADES_DAY = 3
COOLDOWN_H     = 1
SESSION_S      = 7
SESSION_E      = 17
EXTREME_K      = 3.0
MIN_TRADES     = 20   # minimo trade per considerare valida una combinazione

# ── DOWNLOAD ─────────────────────────────────────────────────────────────────
def download_tf(period, interval):
    df = yf.download(SYMBOL, period=period, interval=interval, progress=False)
    if df is None or len(df)==0: return []
    if hasattr(df.columns,'levels'): df.columns = df.columns.get_level_values(0)
    out=[]
    for ts,row in df.iterrows():
        o=row.get('Open'); h=row.get('High'); l=row.get('Low')
        c=row.get('Close'); v=row.get('Volume',0)
        if None in (o,h,l,c) or math.isnan(float(c)): continue
        out.append({'t':int(ts.timestamp()),'o':float(o),'h':float(h),
                    'l':float(l),'c':float(c),'v':float(v or 1)})
    return out

def resample_to_4h(candles_1h):
    """Resample H1 → H4"""
    buckets={}
    for c in candles_1h:
        dt=datetime.datetime.utcfromtimestamp(c['t'])
        b=dt.replace(hour=(dt.hour//4)*4,minute=0,second=0,microsecond=0)
        k=int(b.timestamp())
        if k not in buckets:
            buckets[k]={'t':k,'o':c['o'],'h':c['h'],'l':c['l'],'c':c['c'],'v':c['v']}
        else:
            e=buckets[k]
            e['h']=max(e['h'],c['h']); e['l']=min(e['l'],c['l'])
            e['c']=c['c']; e['v']+=c['v']
    return sorted(buckets.values(),key=lambda x:x['t'])

def resample_to_1d(candles_1h):
    """Resample H1 → D1"""
    buckets={}
    for c in candles_1h:
        dt=datetime.datetime.utcfromtimestamp(c['t'])
        k=dt.strftime('%Y-%m-%d')
        if k not in buckets:
            buckets[k]={'t':c['t'],'o':c['o'],'h':c['h'],'l':c['l'],'c':c['c'],'v':c['v']}
        else:
            e=buckets[k]
            e['h']=max(e['h'],c['h']); e['l']=min(e['l'],c['l'])
            e['c']=c['c']; e['v']+=c['v']
    return sorted(buckets.values(),key=lambda x:x['t'])

# ── MATH ─────────────────────────────────────────────────────────────────────
def ema(s,p):
    k=2/(p+1);v=s[0];o=[v]
    for x in s[1:]:v=x*k+v*(1-k);o.append(v)
    return o

def smma(s,p):
    o=[None]*(p-1);v=sum(s[:p])/p;o.append(v)
    for x in s[p:]:v=(v*(p-1)+x)/p;o.append(v)
    return o

def sma(s,p):
    o=[None]*(p-1)
    for i in range(p-1,len(s)):o.append(sum(s[i-p+1:i+1])/p)
    return o

def rsi(s,p=14):
    n=len(s);out=[None]*n
    g=[max(0,s[i]-s[i-1]) for i in range(1,n)]
    l=[max(0,s[i-1]-s[i]) for i in range(1,n)]
    ag=sum(g[:p])/p;al=sum(l[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p;al=(al*(p-1)+l[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def atr(H,L,C,p=14):
    tr=[0]
    for i in range(1,len(C)):
        tr.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
    return sma(tr,p)

def adx_full(H,L,C,p=14):
    n=len(C);TR=[0];DMP=[0];DMM=[0]
    for i in range(1,n):
        TR.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
        up=H[i]-H[i-1];dn=L[i-1]-L[i]
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
    return sma(DX,p),DIP,DIM

def macd_full(C):
    e1=ema(C,12);e2=ema(C,26);ml=[e1[i]-e2[i] for i in range(len(C))];sg=ema(ml,9)
    return ml,sg,[ml[i]-sg[i] for i in range(len(C))]

def supertrend(H,L,C,p=10,m=3.0):
    atr_v=atr(H,L,C,p);n=len(C);dir_=[1]*n
    fUp=[0.0]*n;fLo=[0.0]*n
    for i in range(1,n):
        ub=(H[i]+L[i])/2+m*(atr_v[i] or 0)
        lb=(H[i]+L[i])/2-m*(atr_v[i] or 0)
        fUp[i]=ub if ub<fUp[i-1] or C[i-1]>fUp[i-1] else fUp[i-1]
        fLo[i]=lb if lb>fLo[i-1] or C[i-1]<fLo[i-1] else fLo[i-1]
        if dir_[i-1]==1 and C[i]<=fUp[i]:dir_[i]=1
        elif dir_[i-1]==1 and C[i]>fUp[i]:dir_[i]=-1
        elif dir_[i-1]==-1 and C[i]>=fLo[i]:dir_[i]=-1
        else:dir_[i]=1
    return dir_

def alligator(H,L):
    med=[(H[i]+L[i])/2 for i in range(len(H))]
    return smma(med,13),smma(med,8),smma(med,5)

def obv_fn(C,V):
    o=[0.0]
    for i in range(1,len(C)):
        o.append(o[-1]+(V[i] if C[i]>C[i-1] else -V[i] if C[i]<C[i-1] else 0))
    return o

def momentum_fn(C,p=10):
    out=[None]*p
    for i in range(p,len(C)):out.append((C[i]-C[i-p])/C[i-p]*100 if C[i-p] else 0)
    return out

def williams_r(H,L,C,p=14):
    out=[None]*(p-1)
    for i in range(p-1,len(C)):
        hi=max(H[i-p+1:i+1]);lo=min(L[i-p+1:i+1])
        out.append((hi-C[i])/(hi-lo)*-100 if hi>lo else -50)
    return out

def vwap_daily(candles):
    cpv=0;cv=0;lastd=None;out=[]
    for c in candles:
        d=datetime.datetime.utcfromtimestamp(c['t']).date()
        if d!=lastd:cpv=0;cv=0;lastd=d
        tp=(c['h']+c['l']+c['c'])/3;cpv+=tp*c['v'];cv+=c['v']
        out.append(cpv/cv if cv>0 else tp)
    return out

def bollinger(C,p=20,m=2.0):
    mid=sma(C,p);up=[];lo=[]
    for i,v in enumerate(mid):
        if v is None:up.append(None);lo.append(None);continue
        sl=C[i-p+1:i+1];mn=sum(sl)/p
        std=math.sqrt(sum((x-mn)**2 for x in sl)/p)
        up.append(v+m*std);lo.append(v-m*std)
    return up,mid,lo

def keltner(H,L,C,p=20,m=2.0,ap=10):
    mid=ema(C,p);atr_v=atr(H,L,C,ap)
    return [mid[i]+m*(atr_v[i] or 0) for i in range(len(C))],[mid[i]-m*(atr_v[i] or 0) for i in range(len(C))]

def order_blocks(H,L,C,thr=0.5):
    n=len(C);bull=[False]*n;bear=[False]*n
    for i in range(5,n-3):
        gain=sum(max(0,C[i+j]-C[i+j-1]) for j in range(1,4))/C[i]*100
        drop=sum(max(0,C[i+j-1]-C[i+j]) for j in range(1,4))/C[i]*100
        if gain>thr and C[i]<C[i-1]:
            for j in range(i+1,min(i+50,n)):
                if C[j]>=L[i] and C[j]<=H[i]:bull[j]=True
                elif C[j]<L[i]:break
        if drop>thr and C[i]>C[i-1]:
            for j in range(i+1,min(i+50,n)):
                if C[j]>=L[i] and C[j]<=H[i]:bear[j]=True
                elif C[j]>H[i]:break
    return bull,bear

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute(candles):
    n=len(candles)
    H=[c['h'] for c in candles];L=[c['l'] for c in candles]
    C=[c['c'] for c in candles];V=[c['v'] for c in candles]
    adx_v,dip,dim=adx_full(H,L,C,14)
    atr_v=atr(H,L,C,14);atr30=sma([x or 0 for x in atr_v],30)
    ml,sg,hist_m=macd_full(C)
    rsi14=rsi(C,14)
    bb_up,bb_mid,bb_lo=bollinger(C,20,2.0)
    kc_up,kc_lo=keltner(H,L,C,20,2.0,10)
    st=supertrend(H,L,C,10,3.0)
    jaw,teeth,lips=alligator(H,L)
    obv_v=obv_fn(C,V);obv_e=ema(obv_v,20)
    mom=momentum_fn(C,10)
    wpr=williams_r(H,L,C,14)
    vwap=vwap_daily(candles)
    ob_bull,ob_bear=order_blocks(H,L,C)
    e20=ema(C,20);e50=ema(C,50);e100=ema(C,100);e200=ema(C,200)
    return dict(H=H,L=L,C=C,V=V,n=n,
                adx=adx_v,dip=dip,dim=dim,atr=atr_v,atr30=atr30,
                macd=ml,macd_sig=sg,macd_hist=hist_m,rsi=rsi14,
                bb_up=bb_up,bb_lo=bb_lo,kc_up=kc_up,kc_lo=kc_lo,
                st=st,jaw=jaw,teeth=teeth,lips=lips,
                obv=obv_v,obv_e=obv_e,mom=mom,wpr=wpr,vwap=vwap,
                ob_bull=ob_bull,ob_bear=ob_bear,
                e20=e20,e50=e50,e100=e100,e200=e200)

# ── STRATEGIES ───────────────────────────────────────────────────────────────
def s01_exhaustion(ind,i,hour):
    a=ind['adx'][i];dp=ind['dip'][i];dm=ind['dim'][i]
    m=ind['macd'][i];sg=ind['macd_sig'][i]
    if None in (a,dp,dm,m,sg):return None
    diff=m-sg;spread=abs(dp-dm)
    if a>=30 and dm>dp and spread>=15 and diff>=1.0:return 'sell'
    if a>=28 and dp>dm and spread>=15 and diff<=-1.0:return 'buy'
    return None

def s06_orderblock(ind,i,hour):
    ob_b=ind['ob_bull'][i];ob_s=ind['ob_bear'][i]
    r=ind['rsi'][i];e50=ind['e50'][i];c=ind['C'][i]
    if None in (r,e50):return None
    if ob_b and r<=55 and c>e50*0.998:return 'buy'
    if ob_s and r>=45 and c<e50*1.002:return 'sell'
    return None

def s09_vwap_wpr(ind,i,hour):
    vwap=ind['vwap'][i];c=ind['C'][i]
    wpr=ind['wpr'][i];mom=ind['mom'][i];r=ind['rsi'][i]
    if None in (vwap,wpr,mom,r):return None
    dev=(c-vwap)/vwap*100
    if -0.3<=dev<=0.1 and wpr<-70 and mom>-0.1 and r>=40:return 'buy'
    if -0.1<=dev<=0.3 and wpr>-30 and mom<0.1 and r<=60:return 'sell'
    return None

def s12_wpr_keltner(ind,i,hour):
    wpr=ind['wpr'][i];r=ind['rsi'][i];c=ind['C'][i]
    ku=ind['kc_up'][i];kl=ind['kc_lo'][i];a=ind['adx'][i]
    if None in (wpr,r,ku,kl,a):return None
    if a>=30:return None
    if c<=kl*1.002 and wpr<-80 and r<35:return 'buy'
    if c>=ku*0.998 and wpr>-20 and r>65:return 'sell'
    return None

def s10_session_mom(ind,i,hour):
    # Su H4/D1 no filtro ora, usa semplicemente supertrend+macd+ema50
    st=ind['st'][i];m=ind['macd'][i];sg=ind['macd_sig'][i]
    r=ind['rsi'][i];e50=ind['e50'][i];c=ind['C'][i]
    if None in (m,sg,r,e50):return None
    diff=m-sg
    if st==-1 and diff>0 and 45<=r<=70 and c>e50:return 'buy'
    if st==1  and diff<0 and 30<=r<=55 and c<e50:return 'sell'
    return None

STRATS = {
    'S01_EXHAUSTION':  s01_exhaustion,
    'S06_ORDERBLOCK':  s06_orderblock,
    'S09_VWAP_WPR':    s09_vwap_wpr,
    'S12_WPR_KELTNER': s12_wpr_keltner,
    'S10_SESSION_MOM': s10_session_mom,
}

# ── BACKTEST ─────────────────────────────────────────────────────────────────
def run(candles, ind, strat_fn, tp, sl, tf_label):
    trades=[]; day_n=defaultdict(int); day_h=defaultdict(lambda:-99)
    n=len(candles)
    warmup=220 if len(candles)>220 else max(50,len(candles)//5)
    for i in range(warmup,n):
        c=candles[i]
        dt=datetime.datetime.utcfromtimestamp(c['t'])
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')
        # Sessione solo su H1 (su H4/D1 non filtriamo)
        if tf_label=='1h' and not (SESSION_S<=hour<SESSION_E):continue
        # Extreme day
        av=ind['atr'][i];aa=ind['atr30'][i]
        if av and aa and av>EXTREME_K*aa:continue
        if day_n[day]>=MAX_TRADES_DAY:continue
        if tf_label=='1h' and hour-day_h[day]<COOLDOWN_H:continue
        sig=strat_fn(ind,i,hour)
        if not sig:continue
        entry=c['c']
        tp_p=entry+tp if sig=='buy' else entry-tp
        sl_p=entry-sl if sig=='buy' else entry+sl
        outcome='open';win=False
        lookahead=25 if tf_label=='1h' else 8 if tf_label=='4h' else 4
        for j in range(i+1,min(i+lookahead,n)):
            jh=candles[j]['h'];jl=candles[j]['l']
            if sig=='buy':
                if jh>=tp_p:win=True;outcome='win';break
                if jl<=sl_p:outcome='loss';break
            else:
                if jl<=tp_p:win=True;outcome='win';break
                if jh>=sl_p:outcome='loss';break
        if outcome=='open':continue
        pnl=tp if win else -sl
        trades.append({'date':day,'hour':hour,'dir':sig,'outcome':outcome,'pnl':pnl})
        day_n[day]+=1; day_h[day]=hour
    return trades

def stats(trades,tp,sl):
    if not trades:return {'n':0,'wr':0,'pnl':0,'pf':0,'dd':0,'avg_day':0}
    wins=[t for t in trades if t['outcome']=='win']
    loss=[t for t in trades if t['outcome']=='loss']
    n=len(trades);wr=len(wins)/n*100
    pnl=sum(t['pnl'] for t in trades)
    gw=sum(t['pnl'] for t in wins) if wins else 0
    gl=abs(sum(t['pnl'] for t in loss)) if loss else 0.001
    pf=round(gw/gl,3)
    days=set(t['date'] for t in trades)
    avg=pnl/len(days) if days else 0
    cum=0;peak=0;dd=0
    for t in sorted(trades,key=lambda x:x['date']+f"{x['hour']:02d}"):
        cum+=t['pnl']
        if cum>peak:peak=cum
        if peak-cum>dd:dd=peak-cum
    mo=defaultdict(list)
    for t in trades:mo[t['date'][:7]].append(t['pnl'])
    pos=sum(1 for v in mo.values() if sum(v)>0)
    return {'n':n,'wr':round(wr,1),'pnl':round(pnl,1),'pf':pf,
            'dd':round(dd,1),'avg_day':round(avg,2),
            'months':f"{pos}/{len(mo)}"}

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("TradeFlow AI — Multi-Timeframe Strategy Backtester")
    print("Timeframes: 1h (730gg) · 4h (resample) · 1d (resample)")
    print("="*65)

    # Download H1 base
    print("Download H1 data (730gg)...")
    c1h = download_tf('730d','1h')
    print(f"  {len(c1h)} candele H1")

    # Resample
    c4h = resample_to_4h(c1h)
    c1d = resample_to_1d(c1h)
    print(f"  {len(c4h)} candele H4 (resampled)")
    print(f"  {len(c1d)} candele D1 (resampled)")

    tfs = {'1h':(c1h,EXTREME_K),'4h':(c4h,EXTREME_K),'1d':(c1d,EXTREME_K)}

    # Compute indicators per ogni TF
    print("Calcolo indicatori...")
    inds={}
    for tf,(candles,_) in tfs.items():
        if len(candles)<50:print(f"  {tf}: skip (troppo pochi dati)");continue
        inds[tf]=compute(candles)
        print(f"  {tf}: OK ({inds[tf]['n']} candele)")

    # ── BACKTEST OGNI STRATEGIA × OGNI TF
    print("\n" + "="*65)
    print("BACKTEST: 5 strategie × 3 timeframe")
    print("="*65)

    results={}
    # Header
    print(f"{'Strategia':<22} {'TF':>4} {'N':>5} {'WR%':>6} {'P&L':>8} {'PF':>6} {'$/gg':>7} {'DD':>7} {'Mesi+':>7}")
    print("-"*70)

    for sname,sfn in STRATS.items():
        best_tf=None;best_pf=0;best_s=None
        results[sname]={}
        for tf,(candles,_) in tfs.items():
            if tf not in inds:continue
            tp=TP_CFGS[tf]['tp'];sl=TP_CFGS[tf]['sl']
            trades=run(candles,inds[tf],sfn,tp,sl,tf)
            s=stats(trades,tp,sl)
            results[sname][tf]=s
            valid=s['n']>=MIN_TRADES
            marker='*' if valid and s['pf']>best_pf else ' '
            if valid and s['pf']>best_pf:
                best_pf=s['pf'];best_tf=tf;best_s=s
            print(f"{sname:<22} {tf:>4} {s['n']:>5} {s['wr']:>6.1f}% {s['pnl']:>8.1f} {s['pf']:>6.3f} {s['avg_day']:>7.2f} {s['dd']:>7.1f} {s.get('months','—'):>7} {marker}")
        results[sname]['_best_tf']=best_tf
        results[sname]['_best_pf']=best_pf
        print(f"  → BEST TF: {best_tf} (PF={best_pf:.3f})")
        print()

    # ── RIEPILOGO
    print("="*65)
    print("RIEPILOGO FINALE — Miglior TF per ogni strategia")
    print("="*65)
    print(f"{'Strategia':<22} {'Best TF':>7} {'WR%':>6} {'PF':>6} {'P&L':>8} {'$/gg':>7}")
    print("-"*55)
    output_map={}
    for sname in STRATS:
        btf=results[sname].get('_best_tf')
        if not btf:print(f"{sname:<22} {'—':>7}");continue
        s=results[sname][btf]
        tp=TP_CFGS[btf]['tp'];sl=TP_CFGS[btf]['sl']
        print(f"{sname:<22} {btf:>7} {s['wr']:>6.1f}% {s['pf']:>6.3f} {s['pnl']:>8.1f} {s['avg_day']:>7.2f}")
        output_map[sname]={'tf':btf,'tp':tp,'sl':sl,'stats':s}

    # ── SISTEMA ADATTIVO MTF: ogni strategia usa il proprio TF
    print("\n" + "="*65)
    print("SISTEMA ADATTIVO MTF: ogni strategia usa il proprio best TF")
    print("="*65)

    REGIME_PRIORITY = {
        'TREND_UP':   ['S01_EXHAUSTION','S06_ORDERBLOCK','S10_SESSION_MOM'],
        'TREND_DOWN': ['S01_EXHAUSTION','S06_ORDERBLOCK','S10_SESSION_MOM'],
        'WEAK_UP':    ['S06_ORDERBLOCK','S10_SESSION_MOM','S12_WPR_KELTNER'],
        'WEAK_DOWN':  ['S06_ORDERBLOCK','S10_SESSION_MOM','S12_WPR_KELTNER'],
        'RANGE':      ['S09_VWAP_WPR','S12_WPR_KELTNER','S06_ORDERBLOCK'],
        'VOLATILE':   ['S12_WPR_KELTNER','S09_VWAP_WPR'],
        'UNKNOWN':    ['S10_SESSION_MOM','S09_VWAP_WPR'],
    }

    def regime_detect(ind,i):
        a=ind['adx'][i];dp=ind['dip'][i];dm=ind['dim'][i]
        av=ind['atr'][i];aa=ind['atr30'][i]
        if None in (a,av,aa):return 'UNKNOWN'
        rv=av/aa if aa else 1
        if a>=30 and dp>dm:return 'TREND_UP'
        if a>=30 and dm>dp:return 'TREND_DOWN'
        if a>=22 and dp>dm:return 'WEAK_UP'
        if a>=22 and dm>dp:return 'WEAK_DOWN'
        if rv>1.4:return 'VOLATILE'
        return 'RANGE'

    # Usa H1 come TF base per il regime detection e routing
    ind_h1=inds.get('1h')
    if not ind_h1:print("No H1 data!");return

    all_trades=[];day_n=defaultdict(int);day_h_map=defaultdict(lambda:-99)
    n=len(c1h)
    for i in range(220,n):
        c=c1h[i];dt=datetime.datetime.utcfromtimestamp(c['t'])
        hour=dt.hour;day=dt.strftime('%Y-%m-%d')
        if not (SESSION_S<=hour<SESSION_E):continue
        av=ind_h1['atr'][i];aa=ind_h1['atr30'][i]
        if av and aa and av>EXTREME_K*aa:continue
        if day_n[day]>=MAX_TRADES_DAY:continue
        if hour-day_h_map[day]<COOLDOWN_H:continue

        r=regime_detect(ind_h1,i)
        pool=REGIME_PRIORITY.get(r,['S10_SESSION_MOM'])
        sig=None;used=None;used_tp=20;used_sl=12
        for sname in pool:
            btf=output_map.get(sname,{}).get('tf','1h')
            used_tp=output_map.get(sname,{}).get('tp',20)
            used_sl=output_map.get(sname,{}).get('sl',12)
            # Usa indicatori del best TF per quella strategia
            best_ind=inds.get(btf,ind_h1)
            # Mappa indice H1 → indice del TF corretto
            if btf=='1h': bi=i
            elif btf=='4h':
                # trova indice in c4h corrispondente al timestamp corrente
                ts=c['t'];bi=None
                for ci,cv in enumerate(c4h):
                    if cv['t']<=ts and (ci+1>=len(c4h) or c4h[ci+1]['t']>ts):bi=ci;break
                if bi is None or bi>=len(c4h)-1:continue
            elif btf=='1d':
                ts=c['t'];bi=None
                for ci,cv in enumerate(c1d):
                    if cv['t']<=ts and (ci+1>=len(c1d) or c1d[ci+1]['t']>ts):bi=ci;break
                if bi is None or bi>=len(c1d)-1:continue
            if bi<50:continue
            fn=STRATS[sname]
            s=fn(best_ind,bi,hour)
            if s:sig=s;used=sname;break

        if not sig:continue
        entry=c['c']
        tp_p=entry+used_tp if sig=='buy' else entry-used_tp
        sl_p=entry-used_sl if sig=='buy' else entry+used_sl
        outcome='open';win=False
        for j in range(i+1,min(i+25,n)):
            jh=c1h[j]['h'];jl=c1h[j]['l']
            if sig=='buy':
                if jh>=tp_p:win=True;outcome='win';break
                if jl<=sl_p:outcome='loss';break
            else:
                if jl<=tp_p:win=True;outcome='win';break
                if jh>=sl_p:outcome='loss';break
        if outcome=='open':continue
        pnl=used_tp if win else -used_sl
        all_trades.append({'date':day,'hour':hour,'dir':sig,'outcome':outcome,
                            'pnl':pnl,'strategy':used,'regime':r,'tf':btf})
        day_n[day]+=1;day_h_map[day]=hour

    sa=stats(all_trades,20,12)
    print(f"\n  Trade totali:    {sa['n']}")
    print(f"  Win Rate:        {sa['wr']}%")
    print(f"  P&L totale:      ${sa['pnl']}")
    print(f"  Profit Factor:   {sa['pf']}")
    print(f"  Media $/giorno:  ${sa['avg_day']}")
    print(f"  Mesi positivi:   {sa.get('months','—')}")

    by_s=defaultdict(list)
    for t in all_trades:by_s[t['strategy']].append(t)
    print(f"\n  Dettaglio per strategia nel sistema adattivo MTF:")
    print(f"  {'Strategia':<22} {'TF':>5} {'N':>5} {'WR%':>6} {'P&L':>8}")
    for sname,tl in sorted(by_s.items(),key=lambda x:-len(x[1])):
        s2=stats(tl,output_map.get(sname,{}).get('tp',20),output_map.get(sname,{}).get('sl',12))
        btf=output_map.get(sname,{}).get('tf','?')
        print(f"  {sname:<22} {btf:>5} {s2['n']:>5} {s2['wr']:>6.1f}% {s2['pnl']:>8.1f}")

    # ── SAVE JSON
    out={
        'generated_at':datetime.datetime.utcnow().isoformat(),
        'timeframes_tested':list(tfs.keys()),
        'tp_sl_per_tf':TP_CFGS,
        'per_strategy':results,
        'best_tf_per_strategy':{
            n:{'tf':v.get('tf'),'tp':v.get('tp'),'sl':v.get('sl'),
               'pf':v.get('stats',{}).get('pf',0),'wr':v.get('stats',{}).get('wr',0),
               'n':v.get('stats',{}).get('n',0)}
            for n,v in output_map.items()
        },
        'adaptive_mtf':{'stats':sa,'by_strategy':{n:stats(tl,output_map.get(n,{}).get('tp',20),output_map.get(n,{}).get('sl',12)) for n,tl in by_s.items()}},
        'regime_priority':REGIME_PRIORITY,
    }
    with open('strategy_mtf_results.json','w') as f:
        json.dump(out,f,indent=2,default=str)
    print("\nSalvato: strategy_mtf_results.json")
    print("="*65)

if __name__=='__main__':
    main()
