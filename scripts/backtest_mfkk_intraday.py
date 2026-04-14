#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Backtest MFKK Suite + MFKK Intraday Combo
╔══════════════════════════════════════════════════════════════════╗
║  3 Strategie ufficiali del tab Strategie:                       ║
║  1. S00_MFKK_SCORE  — MFKK Score ponderato (H1, come attuale)  ║
║  2. S00_MFKK_HWR    — MFKK High Win Rate   (H1, SELL ONLY)     ║
║  3. S05_MFKK_INTR   — MFKK Intraday Combo  (OBV+RSI+MOM multi-TF)║
╠══════════════════════════════════════════════════════════════════╣
║  Output: backtest_mfkk_suite.json                               ║
║    - Performance per 1m, 6m, 12m, 24m                          ║
║    - Best TF per S05 su M30 / H1 / H4                          ║
╚══════════════════════════════════════════════════════════════════╝

USO:
  python scripts/backtest_mfkk_intraday.py --h1-file xauusd_h1_mt5.json
  python scripts/backtest_mfkk_intraday.py --mt5
"""
import sys, io, argparse, json, math, datetime, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from collections import defaultdict

# ── CONFIG ────────────────────────────────────────────────────────────────────
MT5_LOGIN    = 1301224666
MT5_PASSWORD = "Alessandro95!"
MT5_SERVER   = "XMGlobal-MT5 6"
SYMBOL_CANDIDATES = ["GOLD", "XAUUSD", "XAUUSD.m"]

DAYS        = 730          # 2 anni
TP_H1       = 20.0         # MFKK Score TP $
SL_H1       = 12.0         # MFKK Score SL $
TP_HWR      = 20.0
SL_HWR      = 12.0
TP_ATR_MULT = 2.0          # MFKK Intraday usa ATR-based TP/SL
SL_ATR_MULT = 1.0
MAX_TRADES  = 10
EXTREME_K   = 3.5
SESSION_ALL = (0, 24)
SESSION_LDN = (7, 22)      # sessione London/NY per M30

LOT         = 0.01         # lotto simulato
PIP_VALUE   = 1.0          # $1/punto su XAU (lotto 0.01)

# ── ARGPARSE ──────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument('--mt5',       action='store_true')
ap.add_argument('--h1-file',   type=str, default=None)
ap.add_argument('--m30-file',  type=str, default=None)
ap.add_argument('--h4-file',   type=str, default=None)
ap.add_argument('--out',       type=str, default='backtest_mfkk_suite.json')
args = ap.parse_args()

# ── MATH HELPERS ──────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for x in src[1:]: v=x*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1, len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def stdev_arr(src, p):
    out=[None]*(p-1)
    for i in range(p-1, len(src)):
        sl=src[i-p+1:i+1]; mn=sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def dema(src, p):
    m1=ema(src,p); m2=ema(m1,p)
    return [2*m1[i]-m2[i] for i in range(len(src))]

def rsi_fn(src, p=14):
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

def atr_fn(H, L, C, p=14):
    tr=[0]
    for i in range(1,len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    return sma(tr, p)

def adx_fn(H, L, C, p=14):
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
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    return sma(DX,p), DIP, DIM

def macd_fn(C, f=12, s=26):
    e1=ema(C,f); e2=ema(C,s)
    return [e1[i]-e2[i] for i in range(len(C))]

def cci_fn(H, L, C, p=50):
    tp=[(H[i]+L[i]+C[i])/3 for i in range(len(C))]
    out=[None]*(p-1)
    for i in range(p-1,len(tp)):
        sl=tp[i-p+1:i+1]; mn=sum(sl)/p
        md=sum(abs(x-mn) for x in sl)/p
        out.append((tp[i]-mn)/(0.015*md) if md>0 else 0)
    return out

def mom_fn(C, p=10):
    out=[None]*p
    for i in range(p,len(C)):
        out.append(C[i]-C[i-p])   # Momentum assoluto (come Pine mom)
    return out

def obv_macd_tchannel(H, L, C, V, wl=28, vl=14, ml=9, sl=26):
    """OBV MACD T-Channel — fedele alla versione Pine Script."""
    n=len(C)
    obv=[0.0]
    for i in range(1,n):
        s=1 if C[i]>C[i-1] else (-1 if C[i]<C[i-1] else 0)
        obv.append(obv[-1]+s*(V[i] or 0))
    hl=[H[i]-L[i] for i in range(n)]
    ps=stdev_arr(hl,wl); sm=sma(obv,vl)
    vd=[obv[i]-(sm[i] or 0) for i in range(n)]
    vs=stdev_arr(vd,wl)
    out=[]
    for i in range(n):
        if sm[i] is None or not vs[i] or not ps[i]: out.append(C[i]); continue
        sh=(obv[i]-sm[i])/vs[i]*ps[i]
        out.append(H[i]+sh if sh>0 else L[i]+sh)
    dm=dema(out,ml); slw=ema(C,sl)
    ml_=[dm[i]-slw[i] for i in range(n)]
    b5=[ml_[0]]; oc=[0]; cd=0.0
    for i in range(1,n):
        cd+=abs(ml_[i]-b5[-1]); a=cd/i
        if   ml_[i]>b5[-1]+a: b5.append(ml_[i])
        elif ml_[i]<b5[-1]-a: b5.append(ml_[i])
        else: b5.append(b5[-1])
        if   b5[-1]>b5[-2]: oc.append(1)
        elif b5[-1]<b5[-2]: oc.append(-1)
        else: oc.append(oc[-1])
    return ml_, b5, oc

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute(candles):
    H=[c['h'] for c in candles]; L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]; V=[c['v'] for c in candles]
    n=len(C)
    adx,dip,dim = adx_fn(H,L,C,14)
    atr14 = atr_fn(H,L,C,14)
    atr30 = sma([x if x else 0 for x in atr14], 30)
    macd  = macd_fn(C)
    rsi14 = rsi_fn(C,14)
    cci50 = cci_fn(H,L,C,50)
    mom10 = mom_fn(C,10)
    e20   = ema(C,20); e50=ema(C,50)
    obv_ml, obv_b5, obv_oc = obv_macd_tchannel(H,L,C,V)
    return {
        'n':n,'H':H,'L':L,'C':C,'V':V,
        'adx':adx,'dip':dip,'dim':dim,
        'atr':atr14,'atr30':atr30,
        'macd':macd,'rsi':rsi14,'cci':cci50,
        'mom':mom10,'e20':e20,'e50':e50,
        'obv_oc':obv_oc,'obv_ml':obv_ml,
    }

# ── STRATEGIA 1: MFKK SCORE ───────────────────────────────────────────────────
def mfkk_score(ind, i):
    """
    MFKK Score ponderato — logica identica a strategy.js S00_MFKK
    Composito 80% ADX + 10% MACD + 10% CCI(50)
    SELL≥75, BUY≥90
    """
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; c=ind['cci'][i]
    if None in (a,dp,dm,m,c): return None

    score_bull = score_bear = 0.0

    # ADX (80%): Trend BEAR → score sell; BULL → score buy
    adx_capped = min(a/40*100, 100)
    if dm > dp:   score_bear += adx_capped * 0.80
    else:         score_bull += adx_capped * 0.80

    # MACD (10%): val positivo → bull, negativo → bear
    macd_score = min(abs(m)/0.5*100, 100)
    if m >= 0:   score_bull += macd_score * 0.10
    else:        score_bear += macd_score * 0.10

    # CCI (10%): > 0 → bull, < 0 → bear
    cci_score = min(abs(c)/100*100, 100)
    if c >= 0:   score_bull += cci_score * 0.10
    else:        score_bear += cci_score * 0.10

    # Thresholds
    if score_bull >= 90: return 'buy'
    if score_bear >= 75: return 'sell'
    return None

# ── STRATEGIA 2: MFKK HIGH WIN RATE ──────────────────────────────────────────
def mfkk_hwr(ind, i):
    """
    MFKK HighWR — SELL ONLY
    ADX≥35 · DI spread≥20 · MACD diff≥0.5 · CCI non OS
    """
    a=ind['adx'][i]; dp=ind['dip'][i]; dm=ind['dim'][i]
    m=ind['macd'][i]; c=ind['cci'][i]
    if None in (a,dp,dm,m,c): return None

    spread = dm - dp  # positivo = SELL bias
    if a >= 35 and spread >= 20 and m >= 0.5 and c > -100:
        return 'sell'
    return None

# ── STRATEGIA 3: MFKK INTRADAY COMBO ─────────────────────────────────────────
def mfkk_intraday_v1(ind, i):
    """
    V1 — OBV FLIP + RSI + MOMENTUM
    Standard: flip T-Channel + RSI non saturo + Momentum allineato
    """
    if i<1: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; m=ind['mom'][i]; a=ind['adx'][i]
    if None in (r,m,a): return None
    if oc[i]==1  and oc[i-1]!=1  and r<62 and m>0 and a>=18: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>38 and m<0 and a>=18: return 'sell'
    return None

def mfkk_intraday_v2(ind, i):
    """
    V2 — TRIPLE CONFLUENCE: OBV + RSI + MOM + MACD
    4 conferme: più selettivo, WR più alto
    """
    if i<2: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; m=ind['mom'][i]
    a=ind['adx'][i]; mc=ind['macd'][i]
    if None in (r,m,a,mc): return None
    if a<20: return None
    if oc[i]==1  and r>50 and m>0 and mc>0: return 'buy'
    if oc[i]==-1 and r<50 and m<0 and mc<0: return 'sell'
    return None

def mfkk_intraday_v3(ind, i):
    """
    V3 — SELL EXHAUSTION ONLY
    OBV bear + RSI>55 + ADX≥20 + Momentum negativo
    Bias short: sfrutta la natura ribassista del Gold
    """
    if i<1: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; a=ind['adx'][i]; m=ind['mom'][i]
    if None in (r,a,m): return None
    if oc[i]==-1 and r>55 and a>=20 and m<0: return 'sell'
    return None

def mfkk_intraday_v4(ind, i):
    """
    V4 — STRONG: 5 condizioni
    OBV flip + RSI + ADX alto + MACD + Mom + prezzo sopra/sotto EMA50
    Alta qualità, pochi trade
    """
    if i<2: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; a=ind['adx'][i]
    mc=ind['macd']; m=ind['mom'][i]; c=ind['C'][i]; e50=ind['e50'][i]
    if None in (r,a,mc[i],mc[i-1],m,e50): return None
    macd_up = mc[i]>0 and mc[i-1]<=0
    macd_dn = mc[i]<0 and mc[i-1]>=0
    if oc[i]==1  and oc[i-1]!=1  and r<58 and a>=25 and (macd_up or mc[i]>0) and m>0 and c>e50: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>42 and a>=25 and (macd_dn or mc[i]<0) and m<0 and c<e50: return 'sell'
    return None

INTRADAY_VARIANTS = {
    'V1_OBV_RSI_MOM':       mfkk_intraday_v1,
    'V2_Triple_MACD':       mfkk_intraday_v2,
    'V3_Sell_Exhaustion':   mfkk_intraday_v3,
    'V4_Strong_5cond':      mfkk_intraday_v4,
}

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def run_backtest(candles, ind, fn, tp_mode='fixed', tp_val=20.0, sl_val=12.0,
                 session=(0,24), cooldown_bars=1, use_atr=False, label='H1'):
    n=len(candles); warmup=max(80, int(n*0.05))
    sess_s, sess_e = session
    trades=[]; day_n=defaultdict(int); last_bar=defaultdict(lambda:-9999)

    for i in range(warmup, n-1):
        c=candles[i]; ts=c['t']
        dt=datetime.datetime.utcfromtimestamp(ts)
        hour=dt.hour; day=dt.strftime('%Y-%m-%d')

        if not (sess_s<=hour<sess_e): continue
        av=ind['atr'][i]; aa=ind['atr30'][i]
        if av and aa and av>EXTREME_K*aa: continue
        if day_n[day]>=MAX_TRADES: continue
        if i-last_bar[day]<cooldown_bars: continue

        sig=fn(ind, i)
        if sig is None: continue

        entry=c['c']
        if use_atr and av:
            tp_p_val = av*TP_ATR_MULT
            sl_p_val = av*SL_ATR_MULT
        else:
            tp_p_val = tp_val
            sl_p_val = sl_val

        tp_p = entry+tp_p_val if sig=='buy' else entry-tp_p_val
        sl_p = entry-sl_p_val if sig=='buy' else entry+sl_p_val

        outcome='open'
        for j in range(i+1, min(i+60, n)):
            jh=candles[j]['h']; jl=candles[j]['l']
            if sig=='buy':
                if jh>=tp_p: outcome='win'; break
                if jl<=sl_p: outcome='loss'; break
            else:
                if jl<=tp_p: outcome='win'; break
                if jh>=sl_p: outcome='loss'; break
        if outcome=='open': continue

        win=(outcome=='win')
        pnl=tp_p_val if win else -sl_p_val
        trades.append({
            'date':day,'hour':hour,'dir':sig,
            'outcome':outcome,'pnl':round(pnl,2),
            'ts':ts
        })
        day_n[day]+=1; last_bar[day]=i
    return trades

def calc_stats(trades, all_trades=None):
    """Calcola stats su subset di trade. all_trades se None = trades stesso."""
    if not trades: return None
    wins  = [t for t in trades if t['outcome']=='win']
    loss  = [t for t in trades if t['outcome']=='loss']
    n=len(trades); wr=len(wins)/n*100
    pnl=sum(t['pnl'] for t in trades)
    gw=sum(t['pnl'] for t in wins) if wins else 0
    gl=abs(sum(t['pnl'] for t in loss)) if loss else 0.001
    pf=round(gw/gl,3)
    days=set(t['date'] for t in trades)
    avg_d=pnl/len(days) if days else 0
    mo=defaultdict(list)
    for t in trades: mo[t['date'][:7]].append(t['pnl'])
    pos_mo=sum(1 for v in mo.values() if sum(v)>0)
    # Max DD
    cum=0; peak=0; dd=0
    for t in sorted(trades, key=lambda x: x['ts']):
        cum+=t['pnl']
        if cum>peak: peak=cum
        if peak-cum>dd: dd=peak-cum
    # buy/sell breakdown
    buys=[t for t in trades if t['dir']=='buy']
    sells=[t for t in trades if t['dir']=='sell']
    bwr=len([t for t in buys if t['outcome']=='win'])/len(buys)*100 if buys else 0
    swr=len([t for t in sells if t['outcome']=='win'])/len(sells)*100 if sells else 0
    return {
        'n':n,'wr':round(wr,1),'pnl':round(pnl,1),'pf':pf,
        'dd':round(dd,1),'avg_day':round(avg_d,2),
        'pos_months':f"{pos_mo}/{len(mo)}",
        'n_buy':len(buys),'n_sell':len(sells),
        'buy_wr':round(bwr,1),'sell_wr':round(swr,1),
    }

def stats_by_period(trades, candles):
    """Calcola P&L per 1m, 6m, 12m, 24m."""
    if not trades or not candles: return {}
    now_ts=candles[-1]['t']
    cutoffs={
        '1m':  now_ts - 30*24*3600,
        '6m':  now_ts - 180*24*3600,
        '12m': now_ts - 365*24*3600,
        '24m': now_ts - 730*24*3600,
    }
    result={}
    for period, cutoff in cutoffs.items():
        subset=[t for t in trades if t['ts']>=cutoff]
        s=calc_stats(subset)
        result[period]={
            'n':s['n'] if s else 0,
            'pnl':s['pnl'] if s else 0,
            'wr':s['wr'] if s else 0,
            'pf':s['pf'] if s else 0,
            'dd':s['dd'] if s else 0,
        }
    return result

# ── RESAMPLE ──────────────────────────────────────────────────────────────────
def resample(candles, tf_minutes):
    buckets={}
    for c in candles:
        dt=datetime.datetime.utcfromtimestamp(c['t'])
        minutes=dt.hour*60+dt.minute
        bucket_m=(minutes//tf_minutes)*tf_minutes
        b=dt.replace(hour=bucket_m//60, minute=bucket_m%60, second=0, microsecond=0)
        k=int(b.timestamp())
        if k not in buckets:
            buckets[k]={'t':k,'o':c['o'],'h':c['h'],'l':c['l'],'c':c['c'],'v':c['v']}
        else:
            e=buckets[k]
            e['h']=max(e['h'],c['h']); e['l']=min(e['l'],c['l'])
            e['c']=c['c']; e['v']+=c['v']
    return sorted(buckets.values(), key=lambda x:x['t'])

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_json(path):
    if not path or not os.path.exists(path): return None
    with open(path, encoding='utf-8') as f:
        d=json.load(f)
    candles=d['candles'] if isinstance(d,dict) and 'candles' in d else d
    print(f"  Caricato {len(candles)} candele da {path}")
    return candles

def fetch_mt5(tf_name, days=DAYS):
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("  SKIP (MetaTrader5 non installato)")
        return None
    tf_map={'M30':mt5.TIMEFRAME_M30,'H1':mt5.TIMEFRAME_H1,'H4':mt5.TIMEFRAME_H4}
    if tf_name not in tf_map: return None
    if not mt5.initialize():
        print(f"  ERRORE mt5.initialize(): {mt5.last_error()}")
        return None
    mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    sym=None
    for s in SYMBOL_CANDIDATES:
        info=mt5.symbol_info(s)
        if info and info.visible: sym=s; break
        if info: mt5.symbol_select(s,True); info=mt5.symbol_info(s)
        if info and info.visible: sym=s; break
    if not sym:
        print("  ERRORE: simbolo GOLD non trovato")
        mt5.shutdown(); return None
    dt_to=datetime.datetime.now(datetime.timezone.utc)
    dt_from=dt_to-datetime.timedelta(days=days+5)
    rates=mt5.copy_rates_range(sym, tf_map[tf_name], dt_from, dt_to)
    mt5.shutdown()
    if rates is None or len(rates)==0: return None
    cutoff=(dt_to-datetime.timedelta(days=days)).timestamp()
    out=[]
    for r in rates:
        if float(r['time'])<cutoff: continue
        c=float(r['close'])
        if math.isnan(c) or c<=0: continue
        out.append({'t':int(r['time']),'o':float(r['open']),'h':float(r['high']),
                    'l':float(r['low']),'c':c,'v':float(r['tick_volume'] if 'tick_volume' in r.dtype.names else 0)})
    print(f"  {len(out)} candele {tf_name} da MT5 ({sym})")
    return out

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("="*72)
    print("TradeFlow AI — MFKK Suite Backtest")
    print("Strategie: MFKK Score · MFKK HighWR · MFKK Intraday Combo")
    print("="*72)

    # ── CARICAMENTO DATI
    print("\nCaricamento dati H1...")
    c_h1=None
    if args.h1_file:
        c_h1=load_json(args.h1_file)
    if c_h1 is None and args.mt5:
        print("  Fetching H1 da MT5...")
        c_h1=fetch_mt5('H1')

    if c_h1 is None:
        print("\nERRORE: specificare --h1-file <file.json> oppure --mt5")
        sys.exit(1)

    # Resample H1 → M30 e H4 se non forniti
    print("\nResampling...")
    c_m30=load_json(args.m30_file) if args.m30_file else resample(c_h1, 30)
    c_h4=load_json(args.h4_file) if args.h4_file else resample(c_h1, 240)

    if args.mt5 and not args.m30_file:
        print("  Fetching M30 da MT5...")
        c_m30_mt5=fetch_mt5('M30')
        if c_m30_mt5: c_m30=c_m30_mt5
    if args.mt5 and not args.h4_file:
        print("  Fetching H4 da MT5...")
        c_h4_mt5=fetch_mt5('H4')
        if c_h4_mt5: c_h4=c_h4_mt5

    print(f"  H1:  {len(c_h1)} candele")
    print(f"  M30: {len(c_m30)} candele")
    print(f"  H4:  {len(c_h4)} candele")

    # ── CALCOLO INDICATORI
    print("\nCalcolo indicatori...")
    ind_h1  = compute(c_h1)
    ind_m30 = compute(c_m30)
    ind_h4  = compute(c_h4)
    print("  OK")

    results = {}

    # ════════════════════════════════════════════════════════════════════════════
    # STRATEGIA 1: MFKK SCORE (H1)
    # ════════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*72}")
    print("MFKK SCORE — H1 — TP $20 / SL $12")
    print('='*72)

    trades_mfkk = run_backtest(c_h1, ind_h1, mfkk_score,
                               tp_val=TP_H1, sl_val=SL_H1,
                               session=SESSION_ALL, cooldown_bars=1)
    s_mfkk = calc_stats(trades_mfkk)
    periods_mfkk = stats_by_period(trades_mfkk, c_h1)

    if s_mfkk:
        print(f"  Trade: {s_mfkk['n']} | WR: {s_mfkk['wr']}% | PF: {s_mfkk['pf']} | P&L: ${s_mfkk['pnl']}")
        print(f"  MaxDD: ${s_mfkk['dd']} | BUY WR: {s_mfkk['buy_wr']}% | SELL WR: {s_mfkk['sell_wr']}%")
        print(f"  Mesi positivi: {s_mfkk['pos_months']}")
    print(f"\n  Breakdown per periodo:")
    for p,ps in periods_mfkk.items():
        print(f"    {p:>4}: {ps['n']:>4} trade | WR={ps['wr']:>5.1f}% | P&L=${ps['pnl']:>8.1f} | PF={ps['pf']:>5.3f}")

    results['S00_MFKK_SCORE'] = {
        'strategy':'MFKK Score', 'tf':'H1', 'tp':TP_H1, 'sl':SL_H1,
        'stats':s_mfkk, 'periods':periods_mfkk,
    }

    # ════════════════════════════════════════════════════════════════════════════
    # STRATEGIA 2: MFKK HIGH WIN RATE (H1 SELL ONLY)
    # ════════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*72}")
    print("MFKK HIGH WIN RATE — H1 — SELL ONLY — TP $20 / SL $12")
    print('='*72)

    trades_hwr = run_backtest(c_h1, ind_h1, mfkk_hwr,
                              tp_val=TP_HWR, sl_val=SL_HWR,
                              session=SESSION_ALL, cooldown_bars=1)
    s_hwr = calc_stats(trades_hwr)
    periods_hwr = stats_by_period(trades_hwr, c_h1)

    if s_hwr:
        print(f"  Trade: {s_hwr['n']} | WR: {s_hwr['wr']}% | PF: {s_hwr['pf']} | P&L: ${s_hwr['pnl']}")
        print(f"  MaxDD: ${s_hwr['dd']} | SELL WR: {s_hwr['sell_wr']}%")
        print(f"  Mesi positivi: {s_hwr['pos_months']}")
    print(f"\n  Breakdown per periodo:")
    for p,ps in periods_hwr.items():
        print(f"    {p:>4}: {ps['n']:>4} trade | WR={ps['wr']:>5.1f}% | P&L=${ps['pnl']:>8.1f} | PF={ps['pf']:>5.3f}")

    results['S00_MFKK_HWR'] = {
        'strategy':'MFKK HighWR', 'tf':'H1', 'tp':TP_HWR, 'sl':SL_HWR,
        'stats':s_hwr, 'periods':periods_hwr,
    }

    # ════════════════════════════════════════════════════════════════════════════
    # STRATEGIA 3: MFKK INTRADAY COMBO — Multi-TF sweep
    # ════════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*72}")
    print("MFKK INTRADAY COMBO — OBV MACD + RSI + MOMENTUM")
    print("Multi-TF: M30 / H1 / H4")
    print('='*72)

    tf_configs = {
        'M30': (c_m30, ind_m30, SESSION_LDN,   2),   # London/NY, cooldown 2 bar
        'H1':  (c_h1,  ind_h1,  SESSION_ALL,   1),   # 24h, cooldown 1 bar
        'H4':  (c_h4,  ind_h4,  SESSION_ALL,   1),   # 24h, cooldown 1 bar
    }

    best_overall_score = -1
    best_overall = None
    intraday_results = {}

    print(f"\n{'Variante':<22} {'TF':<5} {'N':>5} {'WR':>6} {'PF':>6} {'P&L':>9} {'DD':>8} {'BuyWR':>7} {'SellWR':>8}")
    print('-'*75)

    for vname, vfn in INTRADAY_VARIANTS.items():
        intraday_results[vname] = {}
        for tf_label, (candles, ind, session, cooldown) in tf_configs.items():
            trades = run_backtest(candles, ind, vfn, use_atr=True,
                                  session=session, cooldown_bars=cooldown, label=tf_label)
            s = calc_stats(trades)
            periods = stats_by_period(trades, candles)
            intraday_results[vname][tf_label] = {'stats':s,'periods':periods,'trades_count':len(trades) if trades else 0}

            if s and s['n']>=20:
                status = '✅' if s['pf']>=1.5 else ('⚠️' if s['pf']>=1.1 else '❌')
                print(f"{status} {vname:<20} {tf_label:<5} {s['n']:>5} {s['wr']:>5.1f}% {s['pf']:>6.3f} {s['pnl']:>9.1f} {s['dd']:>8.1f} {s['buy_wr']:>6.1f}% {s['sell_wr']:>7.1f}%")
                # Score composito
                rr=(s['pnl']/s['dd']) if s['dd']>0 else s['pnl']
                score=s['pf']*(s['wr']/100)*math.log(s['n']+1)*min(rr/3,1.5)
                if score>best_overall_score:
                    best_overall_score=score
                    best_overall={'variant':vname,'tf':tf_label,'stats':s,'periods':periods,'score':round(score,3)}
            else:
                n_=s['n'] if s else 0
                print(f"── {vname:<20} {tf_label:<5} {n_:>5}  (N<20, skip)")

    # Raccomandazione
    print(f"\n{'='*72}")
    if best_overall:
        b=best_overall
        print(f"🏆 BEST MFKK INTRADAY: {b['variant']} su {b['tf']} (Score={b['score']:.3f})")
        s=b['stats']
        print(f"   WR={s['wr']}% | PF={s['pf']} | P&L=${s['pnl']} | MaxDD=${s['dd']}")
        print(f"   Trade={s['n']} | BUY WR={s['buy_wr']}% | SELL WR={s['sell_wr']}%")
        print(f"\n   Breakdown per periodo (best combo):")
        for p,ps in b['periods'].items():
            print(f"     {p:>4}: {ps['n']:>4} trade | WR={ps['wr']:>5.1f}% | P&L=${ps['pnl']:>8.1f} | PF={ps['pf']:>5.3f}")
    else:
        print("⚠️  Nessuna variante MFKK Intraday con N>=20. Usa più dati storici.")
        best_overall={'variant':'V1_OBV_RSI_MOM','tf':'H1','stats':None,'periods':{},'score':0}

    results['S05_MFKK_INTRADAY'] = {
        'strategy':'MFKK Intraday',
        'best':best_overall,
        'all_variants':intraday_results,
    }

    # ── RIEPILOGO FINALE
    print(f"\n{'='*72}")
    print("RIEPILOGO FINALE — 3 Strategie Ufficiali")
    print('='*72)
    print(f"{'Strategia':<20} {'TF':<5} {'WR':>6} {'PF':>6} {'24m P&L':>10} {'12m P&L':>10} {'6m P&L':>10} {'1m P&L':>9}")
    print('-'*78)

    for sid, r in results.items():
        if sid == 'S05_MFKK_INTRADAY':
            s  = r['best']['stats'] or {}
            ps = r['best']['periods']
            tf = r['best']['tf']
            nm = r['strategy']
        else:
            s  = r['stats'] or {}
            ps = r['periods']
            tf = r['tf']
            nm = r['strategy']
        wr  = s.get('wr',0)
        pf  = s.get('pf',0)
        p24 = ps.get('24m',{}).get('pnl',0)
        p12 = ps.get('12m',{}).get('pnl',0)
        p6  = ps.get('6m',{}).get('pnl',0)
        p1  = ps.get('1m',{}).get('pnl',0)
        print(f"{nm:<20} {tf:<5} {wr:>5.1f}% {pf:>6.3f} {p24:>10.1f} {p12:>10.1f} {p6:>10.1f} {p1:>9.1f}")

    # ── SAVE JSON
    out={
        'generated': datetime.datetime.utcnow().isoformat(),
        'config':{
            'tp_mfkk':TP_H1,'sl_mfkk':SL_H1,
            'tp_atr_mult':TP_ATR_MULT,'sl_atr_mult':SL_ATR_MULT,
            'days':DAYS,'extreme_k':EXTREME_K,
        },
        'strategies': results,
    }
    with open(args.out,'w',encoding='utf-8') as f:
        json.dump(out,f,indent=2,ensure_ascii=False)
    print(f"\nSalvato: {args.out}")
    print(f"\nProssimo step:")
    print(f"  python scripts/backtest_mfkk_intraday.py --h1-file xauusd_h1_mt5.json")
    print(f"  python scripts/backtest_mfkk_intraday.py --mt5  (richiede MT5 aperto)")
    print('='*72)

if __name__=='__main__':
    main()
